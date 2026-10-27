"""Date model spend independently of job creation.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_spend",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("job_id", sa.String(40), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(40), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("spent_usd", sa.Float, nullable=False),
        sa.UniqueConstraint("job_id", "month"),
    )
    op.create_index("ix_model_spend_project_id", "model_spend", ["project_id"])
    op.create_index("ix_model_spend_month", "model_spend", ["month"])
    # Old totals have no individual charge timestamps. Preserve their historical
    # creation-month allocation; every new increment is dated independently.
    op.execute("""INSERT INTO model_spend (id, job_id, project_id, month, spent_usd)
        SELECT 'spn_' || md5(id), id, project_id,
               to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM'), spent_usd
        FROM jobs WHERE spent_usd > 0 AND spent_usd < 'Infinity'::float8""")


def downgrade() -> None:
    op.drop_table("model_spend")
