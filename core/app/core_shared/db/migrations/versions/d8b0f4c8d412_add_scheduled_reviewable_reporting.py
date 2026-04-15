"""add_scheduled_reviewable_reporting

Revision ID: d8b0f4c8d412
Revises: 830150613e8f
Create Date: 2026-04-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d8b0f4c8d412"
down_revision = "830150613e8f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_schedules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("department_id", sa.UUID(), nullable=False),
        sa.Column("preset", sa.String(length=30), nullable=False),
        sa.Column("manager_ids", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.String(length=8), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("recurrence_type", sa.String(length=20), nullable=False),
        sa.Column("report_period_rule", sa.String(length=30), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("business_email_enabled", sa.Boolean(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_schedules")),
    )
    op.create_index(op.f("ix_report_schedules_department_id"), "report_schedules", ["department_id"], unique=False)
    op.create_index(
        "ix_report_schedules_department_enabled",
        "report_schedules",
        ["department_id", "enabled"],
        unique=False,
    )
    op.create_index(op.f("ix_report_schedules_next_run_at"), "report_schedules", ["next_run_at"], unique=False)

    op.create_table(
        "scheduled_report_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("schedule_id", sa.UUID(), nullable=False),
        sa.Column("department_id", sa.UUID(), nullable=False),
        sa.Column("preset", sa.String(length=30), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("report_period_rule", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("planned_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period", sa.JSON(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("business_email_enabled", sa.Boolean(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("observability", sa.JSON(), nullable=True),
        sa.Column("diagnostics", sa.JSON(), nullable=True),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_required_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_report_batches")),
    )
    op.create_index(
        op.f("ix_scheduled_report_batches_department_id"),
        "scheduled_report_batches",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_report_batches_department_status",
        "scheduled_report_batches",
        ["department_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_report_batches_schedule_planned",
        "scheduled_report_batches",
        ["schedule_id", "planned_for"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduled_report_batches_schedule_id"),
        "scheduled_report_batches",
        ["schedule_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduled_report_batches_status"),
        "scheduled_report_batches",
        ["status"],
        unique=False,
    )

    op.create_table(
        "scheduled_report_drafts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("department_id", sa.UUID(), nullable=False),
        sa.Column("preset", sa.String(length=30), nullable=False),
        sa.Column("group_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("generated_payload", sa.JSON(), nullable=True),
        sa.Column("generated_blocks", sa.JSON(), nullable=True),
        sa.Column("edited_blocks", sa.JSON(), nullable=True),
        sa.Column("edit_audit", sa.JSON(), nullable=True),
        sa.Column("preview", sa.JSON(), nullable=True),
        sa.Column("artifact", sa.JSON(), nullable=True),
        sa.Column("delivery", sa.JSON(), nullable=True),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_report_drafts")),
    )
    op.create_index(
        "ix_scheduled_report_drafts_batch_status",
        "scheduled_report_drafts",
        ["batch_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduled_report_drafts_batch_id"),
        "scheduled_report_drafts",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduled_report_drafts_department_id"),
        "scheduled_report_drafts",
        ["department_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_scheduled_report_drafts_department_id"), table_name="scheduled_report_drafts")
    op.drop_index(op.f("ix_scheduled_report_drafts_batch_id"), table_name="scheduled_report_drafts")
    op.drop_index("ix_scheduled_report_drafts_batch_status", table_name="scheduled_report_drafts")
    op.drop_table("scheduled_report_drafts")

    op.drop_index(op.f("ix_scheduled_report_batches_status"), table_name="scheduled_report_batches")
    op.drop_index(op.f("ix_scheduled_report_batches_schedule_id"), table_name="scheduled_report_batches")
    op.drop_index("ix_scheduled_report_batches_schedule_planned", table_name="scheduled_report_batches")
    op.drop_index("ix_scheduled_report_batches_department_status", table_name="scheduled_report_batches")
    op.drop_index(op.f("ix_scheduled_report_batches_department_id"), table_name="scheduled_report_batches")
    op.drop_table("scheduled_report_batches")

    op.drop_index(op.f("ix_report_schedules_next_run_at"), table_name="report_schedules")
    op.drop_index("ix_report_schedules_department_enabled", table_name="report_schedules")
    op.drop_index(op.f("ix_report_schedules_department_id"), table_name="report_schedules")
    op.drop_table("report_schedules")
