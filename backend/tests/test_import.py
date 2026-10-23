import os
import tempfile
import unittest
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[2] / 'artifacts'
TEST_ROOT.mkdir(exist_ok=True)
TEST_DIRECTORY = tempfile.TemporaryDirectory(dir=TEST_ROOT, ignore_cleanup_errors=True)
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(TEST_DIRECTORY.name) / 'imports.db').as_posix()
os.environ['JOB_MODE'] = 'local'

from app.database import Base, engine, SessionLocal
from app.engine import load_snapshot
from app.import_results import ResultImport, apply_results
from app.seed import seed_demo


class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)
        with SessionLocal() as session:
            seed_demo(session)

    def test_atomic_idempotent_revisioned_import(self):
        with SessionLocal() as session:
            before = load_snapshot(session, 'ipl-demo-0')
            match = next(m for m in before['fixtures'] if m['outcome'] == 'pending')
            payload = ResultImport(expected_revision=before['revision'], outcomes={match['id']: 'washout'})
            revision, changed = apply_results(session, 'ipl-demo-0', payload)
            session.commit()
            self.assertTrue(changed)
            self.assertEqual(revision, before['revision'] + 1)
            self.assertEqual(next(m for m in load_snapshot(session, 'ipl-demo-0')['fixtures'] if m['id'] == match['id'])['outcome'], 'washout')
            repeat = payload.model_copy(update={'expected_revision': revision})
            self.assertEqual(apply_results(session, 'ipl-demo-0', repeat), (revision, False))
            with self.assertRaises(ValueError):
                apply_results(session, 'ipl-demo-0', payload)
            session.rollback()

    def test_invalid_import_does_not_partially_write(self):
        with SessionLocal() as session:
            before = load_snapshot(session, 'bbl-demo-0')
            match = next(m for m in before['fixtures'] if m['outcome'] == 'pending')
            with self.assertRaises(ValueError):
                apply_results(session, 'bbl-demo-0', ResultImport(expected_revision=before['revision'], outcomes={match['id']: 'home', 'foreign': 'away'}))
            session.rollback()
            self.assertEqual(load_snapshot(session, 'bbl-demo-0'), before)

    def test_nonfinite_nrr_rejected(self):
        with self.assertRaises(ValueError):
            ResultImport(expected_revision=1, nrr={'team': float('nan')})
