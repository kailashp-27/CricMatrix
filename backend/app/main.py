import asyncio
import re
from uuid import UUID
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from .config import settings
from .database import Base, SessionLocal, engine, session_dependency
from .engine import load_snapshot, standings, validate_overrides
from .jobs import read_job, redis_client, submit
from .models import LiveFeed, Season, Stage, StageRule, SyncSource, Tournament
from .rules import TEMPLATES, get_rules
from .schemas import CompetitionForecastRequest, LiveFeedResponse, PredictionRequest, ProviderTablesResponse
from .seed import seed_demo
from .sync import sync_status
from .live import read_feed
from .scheduler import run_local_scheduler
from .provider_tables import read_tables
from .competition_fixtures import read_fixtures
from .competition_predictions import competition_analysis, fixture_snapshot


@asynccontextmanager
async def lifespan(app):
    # Development convenience. Production schema upgrades use Alembic.
    if settings.demo_seed:
        Base.metadata.create_all(engine)
        with SessionLocal() as session:
            seed_demo(session)
    stop = asyncio.Event()
    scheduler = asyncio.create_task(run_local_scheduler(stop)) if settings.job_mode == 'local' else None
    try:
        yield
    finally:
        stop.set()
        if scheduler:
            await scheduler


app = FastAPI(title='CricMatrix qualification API', version='0.3.0', lifespan=lifespan,
              description='Stage-scoped cricket standings and asynchronous qualification predictions. Demo data is synthetic.')
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(','), allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])


@app.get('/', include_in_schema=False)
def api_home():
    return RedirectResponse('/docs')


@app.get('/api/health')
def health(session: Session = Depends(session_dependency)):
    try:
        session.execute(text('SELECT 1'))
        session.execute(select(StageRule.stage_id).limit(1))
        session.execute(select(SyncSource.stage_id).limit(1))
        session.execute(select(LiveFeed.provider).limit(1))
    except SQLAlchemyError as exc:
        raise HTTPException(503, 'Database unavailable or schema not initialized') from exc
    if settings.job_mode == 'celery':
        try:
            redis_client().ping()
        except Exception as exc:
            raise HTTPException(503, 'Redis unavailable') from exc
    return {'status': 'ok', 'job_mode': settings.job_mode, 'database': engine.dialect.name}


@app.get('/api/health/live')
def liveness():
    return {'status': 'ok', 'service': 'CricMatrix', 'version': app.version}


@app.get('/api/health/ready')
def readiness(session: Session = Depends(session_dependency)):
    return health(session)


@app.get('/api/tournaments')
def tournaments(session: Session = Depends(session_dependency)):
    result = []
    for tournament in session.scalars(select(Tournament)):
        seasons = []
        for season in session.scalars(select(Season).where(Season.tournament_id == tournament.id)):
            stages = [{'id': s.id, 'name': s.name, 'rules': get_rules(session, s).model_dump()} for s in session.scalars(select(Stage).where(Stage.season_id == season.id))]
            seasons.append({'id': season.id, 'name': season.name, 'source': season.source, 'stages': stages})
        result.append({'id': tournament.id, 'name': tournament.name, 'country': tournament.country, 'seasons': seasons})
    return result


@app.get('/api/live', response_model=LiveFeedResponse)
def live_matches(session: Session = Depends(session_dependency)):
    """Cached multi-competition matches. Reading never spends provider quota."""
    return read_feed(session)


@app.get('/api/standings', response_model=ProviderTablesResponse)
def provider_standings(session: Session = Depends(session_dependency)):
    """Fetched provider tables only. No demo fallback or visitor-triggered calls."""
    return read_tables(session)


@app.get('/api/competitions/{series_id}/fixtures')
def competition_fixtures(series_id: UUID, session: Session = Depends(session_dependency)):
    try:
        return read_fixtures(session, str(series_id))
    except KeyError as exc:
        raise HTTPException(404, 'Competition is not in the fetched match catalog') from exc


