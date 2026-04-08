"""Pydantic schemas for OnlinePBX intake, STT, and interaction creation."""

from uuid import UUID

from pydantic import BaseModel, Field


class CDRRecord(BaseModel):
    """Запись CDR из OnlinePBX API."""

    call_id: str
    call_date: str
    duration: int
    talk_duration: int
    direction: str
    status: str
    extension: str
    phone: str
    record_url: str | None = None


class InteractionCreate(BaseModel):
    """Данные для создания записи в таблицу interactions."""

    department_id: UUID
    manager_id: UUID | None = None
    type: str = "call"
    source: str = "onlinepbx"
    external_id: str
    raw_ref: str | None = None
    duration_sec: int | None = None
    metadata_: dict = Field(default_factory=dict, alias="metadata")
    status: str = "NEW"

    model_config = {"populate_by_name": True}


class SpeakerSegment(BaseModel):
    """Реплика одного спикера из диаризации AssemblyAI."""

    speaker: str
    text: str
    start_ms: int
    end_ms: int


class TranscriptResult(BaseModel):
    """Результат транскрипции одного звонка."""

    interaction_id: str
    full_text: str
    segments: list[SpeakerSegment]
    speaker_a_is_manager: bool = True
    confidence: float | None = None
    duration_sec: int | None = None
