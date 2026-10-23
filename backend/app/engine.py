"""Points-based qualification, with explicit assumptions about unknown future NRR."""
from itertools import combinations
from math import sqrt

import networkx as nx
import numpy as np
from sqlalchemy import select

from .models import Entry, Fixture, Season, Stage, SyncSource, Team
from .schemas import Rules
from .rules import get_rules, validate_schedule


def load_snapshot(session, stage_id):
    # Shared row lock on PostgreSQL lets readers coexist while preventing a
    # revision writer from committing halfway through the snapshot's queries.
    stage = session.get(Stage, stage_id, with_for_update={'read': True})
    if not stage:
        raise KeyError(stage_id)
    season = session.get(Season, stage.season_id)
    rules = get_rules(session, stage).model_dump()
    teams = []
    for entry, team in session.execute(select(Entry, Team).join(Team, Entry.team_id == Team.id).where(Entry.stage_id == stage_id).order_by(Team.id)):
        teams.append({'id': team.id, 'name': team.name, 'short_name': team.short_name,
                      'color': team.color, 'nrr': entry.nrr, 'rating': entry.rating})
    if not 2 <= len(teams) <= 16 or rules['qualifying_spots'] > len(teams):
        raise ValueError('A supported stage needs 2–16 teams and qualifying spots no greater than its team count')
    fixtures = [{key: getattr(f, key) for key in ['id', 'home_id', 'away_id', 'starts_at', 'venue', 'outcome']}
                for f in session.scalars(select(Fixture).where(Fixture.stage_id == stage_id).order_by(Fixture.starts_at, Fixture.id))]
    validate_schedule(Rules.model_validate(rules), [t['id'] for t in teams], fixtures)
    source = session.get(SyncSource, stage_id)
    nrr_trusted = source is None or source.nrr_verified_revision == stage.revision
    return {'stage_id': stage.id, 'season_id': season.id, 'name': stage.name, 'source': season.source,
            'revision': stage.revision, 'updated_at': stage.updated_at, 'rules': rules,
            'teams': teams, 'fixtures': fixtures, 'nrr_trusted': nrr_trusted}


def validate_overrides(snapshot, overrides):
    fixtures = {m['id']: m for m in snapshot['fixtures']}
    for match_id, outcome in overrides.items():
        if match_id not in fixtures:
            raise ValueError(f'Unknown fixture: {match_id}')
        if fixtures[match_id]['outcome'] != 'pending':
            raise ValueError(f'Completed fixture cannot be changed: {match_id}')
        if outcome not in ('home', 'away', 'washout'):
            raise ValueError('Invalid fixture outcome')


def standings(snapshot, overrides=None):
    overrides = overrides or {}
    validate_overrides(snapshot, overrides)
    rows = {t['id']: {**t, 'played': 0, 'won': 0, 'lost': 0, 'washouts': 0, 'points': 0, 'remaining': 0} for t in snapshot['teams']}
    rules = snapshot['rules']
    for match in snapshot['fixtures']:
        home, away = rows[match['home_id']], rows[match['away_id']]
        outcome = overrides.get(match['id'], match['outcome'])
        if outcome == 'pending':
            home['remaining'] += 1
            away['remaining'] += 1
            continue
        home['played'] += 1
        away['played'] += 1
        if outcome == 'washout':
            for team in (home, away):
                team['points'] += rules['washout_points']
                team['washouts'] += 1
        else:
            winner, loser = (home, away) if outcome == 'home' else (away, home)
            winner['points'] += rules['win_points']
            winner['won'] += 1
            loser['points'] += rules['loss_points']
            loser['lost'] += 1
    result = sorted(rows.values(), key=lambda t: tuple([-v for v in ranking_values(t, rules)] + [t['id']]))
    for rank, team in enumerate(result, 1):
        team['rank'] = rank
        team['max_points'] = team['points'] + rules['win_points'] * team['remaining']
    return result


def ranking_values(team, rules):
    return (team['points'], *(team['won'] if field == 'wins' else team['nrr'] for field in rules.get('tie_breakers', ['nrr'])))


def known_final_values(team, snapshot):
    values = [team['points']]
    for field in snapshot['rules'].get('tie_breakers', ['nrr']):
        if field == 'nrr' and not snapshot.get('nrr_trusted', True):
            break
        values.append(team['won'] if field == 'wins' else team['nrr'])
    return tuple(values)


