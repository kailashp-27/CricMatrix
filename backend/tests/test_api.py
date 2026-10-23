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
