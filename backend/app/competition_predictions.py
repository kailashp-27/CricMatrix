"""Exploratory forecasts from fetched records and complete, single-stage fixtures."""
import hashlib
import json
import math
from collections import Counter
from itertools import combinations

from .competition_fixtures import read_fixtures
from .provider_tables import read_tables


def team_id(name):
    return hashlib.sha256(name.casefold().encode()).hexdigest()[:16]


def record_rate(row):
    if row is None:
        return 0.5
    return (row['won'] + 1) / (row['won'] + row['lost'] + 2)


def fixture_snapshot(schedule, provider_rows, qualifying_spots):
    fixtures = schedule['fixtures']
    if not schedule['schedule_complete']:
        raise ValueError('The provider has not supplied a complete series schedule.')
    names = sorted({team for m in fixtures for team in m['teams']})
    if not 2 <= len(names) <= 16:
        raise ValueError('Qualification simulation supports 2–16 teams.')
    if not 1 <= qualifying_spots <= len(names):
        raise ValueError('Qualifying spots must be between 1 and the number of teams.')
    formats = {m['format'] for m in fixtures}
    if len(formats) != 1 or next(iter(formats)) not in {'t10', 't20', 'odi'}:
        raise ValueError('Qualification requires one limited-overs format; mixed-format tours and Tests are unsupported.')
    pairs = Counter(tuple(sorted(m['teams'])) for m in fixtures)
    if set(pairs) != set(combinations(names, 2)) or len(set(pairs.values())) != 1:
        raise ValueError('This series is not a complete uniform league/group schedule; knockout or mixed stages need verified stage separation.')
    if any(m['unresolved_result'] or m['state'] == 'unknown' for m in fixtures):
        raise ValueError('Some provider results or match states are unresolved. They cannot be treated as future results.')
    counts = {name: {'played': 0, 'won': 0, 'lost': 0, 'no_result': 0} for name in names}
    for match in fixtures:
        if match['outcome'] is None:
            continue
        a, b = match['teams']
        counts[a]['played'] += 1; counts[b]['played'] += 1
        if match['outcome'] == 'washout':
            counts[a]['no_result'] += 1; counts[b]['no_result'] += 1
        else:
            winner, loser = (a, b) if match['outcome'] == 'home' else (b, a)
            counts[winner]['won'] += 1; counts[loser]['lost'] += 1
    for row in provider_rows:
        if row['name'] not in counts or any(row[key] != counts[row['name']][key] for key in ('played', 'won', 'lost', 'no_result')) or row['tied']:
            raise ValueError('Fetched table counts and fixture results disagree, or a tied result needs review.')
    by_name = {r['name']: r for r in provider_rows}
    teams = []
    for name in names:
        # Missing table rows can be reconstructed from the complete fetched
        # schedule. The source of these simulation rows is explicitly labelled.
        rate = record_rate(counts[name])
        teams.append({'id': team_id(name), 'name': name, 'short_name': by_name.get(name, {}).get('short_name') or name[:8],
            'color': '#b99aff', 'nrr': 0, 'rating': 1500 + 400 * math.log10(rate / (1 - rate))})
    state = json.dumps({'fixtures': fixtures, 'rows': provider_rows}, sort_keys=True)
    return {'stage_id': schedule['series_id'], 'season_id': schedule['series_id'], 'name': schedule['name'],
        'source': 'provider', 'revision': int(hashlib.sha256(state.encode()).hexdigest()[:8], 16),
        'updated_at': schedule['fetched_at'], 'nrr_trusted': False,
        'rules': {'team_count': len(names), 'qualifying_spots': qualifying_spots, 'matches_per_team': None,
            'win_points': 2, 'loss_points': 0, 'washout_points': 1, 'tie_breakers': ['nrr'],
            'stage_format': 'league', 'regulation_overs': {'t10': 10, 't20': 20, 'odi': 50}[next(iter(formats))], 'schedule_complete': True},
        'teams': teams, 'fixtures': [{'id': m['id'], 'home_id': team_id(m['teams'][0]), 'away_id': team_id(m['teams'][1]),
            'starts_at': m['starts_at'], 'venue': m['venue'], 'outcome': m['outcome'] or 'pending'} for m in fixtures]}


def competition_analysis(session, identity):
    schedule = read_fixtures(session, identity)
    table = next(c for c in read_tables(session)['competitions'] if c['id'] == identity)
    records = {row['name']: row for row in table['rows']}
    try:
        snapshot = fixture_snapshot(schedule, table['rows'], 1)
        reason, eligible = None, True
        teams = [{'id': t['id'], 'name': t['name']} for t in snapshot['teams']]
        from .engine import standings
        records = {row['name']: row for row in standings(snapshot)}
    except ValueError as exc:
        reason, eligible = str(exc), False
        teams = [{'id': team_id(name), 'name': name} for name in sorted({t for m in schedule['fixtures'] for t in m['teams']})]
    single_format = len({m['format'] for m in schedule['fixtures']}) == 1
    forecasts = []
    for match in schedule['fixtures']:
        if match['state'] == 'completed':
            continue
        a, b = match['teams']
        supported = match['format'] in {'t10', 't20', 'odi'}
        rates = [record_rate(records.get(name)) for name in (a, b)]
        enough = single_format and all(name in records and records[name]['won'] + records[name]['lost'] > 0 for name in (a, b))
        pa, pb = rates
        chance = pa * (1 - pb) / (pa * (1 - pb) + pb * (1 - pa)) if enough else None
        forecasts.append({'fixture_id': match['id'], 'equal_home_pct': 50.0 if supported else None,
            'record_home_pct': round(chance * 100, 1) if supported and chance is not None else None,
            'record_samples': {name: (records[name]['won'] + records[name]['lost']) if name in records else 0 for name in (a, b)},
            'note': 'Exploratory estimate from smoothed win/loss records; no player, venue or in-play score model.' if enough else 'Comparable win/loss records are unavailable. Only an explicitly chosen equal-chance model is available.'})
    return {**schedule, 'forecasts': forecasts, 'teams': teams, 'qualification_eligible': eligible,
        'qualification_blocker': reason, 'simulation_basis': 'Reconstructed from complete fetched fixture results, not filled-in provider table values.',
        'assumptions': ['User-selected Top K under a 2 points/win, 1/no-result, 0/loss model.',
            'NRR is unavailable; points ties are randomized. These are scenario-model estimates, not official qualification forecasts.']}
