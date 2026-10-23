"""Transactional boundary for normalized results; no external API is called.

CLI: python -m app.import_results STAGE_ID result.json
Run with the same DATABASE_URL and JOB_MODE as the API. This is an operator
command, not a public write endpoint. Provider adapters should call apply_results.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from .database import SessionLocal
from .models import Entry, Fixture, Stage
from .schemas import Outcome


class ResultImport(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    expected_revision: int = Field(ge=1)
    outcomes: dict[str, Outcome] = Field(default_factory=dict, max_length=800)
    nrr: dict[str, float] = Field(default_factory=dict, max_length=16)


def apply_results(session, stage_id: str, payload: ResultImport):
    """Caller commits once. Failed validation must never leave partial writes."""
    stage = session.get(Stage, stage_id)
    if not stage:
        raise ValueError('Unknown stage')
    if stage.revision != payload.expected_revision:
        raise ValueError('Stage revision changed; reload before importing')
    fixtures = {f.id: f for f in session.scalars(select(Fixture).where(Fixture.stage_id == stage_id))}
    entries = {e.team_id: e for e in session.scalars(select(Entry).where(Entry.stage_id == stage_id))}
    if set(payload.outcomes) - fixtures.keys() or set(payload.nrr) - entries.keys():
        raise ValueError('Import contains a fixture or team outside this stage')
    changed = any(fixtures[k].outcome != v for k, v in payload.outcomes.items()) or any(entries[k].nrr != v for k, v in payload.nrr.items())
    if not changed:
        return stage.revision, False
    # Atomic optimistic lock works across PostgreSQL workers; all updates are
    # committed together, so readers retain the last complete snapshot.
    claim = session.execute(update(Stage).where(Stage.id == stage_id, Stage.revision == payload.expected_revision).values(revision=payload.expected_revision + 1, updated_at=datetime.now(timezone.utc).isoformat()))
    if claim.rowcount != 1:
        raise ValueError('Concurrent import changed the stage; retry from a fresh snapshot')
    for match_id, outcome in payload.outcomes.items():
        fixtures[match_id].outcome = outcome
    for team_id, nrr in payload.nrr.items():
        entries[team_id].nrr = nrr
    session.flush()
    return payload.expected_revision + 1, True


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python -m app.import_results STAGE_ID results.json')
    payload = ResultImport.model_validate_json(Path(sys.argv[2]).read_text(encoding='utf-8'))
    with SessionLocal.begin() as session:
        revision, changed = apply_results(session, sys.argv[1], payload)
    if changed:
        from .engine import load_snapshot
        from .jobs import submit
        from .schemas import PredictionRequest
        with SessionLocal() as session:
            snapshot = load_snapshot(session, sys.argv[1])
            if snapshot['rules']['schedule_complete']:
                submit(snapshot, PredictionRequest(iterations=10000).model_dump())
    print(json.dumps({'stage_id': sys.argv[1], 'revision': revision, 'changed': changed}))


if __name__ == '__main__':
    main()
