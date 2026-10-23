"""Route/service checks that do not require a localhost socket or event loop.

Run separately from test_api.py, which verifies the actual ASGI HTTP contract.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[2] / 'artifacts'
TEST_ROOT.mkdir(exist_ok=True)
TEST_DIRECTORY = tempfile.TemporaryDirectory(dir=TEST_ROOT, ignore_cleanup_errors=True)
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(TEST_DIRECTORY.name) / 'routes.db').as_posix()
os.environ['JOB_MODE'] = 'local'

from fastapi import HTTPException, Response
from app.database import Base, engine, SessionLocal
from app.main import app, health, prediction, prediction_result, stage, tournaments
from app.schemas import PredictionRequest
from app.seed import seed_demo


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)
        with SessionLocal() as session:
            seed_demo(session)
            seed_demo(session)

    def test_stage_isolation_seed_idempotence_and_health(self):
        with SessionLocal() as session:
            self.assertEqual(health(session)['status'], 'ok')
            self.assertEqual(len(tournaments(session)), 4)
            self.assertEqual(len(stage('ipl-demo-0', session)['teams']), 10)
            a, b = stage('wc-demo-0', session), stage('wc-demo-1', session)
            self.assertFalse({t['id'] for t in a['teams']} & {t['id'] for t in b['teams']})

    def test_async_job_roundtrip_cache_and_sandbox_isolation(self):
        with SessionLocal() as session:
            initial = stage('ipl-demo-0', session)
            match = next(m for m in initial['fixtures'] if m['outcome'] == 'pending')
            request = PredictionRequest(iterations=100, overrides={match['id']: 'washout'})
            response = Response()
            queued = prediction('ipl-demo-0', request, response, session)
            self.assertEqual(response.headers['location'], f'/api/predictions/{queued["id"]}')
            for _ in range(100):
                result = prediction_result(queued['id'])
                if result['status'] in ('completed', 'failed'):
                    break
                time.sleep(0.02)
            self.assertEqual(result['status'], 'completed', result)
            self.assertEqual(result['result']['iterations'], 100)
            self.assertEqual(prediction('ipl-demo-0', request, Response(), session)['id'], queued['id'])
            self.assertEqual(stage('ipl-demo-0', session)['standings'], initial['standings'])

    def test_route_rejects_bad_or_completed_overrides(self):
        with SessionLocal() as session:
            initial = stage('ipl-demo-0', session)
            completed = next(m for m in initial['fixtures'] if m['outcome'] != 'pending')
            for match_id in (completed['id'], 'foreign'):
                with self.assertRaises(HTTPException) as error:
                    prediction('ipl-demo-0', PredictionRequest(overrides={match_id: 'home'}), Response(), session)
                self.assertEqual(error.exception.status_code, 422)
            with self.assertRaises(HTTPException) as error:
                stage('missing', session)
            self.assertEqual(error.exception.status_code, 404)

    def test_openapi_contract(self):
        contract = app.openapi()
        path = contract['paths']['/api/stages/{stage_id}/predictions']['post']
        self.assertIn('202', path['responses'])
        self.assertIn('422', path['responses'])
        self.assertEqual(contract['components']['schemas']['PredictionRequest']['properties']['iterations']['maximum'], 10000)
