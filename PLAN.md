# Crease: development plan

## Frontend and next phases update

- **Phase 3:** implemented source configuration, normalized-file feeds, a mapped CricketData scorecard adapter, persistent quotas, run history, overlap leases, stale markers and scheduled dispatch. No live source is enabled or verified. Provisioned fixture schedules are retained; automated schedule discovery and official points-table ingestion remain future work.
- **Phase 4:** existing Top-k/Monte Carlo engines are connected to the new sync and UI flow. Final NRR ties remain unknown until NRR is verified for the current revision. New data/provenance/NRR-trust revisions invalidate prediction identities.
- **Phase 5:** frontend expanded into components and a data hook, with team focus, fixture filters, saved/shared scenarios, CSV exports, rain/model controls, draft guards, periodic refresh and stale-result protection. Domain tests pass. A TypeScript/Vite build and browser QA remain blocked by unavailable dependency downloads.
- **Phase 6 / NRR:** exact score-aware NRR, calibrated future NRR modeling, tournament-stage advancement and production release are not implemented in this iteration.

See [frontend usage](docs/frontend.md), [pipeline activation](docs/data-pipeline.md) and [verification](VERIFICATION.md).

## Current focus: original Phases 1 and 2

| Requested phase | Delivered source | Verification |
| --- | --- | --- |
| 1. System architecture and stack | FastAPI, relational models, PostgreSQL pooling, Redis/Celery path, React/Zustand, Compose, readiness/liveness, HTTP smoke script and CI workflow | SQLite/service checks pass. Downloads are blocked and Docker's engine remains unavailable; shared services and frontend build still need runtime verification. |
| 2. Universal tournament configuration | Dedicated stage rules table, migration/backfill, checked season files, templates, operator provisioning, revision-safe updates, fixture membership constraints and draft guards | 14 configuration/runtime tests pass, alongside 17 existing math/service/import checks. All four examples validate and are provisioned locally. Alembic execution remains pending dependency installation. |

See [architecture](docs/architecture.md) and [configuration examples](examples/README.md) for implementation and commands. No external provider integration was added in this phase.

## First milestone

A local, stage-scoped qualification laboratory with synthetic data: FastAPI, relational storage, deterministic scenario tables, exact points elimination, asynchronous Monte Carlo, and React/Zustand. Real provider integration follows the verified demo.

## Architecture decisions

- Use FastAPI and Python math modules in one backend initially. Separate worker processes handle simulations. Two independent microservices would add deployment overhead before there is a measured need.
- PostgreSQL is the target database; SQLite is a development fallback only.
- Redis stores asynchronous job results; Celery workers run CPU work; a single Beat scheduler refreshes baseline calculations twice daily.
- Keep rules at **season/stage/group** level. Never infer a real season's rules from a tournament name or this demo's team counts.
- Teams belong to stages through entries; fixtures belong to exactly one stage. World Cup groups are independent stage examples. Advancement and carry-forward points between stages remain future work.

## Mathematical corrections

The proposed simple max-flow test establishes first-place feasibility, not Top-4 qualification. To test Top-k, enumerate the k−1 opponents allowed to finish above the target, and solve a flow problem for each candidate set. Use **points** for all capacities: source → game capacity 2; game → team capacity 2; constrained team → sink capacity target maximum minus current points. A complete integral flow allocates each match as 2/0, 1/1 or 0/2, representing either winner or a washout.

This is exact for the supported 2/0 win/loss and 1/1 washout model, with favorable unresolved points ties. An alive result is points-feasible, conditional on those assumptions. A bounded incomplete search yields unknown, never eliminated. Fully resolved tables use current supplied NRR. A final exact points/NRR tie crossing the cutoff yields unknown; display ordering uses stable IDs, while simulations randomize unresolved equal ties.

Monte Carlo randomizes future points ties rather than inventing an NRR formula. NRR remains fixed in the browser's provisional table. A sampled 0% never causes an eliminated label. Wilson intervals quantify simulation sampling error only; they do not measure probability model quality.

## Delivery sequence

| Milestone | Scope | Status |
| --- | --- | --- |
| 1. Data foundation | SQLAlchemy tables, initial Alembic migration, idempotent synthetic IPL/BBL/PSL and World Cup group seeds | SQLite checks passed; PostgreSQL/Alembic runtime pending |
| 2. Mathematical core | Deterministic standings, Top-k flow, vectorized Monte Carlo, reproducible runs | Implemented; ten core tests passed |
| 3. API and workers | Discover stages, retrieve state, submit/poll jobs; local executor and Redis/Celery modes | Four direct service checks passed; HTTP and Celery runtime pending |
| 4. Interactive dashboard | Responsive React/Zustand, outcome picks, reset, immediate points, debounced/abortable predictions | Source implemented; build verification pending dependencies |
| 5. Normalized import | Validated operator-only import, atomic revision change, no-op detection, recompute after committed results | Three tests passed; provider adapter pending |
| 6. Provider pipeline | Normalized feeds, mapped scorecard adapter, request budget, durable sync log, retries/backoff, stale markers, scheduled dispatch | Source and database/parser tests implemented; live contract/HTTP verification and automatic fixture discovery pending |
| 7. Exact NRR and tournament progression | Innings totals, legal balls, all-out/DLS rules, stage advancement, season-specific rules | Later |
| 8. Production hardening | Public rate limits, distributed queue admission, authentication for management, observability, deploy and load checks | Later |

## Provider pipeline acceptance

Choose CricketData or Sportmonks only after confirming its current plan and the required series' fixture/results coverage. API keys stay on the server. Do not assume a fixed free request allowance.

Use provider IDs scoped to series/stage. Apply transactional upserts; retain last-good data on upstream failures. Count every request, including retries and pages, against a durable daily budget. Sync only configured active series twice daily; add bounded polling or supported events near match completion if quota allows. A schedule alone does not detect a match ending. Recompute only after a committed state revision changes. Verify the adapter against recorded provider contracts before enabling live ingestion.

## Verification gates

- Compare exact elimination against exhaustive small schedules including washouts.
- Verify point conservation, fixed outcomes, completed fixtures, final tables, reproducible seeds and group isolation.
- Verify imports are idempotent and reject stale revisions and cross-stage data without partial writes.
- Verify API request validation, simulation round trip, cache reuse and scenario isolation.
- Build TypeScript/Vite; browser-check rapid toggles, resets, stage switching, narrow screens and errors.
- Test migrations and full PostgreSQL/Redis/Celery deployment before calling the Docker path verified.

No live provider is configured. All demo fixtures, standings, NRR values and ratings are synthetic. Fresh demos and example files match the illustrative per-team counts. Existing older compact demos are preserved and their rules are derived from their stored schedules.
