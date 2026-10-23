"""Multi-competition score discovery, with a durable, freshness-aware cache.

RSS supplies score headlines only. It cannot establish tournament rules, NRR,
complete schedules or even whether a match is still in progress.
"""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4
from xml.etree import ElementTree

import httpx
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .config import settings
from .database import SessionLocal
from .models import LiveFeed
from .sync import SyncFailure, reserve_request


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)  # Provider dateTimeGMT.
    return result.astimezone(timezone.utc).isoformat()


def parse_rss(content):
    if len(content) > 2_000_000 or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise SyncFailure('provider_payload_invalid')
    try:
        channel = ElementTree.fromstring(content).find('channel')
        if channel is None:
            raise ValueError('Missing channel')
        published = parsedate_to_datetime(channel.findtext('pubDate', ''))
        if published.tzinfo is None or published.timestamp() > time.time() + 300:
            raise ValueError('Invalid publication time')
        matches = []
        seen = set()
        for item in channel.findall('item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            url = urlparse(link)
            identity = re.fullmatch(r'/ci/engine/match/(\d+)\.html', url.path)
            if not title or not identity or url.hostname not in {'www.cricinfo.com', 'www.espncricinfo.com'} or url.scheme not in {'http', 'https'}:
                raise ValueError('Invalid match item')
            match_id = identity.group(1)
            if match_id in seen:
                continue
            seen.add(match_id)
            matches.append({'id': match_id, 'title': title, 'series_id': None,
                            'series_name': None, 'format': None, 'state': 'unknown',
                            'status': 'Score headline from ESPNcricinfo', 'scores': [],
                            'url': 'https://www.espncricinfo.com' + url.path})
        return {'matches': matches, 'series': [], 'observed_at': published.astimezone(timezone.utc).isoformat(),
                'timestamp_basis': 'publisher', 'truncated': False}
    except (ElementTree.ParseError, ValueError, TypeError, OverflowError):
        raise SyncFailure('provider_payload_invalid') from None


class CricketDataClient:
    """Only generic endpoints; each page spends one durable quota unit."""
    def __init__(self, factory=SessionLocal):
        self.factory = factory

    def get(self, client, endpoint, **params):
        key = settings.cricketdata_api_key.get_secret_value()
        reserve_request(self.factory, key, settings.provider_daily_budget)
        try:
            response = client.get(settings.cricketdata_base_url.rstrip('/') + '/' + endpoint,
                                  params={'apikey': key, **params})
            if response.status_code == 429:
                raise SyncFailure('provider_rate_limited')
            if response.status_code in (401, 403):
                raise SyncFailure('provider_credentials_or_plan_invalid')
            if response.status_code != 200:
                raise SyncFailure('provider_http_error')
            payload = response.json()
            if not isinstance(payload, dict) or payload.get('status') != 'success' or 'data' not in payload:
                raise SyncFailure('provider_payload_invalid')
            # Do not retain or return the envelope, which can echo the API key.
            return payload['data'], payload.get('info', {})
        except httpx.RequestError:
            raise SyncFailure('provider_unreachable') from None
        except (ValueError, TypeError):
            raise SyncFailure('provider_payload_invalid') from None

    def pages(self, client, endpoint, **params):
        rows, seen, offset = [], set(), 0
        for _ in range(settings.live_max_pages):
            data, info = self.get(client, endpoint, offset=offset, **params)
            if not isinstance(data, list) or not isinstance(info, dict):
                raise SyncFailure('provider_payload_invalid')
            if not data:
                return rows, False
            for row in data:
                if not isinstance(row, dict) or not row.get('id'):
                    raise SyncFailure('provider_payload_invalid')
                if row['id'] in seen:
                    raise SyncFailure('provider_pagination_repeated')
                seen.add(row['id']); rows.append(row)
            offset += len(data)
            total = info.get('totalRows')
            if isinstance(total, int) and offset >= total:
                return rows, False
            if total is None and len(data) < 25:
                return rows, False
        return rows, True


def parse_matches(rows):
    matches = []
    try:
        for row in rows:
            match_id = str(UUID(row['id']))
            series_id = str(UUID(row['series_id'])) if row.get('series_id') else None
            teams = row['teams']
            if not isinstance(teams, list) or len(teams) != 2 or not all(isinstance(t, str) and t for t in teams):
                raise ValueError('Invalid teams')
            title, status = row['name'], row['status']
            if not isinstance(title, str) or not isinstance(status, str):
                raise ValueError('Invalid match')
            scores = []
            for score in row.get('score') or []:
                if not isinstance(score, dict) or not all(k in score for k in ('inning', 'r', 'w', 'o')):
                    raise ValueError('Invalid score')
                scores.append(f"{score['inning']}: {score['r']}/{score['w']} ({score['o']} ov)")
            # Lack of flags is unknown, not live. Never guess completion from a score.
            state = 'completed' if row.get('matchEnded') is True else 'live' if row.get('matchStarted') is True and row.get('matchEnded') is False else 'upcoming' if row.get('matchStarted') is False else 'unknown'
            matches.append({'id': match_id, 'title': title, 'series_id': series_id, 'series_name': None,
                            'format': row.get('matchType'), 'state': state, 'status': status,
                            'scores': scores, 'starts_at': timestamp(row['dateTimeGMT']),
                            'venue': row.get('venue', ''), 'url': None})
        return matches
    except (ValueError, TypeError, KeyError, AttributeError):
        raise SyncFailure('provider_payload_invalid') from None


def fetch_feed(factory=SessionLocal):
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        if settings.live_feed_provider == 'espn_rss':
            try:
                response = client.get(settings.live_feed_url)
                if response.status_code != 200:
                    raise SyncFailure('provider_http_error')
                return parse_rss(response.content)
            except httpx.RequestError:
                raise SyncFailure('provider_unreachable') from None
        rows, truncated = CricketDataClient(factory).pages(client, 'currentMatches')
        return {'matches': parse_matches(rows), 'series': [], 'observed_at': utc_now(),
                'timestamp_basis': 'retrieval', 'truncated': truncated}


def refresh_cached(provider, interval, factory, fetcher):
    now, token = time.time(), str(uuid4())
    with factory.begin() as session:
        if session.get(LiveFeed, provider) is None:
            try:
                with session.begin_nested():
                    session.add(LiveFeed(provider=provider)); session.flush()
            except IntegrityError:
                pass
        claimed = session.execute(update(LiveFeed).where(LiveFeed.provider == provider,
            LiveFeed.next_attempt <= now, LiveFeed.lease_until <= now).values(lease_token=token, lease_until=now + 600))
        if claimed.rowcount != 1:
            return {'status': 'not_due_or_running'}
    try:
        payload = fetcher(factory)
        with factory.begin() as session:
            feed = session.get(LiveFeed, provider, with_for_update=True)
            if feed.lease_token != token or feed.lease_until <= time.time():
                return {'status': 'lease_expired'}
            if feed.payload.get('observed_at', '') > payload['observed_at']:
                raise SyncFailure('stale_provider_payload')
            feed.payload = payload; feed.last_success_at = utc_now(); feed.error_code = None
            feed.next_attempt = time.time() + interval
            feed.lease_until = 0; feed.lease_token = None
        return {'status': 'updated', 'matches': len(payload.get('matches', [])), 'series': len(payload.get('series', []))}
    except Exception as exc:
        code = str(exc) if isinstance(exc, SyncFailure) else 'provider_payload_invalid'
        with factory.begin() as session:
            session.execute(update(LiveFeed).where(LiveFeed.provider == provider, LiveFeed.lease_token == token).values(
                error_code=code, next_attempt=time.time() + interval, lease_until=0, lease_token=None))
        return {'status': 'failed', 'error': code}


def refresh_feed(factory=SessionLocal, fetcher=None):
    return refresh_cached(settings.live_feed_provider, settings.live_poll_seconds, factory, fetcher or fetch_feed)


def fetch_series(factory):
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        rows, truncated = CricketDataClient(factory).pages(client, 'series')
    series = []
    for row in rows:
        if not isinstance(row.get('name'), str):
            raise SyncFailure('provider_payload_invalid')
        try:
            identity = str(UUID(row['id']))
        except (ValueError, TypeError, AttributeError):
            raise SyncFailure('provider_payload_invalid') from None
        series.append({'id': identity, 'name': row['name'],
                       'start_date': row.get('startDate'), 'end_date': row.get('endDate')})
    return {'series': series, 'observed_at': utc_now(), 'truncated': truncated}


def refresh_series(factory=SessionLocal):
    return refresh_cached('cricketdata_series', 86400, factory, fetch_series)


def read_feed(session):
    provider = settings.live_feed_provider
    feed = session.get(LiveFeed, provider)
    payload = feed.payload if feed else {}
    catalog = session.get(LiveFeed, 'cricketdata_series') if provider == 'cricketdata' else None
    series = catalog.payload.get('series', []) if catalog else []
    names = {s['id']: s['name'] for s in series}
    matches = [{**match, 'series_name': names.get(match['series_id'])} for match in payload.get('matches', [])]
    observed = payload.get('observed_at')
    stale = not observed or time.time() - datetime.fromisoformat(observed).timestamp() > max(600, settings.live_poll_seconds * 3)
    return {**payload, 'matches': matches, 'series': series,
            'series_truncated': bool(catalog and catalog.payload.get('truncated')),
            'series_error': catalog.error_code if catalog else None,
            'provider': provider, 'enabled': settings.live_feed_enabled,
            'stale': bool(stale or not settings.live_feed_enabled or (feed and feed.error_code)),
            'last_success_at': feed.last_success_at if feed else None,
            'error': feed.error_code if feed else None, 'poll_seconds': settings.live_poll_seconds,
            'coverage': 'Matches supplied by the provider; coverage is not guaranteed for every tournament.',
            'qualification_ready': False}


def main():
    parser = argparse.ArgumentParser(description='Discover cricket across tournaments (operator only)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('refresh')
    series = commands.add_parser('series'); series.add_argument('--search', default='')
    detail = commands.add_parser('series-info'); detail.add_argument('id', type=UUID)
    detail.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'refresh':
            result = refresh_feed(); print(json.dumps(result))
            if result['status'] == 'failed':
                raise SystemExit(1)
            return
        provider = CricketDataClient()
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            if args.command == 'series':
                rows, truncated = provider.pages(client, 'series', **({'search': args.search} if args.search else {}))
                # Whitelist fields; no echoed credentials or raw envelope.
                print(json.dumps({'series': [{k: row[k] for k in ('id', 'name', 'startDate', 'endDate', 'matches') if k in row} for row in rows], 'truncated': truncated}, indent=2))
            else:
                data, _ = provider.get(client, 'series_info', id=str(args.id), offset=0)
                if not isinstance(data, dict) or not isinstance(data.get('matchList'), list):
                    raise SyncFailure('provider_payload_invalid')
                if str(data.get('info', {}).get('id')) != str(args.id):
                    raise SyncFailure('provider_series_identity_mismatch')
                args.output.write_text(json.dumps({'series': {k: data['info'][k] for k in ('id', 'name', 'startDate', 'endDate', 'matches') if k in data['info']}, 'matches': parse_matches(data['matchList']),
                    'note': 'Review coverage and stage rules before provisioning qualification. This is not a complete-schedule guarantee.'}, indent=2), encoding='utf-8')
                print(json.dumps({'output': str(args.output), 'matches': len(data['matchList'])}))
    except SyncFailure as exc:
        raise SystemExit(str(exc)) from None


if __name__ == '__main__':
    main()
