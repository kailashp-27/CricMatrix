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

Configuration changes receive a new stage revision. Repeated identical configuration is a no-op. `--force` bypasses the due-time check, but does not enable disabled sources, bypass a running lease or bypass quotas. Local mode checks enabled, due sources every 30 seconds; Compose Celery Beat dispatches them once per minute. A source's default interval is 43,200 seconds, so it normally runs twice daily. A shorter interval around matches must be chosen within the account's quota.

## CricketData adapter

The adapter uses the generic `match_info` endpoint. It updates **winner results for mapped, already-started fixtures**. Exact series, fixture and team identities are checked before any write. Finished local fixtures are not polled again; corrections use an operator import. The configured mappings must cover the entire provisioned stage. If a newly configured season has many completed games, each run processes up to `max_calls_per_run` pending local fixtures in start-time order; subsequent runs catch up the rest.

The path, query authentication, pagination and winner/series fields were checked against the vendor's [generic API documentation](https://cricketdata.org/how-to-use-cricket-data-api.aspx). This avoids requiring the fantasy scorecard endpoint just to obtain a winner. The adapter has **not** been exercised with a live key. Confirm endpoint access and fields on your actual plan before activation.

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

Local tests execute database/sync state transitions and the production HTTP client against local provider contract fixtures. They exercise score-feed pagination, rate limits, daily budgets, stale publication times, malformed responses, retained snapshots, competition names and generic `match_info` result imports. Postman CLI is unavailable; these tests use a local HTTP fixture server instead. Orbit discovery ran successfully but its suggested structured APIs required accounts. An actual public RSS fetch returned 27 match headlines, with an old publication timestamp correctly marked stale. Authenticated provider-plan validation and PostgreSQL/Celery runtime verification remain outstanding.

## Cross-competition score discovery

`app.live` maintains a separate `live_feeds` cache added by migration `0004`. It never writes score headlines into qualification fixtures. The public `/api/live` endpoint only reads the cache; visitors cannot force upstream calls. Local scheduling and Celery Beat use the same due-time and lease guards.

The default public ESPNcricinfo RSS feed requires no credential. Match states and competition identities are not supplied, so they remain unknown. Freshness uses the publisher's `pubDate`, not the time of the HTTP request. A stale upstream feed stays stale even if it is fetched successfully every two minutes.

Selecting `LIVE_FEED_PROVIDER=cricketdata` enables generic `/currentMatches` discovery plus daily `/series` name discovery with server-side credentials. Each page reserves a request from the same daily budget used by stage syncs. Pagination is bounded by `LIVE_MAX_PAGES`; partial coverage is explicit. Errors do not silently switch providers. Operator commands discover series by name and export `/series_info` schedules for review; see the [README](../README.md) for setup and examples. Complete schedules, official stage rules and trusted NRR still require verification before using real qualification estimates.
