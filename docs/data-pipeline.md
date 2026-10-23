# Data pipeline and activation

The pipeline updates provisioned stages. It does not let visitors spend provider quota. External credentials stay in server settings; only sanitized status fields are exposed through `/api/stages/{id}/sync` and the stage snapshot.

## Normalized file feed

Use this for operator-managed imports or a future upstream adapter. Start with `examples/sync-normalized.example.json`, which is **disabled** and targets the already-provisioned example season. Copy it, set `enabled` to true, and point `file_path` at a JSON feed file on the machine/container running the worker.

Feed format:

```json
{
  "stage_id": "ipl-phase2-example-0",
  "observed_at": "2026-10-22T00:00:00Z",
  "outcomes": {"ipl-phase2-example-0-m1": "home"},
  "nrr": {}
}
```

Use the actual UTC observation time rather than the illustrative timestamp. Outcomes may be `home`, `away` or `washout`. Missing fixtures retain their current state. Include every team's verified NRR to establish NRR trust for the resulting stage revision. A subset of NRR values may be imported, but will not establish trust for a complete table.

From the project root, after schema initialization:

```powershell
$env:PYTHONPATH = 'backend'
python -m app.sync configure my-sync-source.json
python -m app.sync run ipl-phase2-example-0 --force
```

Configuration changes receive a new stage revision. Repeated identical configuration is a no-op. `--force` bypasses the due-time check, but does not enable disabled sources, bypass a running lease or bypass quotas. Local mode runs this command manually; the Compose Celery scheduler dispatches enabled, due sources once per minute. A source's default interval is 43,200 seconds, so it normally runs twice daily. A shorter interval around matches must be chosen within the account's quota.

## CricketData adapter

The current adapter uses the vendor-documented `match_scorecard` endpoint. It updates **winner results for mapped, already-started fixtures**. Exact series, fixture and team identities are checked before any write. Finished local fixtures are not polled again; corrections use an operator import. The configured mappings must cover the entire provisioned stage.

The request path/authentication were checked against the vendor's [Python samples](https://cricketdata.org/python-code-samples/) and [official scorecard example](https://github.com/CricketData/Python-Code-Samples/blob/main/Fantasy_matchscorecard.py). Winner/series fields follow the vendor's [scorecard documentation](https://cricketdata.org/how-to-use-fantasy-cricket-api.aspx). This adapter has **not** been exercised with a live key. Confirm endpoint access and fields on your actual plan before activation.

Provision a new **manual** season with a verified complete schedule first. Demo seasons cannot be connected to real CricketData results. Then prepare a configuration like:

```json
{
  "stage_id": "your-manual-stage",
  "provider": "cricketdata",
  "enabled": false,
  "interval_seconds": 43200,
  "series_id": "00000000-0000-0000-0000-000000000001",
  "fixture_map": {"00000000-0000-0000-0000-000000000002": "your-local-match"},
  "team_names": {"Exact Provider Home Name": "local-home", "Exact Provider Away Name": "local-away"},
  "max_calls_per_run": 20
}
```

Replace every placeholder, provide all stage fixtures and team names, and keep it disabled while checking the mapping. Set `CRICKETDATA_API_KEY` and a positive `PROVIDER_DAILY_BUDGET` in the server environment, then explicitly enable the source. The default budget is zero. The provider's current plan may count requests differently or require paid endpoint access; do not infer entitlement from this example.

The adapter deliberately does not guess washouts from prose, discover official groups/playoffs, replace schedules, calculate NRR, or fetch an official points table. Confirmed no-results, corrections and authoritative NRR can be supplied through a normalized import. This limits what activation establishes: mapped winner synchronization, not a complete live-score platform.

## Failure and quota behavior

- A request is reserved in a durable daily counter **before** sending it. Retries, timeouts and failures consume reservations. Each request can retry once for a connection error or 5xx. A 429 stops the run.
- Counters are keyed by a hash of the credential and UTC date. Raw keys are not stored in the database or returned by status routes. This budget covers calls from this database; it cannot account for calls made by other apps or the provider playground.
- A database lease prevents overlapping runs. A stale worker cannot commit after losing its lease. Hard-killed workers become eligible again when the lease expires.
- Fixture/NRR changes and stage revisions commit atomically. A failure leaves the previous snapshot intact and records a sanitized failure code. Older observations, or changed content at an already-applied observation time, are rejected.
- Freshness considers both the last successful fetch and the observation time. Repeatedly reading an old file does not make its data fresh. Failed/disabled/overdue sources remain visibly stale.
- Successful changed snapshots trigger new baseline prediction jobs through the operator CLI or Celery task. Rule and NRR-trust changes also invalidate browser/cache identities through the stage revision.
- NRR is untrusted after source configuration or new results unless a complete verified NRR set accompanies the revision. Unknown NRR cannot decide qualification at a final cutoff.

Provider HTTP exceptions and URLs are not recorded as public error details. Avoid enabling verbose HTTP client request logging with a live query-string API key.

## Verification limits

Local tests execute the real database/sync state transitions with normalized in-memory fetch functions, and separately check the scorecard parser against a synthetic contract-shaped response. They do not establish real HTTP transport or the live vendor contract. Postman simulation could not run because the CLI was unavailable; Orbit discovery and package downloads failed DNS resolution. Full HTTP simulation, live-plan validation and PostgreSQL/Celery runtime verification remain required before release.
