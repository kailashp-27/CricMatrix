import importlib.util
import unittest
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, select


@unittest.skipUnless(importlib.util.find_spec('alembic'), 'Alembic is not installed')
class MigrationTests(unittest.TestCase):
    def setUp(self):
        from alembic.config import Config
        self.engine = create_engine('sqlite://')
        self.connection = self.engine.connect()
        self.config = Config()
        self.config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'migrations'))
        self.config.attributes['connection'] = self.connection

    def tearDown(self):
        self.connection.close()
        self.engine.dispose()

    def test_fresh_schema_upgrade_and_fixture_integrity(self):
        from alembic import command
        command.upgrade(self.config, 'head')
        schema = inspect(self.connection)
        self.assertIn('stage_rules', schema.get_table_names())
        for table in ('sync_sources', 'sync_runs', 'provider_quotas'):
            self.assertIn(table, schema.get_table_names())
        self.assertIn('team_count', {c['name'] for c in schema.get_columns('stage_rules')})
        self.assertIn('fk_fixture_home_entry', {c['name'] for c in schema.get_foreign_keys('fixtures')})

    def test_upgrade_legacy_results_and_downgrade_roundtrip(self):
        from alembic import command
        command.upgrade(self.config, '0001')
        metadata = MetaData()
        tables = {name: Table(name, metadata, autoload_with=self.connection) for name in ['tournaments', 'seasons', 'stages', 'teams', 'stage_entries', 'fixtures']}
        self.connection.execute(tables['tournaments'].insert(), {'id': 't', 'name': 'Test', 'country': 'Test'})
        self.connection.execute(tables['teams'].insert(), [{'id': t, 'name': t, 'short_name': t, 'color': '#abcdef'} for t in ['a', 'b']])
        self.connection.execute(tables['seasons'].insert(), {'id': 's', 'tournament_id': 't', 'name': 'Test season', 'source': 'manual'})
        self.connection.execute(tables['stages'].insert(), {'id': 'g', 'season_id': 's', 'name': 'Group A', 'rules': {'qualifying_spots': 1}, 'revision': 3, 'updated_at': '2027-01-01T00:00:00Z'})
        self.connection.execute(tables['stage_entries'].insert(), [{'stage_id': 'g', 'team_id': t, 'nrr': 0, 'rating': 1500} for t in ['a', 'b']])
        self.connection.execute(tables['fixtures'].insert(), {'id': 'm', 'stage_id': 'g', 'home_id': 'a', 'away_id': 'b', 'starts_at': '2027-01-01T00:00:00Z', 'venue': 'Test', 'outcome': 'home'})
        command.upgrade(self.config, 'head')
        rules = Table('stage_rules', MetaData(), autoload_with=self.connection)
        record = self.connection.execute(select(rules)).mappings().one()
        self.assertEqual((record['team_count'], record['matches_per_team'], record['qualifying_spots']), (2, 1, 1))
        self.assertEqual(record['stage_format'], 'group')
        self.assertEqual(self.connection.scalar(select(tables['fixtures'].c.outcome)), 'home')
        command.downgrade(self.config, '0001')
        command.upgrade(self.config, 'head')
        self.assertEqual(self.connection.scalar(select(tables['fixtures'].c.outcome)), 'home')