def elimination(snapshot, overrides=None):
    """Exact Top-k feasibility with favorable ties and all 2-point splits.

    Enumerate up to k-1 opponents allowed above target. Allocate remaining
    points using integral flow. A game's flow of (2,0), (1,1), or (0,2)
    corresponds to a home win, washout, or away win. Target wins its games.
    Future NRR is unconstrained: 'alive' means alive on points, not a promise.
    Bound the search; never label a team eliminated after an incomplete search.
    """
    if not snapshot['rules'].get('schedule_complete', True):
        raise ValueError('Predictions require a complete fixture schedule')
    overrides = overrides or {}
    rows = standings(snapshot, overrides)
    remaining = [m for m in snapshot['fixtures'] if m['outcome'] == 'pending' and m['id'] not in overrides]
    k = snapshot['rules']['qualifying_spots']
    if not any(m['outcome'] == 'pending' for m in snapshot['fixtures']):
        cutoff = rows[min(k, len(rows)) - 1]
        tied = [t for t in rows if known_final_values(t, snapshot) == known_final_values(cutoff, snapshot)]
        unresolved = {t['id'] for t in tied} if min(t['rank'] for t in tied) <= k < max(t['rank'] for t in tied) else set()
        return {t['id']: {'status': 'unknown' if t['id'] in unresolved else ('qualified' if t['rank'] <= k else 'eliminated'),
                           'basis': 'final_tie_needs_additional_rules' if t['id'] in unresolved else 'final_points_and_current_nrr'} for t in rows}
    result = {}
    for target in rows:
        cap = target['max_points']
        others = [t for t in rows if t['id'] != target['id']]
        forced = {t['id'] for t in others if t['points'] > cap}
        if len(forced) >= k:
            result[target['id']] = {'status': 'eliminated', 'basis': 'points', 'max_points': cap}
            continue
        games = [m for m in remaining if target['id'] not in (m['home_id'], m['away_id'])]
        total = 2 * len(games)
        candidates = [t['id'] for t in others if t['id'] not in forced]
        free_count = min(k - 1 - len(forced), len(candidates))
        alive, exhausted = False, False
        for attempt, subset in enumerate(combinations(candidates, free_count)):
            if attempt >= 5000:
                exhausted = True
                break
            exempt = forced | set(subset)
            graph = nx.DiGraph()
            graph.add_nodes_from(['source', 'sink'])
            for team in others:
                graph.add_edge(team['id'], 'sink', capacity=total if team['id'] in exempt else cap - team['points'])
            for i, match in enumerate(games):
                game = f'game:{i}'
                graph.add_edge('source', game, capacity=2)
                graph.add_edge(game, match['home_id'], capacity=2)
                graph.add_edge(game, match['away_id'], capacity=2)
            if total == 0 or nx.maximum_flow_value(graph, 'source', 'sink') == total:
                alive = True
                break
        result[target['id']] = {'status': 'alive' if alive else ('unknown' if exhausted else 'eliminated'),
                                'basis': 'points_with_favorable_ties_and_possible_washouts', 'max_points': cap}
    return result


def simulate(snapshot, request):
    if not snapshot['rules'].get('schedule_complete', True):
        raise ValueError('Predictions require a complete fixture schedule')
    overrides = request.get('overrides', {})
    rows = standings(snapshot, overrides)
    teams = snapshot['teams']
    count = request.get('iterations', 1000)
    rng = np.random.default_rng(request.get('seed', 42))
    index = {t['id']: i for i, t in enumerate(teams)}
    by_id = {t['id']: t for t in rows}
    points = np.tile([by_id[t['id']]['points'] for t in teams], (count, 1))
    wins = np.tile([by_id[t['id']]['won'] for t in teams], (count, 1))
    pending = [m for m in snapshot['fixtures'] if m['outcome'] == 'pending' and m['id'] not in overrides]
    washout_probability = request.get('washout_probability', 0.03)
    for match in pending:
        a, b = index[match['home_id']], index[match['away_id']]
        p = 0.5 if request.get('model', 'equal') == 'equal' else 1 / (1 + 10 ** ((teams[b]['rating'] - teams[a]['rating']) / 400))
        roll = rng.random(count)
        washout = roll < washout_probability
        home = (~washout) & (roll < washout_probability + (1 - washout_probability) * p)
        away = ~(washout | home)
        points[:, a] += 2 * home + washout
        points[:, b] += 2 * away + washout
        wins[:, a] += home
        wins[:, b] += away
    # Future NRR is not inferable from winners alone. Randomize points ties;
    # with all fixtures resolved, preserve supplied NRR instead.
    future_nrr_unknown = any(m['outcome'] == 'pending' for m in snapshot['fixtures']) or not snapshot.get('nrr_trusted', True)
    ties = rng.random(points.shape) if future_nrr_unknown else np.tile([t['nrr'] for t in teams], (count, 1))
    tie_keys = [-wins if name == 'wins' else -ties for name in reversed(snapshot['rules'].get('tie_breakers', ['nrr']))]
    order = np.lexsort(tuple([rng.random(points.shape), *tie_keys, -points]), axis=1)
    k = min(snapshot['rules']['qualifying_spots'], len(teams))
    hits = np.bincount(order[:, :k].ravel(), minlength=len(teams))
    exact = elimination(snapshot, overrides)
    probabilities = []
    for i, team in enumerate(teams):
        probability = float(hits[i] / count)
        # Wilson intervals remain meaningful for 0/N and N/N estimates.
        z = 1.96
        center = (probability + z * z / (2 * count)) / (1 + z * z / count)
        half = z * sqrt(probability * (1 - probability) / count + z * z / (4 * count * count)) / (1 + z * z / count)
        probabilities.append({'team_id': team['id'], 'qualification_pct': round(100 * probability, 2),
                              'interval_95': [round(100 * max(0, center - half), 2), round(100 * min(1, center + half), 2)],
                              **exact[team['id']]})
    return {'stage_id': snapshot['stage_id'], 'revision': snapshot['revision'], 'iterations': count,
            'model': request.get('model', 'equal'), 'tie_model': 'random_points_ties' if future_nrr_unknown else 'current_nrr',
            'washout_probability': washout_probability, 'seed': request.get('seed', 42),
            'standings': rows, 'probabilities': probabilities,
            'assumptions': ['Ties follow configured wins/NRR priority. Unknown future NRR is randomized; no score model.',
                            'Alive means a points-feasible path, allowing favorable ties and washouts.',
                            'Percentages estimate this model, not real-world certainty.']}
