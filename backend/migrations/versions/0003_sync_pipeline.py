"""Durable sync sources, run history and daily provider request budgets."""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sync_sources',
        sa.Column('stage_id', sa.String(80), sa.ForeignKey('stages.id'), primary_key=True),
        sa.Column('provider', sa.String(), nullable=False), sa.Column('configuration', sa.JSON(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('interval_seconds', sa.Integer(), nullable=False),
        sa.Column('next_attempt', sa.Float(), nullable=False), sa.Column('lease_until', sa.Float(), nullable=False),
        sa.Column('lease_token', sa.String(), nullable=True), sa.Column('status', sa.String(), nullable=False),
        sa.Column('error_code', sa.String(), nullable=True), sa.Column('last_attempt_at', sa.String(), nullable=True),
        sa.Column('last_success_at', sa.String(), nullable=True), sa.Column('last_observed_at', sa.String(), nullable=True),
        sa.Column('nrr_verified_revision', sa.Integer(), nullable=True))
    op.create_table('sync_runs', sa.Column('id', sa.String(40), primary_key=True),
        sa.Column('stage_id', sa.String(80), sa.ForeignKey('stages.id'), nullable=False),
        sa.Column('started_at', sa.String(), nullable=False), sa.Column('finished_at', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False), sa.Column('changed', sa.Boolean(), nullable=False),
        sa.Column('error_code', sa.String(), nullable=True))
    op.create_index('ix_sync_runs_stage_id', 'sync_runs', ['stage_id'])
    op.create_table('provider_quotas', sa.Column('key', sa.String(120), primary_key=True), sa.Column('used', sa.Integer(), nullable=False))


def downgrade():
    op.drop_table('provider_quotas')
    op.drop_index('ix_sync_runs_stage_id', table_name='sync_runs')
    op.drop_table('sync_runs')
    op.drop_table('sync_sources')
