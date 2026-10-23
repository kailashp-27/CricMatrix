"""Dedicated stage rules, lookup indexes, and fixture membership integrity."""
from collections import Counter

from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'stage_rules' not in inspector.get_table_names():
        op.create_table('stage_rules',
            sa.Column('stage_id', sa.String(80), sa.ForeignKey('stages.id'), primary_key=True),
            sa.Column('schema_version', sa.Integer(), nullable=False),
            sa.Column('team_count', sa.Integer(), nullable=False),
            sa.Column('matches_per_team', sa.Integer(), nullable=True),
            sa.Column('qualifying_spots', sa.Integer(), nullable=False),
            sa.Column('win_points', sa.Integer(), nullable=False),
            sa.Column('loss_points', sa.Integer(), nullable=False),
            sa.Column('washout_points', sa.Integer(), nullable=False),
            sa.Column('tie_breakers', sa.JSON(), nullable=False),
            sa.Column('stage_format', sa.String(), nullable=False),
            sa.Column('regulation_overs', sa.Integer(), nullable=False),
            sa.Column('schedule_complete', sa.Boolean(), nullable=False),
            sa.CheckConstraint('team_count >= 2 AND team_count <= 16', name='ck_rule_team_count'),
            sa.CheckConstraint('qualifying_spots >= 1 AND qualifying_spots <= team_count', name='ck_rule_spots'),
            sa.CheckConstraint('matches_per_team IS NULL OR matches_per_team >= 1', name='ck_rule_matches'),
            sa.CheckConstraint('win_points = 2 AND loss_points = 0 AND washout_points = 1', name='ck_rule_scoring'),
            sa.CheckConstraint("stage_format IN ('league', 'group')", name='ck_rule_format'),
            sa.CheckConstraint('regulation_overs >= 1 AND regulation_overs <= 100', name='ck_rule_overs'))
    metadata = sa.MetaData()
    stages = sa.Table('stages', metadata, autoload_with=connection)
    seasons = sa.Table('seasons', metadata, autoload_with=connection)
    season_sources = dict(connection.execute(sa.select(seasons.c.id, seasons.c.source)).all())
    entries = sa.Table('stage_entries', metadata, autoload_with=connection)
    fixtures = sa.Table('fixtures', metadata, autoload_with=connection)
    rules_table = sa.Table('stage_rules', metadata, autoload_with=connection)
    existing = set(connection.scalars(sa.select(rules_table.c.stage_id)))
    for stage in connection.execute(sa.select(stages)).mappings():
        if stage['id'] in existing:
            continue
        team_ids = list(connection.scalars(sa.select(entries.c.team_id).where(entries.c.stage_id == stage['id'])))
        counts = Counter({t: 0 for t in team_ids})
        for match in connection.execute(sa.select(fixtures.c.home_id, fixtures.c.away_id).where(fixtures.c.stage_id == stage['id'])):
            counts[match.home_id] += 1
            counts[match.away_id] += 1
        uniform = set(counts.values())
        legacy = stage['rules']
        connection.execute(rules_table.insert().values(
            stage_id=stage['id'], schema_version=1, team_count=len(team_ids),
            matches_per_team=next(iter(uniform)) if len(uniform) == 1 and 0 not in uniform else None,
            qualifying_spots=legacy['qualifying_spots'], win_points=legacy.get('win_points', 2),
            loss_points=legacy.get('loss_points', 0), washout_points=legacy.get('washout_points', 1),
            tie_breakers=legacy.get('tie_breakers', ['nrr']), stage_format=legacy.get('stage_format', 'group' if stage['name'].lower().startswith('group') else 'league'),
            regulation_overs=legacy.get('regulation_overs', 20), schedule_complete=legacy.get('schedule_complete', season_sources.get(stage['season_id']) == 'demo' and bool(counts) and all(counts.values()))))
    for table, column in [('seasons', 'tournament_id'), ('stages', 'season_id'), ('stage_entries', 'stage_id'), ('fixtures', 'stage_id')]:
        name = f'ix_{table}_{column}'
        if name not in {index['name'] for index in sa.inspect(connection).get_indexes(table)}:
            op.create_index(name, table, [column])
    checks = {check['name'] for check in sa.inspect(connection).get_check_constraints('fixtures')}
    foreign_keys = {fk['name'] for fk in sa.inspect(connection).get_foreign_keys('fixtures')}
    with op.batch_alter_table('fixtures') as batch:
        if 'ck_fixture_opponents' not in checks:
            batch.create_check_constraint('ck_fixture_opponents', 'home_id <> away_id')
        if 'ck_fixture_outcome' not in checks:
            batch.create_check_constraint('ck_fixture_outcome', "outcome IN ('pending', 'home', 'away', 'washout')")
        if 'fk_fixture_home_entry' not in foreign_keys:
            batch.create_foreign_key('fk_fixture_home_entry', 'stage_entries', ['stage_id', 'home_id'], ['stage_id', 'team_id'])
        if 'fk_fixture_away_entry' not in foreign_keys:
            batch.create_foreign_key('fk_fixture_away_entry', 'stage_entries', ['stage_id', 'away_id'], ['stage_id', 'team_id'])


def downgrade():
    with op.batch_alter_table('fixtures') as batch:
        batch.drop_constraint('fk_fixture_away_entry', type_='foreignkey')
        batch.drop_constraint('fk_fixture_home_entry', type_='foreignkey')
        batch.drop_constraint('ck_fixture_outcome', type_='check')
        batch.drop_constraint('ck_fixture_opponents', type_='check')
    for table, column in [('seasons', 'tournament_id'), ('stages', 'season_id'), ('stage_entries', 'stage_id'), ('fixtures', 'stage_id')]:
        op.drop_index(f'ix_{table}_{column}', table_name=table)
    op.drop_table('stage_rules')
