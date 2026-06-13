"""Call-processing service boundary contracts.

This package starts as a contract skeleton for the service split. Runtime
ownership moves here in later task cards.
"""

from app.agents.call_processing.schemas import (
    APP_SERVICE_VALUES,
    CALL_PROCESSING_MODE_VALUES,
    LLM1_FIRST_PASS_SCHEMA_VERSION,
    NON_RETRYABLE_ERROR_CLASSES,
    RETRYABLE_ERROR_CLASSES,
    AccessGrant,
    AppService,
    ArtifactError,
    ArtifactKind,
    ArtifactStatus,
    CallProcessingMode,
    EnsureRequest,
    EnsureResponse,
    LLM1FirstPassPayload,
    ProcessingClientRole,
    ProcessingClientType,
    ProcessingErrorClass,
    ProcessingRunStatus,
    ProcessingScope,
    RequiredArtifactKind,
    stable_scope_hash,
)

__all__ = [
    "APP_SERVICE_VALUES",
    "CALL_PROCESSING_MODE_VALUES",
    "LLM1_FIRST_PASS_SCHEMA_VERSION",
    "NON_RETRYABLE_ERROR_CLASSES",
    "RETRYABLE_ERROR_CLASSES",
    "AccessGrant",
    "AppService",
    "ArtifactError",
    "ArtifactKind",
    "ArtifactStatus",
    "CallProcessingMode",
    "EnsureRequest",
    "EnsureResponse",
    "LLM1FirstPassPayload",
    "ProcessingClientRole",
    "ProcessingClientType",
    "ProcessingErrorClass",
    "ProcessingRunStatus",
    "ProcessingScope",
    "RequiredArtifactKind",
    "stable_scope_hash",
]
