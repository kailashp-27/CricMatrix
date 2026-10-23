"""Local mode schedules the same stored-source refreshes as Celery Beat."""
import asyncio
import logging
import time

from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .live import refresh_feed, refresh_series, refresh_match_series
from .models import SyncSource

logger = logging.getLogger(__name__)


def local_tick():
    if settings.live_feed_enabled:
        refresh_feed()
        if settings.live_feed_provider == 'cricketdata':
            refresh_match_series()
            refresh_series()
    from .jobs import sync_stage_task
    with SessionLocal() as session:
        stages = list(session.scalars(select(SyncSource.stage_id).where(
            SyncSource.enabled.is_(True), SyncSource.next_attempt <= time.time(), SyncSource.lease_until <= time.time())))
    for stage_id in stages:
        sync_stage_task(stage_id)


async def run_local_scheduler(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(local_tick)
        except Exception:
            # Never log an upstream exception/URL which might contain a key.
            logger.warning('Stored-source refresh failed; retrying on the next scheduler tick')
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            pass
