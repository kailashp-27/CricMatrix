import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.engine import load_snapshot, simulate
from app.models import Entry, Fixture, ProviderQuota, SyncRun
from app.schemas import PredictionRequest
from app.seed import seed_demo
from app.sync import NormalizedResults, SourceConfig, SyncFailure, configure_source, parse_scorecard, reserve_request, run_sync, sync_status


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        @event.listens_for(self.engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        with self.factory() as session:
            seed_demo(session)
        self.stage_id = 'ipl-demo-0'

    def tearDown(self):
        self.engine.dispose()

    def setup_source(self, enabled=True):
        with self.factory.begin() as session:
            configure_source(session, SourceConfig(stage_id=self.stage_id, provider='normalized_file', file_path='unused.json', enabled=enabled))

    def payload(self, outcomes=None, nrr=None, observed=None):
        return NormalizedResults(stage_id=self.stage_id, observed_at=observed or datetime.now(timezone.utc), outcomes=outcomes or {}, nrr=nrr or {})

    def test_disabled_sources_do_not_fetch(self):
        self.setup_source(False)
        result = run_sync(self.stage_id, self.factory, fetcher=lambda *_: self.fail('Disabled source fetched'))
        self.assertEqual(result['status'], 'disabled')

    def test_transactional_update_replay_and_due_guard(self):
        self.setup_source()
        with self.factory() as session:
            before = load_snapshot(session, self.stage_id)
        match = next(m for m in before['fixtures'] if m['outcome'] == 'pending')
        payload = self.payload({match['id']: 'washout'})
        result = run_sync(self.stage_id, self.factory, fetcher=lambda *_: payload)
        self.assertTrue(result['changed'])
        self.assertEqual(result['revision'], before['revision'] + 1)
        self.assertEqual(run_sync(self.stage_id, self.factory)['status'], 'not_due_or_running')
        repeated = run_sync(self.stage_id, self.factory, fetcher=lambda *_: payload, force=True)
        self.assertEqual(repeated['status'], 'unchanged')
        with self.factory() as session:
            self.assertEqual(session.get(Fixture, match['id']).outcome, 'washout')
            self.assertEqual(len(list(session.scalars(select(SyncRun)))), 2)
            self.assertFalse(sync_status(session, self.stage_id)['stale'])

    def test_failure_preserves_last_good_snapshot_and_redacts_errors(self):
        self.setup_source()
        with self.factory() as session:
            before = load_snapshot(session, self.stage_id)
        def unavailable(*_):
            raise RuntimeError('https://provider.example/?apikey=must-not-leak')
        result = run_sync(self.stage_id, self.factory, fetcher=unavailable)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('must-not-leak', str(result))
        with self.factory() as session:
            self.assertEqual(load_snapshot(session, self.stage_id), before)
            status = sync_status(session, self.stage_id)
            self.assertTrue(status['stale']); self.assertNotIn('must-not-leak', str(status))

    def test_invalid_or_cross_stage_results_never_partially_commit(self):
        self.setup_source()
        with self.factory() as session:
            before = load_snapshot(session, self.stage_id)
        match = next(m for m in before['fixtures'] if m['outcome'] == 'pending')
        payload = self.payload({match['id']: 'home', 'foreign-stage-fixture': 'away'})
        self.assertEqual(run_sync(self.stage_id, self.factory, fetcher=lambda *_: payload)['status'], 'failed')
        with self.factory() as session:
            self.assertEqual(load_snapshot(session, self.stage_id), before)

    def test_lease_blocks_overlapping_syncs(self):
        self.setup_source()
        def during_fetch(*_):
            duplicate = run_sync(self.stage_id, self.factory, fetcher=lambda *_: self.fail('Duplicate ran'), force=True)
            self.assertEqual(duplicate['status'], 'not_due_or_running')
            return self.payload()
        self.assertEqual(run_sync(self.stage_id, self.factory, fetcher=during_fetch)['status'], 'unchanged')

    def test_observation_time_rejects_stale_replacements(self):
        self.setup_source()
        now = datetime.now(timezone.utc)
        run_sync(self.stage_id, self.factory, fetcher=lambda *_: self.payload(observed=now))
        result = run_sync(self.stage_id, self.factory, fetcher=lambda *_: self.payload(observed=now - timedelta(days=1)), force=True)
        self.assertEqual(result['error'], 'stale_provider_payload')

    def test_quota_is_persistent_and_failed_attempts_cannot_refund_it(self):
        for _ in range(2): reserve_request(self.factory, 'private-key', 2)
        with self.assertRaises(SyncFailure): reserve_request(self.factory, 'private-key', 2)
        with self.factory() as session:
            quota = session.scalars(select(ProviderQuota)).one()
            self.assertEqual(quota.used, 2); self.assertNotIn('private-key', quota.key)

    def test_missing_credentials_or_zero_budget_never_reserves(self):
        for key, limit in [('', 100), ('private', 0)]:
            with self.assertRaises(SyncFailure): reserve_request(self.factory, key, limit)
        with self.factory() as session: self.assertEqual(len(list(session.scalars(select(ProviderQuota)))), 0)

    def test_full_nrr_snapshot_changes_trust_revision_and_is_idempotent(self):
        self.setup_source()
        with self.factory() as session:
            state = load_snapshot(session, self.stage_id)
        self.assertFalse(state['nrr_trusted'])
        payload = self.payload(nrr={t['id']: t['nrr'] for t in state['teams']})
        first = run_sync(self.stage_id, self.factory, fetcher=lambda *_: payload)
        self.assertTrue(first['changed'])
        with self.factory() as session: self.assertTrue(load_snapshot(session, self.stage_id)['nrr_trusted'])
        self.assertFalse(run_sync(self.stage_id, self.factory, fetcher=lambda *_: payload, force=True)['changed'])

    def test_scorecard_adapter_checks_ids_teams_and_winner(self):
        provider_id, series_id = uuid4(), uuid4()
        config = SourceConfig(stage_id='manual-stage', provider='cricketdata', series_id=series_id, fixture_map={provider_id: 'm'}, team_names={'Home': 'a', 'Away': 'b'})
        fixture = {'home_id': 'a', 'away_id': 'b'}
        payload = {'status': 'success', 'data': {'id': str(provider_id), 'series_id': str(series_id), 'teams': ['Home', 'Away'], 'matchWinner': 'Away'}}
        self.assertEqual(parse_scorecard(payload, provider_id, config, fixture), 'away')
        payload['data']['matchWinner'] = ''
        self.assertIsNone(parse_scorecard(payload, provider_id, config, fixture))
        payload['data']['matchWinner'] = 'Unmapped'
        with self.assertRaises(SyncFailure): parse_scorecard(payload, provider_id, config, fixture)
        payload['data']['matchWinner'] = 'Away'; payload['data']['id'] = str(uuid4())
        with self.assertRaises(SyncFailure): parse_scorecard(payload, provider_id, config, fixture)

    def test_untrusted_final_nrr_cannot_decide_qualification(self):
        self.setup_source()
        with self.factory.begin() as session:
            for match in session.scalars(select(Fixture).where(Fixture.stage_id == self.stage_id)):
                match.outcome = 'washout'
            for i, team in enumerate(session.scalars(select(Entry).where(Entry.stage_id == self.stage_id))):
                team.nrr = float(i)
        with self.factory() as session: state = load_snapshot(session, self.stage_id)
        result = simulate(state, PredictionRequest(iterations=100).model_dump())
        self.assertTrue(all(p['status'] == 'unknown' for p in result['probabilities']))
