# CricMatrix

CricMatrix follows cricket across competitions and explores how remaining results can change a team's qualification chances. The app uses React and TypeScript with a FastAPI backend.

## Current data status

The score feed and the qualification explorer have different data requirements:

| Feature | Available now | Limits |
| --- | --- | --- |
| Cross-competition score feed | Public ESPNcricinfo RSS, no account required | Score headlines only; competition names, full schedules and match-state flags are absent. Publisher timestamps determine freshness. |
| Structured match discovery | CricketData adapter for T20, ODI and Test matches; authenticated requests verified | Requires your private API key, provider coverage and a positive daily request budget. Match status can be present without score details. |
| Tournament discovery | Paginated CricketData series discovery and cached competition names | Coverage depends on the provider and plan; page limits are reported explicitly. |
| Qualification explorer | IPL, BBL, PSL and World Cup **synthetic examples**, plus operator-configured seasons | Examples are not current official seasons. Real qualification requires complete stage schedules, confirmed rules, results and trusted NRR. |

**Credentials are private and are not included in this repository.** On 24 October 2026, authenticated CricketData requests returned 25 matches across 10 competitions. Series IDs were resolved directly through `/series_info`, because the generic catalog's first pages contained future tours rather than those competitions. The account reported a 100-request daily limit. The provider marked one match in progress but supplied no score in either the list or detail response; authenticated access does not establish complete real-time coverage.

The optional ESPNcricinfo public RSS request also succeeded, but its publication timestamp was 18 October 2026. The app marks such snapshots as delayed. The structured ESPN endpoint returned HTTP 403 and is not used.

CricMatrix does not claim coverage of every tournament. It accepts the competitions returned by the provider without an IPL-only allowlist. Bilateral series, knockout stages, Test championship points percentages, bonus-point leagues and other unsupported scoring systems cannot be treated as ordinary 2/1/0 qualification tables.

## Run locally on Windows

Prerequisites: Python 3.12+ and Node.js 22+.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
.\START_BACKEND.ps1
```

The script serves the API at `http://127.0.0.1:8010`. In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open [CricMatrix](http://127.0.0.1:5173/) or the [API documentation](http://127.0.0.1:8010/docs). Vite proxies `/api` to port 8010. Local mode uses SQLite and a bounded prediction worker; Redis is optional. Keep local mode to one API process. Demo startup creates missing tables and seeds examples without resetting existing results.

The local scheduler refreshes stored sources automatically. Restart the backend after changing Python files or `.env`; Vite reloads frontend changes automatically.

## Score feed configuration

Defaults in `.env.example` use the public feed:

```dotenv
LIVE_FEED_ENABLED=true
LIVE_FEED_PROVIDER=espn_rss
LIVE_FEED_URL=https://static.espncricinfo.com/rss/livescores.xml
LIVE_POLL_SECONDS=120
LIVE_MAX_PAGES=4
```

The server fetches once per interval, shares the cached result with all visitors, persists the last successful response, and uses a database lease to prevent overlapping refreshes. Browser refresh reads the cache and does not force provider requests. The browser checks once a minute while visible. Failures preserve the last snapshot and mark it stale. RSS match states stay unknown; a batting asterisk is not proof a match is live.

