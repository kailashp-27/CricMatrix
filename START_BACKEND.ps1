$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment missing. Run: py -3.12 -m venv .venv, then install backend/requirements.txt.'
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'backend'
$env:JOB_MODE = 'local'
$env:DEMO_SEED = 'true'
# Check binding before Uvicorn creates its event loop, so failures are immediate.
& $python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',8010)); s.close()"
if ($LASTEXITCODE -ne 0) {
    throw 'Windows refused port 8010. Check reserved TCP ranges with: netsh interface ipv4 show excludedportrange protocol=tcp. Send that output and the error above.'
}
Write-Host 'Starting CricMatrix API: http://127.0.0.1:8010/docs' -ForegroundColor Magenta
Write-Host 'Keep this window open. Refresh http://127.0.0.1:5173 once startup completes.'
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
if ($LASTEXITCODE -ne 0) { throw 'Backend stopped with an error. Copy the error output above.' }
