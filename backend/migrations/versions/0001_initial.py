"""Initial stage-scoped tournament schema."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('tournaments', sa.Column('id', sa.String(80), primary_key=True), sa.Column('name', sa.String(), nullable=False), sa.Column('country', sa.String(), nullable=False))
    op.create_table('teams', sa.Column('id', sa.String(80), primary_key=True), sa.Column('name', sa.String(), nullable=False), sa.Column('short_name', sa.String(), nullable=False), sa.Column('color', sa.String(), nullable=False))
    op.create_table('seasons', sa.Column('id', sa.String(80), primary_key=True), sa.Column('tournament_id', sa.String(80), sa.ForeignKey('tournaments.id'), nullable=False), sa.Column('name', sa.String(), nullable=False), sa.Column('source', sa.String(), nullable=False))
    op.create_table('stages', sa.Column('id', sa.String(80), primary_key=True), sa.Column('season_id', sa.String(80), sa.ForeignKey('seasons.id'), nullable=False), sa.Column('name', sa.String(), nullable=False), sa.Column('rules', sa.JSON(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('updated_at', sa.String(), nullable=False))
    op.create_table('stage_entries', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('stage_id', sa.String(80), sa.ForeignKey('stages.id'), nullable=False), sa.Column('team_id', sa.String(80), sa.ForeignKey('teams.id'), nullable=False), sa.Column('nrr', sa.Float(), nullable=False), sa.Column('rating', sa.Float(), nullable=False), sa.UniqueConstraint('stage_id', 'team_id'))
    op.create_table('fixtures', sa.Column('id', sa.String(100), primary_key=True), sa.Column('stage_id', sa.String(80), sa.ForeignKey('stages.id'), nullable=False), sa.Column('home_id', sa.String(80), sa.ForeignKey('teams.id'), nullable=False), sa.Column('away_id', sa.String(80), sa.ForeignKey('teams.id'), nullable=False), sa.Column('starts_at', sa.String(), nullable=False), sa.Column('venue', sa.String(), nullable=False), sa.Column('outcome', sa.String(), nullable=False))


def downgrade():
    for table in ('fixtures', 'stage_entries', 'stages', 'seasons', 'teams', 'tournaments'):
        op.drop_table(table)
