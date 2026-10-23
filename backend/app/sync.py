"""Quota-aware, operator-configured ingestion. No credentials in public routes."""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .config import settings
from .database import SessionLocal
from .import_results import ResultImport, apply_results
from .models import Entry, Fixture, ProviderQuota, Season, Stage, SyncRun, SyncSource
from .schemas import Outcome


class SyncFailure(Exception):
    pass


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stage_id: str = Field(min_length=1, max_length=80)
    provider: Literal['normalized_file', 'cricketdata']
    enabled: bool = False
    interval_seconds: int = Field(default=43200, ge=60, le=604800)
    file_path: str | None = None
    series_id: UUID | None = None
    fixture_map: dict[UUID, str] = Field(default_factory=dict, max_length=800)
    team_names: dict[str, str] = Field(default_factory=dict, max_length=64)
    max_calls_per_run: int = Field(default=20, ge=1, le=30)

    @model_validator(mode='after')
    def complete_config(self):
        if self.provider == 'normalized_file' and not self.file_path:
            raise ValueError('Normalized-file sources require file_path')
        if self.provider == 'cricketdata' and (not self.series_id or not self.fixture_map or not self.team_names):
            raise ValueError('CricketData requires a series ID, fixture mappings and exact team-name mappings')
        if len(set(self.fixture_map.values())) != len(self.fixture_map):
            raise ValueError('Each provider fixture must map to a distinct local fixture')
        return self


