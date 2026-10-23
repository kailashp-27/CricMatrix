# Run Crease on your computer

The source includes the React dashboard, FastAPI API, rules engine, predictions and provider-sync foundation. The bundled tournaments are synthetic demos. No API key is needed for the demo.

## 1. Install dependencies in a normal PowerShell window

Use Python 3.12+ and Node.js 22.6+ (Node 24 recommended). From the project folder:

```powershell
cd D:\Projects\IPL
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Push-Location frontend
npm install
npm run build
Pop-Location
.\.venv\Scripts\python.exe scripts\verify_local.py --http --build
```

If you extracted the ZIP elsewhere, use that folder instead. Re-running the venv command repairs the partially created environment from this session. No activation or PowerShell execution-policy change is required.

If downloads fail in your own terminal, check `npm ping` and `Resolve-DnsName registry.npmjs.org`. This session could not resolve the npm registry; that does not establish a problem with your computer's normal internet connection. Keep TLS verification enabled.

## 2. Start the backend

In the first PowerShell window, from the project root:

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep this window open. Defaults use SQLite and the local job runner. If you previously changed `.env` to PostgreSQL/Celery, restore `DATABASE_URL=sqlite:///./crease.db`, `JOB_MODE=local`, and `DEMO_SEED=true` for this demo.

## 3. Start the frontend

In a second PowerShell window:

```powershell
cd D:\Projects\IPL\frontend
npm run dev
```

Open <http://127.0.0.1:5173>. API documentation: <http://127.0.0.1:8000/docs>.

Select a tournament/season/group, switch to What-If, pick a winner or washout, and check that points update immediately and percentages finish recalculating. Try reset, refresh, a scenario link and CSV export.

## 4. Verify the complete shared-service stack later

Start Docker Desktop and wait for its Linux engine to be running (`docker info` must succeed). From the root, create `.env` from `.env.example` if it does not already exist, and replace its example PostgreSQL password with a long random value using letters and digits. Stop the two local dev servers before using the same ports:

```powershell
docker compose up --build
```

Once services are healthy, in another terminal:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_stack.py --expect-mode celery
```

The Docker runtime, migrations and real Celery job must pass before treating this stack as verified. Provider activation is a separate step: see `docs/data-pipeline.md` for the key, positive request budget and verified real-season mappings. Leave the provider disabled while trying the demo.

## Verification from this session

- 42 backend checks and 9 frontend domain checks passed.
- Two Alembic migration checks were skipped because its package could not be installed.
- npm dependency downloads failed with `ENOTFOUND`; Python dependency installation also failed.
- Frontend compilation, browser behavior, HTTP integration, live provider requests and PostgreSQL/Redis/Celery runtime remain unverified.
- Docker's Linux engine was unavailable.

See `VERIFICATION.md` for detailed evidence. If a command fails on your computer, share that command and its complete error output.
