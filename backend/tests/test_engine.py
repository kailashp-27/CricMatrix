import copy
import itertools
import random
import unittest

from app.engine import elimination, simulate, standings
from app.schemas import PredictionRequest, Rules


def snapshot(n=4, k=2):
    teams = [{'id': str(i), 'name': str(i), 'short_name': str(i), 'color': '#abcdef', 'nrr': i / 10, 'rating': 1500} for i in range(n)]
    fixtures = [{'id': f'm{i}', 'home_id': a['id'], 'away_id': b['id'], 'outcome': 'pending'}
                for i, (a, b) in enumerate(itertools.combinations(teams, 2))]
    return {'stage_id': 'test', 'revision': 1, 'rules': Rules(qualifying_spots=k).model_dump(), 'teams': teams, 'fixtures': fixtures}


class EngineTests(unittest.TestCase):
    def test_picked_win_and_loss_use_paired_baseline_samples(self):
        data = snapshot(k=1)
        for seed in range(32):
            request = {'iterations': 1, 'seed': seed, 'model': 'equal', 'washout_probability': 0}
            baseline = {p['team_id']: p['qualification_pct'] for p in simulate(data, request)['probabilities']}
            scenario = {p['team_id']: p['qualification_pct'] for p in simulate(data, {**request, 'overrides': {'m0': 'home'}})['probabilities']}
            self.assertGreaterEqual(scenario['0'], baseline['0'], f'Winning team decreased at seed {seed}')
            self.assertLessEqual(scenario['1'], baseline['1'], f'Losing team increased at seed {seed}')

    def test_points_conservation_washout_and_no_mutation(self):
        data = snapshot()
        original = copy.deepcopy(data)
        table = standings(data, {'m0': 'home', 'm1': 'washout'})
        self.assertEqual(sum(t['points'] for t in table), 4)
        self.assertEqual(sum(t['played'] for t in table), 4)
        self.assertEqual(sum(t['remaining'] for t in table), 8)
        self.assertEqual(data, original)

    def test_completed_or_foreign_overrides_rejected(self):
        data = snapshot()
        data['fixtures'][0]['outcome'] = 'home'
        for override in ({'m0': 'away'}, {'other-stage': 'home'}, {'m1': 'draw'}):
            with self.assertRaises(ValueError):
                standings(data, override)

    def test_flow_matches_exhaustive_top_k_with_washouts(self):
        rng = random.Random(94)
        for case in range(35):
            data = snapshot(k=rng.choice([1, 2, 3]))
            for match in data['fixtures'][:3]:
                match['outcome'] = rng.choice(['home', 'away', 'washout'])
            unresolved = data['fixtures'][3:]
            feasible = set()
            for outcomes in itertools.product(['home', 'away', 'washout'], repeat=len(unresolved)):
                picks = {m['id']: outcome for m, outcome in zip(unresolved, outcomes)}
                table = standings(data, picks)
                for target in table:
                    higher = sum(t['points'] > target['points'] for t in table)
                    if higher < data['rules']['qualifying_spots']:
                        feasible.add(target['id'])
            actual = elimination(data)
            for team in data['teams']:
                self.assertEqual(actual[team['id']]['status'] != 'eliminated', team['id'] in feasible, f'case {case}, team {team["id"]}')

    def test_top_two_survival_does_not_require_first_place(self):
        data = snapshot(n=3, k=2)
        data['fixtures'][0]['outcome'] = 'home'  # 0 beats 1
        data['fixtures'][1]['outcome'] = 'home'  # 0 beats 2
        self.assertEqual(elimination(data)['1']['status'], 'alive')
        self.assertEqual(elimination(data)['2']['status'], 'alive')

    def test_final_table_uses_nrr(self):
        data = snapshot()
        for match in data['fixtures']:
            match['outcome'] = 'washout'
        final = elimination(data)
        self.assertEqual(final['3']['status'], 'qualified')
        self.assertEqual(final['2']['status'], 'qualified')
        self.assertEqual(final['1']['status'], 'eliminated')
        result = simulate(data, {'iterations': 100})
        self.assertEqual({p['team_id']: p['qualification_pct'] for p in result['probabilities']}, {'0': 0, '1': 0, '2': 100, '3': 100})

    def test_reproducibility_and_probability_mass(self):
        data = snapshot()
        request = PredictionRequest(iterations=1000, seed=12).model_dump()
        result = simulate(data, request)
        self.assertEqual(result, simulate(data, request))
        self.assertAlmostEqual(sum(p['qualification_pct'] for p in result['probabilities']), 200, delta=0.03)
        for p in result['probabilities']:
            self.assertTrue(0 <= p['interval_95'][0] <= p['interval_95'][1] <= 100)

    def test_fixed_picks_and_no_remaining_match(self):
        data = snapshot()
        picks = {m['id']: 'home' for m in data['fixtures']}
        result = simulate(data, PredictionRequest(overrides=picks, iterations=100).model_dump())
        self.assertEqual(result['tie_model'], 'random_points_ties')
        self.assertEqual(sum(p['qualification_pct'] for p in result['probabilities']), 200)

    def test_all_future_results_picked_does_not_claim_known_nrr(self):
        data = snapshot()
        picks = {m['id']: 'washout' for m in data['fixtures']}
        result = simulate(data, PredictionRequest(overrides=picks, iterations=1000).model_dump())
        self.assertTrue(all(p['status'] == 'alive' for p in result['probabilities']))
        self.assertTrue(all(30 < p['qualification_pct'] < 70 for p in result['probabilities']))

    def test_final_exact_nrr_tie_cannot_claim_elimination(self):
        data = snapshot()
        for team in data['teams']:
            team['nrr'] = 0
        for match in data['fixtures']:
            match['outcome'] = 'washout'
        result = simulate(data, PredictionRequest(iterations=1000).model_dump())
        self.assertTrue(all(p['status'] == 'unknown' for p in result['probabilities']))
        self.assertTrue(all(30 < p['qualification_pct'] < 70 for p in result['probabilities']))

    def test_invalid_configuration_rejected(self):
        for config in ({'qualifying_spots': 0}, {'qualifying_spots': 2, 'win_points': 3}):
            with self.assertRaises(ValueError):
                Rules(**config)
        with self.assertRaises(ValueError):
            PredictionRequest(iterations=1000000)


if __name__ == '__main__':
    unittest.main()
