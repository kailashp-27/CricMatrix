import os
import tempfile
import time
import unittest
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[2] / 'artifacts'
TEST_ROOT.mkdir(exist_ok=True)
TEST_DIRECTORY = tempfile.TemporaryDirectory(dir=TEST_ROOT, ignore_cleanup_errors=True)
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(TEST_DIRECTORY.name) / 'test.db').as_posix()
os.environ['JOB_MODE'] = 'local'
os.environ['DEMO_SEED'] = 'true'
os.environ['LIVE_FEED_ENABLED'] = 'false'

from fastapi.testclient import TestClient
from app.main import app


class APITests(unittest.TestCase):
    def test_fetched_schedule_qualification_jobs_and_validation(self):
        import copy
        from unittest.mock import patch
        from uuid import uuid4
        from app.config import settings
        from app.database import SessionLocal
        from app.models import LiveFeed
        from app.live import series_cache_key
        from app.provider_tables import table_key
        from app.competition_predictions import team_id
        from test_competition_predictions import schedule_data, provider_rows
        schedule = schedule_data(); identity = schedule['series_id']
        keys = ['cricketdata', series_cache_key(identity), table_key(identity)]
        with patch.object(settings, 'live_feed_provider', 'cricketdata'), TestClient(app) as client:
            try:
                with SessionLocal.begin() as session:
                    session.add(LiveFeed(provider='cricketdata', payload={'matches': [{'id': str(uuid4()), 'series_id': identity, 'state': 'upcoming'}]}))
                    session.add(LiveFeed(provider=series_cache_key(identity), payload={**schedule, 'series': [{'id': identity, 'name': schedule['name']}]}))
                    rows = [{**r, 'team_id': team_id(r['name']), 'group': None, 'points': None, 'nrr': None} for r in provider_rows()]
                    session.add(LiveFeed(provider=table_key(identity), payload={'rows': rows}))
                analysis = client.get(f'/api/competitions/{identity}/analysis')
                self.assertEqual(analysis.status_code, 200)
                self.assertTrue(analysis.json()['qualification_eligible'])
                body = {'qualifying_spots': 1, 'iterations': 100, 'washout_probability': 0}
                route = f'/api/competitions/{identity}/forecast'
                self.assertEqual(client.post(route, json=body).status_code, 422)
                body['accept_points_assumptions'] = True
                completed = next(m for m in schedule['fixtures'] if m['state'] == 'completed')
                self.assertEqual(client.post(route, json={**body, 'overrides': {completed['id']: 'away'}}).status_code, 409)
                response = client.post(route, json=body)
                self.assertEqual(response.status_code, 202)
                for _ in range(100):
                    job = client.get(response.headers['Location']).json()
                    if job['status'] in {'completed', 'failed'}: break
                    time.sleep(.02)
                self.assertEqual(job['status'], 'completed')
                self.assertEqual(len(job['result']['probabilities']), 3)
                with SessionLocal() as session:
                    stored = session.get(LiveFeed, series_cache_key(identity)).payload
                    self.assertEqual(stored['fixtures'], schedule['fixtures'])
                self.assertEqual(client.get(f'/api/competitions/{uuid4()}/analysis').status_code, 404)
            finally:
                with SessionLocal.begin() as session:
                    for key in keys:
                        entity = session.get(LiveFeed, key)
                        if entity: session.delete(entity)

    def test_provider_table_endpoint_never_returns_demo_tables(self):
        with TestClient(app) as client:
            response = client.get('/api/standings')
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(result['competitions'], [])
            self.assertFalse(result['qualification_available'])
            self.assertNotIn('RCB', str(result))

    def test_live_feed_contract_is_explicit_when_paused(self):
        with TestClient(app) as client:
            response = client.get('/api/live')
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertFalse(result['enabled'])
            self.assertTrue(result['stale'])
            self.assertFalse(result['qualification_ready'])
            self.assertIsInstance(result['matches'], list)
            self.assertNotIn('apikey', result)

    def test_seed_stage_isolation_and_job_round_trip(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/health').status_code, 200)
            tournaments = client.get('/api/tournaments').json()
            self.assertEqual(len(tournaments), 4)
            stage = client.get('/api/stages/ipl-demo-0').json()
            self.assertEqual(len(stage['teams']), 10)
            a = client.get('/api/stages/wc-demo-0').json()
            b = client.get('/api/stages/wc-demo-1').json()
            self.assertFalse({t['id'] for t in a['teams']} & {t['id'] for t in b['teams']})
            pending = next(m for m in stage['fixtures'] if m['outcome'] == 'pending')
            request = {'iterations': 100, 'overrides': {pending['id']: 'washout'}}
            response = client.post('/api/stages/ipl-demo-0/predictions', json=request)
            self.assertEqual(response.status_code, 202)
            self.assertTrue(response.headers['location'].startswith('/api/predictions/'))
            job_id = response.json()['id']
            for _ in range(100):
                job = client.get(f'/api/predictions/{job_id}').json()
                if job['status'] in ('completed', 'failed'):
                    break
                time.sleep(0.02)
            self.assertEqual(job['status'], 'completed', job)
            self.assertEqual(job['result']['iterations'], 100)
            self.assertEqual(client.post('/api/stages/ipl-demo-0/predictions', json=request).json()['id'], job_id)
            self.assertEqual(client.get('/api/stages/ipl-demo-0').json()['standings'], stage['standings'])
        with TestClient(app) as client:
            self.assertEqual(len(client.get('/api/tournaments').json()), 4)

    def test_invalid_input_and_missing_resources(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/stages/missing').status_code, 404)
            self.assertEqual(client.get('/api/predictions/nonsense').status_code, 404)
            self.assertEqual(client.post('/api/stages/ipl-demo-0/predictions', json={'iterations': 999999}).status_code, 422)
            stage = client.get('/api/stages/ipl-demo-0').json()
            done = next(m for m in stage['fixtures'] if m['outcome'] != 'pending')
            self.assertEqual(client.post('/api/stages/ipl-demo-0/predictions', json={'overrides': {done['id']: 'home'}}).status_code, 422)
            self.assertEqual(client.post('/api/stages/ipl-demo-0/predictions', json={'overrides': {'foreign': 'home'}}).status_code, 422)
