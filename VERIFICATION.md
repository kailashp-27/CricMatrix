# Verification record

## 24 October 2026 — resumed qualification review

- Fixed baseline/scenario sample pairing: picking a result no longer shifts all later random draws. Unchanged fixtures and tie-breaks use the same seeded samples. Bumped the engine cache version so earlier unpaired jobs are not reused.
- Added a source revision covering fixtures, table counts and schedule completeness. The UI sends its expected revision; the API rejects changed source data, and stale/ineligible analysis no longer leaves older estimates visible.
- Regression tests check paired-sample monotonicity across 32 seeds, source revisions independent of fetch timestamps, and API rejection of outdated revisions. These changes do not increase provider polling or modify fetched match results.
- Verification passed 74 backend tests, 9 frontend tests and the production build. The running browser calculated baseline chances, accepted a Nigeria win pick and updated all six team rows using the current source revision.

## 24 October 2026 — upcoming fixtures and qualification scenarios

- Added top navigation for Tables & predictions and Cricket across competitions. The score feed now has its own tab; table selection drives the fetched schedule and prediction workspace.
- Full `/series_info` fixtures are normalized and cached alongside series names. Result parsing requires a finished flag and either a matching structured winner or an exact team-name `won by` result. Toss statuses never become wins. Ambiguous completed results block simulation.
- Added upcoming fixture/analysis routes and async competition qualification jobs. The model requires explicit user acceptance of Top K, 2 points/win, 1/no-result, 0/loss and randomized unknown-NRR ties. Complete fetched results reconstruct simulation rows; fetched table counts must agree. Mixed-format, Test, incomplete, non-uniform/knockout and unresolved schedules are blocked.
- Added baseline vs picked-result chances and percentage-point increases/decreases for every team. Picks are debounced, completed/foreign fixtures are rejected, old calculations are aborted when inputs change, and provider results remain unchanged. Reset returns to the same baseline. Daily provider polling remains unchanged.
- Full verification passed **72 backend tests and 9 frontend domain tests**, plus the production build. New checks cover fixture normalization, missing-team reconstruction, conflicting results, completed picks, invalid schedules, conditional probability increases/decreases and the actual ASGI job round trip.
- An actual cached qualifier schedule contained 15 fixtures and passed the structural/consistency checks. Under a Top-2 equal-chance model, picking Nigeria to beat Lesotho increased Nigeria from 90.33% to 100% and reduced Lesotho from 10.07% to 0.29%. These are conditional model outputs, not official qualification probabilities.

## 24 October 2026 — replace demo dashboard with fetched provider tables

- Removed the synthetic qualification dashboard from the public React page. It no longer calls the seeded-stage catalog or prediction APIs. The database's development fixtures remain intact for backend tests; the new table API never falls back to them.
- Verified successful authenticated `/series_points` requests for all 10 discovered competitions. Five returned team rows; five returned empty lists. Rows expose the actual played/won/lost/tied/no-result counters. None of the checked tables supplied points or NRR, so those cells are null in the API and shown as dashes in the UI.
- Compared the active qualifier's fetched table with its fetched schedule: Mozambique appears in the fixtures but is omitted from the provider table. The API and UI flag this explicitly rather than adding a fabricated row.
- Added `/api/standings` with a typed response contract, database cache, failure retention and the existing 24-hour provider interval. Browser Refresh only reads the cache. Qualified spots, rankings and probabilities are not invented from incomplete provider tables.
- The full regression run passed; final affected suites passed 17 real-HTTP fixture tests and 4 ASGI tests. These include provider-counter preservation, absent metrics, empty-table behavior with seeded demo data present, error retention and missing-team warnings. Production build passed. Browser checks verified actual qualifier rows and the absence of the former RCB demo and synthetic controls.

## 24 October 2026 — daily refresh preference

Changed the local provider refresh interval and the documented defaults to 86,400 seconds at the user's request. Existing cached data remains available; the next match fetch is due 24 hours after the last successful fetch. The UI displays the interval in hours. The earlier 20-minute activation settings below are historical.

## 24 October 2026 — authenticated CricketData activation

