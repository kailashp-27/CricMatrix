import copy
import unittest

from fastapi import HTTPException, Response
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.configuration import SeasonConfig, provision_season
from app.database import Base
from app.engine import load_snapshot, simulate, standings
from app.main import health, liveness, prediction, rule_templates, stage_rules
from app.models import Fixture, Stage, StageRule
from app.rules import backfill_rules, get_rules, update_rules
from app.schemas import PredictionRequest, Rules
from app.seed import seed_demo


def example():
    return {
        'tournament': {'id': 'custom', 'name': 'Custom tournament', 'country': 'International'},
        'id': 'custom-2027', 'name': '2027 example', 'source': 'manual',
        'teams': [{'id': f't{i}', 'name': f'Team {i}', 'short_name': f'T{i}', 'color': '#abcdef'} for i in range(3)],
        'stages': [{'id': 'group-one', 'name': 'Group A',
                    'rules': {'team_count': 3, 'matches_per_team': 2, 'qualifying_spots': 1, 'stage_format': 'group'},
                    'entries': [{'team_id': f't{i}'} for i in range(3)],
                    'fixtures': [{'id': f'f{i}', 'home_id': f't{a}', 'away_id': f't{b}', 'starts_at': '2027-04-01T14:00:00Z', 'venue': 'Example ground'}
                                 for i, (a, b) in enumerate([(0, 1), (0, 2), (1, 2)])]}],
    }


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        @event.listens_for(self.engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_provision_and_repeat_preserves_match_results(self):
        config = SeasonConfig.model_validate(example())
        self.assertTrue(provision_season(self.session, config))
        self.session.commit()
        match = self.session.get(Fixture, 'f0')
        match.outcome = 'home'
        self.session.commit()
        self.assertFalse(provision_season(self.session, config))
        self.assertEqual(match.outcome, 'home')
        state = load_snapshot(self.session, 'group-one')
        self.assertEqual(state['rules']['team_count'], 3)
        self.assertEqual(state['rules']['stage_format'], 'group')

    def test_fixture_schedule_validation(self):
        for mutation in ('missing', 'self', 'foreign', 'duplicate', 'timezone', 'extra', 'membership'):
            with self.subTest(mutation=mutation):
                data = example()
                stage = data['stages'][0]
                if mutation == 'missing': stage['fixtures'].pop()
                if mutation == 'self': stage['fixtures'][0]['away_id'] = 't0'
                if mutation == 'foreign': stage['fixtures'][0]['away_id'] = 'other-group'
                if mutation == 'duplicate': stage['fixtures'][1]['id'] = stage['fixtures'][0]['id']
                if mutation == 'timezone': stage['fixtures'][0]['starts_at'] = '2027-04-01T14:00:00'
                if mutation == 'extra': stage['fixtures'].append({**stage['fixtures'][0], 'id': 'extra'})
                if mutation == 'membership': stage['entries'][1]['team_id'] = 't0'
                with self.assertRaises(ValueError):
                    SeasonConfig.model_validate(data)

    def test_rules_bounds_and_tie_break_priority_validation(self):
        for values in ({'team_count': 3, 'qualifying_spots': 4}, {'team_count': 3, 'matches_per_team': 3, 'qualifying_spots': 1},
                       {'qualifying_spots': 2, 'tie_breakers': ['nrr', 'nrr']}, {'qualifying_spots': 2, 'tie_breakers': ['head_to_head']}):
            with self.assertRaises(ValueError):
                Rules.model_validate(values)

    def test_draft_schedule_cannot_make_predictions(self):
        data = example()
        data['stages'][0]['fixtures'] = []
        data['stages'][0]['rules']['schedule_complete'] = False
        provision_season(self.session, SeasonConfig.model_validate(data))
        self.session.commit()
        with self.assertRaises(HTTPException) as error:
            prediction('group-one', PredictionRequest(), Response(), self.session)
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(ValueError):
            simulate(load_snapshot(self.session, 'group-one'), PredictionRequest().model_dump())

    def test_rules_revision_update_and_noop(self):
        provision_season(self.session, SeasonConfig.model_validate(example()))
        self.session.commit()
        current = get_rules(self.session, self.session.get(Stage, 'group-one'))
        revised = Rules.model_validate({**current.model_dump(), 'qualifying_spots': 2, 'tie_breakers': ['wins', 'nrr']})
        self.assertEqual(update_rules(self.session, 'group-one', revised, 1), (2, True))
        self.session.commit()
        self.assertEqual(update_rules(self.session, 'group-one', revised, 2), (2, False))
        with self.assertRaises(ValueError):
            update_rules(self.session, 'group-one', current, 1)
        self.assertEqual(stage_rules('group-one', self.session)['rules']['qualifying_spots'], 2)

    def test_rule_table_is_authoritative(self):
        provision_season(self.session, SeasonConfig.model_validate(example()))
        self.session.commit()
        self.session.get(Stage, 'group-one').rules = {'qualifying_spots': 99}
        self.session.commit()
        self.assertEqual(load_snapshot(self.session, 'group-one')['rules']['qualifying_spots'], 1)

    def test_reprovision_conflict_rejected_without_overwrite(self):
        config = SeasonConfig.model_validate(example())
        provision_season(self.session, config)
        self.session.commit()
        data = example()
        data['stages'][0]['rules']['qualifying_spots'] = 2
        with self.assertRaises(ValueError):
            provision_season(self.session, SeasonConfig.model_validate(data))
        self.session.rollback()
        self.assertEqual(get_rules(self.session, self.session.get(Stage, 'group-one')).qualifying_spots, 1)

    def test_legacy_backfill_preserves_results(self):
        seed_demo(self.session)
        before = load_snapshot(self.session, 'ipl-demo-0')
        self.session.delete(self.session.get(StageRule, 'ipl-demo-0'))
        self.session.commit()
        self.assertEqual(backfill_rules(self.session), 1)
        self.session.commit()
        self.assertEqual(load_snapshot(self.session, 'ipl-demo-0'), before)

    def test_database_rejects_outcome_and_cross_stage_membership(self):
        seed_demo(self.session)
        for home, away, outcome in [('ipl-CSK', 'bbl-SIX', 'pending'), ('ipl-CSK', 'ipl-CSK', 'pending'), ('ipl-CSK', 'ipl-MI', 'draw')]:
            with self.subTest(home=home, away=away, outcome=outcome):
                self.session.add(Fixture(id='invalid', stage_id='ipl-demo-0', home_id=home, away_id=away, outcome=outcome, starts_at='2027-01-01T00:00:00Z', venue='Test'))
                with self.assertRaises(IntegrityError):
                    self.session.flush()
                self.session.rollback()

    def test_seed_matches_template_counts_and_is_idempotent(self):
        seed_demo(self.session)
        seed_demo(self.session)
        self.assertEqual(len(list(self.session.scalars(select(StageRule)))), 5)
        for stage_id, matches in [('ipl-demo-0', 14), ('bbl-demo-0', 10), ('psl-demo-0', 10), ('wc-demo-0', 3), ('wc-demo-1', 3)]:
            state = load_snapshot(self.session, stage_id)
            self.assertEqual(state['rules']['matches_per_team'], matches)
            self.assertTrue(all(t['played'] + t['remaining'] == matches for t in standings(state)))
        self.assertFalse(rule_templates()['official_regulations'])

    def test_wins_before_nrr_changes_final_ranking_and_simulation(self):
        teams = [{'id': str(i), 'nrr': float(i), 'rating': 1500} for i in range(4)]
        fixtures = [{'id': str(i), 'home_id': str(a), 'away_id': str(b), 'outcome': outcome} for i, (a, b, outcome) in enumerate([(0, 1, 'home'), (0, 1, 'away'), (2, 3, 'washout'), (2, 3, 'washout')])]
        state = {'stage_id': 'test', 'revision': 1, 'rules': Rules(qualifying_spots=2, tie_breakers=['wins', 'nrr']).model_dump(), 'teams': teams, 'fixtures': fixtures}
        self.assertEqual([t['id'] for t in standings(state)], ['1', '0', '3', '2'])
        result = simulate(state, PredictionRequest(iterations=100).model_dump())
        self.assertEqual({p['team_id'] for p in result['probabilities'] if p['qualification_pct'] == 100}, {'0', '1'})
        reversed_state = copy.deepcopy(state)
        reversed_state['rules']['tie_breakers'] = ['nrr', 'wins']
        self.assertEqual([t['id'] for t in standings(reversed_state)], ['3', '2', '1', '0'])

    def test_runtime_configuration_validates_shared_services(self):
        from app.config import Settings
        with self.assertRaises(ValueError):
            Settings(database_url='sqlite://', job_mode='celery', _env_file=None)
        shared = Settings(database_url='postgresql://crease:example@localhost/crease', job_mode='celery', _env_file=None)
        self.assertTrue(shared.database_url.startswith('postgresql+psycopg://'))
        with self.assertRaises(ValueError):
            Settings(database_url='postgresql+psycopg://localhost/crease', job_mode='celery', redis_url='http://localhost', _env_file=None)

    def test_readiness_requires_initialized_schema(self):
        empty_engine = create_engine('sqlite://')
        with Session(empty_engine) as session:
            with self.assertRaises(HTTPException) as error:
                health(session)
            self.assertEqual(error.exception.status_code, 503)
        empty_engine.dispose()
        self.assertEqual(liveness()['status'], 'ok')

    def test_unverified_legacy_manual_schedule_stays_a_draft(self):
        provision_season(self.session, SeasonConfig.model_validate(example()))
        self.session.commit()
        stage = self.session.get(Stage, 'group-one')
        stage.rules = {'qualifying_spots': 1}
        self.session.delete(self.session.get(StageRule, stage.id))
        self.session.commit()
        backfill_rules(self.session)
        self.session.commit()
        self.assertFalse(get_rules(self.session, stage).schedule_complete)
