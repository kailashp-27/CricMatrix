"""Shared live feed cache; never mingle live scores with demo standings."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('live_feeds',
        sa.Column('provider', sa.String(40), primary_key=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('last_success_at', sa.String(), nullable=True),
        sa.Column('error_code', sa.String(), nullable=True),
        sa.Column('next_attempt', sa.Float(), nullable=False),
        sa.Column('lease_until', sa.Float(), nullable=False),
        sa.Column('lease_token', sa.String(), nullable=True))


def downgrade():
    op.drop_table('live_feeds')