- Saved credentials only in the Git-ignored local `.env`. No key is included in source, fixtures, documentation or public API responses.
- Authenticated `/currentMatches`, `/series`, `/series_info` and `/match_info` requests succeeded. The account reported 100 requests/day; setup and validation used 16 provider requests.
- Cached 25 matches across 10 competitions, resolving all 25 competition names by exact series ID. The first 50 generic catalog entries contained future tours and did not match the current competitions, so the implementation now caches targeted series lookups for a day, prioritizing in-progress matches.
- The provider marked 24 matches completed and one in progress. Both list and detail endpoints supplied no score for the in-progress match. This is an upstream coverage/freshness limitation; current ball-by-ball scoring is not established.
- Local configuration uses a 20-minute interval, one match page per refresh and a 90-request application budget. It is not second-by-second real-time data. Page limits remain explicit; wider coverage or faster polling needs a suitable provider allowance.
- All 13 local HTTP integration tests passed after the competition-name fix. The new regression proves that current series names resolve even when the general catalog contains only future tours.

## 24 October 2026 — cross-competition data pipeline

This section supersedes the workstation limitations recorded in the historical sections below.

- The full verification driver passed backend engine, configuration, import, route, sync, migration, live HTTP and ASGI suites. There are now **59 backend tests** (including 12 live HTTP tests and 3 ASGI tests) and **9 frontend domain tests**. Both Alembic tests ran successfully, including upgrade/downgrade through schema revision `0004`; they were not skipped. The latest API contract and result-batch changes were additionally checked in the affected suites.
- The production frontend build passed. Browser checks verified the multi-competition match feed, team search and the existing qualification explorer. A screenshot is saved locally at `artifacts/multi-competition-feed.png` (ignored by Git).
- The running API's local scheduler fetched **27 real ESPNcricinfo RSS headlines** without credentials. The publisher timestamp was **18 October 2026**, so the app correctly marked them delayed on 24 October. This proves transport and freshness handling, not current live scores.
- HTTP fixtures exercise the production client and database cache over localhost, including pagination, page limits, repeated pages, daily quotas, 429s, missing keys, malformed XML, old timestamps, lease overlap, retained snapshots, series-name discovery and generic `/match_info` result batching. These are contract-shaped local responses; authenticated CricketData access has not been verified.
- Orbit discovery worked; its candidate structured providers required accounts. The public structured ESPN endpoint returned 403 and was not used. Postman CLI is unavailable, so the HTTP fixtures use Python's local HTTP server rather than Postman simulation.
- PostgreSQL/Redis/Celery runtime, licensed-provider coverage, official tournament regulations and authoritative NRR remain unverified. The qualification examples remain synthetic. No current real qualification table or guarantee of every-tournament coverage is claimed.

Local logs: `artifacts/verification-live.log`, `artifacts/live-http-tests.log` and `artifacts/api-live.stderr.log`. These are intentionally excluded from Git.

## Frontend and ingestion update

`python scripts/verify_local.py` passed **42 backend checks and 9 frontend domain checks**. Two Alembic tests were explicitly skipped because Alembic is not installed. HTTP integration and frontend compilation were not included; the driver prints those exclusions.

The frontend checks execute the actual TypeScript projection, filtering, scenario validation, prediction identity and CSV code under Node 24. They cover points/no mutation, finished picks, prototype-name fixture IDs, stale-pick pruning, ordered tie-breakers, shared-link validation and export escaping. They do not mount React components or prove browser behavior.

The 11 ingestion checks execute database-backed source/run/quota transitions: disabled sources, atomic updates, replay/no-op handling, overlap leases, stale observations, failure preservation/redaction, daily reservations, missing credentials/budget, NRR-trust revisions and final tie uncertainty. The CricketData parser uses a synthetic response matching the documented scorecard shape; **no real provider HTTP request was made**.

The existing local database was initialized with the new additive tables without enabling a sync source or changing recorded match results. A direct stage call reported `configured: false` and the existing demo's trusted illustrative NRR. Compose/workflow configuration and Python source were checked. PostgreSQL row-lock behavior and new Alembic migration execution remain unverified here.

`npm install` was retried and failed with `ENOTFOUND registry.npmjs.org`. No bundled React, Vite, TypeScript, esbuild or Zustand installation was available as an alternative. Consequently, **no production frontend bundle, browser QA, preview URL or screenshot has been verified**. The Docker engine remained unavailable. Orbit discovery also failed DNS resolution; Postman CLI was absent, so no HTTP simulation was run.

