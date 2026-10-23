# Qualification dashboard

The React/TypeScript frontend uses Zustand for its scenario state. The dashboard has separate tournament, season and group selectors, a points table, team focus, a match model, a washout slider and a filtered fixture browser.

## Interactions

- **Reality** shows stored results and a 10,000-run baseline. **What if?** applies local picks immediately and requests a debounced 1,000-run simulation.
- Choose either team or a washout for any unresolved fixture. Click a selected outcome again to undo it. Completed fixtures cannot be picked.
- Select a team in the table to highlight it, inspect points/maximum points and the sampling interval, and filter its fixtures.
- Browse remaining fixtures, completed results or all matches. More fixtures load in batches of nine.
- Change the equal/Elo model or washout probability to inspect assumptions. NRR is a snapshot value rather than a result of picking a winner.
- Picks and model settings are saved per stage in versioned browser storage. Bad or unavailable storage does not block the calculator. **Copy scenario** creates a validated URL fragment; it copies a link and does not send messages or publish data.
- **CSV** exports the currently displayed points and estimates. Unavailable or recalculating estimates stay blank. Text cells are escaped for quotes and spreadsheet formulas.

The browser checks stored data every minute while visible. Stage changes cancel old requests. New revisions remove completed/foreign picks, invalidate odds and display a notice. Prediction identity includes stage, revision, picks, model, washout probability and iteration count, so a late response cannot overwrite another scenario.

Draft schedules show their table but cannot produce predictions. Refresh failures retain a visible previous snapshot. Provider failures and stale snapshots are labeled separately from a simulation error. The API key is never used by this frontend.

## Run and verify

```powershell
cd D:\Projects\IPL\frontend
npm install
npm run dev
```

The Vite proxy expects FastAPI at `127.0.0.1:8000`. Start the backend using the main README. Then open `http://127.0.0.1:5173`.

```powershell
npm test
npm run build
```

Domain tests use Node's built-in TypeScript stripping and do not require React/Vite installation. Node 24 was used locally; Node 22.6+ supports the experimental stripping flag. The tests cover actual browser projection, no mutation, stale picks, inherited-property fixture IDs, tie-break priority, prediction identity, scenario validation, fixture filters and CSV escaping. They do **not** replace a TypeScript/Vite build or browser interaction tests.

This workstation could run those tests, but npm downloads failed with `ENOTFOUND`. A production frontend build, responsive/browser QA and screenshots have not been verified or generated yet.
