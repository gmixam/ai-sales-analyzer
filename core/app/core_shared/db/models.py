"""SQLAlchemy ORM models for AI Sales Analyzer."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core_shared.db.base import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Manager(Base):
    __tablename__ = "managers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(50))
    bitrix_id: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    telegram_id: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    interactions: Mapped[list["Interaction"]] = relationship(
        back_populates="manager",
        primaryjoin="foreign(Interaction.manager_id) == Manager.id",
        viewonly=True,
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="manager",
        primaryjoin="foreign(Analysis.manager_id) == Manager.id",
        viewonly=True,
    )


class Interaction(Base):
    __tablename__ = "interactions"
    __table_args__ = (
        Index("ix_interactions_department_status", "department_id", "status"),
        Index("ix_interactions_department_week", "department_id", "week_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str | None] = mapped_column(String(50))
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    raw_ref: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="NEW", index=True)
    week_id: Mapped[str | None] = mapped_column(String(10), index=True)
    counted: Mapped[bool] = mapped_column(Boolean, default=False)
    used_for_reco: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    manager: Mapped["Manager | None"] = relationship(
        back_populates="interactions",
        primaryjoin="foreign(Interaction.manager_id) == Manager.id",
        viewonly=True,
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="interaction",
        primaryjoin="foreign(Analysis.interaction_id) == Interaction.id",
        viewonly=True,
    )
    agreements: Mapped[list["Agreement"]] = relationship(
        back_populates="interaction",
        primaryjoin="foreign(Agreement.interaction_id) == Interaction.id",
        viewonly=True,
    )
    insights: Mapped[list["Insight"]] = relationship(
        back_populates="interaction",
        primaryjoin="foreign(Insight.interaction_id) == Interaction.id",
        viewonly=True,
    )


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_department_manager", "department_id", "manager_id"),
        Index("ix_analyses_department_instruction", "department_id", "instruction_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    interaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    instruction_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    score_total: Mapped[float | None] = mapped_column(Float)
    scores_detail: Mapped[dict | None] = mapped_column(JSON)
    strengths: Mapped[list | None] = mapped_column(JSON, default=list)
    weaknesses: Mapped[list | None] = mapped_column(JSON, default=list)
    recommendations: Mapped[list | None] = mapped_column(JSON, default=list)
    call_topic: Mapped[str | None] = mapped_column(String(255))
    topics: Mapped[list | None] = mapped_column(JSON, default=list)
    is_failed: Mapped[bool] = mapped_column(Boolean, default=False)
    fail_reason: Mapped[str | None] = mapped_column(Text)
    raw_llm_response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    interaction: Mapped["Interaction"] = relationship(
        back_populates="analyses",
        primaryjoin="foreign(Analysis.interaction_id) == Interaction.id",
        viewonly=True,
    )
    manager: Mapped["Manager | None"] = relationship(
        back_populates="analyses",
        primaryjoin="foreign(Analysis.manager_id) == Manager.id",
        viewonly=True,
    )


class Agreement(Base):
    __tablename__ = "agreements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    interaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    responsible: Mapped[str | None] = mapped_column(String(20))
    deadline: Mapped[str | None] = mapped_column(String(20))
    next_step: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    bitrix_task_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    interaction: Mapped["Interaction"] = relationship(
        back_populates="agreements",
        primaryjoin="foreign(Agreement.interaction_id) == Interaction.id",
        viewonly=True,
    )


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    interaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(50))
    topic: Mapped[str | None] = mapped_column(String(255))
    quote: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    interaction: Mapped["Interaction"] = relationship(
        back_populates="insights",
        primaryjoin="foreign(Insight.interaction_id) == Interaction.id",
        viewonly=True,
    )


class Prompt(Base):
    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint("department_id", "module", "version"),
        Index("ix_prompts_department_module_active", "department_id", "module", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    checklist: Mapped[dict | None] = mapped_column(JSON)
    critical_errors: Mapped[list | None] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManagerProgress(Base):
    __tablename__ = "manager_progress"
    __table_args__ = (
        UniqueConstraint("manager_id", "week_id"),
        Index("ix_manager_progress_department_week", "department_id", "week_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    manager_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    week_id: Mapped[str] = mapped_column(String(10), nullable=False)
    instruction_version: Mapped[str] = mapped_column(String(50), nullable=False)
    calls_total: Mapped[int] = mapped_column(Integer, default=0)
    calls_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    score_avg: Mapped[float | None] = mapped_column(Float)
    score_delta: Mapped[float | None] = mapped_column(Float)
    top_weakness_1: Mapped[str | None] = mapped_column(String(255))
    top_weakness_2: Mapped[str | None] = mapped_column(String(255))
    top_weakness_3: Mapped[str | None] = mapped_column(String(255))
    top_strength_1: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromptSuggestion(Base):
    __tablename__ = "prompt_suggestions"
    __table_args__ = (
        Index("ix_prompt_suggestions_department_status", "department_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    current_version: Mapped[str] = mapped_column(String(50), nullable=False)
    suggested_version: Mapped[str] = mapped_column(String(50), nullable=False)
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportingSchedule(Base):
    __tablename__ = "report_schedules"
    __table_args__ = (
        Index("ix_report_schedules_department_enabled", "department_id", "enabled"),
        Index("ix_report_schedules_next_run_at", "next_run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    preset: Mapped[str] = mapped_column(String(30), nullable=False)
    manager_ids: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str] = mapped_column(String(8), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    recurrence_type: Mapped[str] = mapped_column(String(20), nullable=False)
    report_period_rule: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    business_email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ScheduledReportBatch(Base):
    __tablename__ = "scheduled_report_batches"
    __table_args__ = (
        Index("ix_scheduled_report_batches_department_status", "department_id", "status"),
        Index("ix_scheduled_report_batches_schedule_planned", "schedule_id", "planned_for"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    preset: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    report_period_rule: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned", index=True)
    planned_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period: Mapped[dict] = mapped_column(JSON, default=dict)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    business_email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    observability: Mapped[dict | None] = mapped_column(JSON)
    diagnostics: Mapped[dict | None] = mapped_column(JSON)
    errors: Mapped[list | None] = mapped_column(JSON, default=list)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_required_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ScheduledReportDraft(Base):
    __tablename__ = "scheduled_report_drafts"
    __table_args__ = (
        Index("ix_scheduled_report_drafts_batch_status", "batch_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    preset: Mapped[str] = mapped_column(String(30), nullable=False)
    group_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="review_required")
    generated_payload: Mapped[dict | None] = mapped_column(JSON)
    generated_blocks: Mapped[dict | None] = mapped_column(JSON)
    edited_blocks: Mapped[dict | None] = mapped_column(JSON, default=dict)
    edit_audit: Mapped[list | None] = mapped_column(JSON, default=list)
    preview: Mapped[dict | None] = mapped_column(JSON)
    artifact: Mapped[dict | None] = mapped_column(JSON)
    delivery: Mapped[dict | None] = mapped_column(JSON)
    errors: Mapped[list | None] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