Run `python scripts/verify_local.py --http --build` after dependency installation in a normal local/CI environment. Then run the stack smoke script and verify the provider with the actual account/plan before activation. See `docs/frontend.md` and `docs/data-pipeline.md` for the supported flows and limits.

## Phase 1 and 2 update

**31 local checks passed:** 10 mathematical, 14 configuration/runtime, 4 database/service, and 3 result-import checks. These are direct Python/SQLite checks, not evidence of a deployed PostgreSQL/Redis/Celery stack.

The new configuration checks cover complete/draft schedules, fixture totals, timezone validation, duplicate IDs and memberships, unsupported rules, operator provisioning/no-op behavior, preserving existing results, authoritative rule-table reads, optimistic revision conflicts, wins/NRR priority, legacy backfill, runtime settings and readiness when schema is missing. Fresh SQLite schemas enforce cross-stage fixture membership and outcome checks.

All four example files validated through the operator CLI and were applied to the existing local database. The catalog now contains **4 tournaments, 8 seasons and 10 stages**: the preserved earlier demos plus the new example seasons. Reapplying the IPL example returned `created: false`. A local SQLite backup was taken before initialization.

The new PostgreSQL table definitions compiled with SQLAlchemy's PostgreSQL dialect. Compose configuration and the CI workflow YAML parsed. This does not verify migration execution or server behavior.

Two Alembic migration tests were **skipped** because Alembic is unavailable. The CI workflow includes actual PostgreSQL migrations, a Celery worker and an HTTP smoke job, but has not been run here.

Dependency installation was retried: npm failed with `ENOTFOUND registry.npmjs.org`, and pip could not obtain Celery. Docker Desktop was launched, but the Linux engine still did not answer. Frontend build/browser checks and the full shared-service stack remain blocked.

## Completed in this workspace

- **10 mathematical tests passed.** Includes point conservation, no mutation, rejecting completed/foreign overrides, deterministic final NRR order, seeded reproducibility, qualification probability mass, fixed-pick behavior, and validation bounds.
- Flow feasibility matched exhaustive enumeration for **35 four-team schedules**, each considering all **27** outcomes of three unresolved fixtures, including washouts and Top-1/2/3 qualification.
- **4 database/service tests passed.** Idempotent demo seed, group isolation, health function, OpenAPI contract bounds, asynchronous local prediction round trip, cache reuse, invalid override handling and sandbox isolation.
- **3 result-import tests passed.** Atomic update/revision increment, no-op detection, stale-revision rejection, no partial write on foreign fixture IDs, and nonfinite NRR rejection.
- Python source compiled successfully with `compileall`.
- `docker compose config --quiet` passed with a temporary configuration-check password. No services were started.
- Initial milestone measurement, using the older synthetic ten-team schedule: a **10,000-run** Monte Carlo calculation plus elimination checks took **0.074 seconds** on this workstation. Qualification probabilities totaled **400%**, consistent with four qualifying places. This is one measurement, not a load-test or latency guarantee for the new schedules.

## Not verified here

- **Frontend install/build and browser interaction.** Package downloads could not resolve registry hosts; offline npm installation was missing required cache entries. No dashboard screenshot was captured and no preview server was left running.
- **ASGI HTTP integration.** FastAPI TestClient stalled when Windows asyncio tried to create its loopback socket pair in the restricted environment. The attempt was stopped. Direct route/service tests passed but do not establish HTTP transport or browser behavior. `test_api.py` remains for a normal local/CI environment.
- **PostgreSQL, Redis, Celery and Alembic runtime.** Docker Desktop's Linux engine was stopped, and Python package installation was blocked by DNS resolution. Compose validation and SQLite/service tests do not establish these runtime paths.
- **Real cricket data.** No API key was supplied or used; no provider data was fetched. No scheduled provider sync is implemented. The current scheduler recomputes demo baselines only.

## Next checks

Install dependencies with normal network access, build the frontend, start Docker Desktop, run the full unittest suite and migrations, and exercise stage switching, rapid scenario edits and reset behavior in the browser. Then implement and contract-test the selected provider adapter against confirmed series coverage and quotas.
