"""Fetch provider standings directly; never substitute synthetic table values."""
import hashlib
import math
from uuid import UUID

import httpx

from .config import settings
from .database import SessionLocal
from .live import CricketDataClient, read_feed, refresh_cached, series_cache_key, utc_now
from .models import LiveFeed
from .sync import SyncFailure


def table_key(identity):
    return 'table:' + UUID(identity).hex


def integer(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise SyncFailure('provider_table_invalid')
    if isinstance(value, str) and not value.isdecimal():
        raise SyncFailure('provider_table_invalid')
    result = int(value)
    if result < 0:
        raise SyncFailure('provider_table_invalid')
    return result


def optional_number(row, keys):
    value = next((row[key] for key in keys if row.get(key) is not None), None)
    if value is None or value == '':
        return None
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number):
            raise ValueError('Invalid numeric value')
        return number
    except (ValueError, TypeError):
        raise SyncFailure('provider_table_invalid') from None


def parse_points(data):
    if not isinstance(data, list) or len(data) > 100:
        raise SyncFailure('provider_table_invalid')
    rows, seen = [], set()
    for raw in data:
        if not isinstance(raw, dict) or not isinstance(raw.get('teamname'), str) or not raw['teamname'].strip():
            raise SyncFailure('provider_table_invalid')
        name = raw['teamname'].strip()
        group = raw.get('group')
        if group is not None and not isinstance(group, str):
            raise SyncFailure('provider_table_invalid')
        identity = (group, name.casefold())
        if identity in seen:
            raise SyncFailure('provider_table_invalid')
        seen.add(identity)
        try:
            played, won, lost, tied, no_result = [integer(raw[key]) for key in ('matches', 'wins', 'loss', 'ties', 'nr')]
        except KeyError:
            raise SyncFailure('provider_table_invalid') from None
        if won + lost + tied + no_result > played:
            raise SyncFailure('provider_table_invalid')
        rows.append({'team_id': hashlib.sha256(repr(identity).encode()).hexdigest()[:16],
            'name': name, 'short_name': raw.get('shortname') if isinstance(raw.get('shortname'), str) else None,
            'group': group, 'played': played, 'won': won, 'lost': lost, 'tied': tied,
            'no_result': no_result, 'points': optional_number(raw, ('points', 'pts')),
            'nrr': optional_number(raw, ('nrr', 'netRunRate'))})
    return rows


def refresh_tables(factory=SessionLocal):
    if not settings.live_feed_enabled or settings.live_feed_provider != 'cricketdata':
        return []
    with factory() as session:
        feed = read_feed(session)
    ids = list(dict.fromkeys(m['series_id'] for m in sorted(feed['matches'], key=lambda m: m['state'] != 'live') if m['series_id']))
    results = []
    for identity in ids[:10]:
        def fetch_table(factory):
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                data, _ = CricketDataClient(factory).get(client, 'series_points', id=identity, offset=0)
            return {'rows': parse_points(data), 'observed_at': utc_now()}
        result = refresh_cached(table_key(identity), settings.live_poll_seconds, factory, fetch_table)
        results.append(result)
        if result.get('error') in {'daily_budget_exhausted', 'provider_credentials_or_budget_missing', 'provider_rate_limited'}:
            break
    return results


def read_tables(session):
    import time
    from datetime import datetime
    feed = read_feed(session)
    names = {s['id']: s['name'] for s in feed['series']}
    competitions = []
    ids = list(dict.fromkeys(m['series_id'] for m in sorted(feed['matches'], key=lambda m: m['state'] != 'live') if m['series_id']))
    for identity in ids:
        cached = session.get(LiveFeed, table_key(identity))
        observed = cached.last_success_at if cached else None
        rows = cached.payload.get('rows', []) if cached else []
        schedule = session.get(LiveFeed, series_cache_key(identity))
        known_teams = schedule.payload.get('team_names', []) if schedule else []
        supplied_names = {row['name'].casefold() for row in rows}
        missing_teams = [name for name in known_teams if name.casefold() not in supplied_names]
        stale = not settings.live_feed_enabled or not observed or time.time() - datetime.fromisoformat(observed).timestamp() > settings.live_poll_seconds * 2
        competitions.append({'id': identity, 'name': names.get(identity, f'Series {identity[:8]}'),
            'rows': rows, 'fetched_at': observed, 'stale': bool(stale or (cached and cached.error_code)),
            'status': 'failed' if cached and cached.error_code else 'available' if rows else 'unavailable' if observed else 'pending',
            'error': cached.error_code if cached else None,
            'missing_teams': missing_teams,
            'points_available': bool(rows) and all(r['points'] is not None for r in rows),
            'nrr_available': bool(rows) and all(r['nrr'] is not None for r in rows)})
    return {'provider': 'cricketdata', 'poll_seconds': settings.live_poll_seconds,
            'competitions': competitions, 'qualification_available': False,
            'note': 'Team rows are fetched from CricketData series_points. Missing points, NRR and qualification odds are not estimated. Provider coverage may be incomplete.'}