To use structured CricketData discovery, obtain your own key from [CricketData](https://cricketdata.org/), place it privately in `.env`, select `LIVE_FEED_PROVIDER=cricketdata`, and set `PROVIDER_DAILY_BUDGET` above zero. The key stays on the server. Do not commit it or put it in a `VITE_` variable.

The adapter calls the documented generic `/currentMatches`, `/series`, `/series_info` and `/match_info` endpoints. It follows pagination and marks lists partial when `LIVE_MAX_PAGES` is reached. Match scores retain each innings and cricket overs notation. Tournament names refresh daily. Up to 10 competitions appearing in the match feed are resolved directly by ID, prioritizing in-progress matches, and cached for a day. This avoids relying on the first pages of a catalog that may start with future tours. Missing state flags remain unknown. No automatic fallback silently substitutes RSS for a failed configured provider.

For a 100-request/day account, a cautious configuration is `LIVE_POLL_SECONDS=1200`, `LIVE_MAX_PAGES=1`, and `PROVIDER_DAILY_BUDGET=90`. One match page every 20 minutes uses 72 requests per full day, leaving room for name resolution and checks. More than one page is explicitly marked partial under this configuration. This is periodic near-live data, not second-by-second streaming. Higher request capacity permits more frequent polling but does not remove upstream delays or missing data.

**Budget deliberately:** a 900-second interval uses 96 requests/day for just one match page, before series discovery and configured-stage result syncs. Multiple pages multiply that number. All CricketData requests share the persistent UTC daily budget; failed requests still count. Choose a provider plan and interval that fit your coverage needs. Setting a local budget does not purchase provider access.

## Discover real tournaments and schedules

From the project root, using the same `.env` and database as the API:

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.live refresh
.\.venv\Scripts\python.exe -m app.live series
.\.venv\Scripts\python.exe -m app.live series --search 'World Cup'
.\.venv\Scripts\python.exe -m app.live series-info <provider-series-uuid> --output artifacts\series.json
```

`refresh` uses your selected feed. The `series` commands require a CricketData key and budget. They discover competitions rather than hardcoding IPL, BBL or PSL. Series information is for schedule review; it does not certify stage completeness or official qualification regulations. Provider responses can cover only part of a competition.

## Configure real qualification

1. Review the discovered schedule and the competition's official regulations. Separate league/group stages from finals and other knockout games.
2. Create a season definition using [the configuration examples](examples/README.md). Use real team and fixture identities, the full stage schedule, and verified qualification spots and tie-breakers. Incomplete schedules must use `schedule_complete: false`; predictions remain disabled.
3. Validate and apply it:

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.manage validate-config path\season.json
.\.venv\Scripts\python.exe -m app.manage apply-config path\season.json
```

4. Configure each stage's provider mapping using the [sync guide](docs/data-pipeline.md), then run it:

```powershell
.\.venv\Scripts\python.exe -m app.sync configure path\source.json
.\.venv\Scripts\python.exe -m app.sync run <stage-id> --force
```

Enabled sources subsequently refresh on their configured interval in both local mode and Celery mode. Fixture and exact team-name mappings must cover the entire stage. Real provider results cannot be mixed into demo seasons. Completed results update points transactionally and trigger baseline recalculation. NRR is not inferred from winners or score headlines; provider-mapped stages show unverified NRR until a complete verified NRR snapshot is imported.

There is no public configuration/write endpoint. Picks affect the scenario only, never stored match results. Reapplying an identical season definition preserves results; changes to existing rules use optimistic revisions.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/live` | Cached cross-competition scores, provider, freshness, errors and partial-coverage flags |
| GET | `/api/tournaments` | Configured qualification tournaments, seasons and stages |
| GET | `/api/stages/{id}` | Stage snapshot, standings and source freshness |
| GET | `/api/stages/{id}/rules` | Stage rules and revision |
| GET | `/api/stages/{id}/sync` | Sanitized provider sync status |
| POST | `/api/stages/{id}/predictions` | Submit or reuse a prediction job |
| GET | `/api/predictions/{id}` | Prediction job state and result |
| GET | `/api/health`, `/api/health/live`, `/api/health/ready` | Runtime checks |

Example prediction body:

```json
{"overrides": {}, "iterations": 1000, "model": "equal", "washout_probability": 0.03, "seed": 42}
```

The UI supports reality/what-if modes, per-stage saved picks, scenario links, CSV exports, fixture filters and team focus. The backend uses exact points-feasibility checks and Monte Carlo estimates with sampling intervals. Completed or foreign-stage fixtures cannot be overridden.

## Docker with PostgreSQL, Redis and Celery

Set `POSTGRES_PASSWORD` in `.env`, then:

```powershell
docker compose up --build
```

The Compose frontend uses port 5173; its API uses port 8000. Compose runs Alembic migrations, workers and Beat. Beat dispatches due stage syncs and the shared match-feed refresh. Ports bind to localhost. This is a development stack, not a public production deployment.

For a non-demo database, apply migrations before starting the API:

```powershell
$env:PYTHONPATH = 'backend'
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

Schema revision `0004` adds the persistent live-feed cache. Back up an existing production database before normal migration operations.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe scripts\verify_local.py --http --build
```

The live integration suite runs the production HTTP client against a local provider fixture server. It covers pagination, quotas, missing credentials, HTTP failures, malformed XML, stale timestamps, retained snapshots, match identities and feed leases. These tests prove adapter behavior against documented fixtures; they do not prove the coverage or timeliness of a paid provider account.

See [VERIFICATION.md](VERIFICATION.md) for recorded results and [the pipeline guide](docs/data-pipeline.md) for ingestion details. Public RSS and authenticated CricketData transport have been checked directly. Complete real-time score coverage and authoritative qualification inputs remain subject to verification.

## Model limits

Qualification currently supports 2 points per win, 1 per washout, 0 per loss, 2–16 teams per stage, and ordered wins/NRR tie-breakers. Future NRR ties are approximated; score-aware NRR, official stage advancement, arbitrary points systems, Test championship qualification and automatic validation of competition rules remain unimplemented. A sampled 0% does not establish elimination. Sampling intervals describe simulation noise, not real-world predictive accuracy.

## Provider references

- [ESPNcricinfo RSS feeds](https://www.cricinfo.com/ci/content/rss/feeds_rss_cricket.html?time=1)
- [Public score feed](https://static.espncricinfo.com/rss/livescores.xml)
- [CricketData generic API contract](https://cricketdata.org/how-to-use-cricket-data-api.aspx)
