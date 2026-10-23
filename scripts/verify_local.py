"""Run isolated backend suites and dependency-free frontend domain checks.

Use --http to include ASGI integration tests on hosts allowing local sockets.
Use --build after installing frontend dependencies to also compile the UI.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--http', action='store_true')
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'backend'), 'LIVE_FEED_ENABLED': 'false'}
    patterns = ['test_engine.py', 'test_configuration.py', 'test_import.py', 'test_routes.py', 'test_sync.py', 'test_migrations.py', 'test_live.py', 'test_competition_predictions.py']
    if args.http:
        patterns.append('test_api.py')
    failures = []
    for pattern in patterns:
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'backend/tests', '-p', pattern, '-v'], cwd=ROOT, env=env, timeout=60)
        if result.returncode: failures.append(pattern)
    node = shutil.which('node')
    if node:
        result = subprocess.run([node, '--experimental-strip-types', '--test', 'frontend/tests/domain.test.ts'], cwd=ROOT, timeout=30)
        if result.returncode: failures.append('frontend domain tests')
    else:
        failures.append('Node.js not found')
    if args.build:
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            failures.append('npm not found')
        elif subprocess.run([npm, 'run', 'build'], cwd=ROOT / 'frontend', timeout=120).returncode:
            failures.append('frontend build')
    if failures:
        raise SystemExit('Checks failed: ' + ', '.join(failures))
    print('Requested checks passed. Skipped migration tests, if reported above, remain unverified.')
    if not args.http:
        print('HTTP integration was not requested; use --http in an unrestricted local environment.')
    if not args.build:
        print('Frontend compilation was not requested; use --build after npm install.')


if __name__ == '__main__':
    main()
