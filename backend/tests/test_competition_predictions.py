import copy
import unittest
from uuid import uuid4

from app.competition_fixtures import normalize_schedule
from app.competition_predictions import fixture_snapshot, record_rate, source_revision, team_id
from app.engine import simulate, standings, validate_overrides


def fixture_data():
    raw = []
    for index, teams in enumerate((['A', 'B'], ['A', 'C'], ['B', 'C'])):
        raw.append({'id': str(uuid4()), 'name': ' vs '.join(teams), 'teams': teams,
            'dateTimeGMT': f'2099-01-0{index + 1}T10:00:00', 'venue': 'Ground', 'matchType': 't20',
            'matchStarted': index == 0, 'matchEnded': index == 0,
            'status': 'A won by 10 runs' if index == 0 else 'Match not started'})
    return {'info': {'matches': 3}, 'matchList': raw}


def schedule_data():
    return {'series_id': str(uuid4()), 'name': 'Fetched three-team league',
        'fetched_at': '2026-10-24T00:00:00+00:00', **normalize_schedule(fixture_data())}


def provider_rows():
    return [{'name': 'A', 'short_name': 'A', 'played': 1, 'won': 1, 'lost': 0, 'no_result': 0, 'tied': 0},
            {'name': 'B', 'short_name': 'B', 'played': 1, 'won': 0, 'lost': 1, 'no_result': 0, 'tied': 0}]


class CompetitionPredictionTests(unittest.TestCase):
    def test_revision_tracks_results_and_table_without_relying_on_fetch_time(self):
        schedule = schedule_data(); rows = provider_rows()
        revision = source_revision(schedule, rows)
        schedule['fetched_at'] = '2026-10-25T00:00:00+00:00'
        self.assertEqual(source_revision(schedule, rows), revision)
        rows[0]['won'] = 0
        self.assertNotEqual(source_revision(schedule, rows), revision)
        rows = provider_rows(); schedule['fixtures'][1]['outcome'] = 'home'
        self.assertNotEqual(source_revision(schedule, rows), revision)

    def test_normalized_fixtures_keep_real_results_and_future_dates(self):
        schedule = schedule_data()
        self.assertTrue(schedule['schedule_complete'])
        self.assertEqual(schedule['fixtures'][0]['outcome'], 'home')
        self.assertEqual(schedule['fixtures'][1]['state'], 'upcoming')
        self.assertTrue(schedule['fixtures'][1]['starts_at'].endswith('+00:00'))

    def test_qualification_reconstructs_missing_table_team_from_actual_results(self):
        snapshot = fixture_snapshot(schedule_data(), provider_rows(), 1)
        rows = {row['name']: row for row in standings(snapshot)}
        self.assertEqual(set(rows), {'A', 'B', 'C'})
        self.assertEqual(rows['A']['points'], 2)
        self.assertEqual(rows['C']['played'], 0)
        self.assertFalse(snapshot['nrr_trusted'])

    def test_picked_win_increases_qualification_and_does_not_mutate_source(self):
        snapshot = fixture_snapshot(schedule_data(), provider_rows(), 1)
        before = copy.deepcopy(snapshot)
        match = next(m for m in snapshot['fixtures'] if m['home_id'] == team_id('A') and m['away_id'] == team_id('C'))
        request = {'iterations': 10000, 'seed': 42, 'model': 'equal', 'washout_probability': 0}
        baseline = simulate(snapshot, request)
        scenario = simulate(snapshot, {**request, 'overrides': {match['id']: 'home'}})
        base = {p['team_id']: p['qualification_pct'] for p in baseline['probabilities']}
        changed = {p['team_id']: p['qualification_pct'] for p in scenario['probabilities']}
        self.assertGreater(changed[team_id('A')], base[team_id('A')])
        self.assertLess(changed[team_id('C')], base[team_id('C')])
        self.assertEqual(changed[team_id('A')], 100)
        self.assertAlmostEqual(sum(changed.values()), 100, places=1)
        self.assertEqual(snapshot, before)

    def test_incomplete_mixed_and_knockout_schedules_are_blocked(self):
        for mutation in ('incomplete', 'mixed', 'knockout', 'unknown'):
            schedule = schedule_data()
            if mutation == 'incomplete': schedule['schedule_complete'] = False
            if mutation == 'mixed': schedule['fixtures'][1]['format'] = 'test'
            if mutation == 'knockout': schedule['fixtures'].append(copy.deepcopy(schedule['fixtures'][0]))
            if mutation == 'unknown': schedule['fixtures'][0]['unresolved_result'] = True
            with self.assertRaises(ValueError): fixture_snapshot(schedule, provider_rows(), 1)

    def test_conflicting_table_and_completed_overrides_are_rejected(self):
        schedule = schedule_data(); rows = provider_rows(); rows[0]['won'] = 0
        with self.assertRaises(ValueError): fixture_snapshot(schedule, rows, 1)
        snapshot = fixture_snapshot(schedule, provider_rows(), 1)
        completed = next(m for m in snapshot['fixtures'] if m['outcome'] != 'pending')
        with self.assertRaises(ValueError): validate_overrides(snapshot, {completed['id']: 'away'})
        with self.assertRaises(ValueError): validate_overrides(snapshot, {str(uuid4()): 'home'})

    def test_toss_is_not_a_result_and_no_winner_is_guessed(self):
        raw = fixture_data(); raw['matchList'][0]['status'] = 'A won the toss'
        parsed = normalize_schedule(raw)
        self.assertIsNone(parsed['fixtures'][0]['outcome'])
        self.assertTrue(parsed['fixtures'][0]['unresolved_result'])
        self.assertEqual(record_rate(None), .5)
        self.assertGreater(record_rate({'won': 3, 'lost': 0}), record_rate({'won': 1, 'lost': 3}))


if __name__ == '__main__':
    unittest.main()
