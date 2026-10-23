# Season configuration examples

These are **synthetic templates**, not current official season regulations or fixtures. Check each season's regulations before using a template for real data.

| File | Teams per stage | Matches per team | Qualifying places |
| --- | --- | --- | --- |
| `ipl-season.json` | 10 | 14 | 4 |
| `bbl-season.json` | 8 | 10 | 4 |
| `psl-season.json` | 6 | 10 | 4 |
| `wc-season.json` | 4 in each of two independent groups | 3 | 2 per group |

From the project root, with backend dependencies installed:

```powershell
$env:PYTHONPATH = 'backend'
python -m app.manage validate-config examples\ipl-season.json
python -m app.manage init-demo
python -m app.manage apply-config examples\ipl-season.json
```

`apply-config` creates a new season, its stages, dedicated rules, teams, memberships and fixtures in one transaction. Reapplying identical configuration is a no-op and preserves results, NRR and ratings already updated by an operator. It rejects conflicting IDs, metadata or schedules rather than silently overwriting existing seasons.

Fixture times must include a timezone and are normalized to UTC. Every fixture must have two distinct members of its stage. Complete schedules must match the configured match count for each team. Set `schedule_complete: false` for drafts; draft stages can be inspected but cannot produce predictions.

`matches_per_team: null` permits uneven schedules; when such a schedule is marked complete, every team must appear in at least one fixture. Completeness is then an operator assertion, since no expected total was declared.

`season-config.schema.json` documents the complete file format. Supported tie-breakers are `wins` and `nrr` in priority order. The current math engine supports 2 points for a win, 0 for a loss, and 1 each for a washout. Other scoring and tie-break rules are rejected.

To revise a stage's rules, copy the `rules` object from `GET /api/stages/{id}/rules` into a JSON file, edit it, and run:

```powershell
python -m app.manage set-rules ipl-phase2-example-0 revised-rules.json --expected-revision 1
```

Use the current revision returned by the API. The operation checks membership and schedule consistency, increases the stage revision only when rules change, and rejects stale revisions. Prediction cache keys include the new rules/revision. Reload the dashboard to retrieve the updated stage.

Groups are independent qualification pools. Automatic advancement, knockout brackets and carry-forward points are outside this phase.

Regenerate the examples and schema with `python scripts\generate_examples.py`.
