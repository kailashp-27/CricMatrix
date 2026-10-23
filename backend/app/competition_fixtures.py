"""Normalized full series schedules, kept separate from partial current-match feeds."""
from uuid import UUID

from .config import settings
from .live import read_feed, series_cache_key, timestamp
from .models import LiveFeed
from .sync import SyncFailure


def normalize_schedule(data):
    raw_matches = data.get('matchList')
    if not isinstance(raw_matches, list) or len(raw_matches) > 800:
        raise SyncFailure('provider_schedule_invalid')
    fixtures, seen = [], set()
    for raw in raw_matches:
        try:
            identity = str(UUID(raw['id']))
            teams = raw['teams']
            if identity in seen or not isinstance(teams, list) or len(teams) != 2 or not all(isinstance(t, str) and t.strip() for t in teams) or teams[0] == teams[1]:
                raise ValueError('Invalid fixture identity')
            seen.add(identity)
            status = raw.get('status', '')
            if not isinstance(status, str):
                raise ValueError('Invalid status')
            ended = raw.get('matchEnded') is True
            started = raw.get('matchStarted') is True
            outcome = None
            if ended:
                winner = raw.get('matchWinner')
                if winner in teams:
                    outcome = 'home' if winner == teams[0] else 'away'
                else:
                    winners = [i for i, team in enumerate(teams) if status.casefold().startswith(team.casefold() + ' won by ') or status.casefold() == team.casefold() + ' won']
                    if len(winners) == 1:
                        outcome = 'home' if winners[0] == 0 else 'away'
                    elif status.strip().casefold() in {'no result', 'match abandoned', 'match abandoned without a ball bowled', 'match abandoned without a ball being bowled'}:
                        outcome = 'washout'
            fixtures.append({'id': identity, 'name': raw.get('name') or ' vs '.join(teams),
                'teams': teams, 'starts_at': timestamp(raw['dateTimeGMT']), 'venue': raw.get('venue') or 'Venue not supplied',
                'format': raw.get('matchType'), 'state': 'completed' if ended else 'live' if started else 'upcoming' if raw.get('matchStarted') is False else 'unknown',
                'status': status, 'outcome': outcome, 'unresolved_result': ended and outcome is None})
        except (KeyError, ValueError, TypeError, AttributeError):
            raise SyncFailure('provider_schedule_invalid') from None
    expected = data.get('info', {}).get('matches')
    complete = isinstance(expected, int) and not isinstance(expected, bool) and expected == len(fixtures) and bool(fixtures)
    return {'fixtures': sorted(fixtures, key=lambda m: (m['starts_at'], m['id'])),
            'schedule_complete': complete, 'expected_matches': expected if isinstance(expected, int) else None}


def read_fixtures(session, identity):
    identity = str(UUID(identity))
    feed = read_feed(session)
    if identity not in {m['series_id'] for m in feed['matches']}:
        raise KeyError(identity)
    cached = session.get(LiveFeed, series_cache_key(identity))
    payload = cached.payload if cached else {}
    name = next((s['name'] for s in payload.get('series', []) if s['id'] == identity), f'Series {identity[:8]}')
    return {'series_id': identity, 'name': name, 'fixtures': payload.get('fixtures', []),
            'schedule_complete': payload.get('schedule_complete', False), 'expected_matches': payload.get('expected_matches'),
            'fetched_at': cached.last_success_at if cached else None,
            'error': cached.error_code if cached else None, 'poll_seconds': settings.live_poll_seconds,
            'note': 'Fetched series fixtures. Completed results stay fixed; unresolved provider results cannot be simulated as future matches.'}
