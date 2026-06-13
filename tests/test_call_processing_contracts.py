from datetime import date

import pytest
from pydantic import ValidationError

from app.agents.call_processing import (
    LLM1_FIRST_PASS_SCHEMA_VERSION,
    RETRYABLE_ERROR_CLASSES,
    AccessGrant,
    ArtifactError,
    ArtifactKind,
    ArtifactStatus,
    CallProcessingMode,
    LLM1FirstPassPayload,
    ProcessingClientRole,
    ProcessingClientType,
    ProcessingErrorClass,
    ProcessingScope,
    stable_scope_hash,
)


def test_task0_contract_values_match_split_task_pack() -> None:
    assert {item.value for item in ArtifactKind} == {
        "transcript",
        "transcript_segments",
        "llm1_first_pass",
    }
    assert {item.value for item in ArtifactStatus} == {
        "ready",
        "missing",
        "processing",
        "failed",
        "skipped",
        "stale",
    }
    assert CallProcessingMode.LEGACY.value == "legacy"
    assert CallProcessingMode.EXTERNAL_SERVICE.value == "external_service"
    assert RETRYABLE_ERROR_CLASSES == {
        ProcessingErrorClass.PROVIDER_TIMEOUT,
        ProcessingErrorClass.RATE_LIMITED,
        ProcessingErrorClass.PROVIDER_5XX,
    }


def test_llm1_first_pass_contract_validates_version_and_metadata() -> None:
    payload = LLM1FirstPassPayload(
        prompt_version="llm1_v1",
        provider="openai",
        model="gpt-test",
        classification={"kind": "commercial"},
        summary={"short": "client asked about EDO"},
    )

    assert payload.schema_version == LLM1_FIRST_PASS_SCHEMA_VERSION
    assert payload.status == ArtifactStatus.READY
    assert payload.provider == "openai"

    with pytest.raises(ValidationError):
        LLM1FirstPassPayload(
            schema_version="legacy",
            prompt_version="llm1_v1",
            provider="openai",
            model="gpt-test",
        )


def test_llm1_first_pass_rejects_non_terminal_artifact_status() -> None:
    with pytest.raises(ValidationError):
        LLM1FirstPassPayload(
            prompt_version="llm1_v1",
            provider="openai",
            model="gpt-test",
            status=ArtifactStatus.PROCESSING,
        )


def test_processing_scope_hash_is_order_independent() -> None:
    first = ProcessingScope(
        department_id="dep",
        manager_ids=["b", "a"],
        extensions=["322", "321"],
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 3),
    )
    second = ProcessingScope(
        department_id="dep",
        manager_ids=["a", "b"],
        extensions=["321", "322"],
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 3),
    )

    assert stable_scope_hash(first) == stable_scope_hash(second)


def test_access_grant_roles_gate_processing_actions() -> None:
    admin = AccessGrant(
        client_id="edo-analysis",
        client_type=ProcessingClientType.SERVICE,
        role=ProcessingClientRole.ADMIN,
        allowed_artifact_kinds=[ArtifactKind.TRANSCRIPT],
        created_by_admin="operator",
    )
    reader = AccessGrant(
        client_id="qa-reader",
        client_type=ProcessingClientType.EMPLOYEE,
        role=ProcessingClientRole.READER,
        allowed_artifact_kinds=[ArtifactKind.TRANSCRIPT],
        created_by_admin="operator",
    )

    assert admin.can_run_processing is True
    assert reader.can_run_processing is False


def test_artifact_error_retryable_flag_follows_structured_error_class() -> None:
    retryable = ArtifactError(**{"class": ProcessingErrorClass.RATE_LIMITED})
    non_retryable = ArtifactError(**{"class": ProcessingErrorClass.AUTH_ERROR, "retryable": True})

    assert retryable.retryable is True
    assert non_retryable.retryable is False
