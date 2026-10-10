"""users and organisation memberships for console sign-in

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=40), primary_key=True),
        sa.Column('email', sa.String(length=320), nullable=False, unique=True),
        sa.Column('name', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('picture_url', sa.String(length=1000), nullable=True),
        sa.Column('google_sub', sa.String(length=255), nullable=True, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        'memberships',
        sa.Column('id', sa.String(length=40), primary_key=True),
        sa.Column('user_id', sa.String(length=40), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('org_id', sa.String(length=40), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='owner'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'org_id'),
    )


def downgrade() -> None:
    op.drop_table('memberships')
    op.drop_table('users')