class NormalizedResults(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    stage_id: str
    observed_at: datetime
    outcomes: dict[str, Outcome] = Field(default_factory=dict, max_length=800)
    nrr: dict[str, float] = Field(default_factory=dict, max_length=16)

    @model_validator(mode='after')
    def aware_timestamp(self):
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError('observed_at must include a timezone')
        if self.observed_at.timestamp() > time.time() + 300:
            raise ValueError('observed_at cannot be in the future')
        return self


def configure_source(session, definition):
    stage = session.get(Stage, definition.stage_id)
    if stage is None:
        raise ValueError('Unknown stage')
    if definition.provider == 'cricketdata':
        if session.get(Season, stage.season_id).source == 'demo':
            raise ValueError('Provision a manual season before mapping real provider data; demo results must not be mixed with live results')
        fixtures = set(session.scalars(select(Fixture.id).where(Fixture.stage_id == stage.id)))
        members = set(session.scalars(select(Entry.team_id).where(Entry.stage_id == stage.id)))
        if set(definition.fixture_map.values()) != fixtures or set(definition.team_names.values()) != members:
            raise ValueError('Provider mappings must cover exactly the configured stage fixtures and team memberships')
    value = definition.model_dump(mode='json')
    if definition.file_path:
        value['file_path'] = str(Path(definition.file_path).resolve())
    existing = session.get(SyncSource, stage.id)
    if existing is not None:
        if existing.lease_until > time.time():
            raise ValueError('Cannot reconfigure a source while it is syncing')
        if existing.provider == definition.provider and existing.configuration == value:
            return False
        existing.provider = definition.provider; existing.configuration = value
        existing.enabled = definition.enabled; existing.interval_seconds = definition.interval_seconds
        existing.next_attempt = 0; existing.status = 'idle'; existing.error_code = None
        existing.last_success_at = None; existing.last_observed_at = None; existing.nrr_verified_revision = None
    else:
        session.add(SyncSource(stage_id=stage.id, provider=definition.provider, configuration=value, enabled=definition.enabled, interval_seconds=definition.interval_seconds))
    # Changing provenance/NRR trust also changes the prediction state, even
    # when no points move. Give browsers and caches a new revision.
    revision = stage.revision
    changed = session.execute(update(Stage).where(Stage.id == stage.id, Stage.revision == revision).values(revision=revision + 1, updated_at=datetime.now(timezone.utc).isoformat()))
    if changed.rowcount != 1:
        raise ValueError('Concurrent stage update; reload before configuring sync')
    session.flush()
    return True


def reserve_request(factory, api_key, limit):
    if not api_key or limit < 1:
        raise SyncFailure('provider_credentials_or_budget_missing')
    day = datetime.now(timezone.utc).date().isoformat()
    key = f'cricketdata:{hashlib.sha256(api_key.encode()).hexdigest()[:20]}:{day}'
    with factory.begin() as session:
        if session.get(ProviderQuota, key) is None:
            try:
                with session.begin_nested():
                    session.add(ProviderQuota(key=key, used=0)); session.flush()
            except IntegrityError:
                pass
        claimed = session.execute(update(ProviderQuota).where(ProviderQuota.key == key, ProviderQuota.used < limit).values(used=ProviderQuota.used + 1))
        if claimed.rowcount != 1:
            raise SyncFailure('daily_budget_exhausted')


def parse_scorecard(payload, provider_id, config, fixture):
    if payload.get('status') != 'success' or not isinstance(payload.get('data'), dict):
        raise SyncFailure('provider_payload_invalid')
    data = payload['data']
    if str(data.get('id')) != str(provider_id) or str(data.get('series_id')) != str(config.series_id):
        raise SyncFailure('provider_fixture_identity_mismatch')
    teams = data.get('teams')
    if not isinstance(teams, list) or len(teams) != 2 or {config.team_names.get(name) for name in teams} != {fixture['home_id'], fixture['away_id']}:
        raise SyncFailure('provider_team_identity_mismatch')
    winner = data.get('matchWinner')
    if not winner:
        # No guessed washout from free-text status. An operator may import
        # confirmed no-results through the normalized feed instead.
        return None
    if data.get('matchEnded') is False or config.team_names.get(winner) not in {fixture['home_id'], fixture['away_id']}:
        raise SyncFailure('provider_winner_invalid')
    return 'home' if config.team_names[winner] == fixture['home_id'] else 'away'


def fetch_cricketdata(config, fixtures, factory):
    api_key = settings.cricketdata_api_key.get_secret_value()
    if not api_key or settings.provider_daily_budget < 1:
        raise SyncFailure('provider_credentials_or_budget_missing')
    due = {m['id']: m for m in fixtures if m['outcome'] == 'pending' and datetime.fromisoformat(m['starts_at']).timestamp() <= time.time()}
    # Catch up a large real season in bounded batches rather than failing
    # forever whenever more than one batch of played fixtures needs importing.
    due = dict(sorted(due.items(), key=lambda pair: (pair[1]['starts_at'], pair[0]))[:config.max_calls_per_run])
    outcomes = {}
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        for provider_id, local_id in config.fixture_map.items():
            if local_id not in due:
                continue
            for attempt in range(2):
                reserve_request(factory, api_key, settings.provider_daily_budget)
                try:
                    response = client.get(settings.cricketdata_base_url.rstrip('/') + '/match_info', params={'apikey': api_key, 'id': str(provider_id), 'offset': 0})
                except httpx.RequestError:
                    if attempt == 0:
                        time.sleep(0.25); continue
                    raise SyncFailure('provider_unreachable') from None
                if response.status_code == 429:
                    raise SyncFailure('provider_rate_limited')
                if response.status_code >= 500 and attempt == 0:
                    time.sleep(0.25); continue
                if response.status_code != 200:
                    raise SyncFailure('provider_http_error')
                try:
                    outcome = parse_scorecard(response.json(), provider_id, config, due[local_id])
                except (ValueError, TypeError, AttributeError):
                    raise SyncFailure('provider_payload_invalid') from None
                if outcome:
                    outcomes[local_id] = outcome
                break
    return NormalizedResults(stage_id=config.stage_id, observed_at=datetime.now(timezone.utc), outcomes=outcomes)


def run_sync(stage_id, factory=SessionLocal, fetcher=None, force=False):
    now = time.time(); token = str(uuid4()); started = datetime.now(timezone.utc).isoformat()
    with factory.begin() as session:
        source = session.get(SyncSource, stage_id)
        if source is None or not source.enabled:
            return {'status': 'disabled', 'changed': False}
        config = SourceConfig.model_validate(source.configuration)
        claim = session.execute(update(SyncSource).where(SyncSource.stage_id == stage_id, SyncSource.enabled.is_(True), SyncSource.lease_until <= now,
                                *([] if force else [SyncSource.next_attempt <= now])).values(lease_token=token, lease_until=now + 700, status='running', last_attempt_at=started))
        if claim.rowcount != 1:
            return {'status': 'not_due_or_running', 'changed': False}
        revision = session.get(Stage, stage_id).revision
        fixtures = [{k: getattr(m, k) for k in ['id', 'home_id', 'away_id', 'starts_at', 'outcome']} for m in session.scalars(select(Fixture).where(Fixture.stage_id == stage_id))]
        session.add(SyncRun(id=token, stage_id=stage_id, started_at=started, status='running'))
    try:
        if fetcher:
            payload = fetcher(config, fixtures, factory)
        elif config.provider == 'normalized_file':
            payload = NormalizedResults.model_validate_json(Path(config.file_path).read_text(encoding='utf-8'))
        else:
            payload = fetch_cricketdata(config, fixtures, factory)
        if payload.stage_id != stage_id:
            raise SyncFailure('payload_stage_mismatch')
        observed = payload.observed_at.astimezone(timezone.utc).isoformat()
        with factory.begin() as session:
            source = session.get(SyncSource, stage_id)
            if source.lease_token != token or source.lease_until < time.time():
                raise SyncFailure('sync_lease_expired')
            if source.last_observed_at and observed < source.last_observed_at:
                raise SyncFailure('stale_provider_payload')
            if source.last_observed_at == observed:
                stored_fixtures = {m.id: m.outcome for m in session.scalars(select(Fixture).where(Fixture.stage_id == stage_id))}
                stored_nrr = {e.team_id: e.nrr for e in session.scalars(select(Entry).where(Entry.stage_id == stage_id))}
                if any(stored_fixtures.get(k) != v for k, v in payload.outcomes.items()) or any(stored_nrr.get(k) != v for k, v in payload.nrr.items()):
                    raise SyncFailure('stale_provider_payload')
            new_revision, changed = apply_results(session, stage_id, ResultImport(expected_revision=revision, outcomes=payload.outcomes, nrr=payload.nrr))
            members = set(session.scalars(select(Entry.team_id).where(Entry.stage_id == stage_id)))
            if members == set(payload.nrr):
                if not changed and source.nrr_verified_revision != new_revision:
                    claim = session.execute(update(Stage).where(Stage.id == stage_id, Stage.revision == new_revision).values(revision=new_revision + 1, updated_at=datetime.now(timezone.utc).isoformat()))
                    if claim.rowcount != 1:
                        raise SyncFailure('stage_revision_conflict')
                    new_revision += 1; changed = True
                source.nrr_verified_revision = new_revision
            source.status = 'updated' if changed else 'unchanged'; source.error_code = None
            source.last_success_at = datetime.now(timezone.utc).isoformat(); source.last_observed_at = observed
            source.next_attempt = time.time() + source.interval_seconds; source.lease_until = 0; source.lease_token = None
            run = session.get(SyncRun, token); run.finished_at = source.last_success_at; run.status = source.status; run.changed = changed
        return {'status': 'updated' if changed else 'unchanged', 'changed': changed, 'revision': new_revision}
    except Exception as exc:
        code = str(exc) if isinstance(exc, SyncFailure) else 'sync_validation_or_storage_error'
        with factory.begin() as session:
            source = session.get(SyncSource, stage_id)
            if source.lease_token == token:
                source.status = 'failed'; source.error_code = code
                source.next_attempt = time.time() + min(source.interval_seconds, 900); source.lease_until = 0; source.lease_token = None
            run = session.get(SyncRun, token); run.finished_at = datetime.now(timezone.utc).isoformat(); run.status = 'failed'; run.error_code = code
        return {'status': 'failed', 'changed': False, 'error': code}


def sync_status(session, stage_id):
    source = session.get(SyncSource, stage_id)
    if source is None:
        return {'configured': False, 'status': 'not_configured', 'stale': False}
    last = datetime.fromisoformat(source.last_success_at).timestamp() if source.last_success_at else 0
    observed = datetime.fromisoformat(source.last_observed_at).timestamp() if source.last_observed_at else 0
    return {'configured': True, 'provider': source.provider, 'status': 'disabled' if not source.enabled else source.status,
            'stale': not source.enabled or source.status == 'failed' or time.time() - min(last, observed) > source.interval_seconds * 2,
            'last_success_at': source.last_success_at, 'last_attempt_at': source.last_attempt_at, 'error': source.error_code}


def main():
    parser = argparse.ArgumentParser(description='Configure or run database-backed ingestion')
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('configure'); setup.add_argument('file', type=Path)
    run = commands.add_parser('run'); run.add_argument('stage_id'); run.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.command == 'configure':
        definition = SourceConfig.model_validate_json(args.file.read_text(encoding='utf-8'))
        with SessionLocal.begin() as session:
            changed = configure_source(session, definition)
        print(json.dumps({'stage_id': definition.stage_id, 'changed': changed, 'enabled': definition.enabled}))
    else:
        result = run_sync(args.stage_id, force=args.force)
        if result.get('changed'):
            from .jobs import submit
            from .engine import load_snapshot
            from .schemas import PredictionRequest
            with SessionLocal() as session:
                snapshot = load_snapshot(session, args.stage_id)
                if snapshot['rules']['schedule_complete']:
                    submit(snapshot, PredictionRequest(iterations=10000).model_dump())
        print(json.dumps(result))
        if result['status'] == 'failed':
            raise SystemExit(1)


if __name__ == '__main__':
    main()
