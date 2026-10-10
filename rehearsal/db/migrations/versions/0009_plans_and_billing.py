"""plans, plan credits, billing events, and delayed jobs

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('plan_override', sa.String(20), nullable=True))
    op.add_column('organizations', sa.Column('limits_override', JSONB, nullable=False, server_default='{}'))
    op.add_column('organizations', sa.Column('billing', JSONB, nullable=False, server_default='{}'))
    op.add_column('organizations', sa.Column('created_device', sa.String(64), nullable=True))
    op.add_column('organizations', sa.Column('created_ip', sa.String(64), nullable=True))
    op.create_index('ix_organizations_created_device', 'organizations', ['created_device'])
    op.create_index('organizations_customer', 'organizations', [sa.text("(billing->>'customer_id')")])
    op.create_table(
        'plan_credits',
        sa.Column('id', sa.String(40), primary_key=True),
        sa.Column('org_id', sa.String(40), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('quantity', sa.Integer, nullable=False),
        sa.Column('month', sa.String(7), nullable=False),
        sa.Column('ref', sa.String(120), nullable=False, unique=True),
        sa.Column('note', sa.Text, nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'billing_events',
        sa.Column('id', sa.String(120), primary_key=True),
        sa.Column('type', sa.String(80), nullable=False),
        sa.Column('org_id', sa.String(40), nullable=True),
        sa.Column('actor', sa.String(320), nullable=True),
        sa.Column('payload', JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_plan_credits_org_id', 'plan_credits', ['org_id'])
    op.create_index('ix_billing_events_org_id', 'billing_events', ['org_id'])
    op.add_column('jobs', sa.Column('not_before', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'not_before')
    op.drop_table('billing_events')
    op.drop_table('plan_credits')
    op.drop_index('organizations_customer', 'organizations')
    op.drop_index('ix_organizations_created_device', 'organizations')
    for c in ('created_ip', 'created_device', 'billing', 'limits_override', 'plan_override'):
        op.drop_column('organizations', c)