@app.get('/api/competitions/{series_id}/analysis')
def provider_analysis(series_id: UUID, session: Session = Depends(session_dependency)):
    try:
        return competition_analysis(session, str(series_id))
    except KeyError as exc:
        raise HTTPException(404, 'Competition is not in the fetched match catalog') from exc


@app.post('/api/competitions/{series_id}/forecast', status_code=202)
def provider_forecast(series_id: UUID, request: CompetitionForecastRequest, response: Response, session: Session = Depends(session_dependency)):
    if not request.accept_points_assumptions:
        raise HTTPException(422, 'Choose the points-model assumptions before running qualification scenarios.')
    try:
        schedule = read_fixtures(session, str(series_id))
        rows = next(c['rows'] for c in read_tables(session)['competitions'] if c['id'] == str(series_id))
        snapshot = fixture_snapshot(schedule, rows, request.qualifying_spots)
        if request.expected_revision is not None and request.expected_revision != snapshot['revision']:
            raise ValueError('The fetched results changed. Refresh the table before calculating again.')
        validate_overrides(snapshot, request.overrides)
    except KeyError as exc:
        raise HTTPException(404, 'Competition is not in the fetched match catalog') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    model_request = PredictionRequest(overrides=request.overrides, iterations=request.iterations,
        model='equal' if request.model == 'equal' else 'rating', washout_probability=request.washout_probability, seed=request.seed)
    try:
        job = submit(snapshot, model_request.model_dump())
    except Exception as exc:
        raise HTTPException(503, 'Prediction service unavailable. Please retry shortly.') from exc
    response.headers['Location'] = f'/api/predictions/{job["id"]}'
    return job


def snapshot_or_404(session, stage_id):
    try:
        return load_snapshot(session, stage_id)
    except KeyError as exc:
        raise HTTPException(404, 'Stage not found') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get('/api/rule-templates')
def rule_templates():
    return {'schema_version': 1, 'official_regulations': False, 'templates': TEMPLATES,
            'note': 'Examples only. Verify regulations for the particular season and stage.'}


@app.get('/api/stages/{stage_id}/rules')
def stage_rules(stage_id: str, session: Session = Depends(session_dependency)):
    snapshot = snapshot_or_404(session, stage_id)
    return {'stage_id': stage_id, 'revision': snapshot['revision'], 'schema_version': 1, 'source': snapshot['source'], 'rules': snapshot['rules']}


@app.get('/api/stages/{stage_id}')
def stage(stage_id: str, session: Session = Depends(session_dependency)):
    snapshot = snapshot_or_404(session, stage_id)
    return {**snapshot, 'standings': standings(snapshot), 'sync': sync_status(session, stage_id)}


@app.get('/api/stages/{stage_id}/sync')
def stage_sync(stage_id: str, session: Session = Depends(session_dependency)):
    if session.get(Stage, stage_id) is None:
        raise HTTPException(404, 'Stage not found')
    return sync_status(session, stage_id)


@app.post('/api/stages/{stage_id}/predictions', status_code=202)
def prediction(stage_id: str, request: PredictionRequest, response: Response, session: Session = Depends(session_dependency)):
    snapshot = snapshot_or_404(session, stage_id)
    if not snapshot['rules']['schedule_complete']:
        raise HTTPException(409, 'Predictions require a complete fixture schedule')
    try:
        validate_overrides(snapshot, request.overrides)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        job = submit(snapshot, request.model_dump())
    except Exception as exc:
        raise HTTPException(503, 'Prediction service unavailable. Please retry shortly.') from exc
    response.headers['Location'] = f'/api/predictions/{job["id"]}'
    return job


@app.get('/api/predictions/{job_id}')
def prediction_result(job_id: str):
    if not re.fullmatch(r'[a-f0-9]{64}', job_id):
        raise HTTPException(404, 'Prediction not found')
    try:
        result = read_job(job_id)
    except Exception as exc:
        raise HTTPException(503, 'Prediction service unavailable') from exc
    if not result:
        raise HTTPException(404, 'Prediction expired or not found')
    return result
