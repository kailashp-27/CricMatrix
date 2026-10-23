# Crease

A cricket qualification lab: change the remaining results, see the points table move, and estimate each team's path to the next round.

The runtime foundation, stage-rules engine, prediction algorithms, expanded frontend and ingestion pipeline are implemented in source. See [architecture](docs/architecture.md), [frontend guide](docs/frontend.md), [data pipeline](docs/data-pipeline.md) and [configuration examples](examples/README.md). PostgreSQL/Redis/Celery runtime and frontend build/browser verification are still blocked in this workstation environment; see [verification](VERIFICATION.md).

The project includes synthetic IPL, BBL, PSL and T20 World Cup group examples. It does **not** contain current fixtures, live scores or verified official season rules.

## What's implemented

- React + TypeScript dashboard with Zustand, reality/what-if modes and responsive styling.
- Team focus, remaining/results fixture filters, per-stage saved picks, scenario links, CSV export, washout controls and refresh notices.
- Instant browser-side points updates; debounced 1,000-run scenario predictions and 10,000-run baseline predictions.
- Python/FastAPI, SQLAlchemy models, PostgreSQL configuration and a SQLite development option.
- Exact Top-k points elimination using candidate-set enumeration and NetworkX max flow, including washouts.
- NumPy Monte Carlo with equal or illustrative Elo-based win probabilities, reproducible seeds and sampling intervals.
- Async prediction jobs, state-aware cache keys, Redis/Celery integration, and a bounded local runner.
- Initial Alembic migration and transactional operator import with optimistic revision checks.
- A dedicated rules table, validated season provisioning, schedule completeness guards, ordered wins/NRR tie-breakers and revision-safe rule updates.
- Docker Compose for the database, Redis, API, worker, scheduler and frontend.
- Durable sync configuration/run history, daily provider request budgets, overlap leases, stale-data status and post-sync recalculation. CricketData activation requires a real key, verified mappings and a positive budget.

Read [PLAN.md](PLAN.md) for the architecture, mathematics and remaining milestones.

## Configure a tournament season

Four versioned example files and a JSON Schema are provided under `examples`. Their match counts follow the illustrative 10-team/14-match IPL-style, 8-team/10-match BBL-style, 6-team/10-match PSL-style and two four-team World Cup group setups. They are not official season schedules or regulations.

```powershell
$env:PYTHONPATH = 'backend'
python -m app.manage validate-config examples\ipl-season.json
python -m app.manage init-demo
python -m app.manage apply-config examples\ipl-season.json
```

Provisioning creates a new season atomically. Reapplying the same configuration preserves recorded results. Draft/incomplete schedules can be stored but cannot be used for predictions. See [examples/README.md](examples/README.md) for group configuration and safe rule updates.

## Start locally on Windows

Python 3.12+ and Node.js 22+ are recommended. From `D:\Projects\IPL`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd D:\Projects\IPL\frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 and API documentation at http://127.0.0.1:8000/docs. Vite proxies `/api` to the backend. First startup creates a local `crease.db` and seeds the demo. Keep the local runner to a single API process; its jobs are in memory and disappear on restart.

No provider key is needed for the demo. Local mode does not require Redis or Celery to be running. The full requirements include Celery for the Docker path.

## Start with PostgreSQL, Redis and Celery

Start Docker Desktop with Linux containers. Create `.env` from `.env.example`, replace `POSTGRES_PASSWORD` with a long random value using URL-safe characters, then:

```powershell
docker compose up --build
```

Open http://127.0.0.1:5173. The API applies migrations before startup. The worker runs simulations and Beat refreshes baselines at 00:00 and 12:00 UTC. A separate minute dispatcher schedules enabled, due sync sources according to their interval (twice daily by default). **No provider source is enabled by default.** Database and Redis ports are internal; web ports bind to localhost. This is a local development stack, not a public production deployment.

