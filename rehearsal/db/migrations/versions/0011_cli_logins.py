"""browser sign-in for the CLI (rehearsal login)

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cli_logins",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_code", sa.String(16), nullable=False, unique=True),
        sa.Column("device_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("client", sa.String(200), nullable=False, server_default=""),
        sa.Column("requested_ip", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("project_id", sa.String(40), nullable=True),
        sa.Column("approved_by", sa.String(40), nullable=True),
        sa.Column("api_key_id", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cli_logins")
