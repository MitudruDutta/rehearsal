"""evaluation shards claim episodes

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('episodes', sa.Column('job_id', sa.String(length=40), nullable=True))
    op.create_index('ix_episodes_job_id', 'episodes', ['job_id'])


def downgrade() -> None:
    op.drop_index('ix_episodes_job_id', table_name='episodes')
    op.drop_column('episodes', 'job_id')
