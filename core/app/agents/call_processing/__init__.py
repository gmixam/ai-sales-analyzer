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
    EnsureMode,
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
from app.agents.call_processing.service import (
    MAX_PROVIDER_ATTEMPTS,
    STALE_RUN_AFTER,
    CallProcessingService,
    is_retryable_error,
    is_stale_run,
    should_retry_error,
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
    "EnsureMode",
    "EnsureRequest",
    "EnsureResponse",
    "LLM1FirstPassPayload",
    "ProcessingClientRole",
    "ProcessingClientType",
    "ProcessingErrorClass",
    "ProcessingRunStatus",
    "ProcessingScope",
    "RequiredArtifactKind",
    "MAX_PROVIDER_ATTEMPTS",
    "STALE_RUN_AFTER",
    "CallProcessingService",
    "is_retryable_error",
    "is_stale_run",
    "should_retry_error",
    "stable_scope_hash",
]