For a non-demo database, set `DEMO_SEED=false` and apply `alembic upgrade head` from `backend` before starting the API. Alembic reads `DATABASE_URL`; local API startup creates tables only when demo seeding is enabled.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Database and configured Redis connectivity |
| GET | `/api/health/live` | API liveness without dependency checks |
| GET | `/api/health/ready` | Database/schema and configured Redis readiness |
| GET | `/api/tournaments` | Tournaments, seasons, stages and rules |
| GET | `/api/rule-templates` | Illustrative league/group configurations |
| GET | `/api/stages/{id}/rules` | Authoritative rules and current revision |
| GET | `/api/stages/{id}/sync` | Sanitized provider freshness/status |
| GET | `/api/stages/{id}` | Stage snapshot and standings |
| POST | `/api/stages/{id}/predictions` | Submit/reuse a job; HTTP 202 and Location header |
| GET | `/api/predictions/{id}` | queued/running/completed/failed job state |

Example prediction body:

```json
{"overrides": {}, "iterations": 1000, "model": "equal", "washout_probability": 0.03, "seed": 42}
```

`overrides` maps an unresolved fixture ID to `home`, `away` or `washout`. Completed or foreign-stage fixtures are rejected. Iterations are limited to 100–10,000. Jobs expire after one hour; cache identity includes the complete stage state, revision, request and engine version. Scenario calls do not write fixture results.

## Import normalized results

There is no public write endpoint. An operator can update a configured stage through a local JSON file:

```json
{"expected_revision": 1, "outcomes": {"ipl-demo-0-m31": "home"}, "nrr": {"ipl-CSK": 0.321}}
```

Use actual fixture/team IDs and the current revision from the stage endpoint. From `backend`, with the same database environment as the API:

```powershell
..\.venv\Scripts\python.exe -m app.import_results ipl-demo-0 results.json
```

The import validates all IDs before writing, commits changes atomically, increases the revision only when state changes, and requests a new baseline after commit. Retrying the same values at the current revision is a no-op. The newer [sync pipeline](docs/data-pipeline.md) wraps ingestion in leases, freshness checks, run history and request budgets. The browser checks stored snapshots every minute while visible; this is polling rather than push notification.

## Verification

From the project root, with dependencies installed:

```powershell
python scripts\verify_local.py
```

This runs backend suites in separate processes and dependency-free frontend logic tests. Add `--http --build` in a normal environment with installed dependencies to include ASGI and frontend build checks. Individual commands:

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
cd frontend
npm run build
```

Core tests compare flow feasibility with all 27 outcomes of each of 35 small schedules. Additional tests cover final NRR order, point conservation, fixed picks, reproducibility, seed idempotence, groups, jobs, ingestion failures, leases, request budgets and frontend domain behavior. `test_api.py` uses FastAPI TestClient; `test_routes.py` checks service/route behavior directly where localhost event-loop sockets are unavailable.

## Model limits

The supported scoring model is 2 points for a win, 0 for a loss, and 1 each for a washout. Ordered wins/NRR tie-breakers are configurable; future NRR ties are randomized in simulations. NRR stays at its snapshot value in the what-if table because a winner alone cannot determine runs or legal balls. Final ties across every configured criterion use team ID for stable display ordering, but qualification status remains unknown at a tied cutoff and simulations randomly break the remaining tie until further official rules are configured.

“Alive” means a points-feasible path allowing favorable unresolved tie-breaks and washouts. A simulation's 0% result alone does not imply elimination. The 95% intervals describe Monte Carlo sampling uncertainty, not real-world model uncertainty. A flow search that reaches its safety limit returns unknown.

Live-provider activation/contract verification, automatic fixture discovery, exact score-aware NRR, stage advancement, public API throttling and production deployment remain future milestones. Dependencies need online installation; a frontend lockfile should be committed after a successful install. See `VERIFICATION.md` for checks actually completed in this environment.
