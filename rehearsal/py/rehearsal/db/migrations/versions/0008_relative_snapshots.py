"""world snapshots are stored relative to the data folder

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from rehearsal.config import settings

    prefix = str(settings().data_dir).rstrip("/") + "/"
    for table in ("world_versions", "scenarios"):
        op.get_bind().execute(sa.text(f"UPDATE {table} SET snapshot_dir = substr(snapshot_dir, :n) WHERE snapshot_dir LIKE :p"),
                              {"n": len(prefix) + 1, "p": prefix + "%"})


def downgrade() -> None:
    pass  # relative paths still resolve against the data folder
