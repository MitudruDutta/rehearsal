"""organisation owner for self-serve sign-up

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('owner_name', sa.String(length=200), nullable=True))
    op.add_column('organizations', sa.Column('owner_email', sa.String(length=320), nullable=True))
    op.create_unique_constraint('uq_organizations_owner_email', 'organizations', ['owner_email'])


def downgrade() -> None:
    op.drop_constraint('uq_organizations_owner_email', 'organizations', type_='unique')
    op.drop_column('organizations', 'owner_email')
    op.drop_column('organizations', 'owner_name')
