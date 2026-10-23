"""Exercise a running backend over HTTP and verify an actual queued result."""
import argparse
import json
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--expect-mode', choices=['local', 'celery'])
    parser.add_argument('--wait-seconds', type=int, default=30)
    args = parser.parse_args()

    def call(path, body=None):
        request = urllib.request.Request(args.url.rstrip('/') + path, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)

    deadline = time.monotonic() + args.wait_seconds
    while True:
        try:
            _, health = call('/api/health/ready')
            break
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise SystemExit('Backend did not become ready before the timeout')
            time.sleep(0.5)
    if args.expect_mode and health['job_mode'] != args.expect_mode:
        raise SystemExit(f'Expected {args.expect_mode} jobs but got {health["job_mode"]}')
    _, catalog = call('/api/tournaments')
    candidates = [s for t in catalog for season in t['seasons'] for s in season['stages'] if s['rules']['schedule_complete']]
    if not candidates:
        raise SystemExit('No complete stage available; seed the demo or provision a full schedule')
    stage_id = candidates[0]['id']
    _, rules = call(f'/api/stages/{stage_id}/rules')
    assert rules['rules']['team_count'] >= rules['rules']['qualifying_spots']
    status, job = call(f'/api/stages/{stage_id}/predictions', {'iterations': 100, 'seed': 123})
    assert status == 202
    for _ in range(120):
        if job['status'] in ('completed', 'failed'):
            break
        time.sleep(0.5)
        _, job = call(f'/api/predictions/{job["id"]}')
    if job['status'] != 'completed':
        raise SystemExit(f'Prediction did not complete: {job["status"]}')
    assert len(job['result']['probabilities']) == rules['rules']['team_count']
    _, cached = call(f'/api/stages/{stage_id}/predictions', {'iterations': 100, 'seed': 123})
    assert cached['id'] == job['id']
    print(json.dumps({'status': 'passed', 'database': health['database'], 'job_mode': health['job_mode'], 'stage_id': stage_id, 'cached_job_reused': True}))


if __name__ == '__main__':
    main()
