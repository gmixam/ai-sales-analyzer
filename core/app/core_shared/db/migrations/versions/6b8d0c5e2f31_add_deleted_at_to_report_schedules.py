"""add_deleted_at_to_report_schedules

Revision ID: 6b8d0c5e2f31
Revises: d8b0f4c8d412
Create Date: 2026-04-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b8d0c5e2f31"
down_revision = "d8b0f4c8d412"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_schedules",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("report_schedules", "deleted_at")
