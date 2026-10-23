import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from redis import Redis

from .config import settings
from .database import SessionLocal
from .engine import load_snapshot, simulate


logger = logging.getLogger(__name__)
celery_app = None
if settings.job_mode == 'celery':
    from celery import Celery
    from celery.schedules import crontab
    celery_app = Celery('crease', broker=settings.redis_url, backend=settings.redis_url)
    celery_app.conf.update(task_serializer='json', result_serializer='json', accept_content=['json'],
                           task_track_started=True, result_expires=3600, worker_prefetch_multiplier=1,
                           task_soft_time_limit=90, task_time_limit=120,
                           beat_schedule={'refresh-baselines': {'task': 'crease.refresh_baselines', 'schedule': crontab(hour='0,12', minute=0)},
                                          'dispatch-due-syncs': {'task': 'crease.dispatch_syncs', 'schedule': 60.0},
                                          'refresh-live-feed': {'task': 'crease.refresh_live_feed', 'schedule': 60.0}})
pool = ThreadPoolExecutor(max_workers=2)
local_jobs = {}
lock = threading.Lock()
TTL = 3600
ENGINE_VERSION = 3


def redis_client():
    return Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


def write_job(job_id, payload):
    payload = {**payload, 'updated_epoch': time.time()}
    if settings.job_mode == 'celery':
        redis_client().setex(f'crease:job:{job_id}', TTL, json.dumps(payload))
    else:
        with lock:
            local_jobs[job_id] = (time.monotonic() + TTL, payload)


def read_job(job_id):
    if settings.job_mode == 'celery':
        value = redis_client().get(f'crease:job:{job_id}')
        result = json.loads(value) if value else None
        if result and result['status'] in ('queued', 'running') and time.time() - result.get('updated_epoch', 0) > 180:
            result = {'id': job_id, 'status': 'failed', 'error': 'Prediction worker timed out. Please retry.'}
            write_job(job_id, result)
            redis_client().delete(f'crease:claim:{job_id}')
        return result
    with lock:
        for key in [k for k, (expires, _) in local_jobs.items() if expires < time.monotonic()]:
            del local_jobs[key]
        return local_jobs.get(job_id, (0, None))[1]


def execute(job_id, snapshot, request):
    try:
        write_job(job_id, {'id': job_id, 'status': 'running'})
        result = simulate(snapshot, request)
        write_job(job_id, {'id': job_id, 'status': 'completed', 'result': result, 'generated_at': datetime.now(timezone.utc).isoformat()})
    except Exception:
        logger.exception('Simulation failed: %s', job_id)
        write_job(job_id, {'id': job_id, 'status': 'failed', 'error': 'Simulation failed. Please retry.'})
    finally:
        if settings.job_mode == 'celery':
            redis_client().delete(f'crease:claim:{job_id}')


def run_simulation(job_id, snapshot, request):
    execute(job_id, snapshot, request)


def submit(snapshot, request):
    # Revision prevents post-sync results from reusing stale state. Version the
    # model key whenever the simulation algorithm changes.
    serialized = json.dumps({'engine': ENGINE_VERSION, 'snapshot': snapshot, 'request': request}, sort_keys=True)
    job_id = hashlib.sha256(serialized.encode()).hexdigest()
    if settings.job_mode == 'celery':
        redis = redis_client()
        existing = read_job(job_id)
        if existing and existing['status'] != 'failed':
            return existing
        claimed = redis.set(f'crease:claim:{job_id}', '1', nx=True, ex=180)
        if not claimed:
            return {'id': job_id, 'status': 'queued'}
        try:
            write_job(job_id, {'id': job_id, 'status': 'queued'})
            run_simulation.delay(job_id, snapshot, request)
        except Exception:
            redis.delete(f'crease:job:{job_id}', f'crease:claim:{job_id}')
            raise
    else:
        existing = read_job(job_id)
        if existing and existing['status'] != 'failed':
            return existing
        with lock:
            # Recheck under the admission lock when concurrent requests have
            # both missed the initial lookup.
            prior = local_jobs.get(job_id, (0, None))[1]
            if prior and prior['status'] != 'failed':
                return prior
            if sum(p['status'] in ('queued', 'running') for _, p in local_jobs.values()) >= 32:
                raise RuntimeError('Simulation queue is full')
            if len(local_jobs) >= 256:
                evictable = next((k for k, (_, p) in local_jobs.items() if p['status'] in ('completed', 'failed')), None)
                if evictable:
                    del local_jobs[evictable]
            local_jobs[job_id] = (time.monotonic() + TTL, {'id': job_id, 'status': 'queued'})
        pool.submit(execute, job_id, snapshot, request)
    return read_job(job_id)


def refresh_baselines():
    from sqlalchemy import select
    from .models import Stage
    from .schemas import PredictionRequest
    with SessionLocal() as session:
        for stage_id in session.scalars(select(Stage.id)):
            snapshot = load_snapshot(session, stage_id)
            if snapshot['rules']['schedule_complete']:
                submit(snapshot, PredictionRequest(iterations=10000).model_dump())


def sync_stage_task(stage_id):
    from .sync import run_sync
    from .schemas import PredictionRequest
    result = run_sync(stage_id)
    if result.get('changed'):
        with SessionLocal() as session:
            snapshot = load_snapshot(session, stage_id)
            if snapshot['rules']['schedule_complete']:
                submit(snapshot, PredictionRequest(iterations=10000).model_dump())
    return result


def dispatch_syncs():
    from sqlalchemy import select
    from .models import SyncSource
    with SessionLocal() as session:
        stages = list(session.scalars(select(SyncSource.stage_id).where(SyncSource.enabled.is_(True), SyncSource.next_attempt <= time.time(), SyncSource.lease_until <= time.time())))
    for stage_id in stages:
        if celery_app is not None:
            sync_stage_task.delay(stage_id)




def refresh_live_feed_task():
    if settings.live_feed_enabled:
        from .live import refresh_feed, refresh_series, refresh_match_series
        result = refresh_feed()
        if settings.live_feed_provider == 'cricketdata':
            refresh_match_series()
            from .provider_tables import refresh_tables
            refresh_tables()
            refresh_series()
        return result
    return {'status': 'disabled'}


if celery_app is not None:
    run_simulation = celery_app.task(name='crease.simulate')(run_simulation)
    refresh_baselines = celery_app.task(name='crease.refresh_baselines')(refresh_baselines)
    sync_stage_task = celery_app.task(name='crease.sync_stage', soft_time_limit=650, time_limit=680)(sync_stage_task)
    dispatch_syncs = celery_app.task(name='crease.dispatch_syncs')(dispatch_syncs)
    refresh_live_feed_task = celery_app.task(name='crease.refresh_live_feed', soft_time_limit=550, time_limit=580)(refresh_live_feed_task)
