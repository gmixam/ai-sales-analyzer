from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.agents.call_processing import (
    ArtifactKind,
    ArtifactStatus,
    CallProcessingArtifactError,
    EnsureMode,
    EnsureResponse,
    HttpCallProcessingClient,
    LocalCallProcessingClient,
    ProcessingRunStatus,
    ProcessingScope,
    RequiredArtifactKind,
    llm1_first_pass_payload_from_artifact,
)
from app.agents.call_processing import client as call_processing_client_module


class _FakeArtifactRepository:
    def __init__(self, rows: list[SimpleNamespace] | None = None) -> None:
        self.rows = rows or []
        self.latest_active_calls: list[tuple[object, object, object]] = []
        self.list_latest_active_calls: list[tuple[list[object], list[object]]] = []

    def latest_active(
        self,
        interaction_id: uuid.UUID | str,
        artifact_kind: ArtifactKind | RequiredArtifactKind | str,
        artifact_version: str | None = None,
    ) -> SimpleNamespace | None:
        self.latest_active_calls.append((interaction_id, artifact_kind, artifact_version))
        kind = str(artifact_kind.value if hasattr(artifact_kind, "value") else artifact_kind)
        for row in self.rows:
            if (
                row.interaction_id == interaction_id
                and row.artifact_kind == kind
                and row.artifact_version == artifact_version
                and row.is_active
            ):
                return row
        return None

    def list_latest_active(
        self,
        interaction_ids: list[uuid.UUID | str],
        artifact_kinds: list[ArtifactKind | RequiredArtifactKind | str],
    ) -> list[SimpleNamespace]:
        self.list_latest_active_calls.append((interaction_ids, artifact_kinds))
        kinds = {str(kind.value if hasattr(kind, "value") else kind) for kind in artifact_kinds}
        return [
            row
            for row in self.rows
            if row.interaction_id in interaction_ids and row.artifact_kind in kinds and row.is_active
        ]


class _FakeService:
    def __init__(self, interactions: list[SimpleNamespace] | None = None) -> None:
        self.interactions = interactions or []
        self.ensure_calls: list[dict[str, object]] = []
        self.ensure_async_calls: list[dict[str, object]] = []

    def ensure(
        self,
        scope: ProcessingScope | dict,
        required_artifacts: list[RequiredArtifactKind],
        mode: EnsureMode | str = EnsureMode.ENSURE,
        *,
        requested_by: str | None = None,
    ) -> EnsureResponse:
        self.ensure_calls.append(
            {
                "scope": scope,
                "required_artifacts": required_artifacts,
                "mode": mode,
                "requested_by": requested_by,
            }
        )
        return EnsureResponse(
            run_id="run-1",
            status=ProcessingRunStatus.READY,
            scope_hash="hash",
            requested_by=requested_by or "unknown",
            planned={"provider_calls_made": 0},
            quota={"provider_calls_made": 0},
        )

    async def ensure_async(
        self,
        scope: ProcessingScope | dict,
        required_artifacts: list[RequiredArtifactKind],
        mode: EnsureMode | str = EnsureMode.ENSURE,
        *,
        requested_by: str | None = None,
    ) -> EnsureResponse:
        self.ensure_async_calls.append(
            {
                "scope": scope,
                "required_artifacts": required_artifacts,
                "mode": mode,
                "requested_by": requested_by,
            }
        )
        return EnsureResponse(
            run_id="run-async",
            status=ProcessingRunStatus.READY,
            scope_hash="hash-async",
            requested_by=requested_by or "unknown",
            planned={"provider_calls_made": 0},
            quota={"provider_calls_made": 0},
        )

    def _find_interactions(self, _scope: ProcessingScope) -> list[SimpleNamespace]:
        return self.interactions


def _scope() -> ProcessingScope:
    return ProcessingScope(
        department_id=str(uuid.uuid4()),
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        source="onlinepbx",
    )


def _llm1_artifact(
    interaction_id: uuid.UUID,
    *,
    status: str = ArtifactStatus.READY.value,
    payload: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        interaction_id=interaction_id,
        artifact_kind=ArtifactKind.LLM1_FIRST_PASS.value,
        artifact_version="llm1_first_pass_v1",
        status=status,
        is_active=True,
        payload_json=payload
        or {
            "prompt_version": "llm1_v1",
            "classification": {"call_type": "sales_primary"},
            "summary": {"brief": "Client asked for materials."},
            "follow_up": {"next_step": "Send materials."},
            "data_quality": {"transcript_quality": "sufficient"},
            "analysis_focus": ["Verify concrete next step."],
        },
        provider="openai",
        model="gpt-test",
        account_alias="primary",
    )


def test_get_llm1_first_pass_artifact_returns_ready_payload() -> None:
    interaction_id = uuid.uuid4()
    artifacts = _FakeArtifactRepository([_llm1_artifact(interaction_id)])
    client = LocalCallProcessingClient(
        object(),
        service=_FakeService(),
        artifacts=artifacts,
        requested_by="analysis-test",
    )

    payload = client.get_llm1_first_pass_artifact(interaction_id)

    assert payload is not None
    assert payload.schema_version == "llm1_first_pass_v1"
    assert payload.status == ArtifactStatus.READY
    assert payload.provider == "openai"
    assert payload.model == "gpt-test"
    assert payload.analysis_focus == ["Verify concrete next step."]


def test_get_llm1_first_pass_artifact_returns_none_when_missing() -> None:
    interaction_id = uuid.uuid4()
    client = LocalCallProcessingClient(
        object(),
        service=_FakeService(),
        artifacts=_FakeArtifactRepository(),
    )

    assert client.get_llm1_first_pass_artifact(interaction_id) is None


def test_ensure_processed_calls_delegates_to_service_without_provider_call() -> None:
    service = _FakeService()
    client = LocalCallProcessingClient(
        object(),
        service=service,
        artifacts=_FakeArtifactRepository(),
        requested_by="analysis-test",
    )
    scope = _scope()

    response = client.ensure_processed_calls(
        scope,
        [RequiredArtifactKind.TRANSCRIPT, "llm1_first_pass"],
        mode=EnsureMode.DRY_RUN,
    )

    assert response.quota["provider_calls_made"] == 0
    assert service.ensure_calls == [
        {
            "scope": scope,
            "required_artifacts": [
                RequiredArtifactKind.TRANSCRIPT,
                RequiredArtifactKind.LLM1_FIRST_PASS,
            ],
            "mode": EnsureMode.DRY_RUN,
            "requested_by": "analysis-test",
        }
    ]


@pytest.mark.asyncio
async def test_ensure_processed_calls_async_delegates_to_service_async() -> None:
    service = _FakeService()
    client = LocalCallProcessingClient(
        object(),
        service=service,
        artifacts=_FakeArtifactRepository(),
        requested_by="analysis-test",
    )
    scope = _scope()

    response = await client.ensure_processed_calls_async(
        scope,
        [RequiredArtifactKind.TRANSCRIPT, "llm1_first_pass"],
        mode=EnsureMode.ENSURE,
    )

    assert response.run_id == "run-async"
    assert service.ensure_calls == []
    assert service.ensure_async_calls == [
        {
            "scope": scope,
            "required_artifacts": [
                RequiredArtifactKind.TRANSCRIPT,
                RequiredArtifactKind.LLM1_FIRST_PASS,
            ],
            "mode": EnsureMode.ENSURE,
            "requested_by": "analysis-test",
        }
    ]


def test_get_processed_artifacts_reads_latest_active_artifacts_for_scope() -> None:
    interaction = SimpleNamespace(id=uuid.uuid4())
    ready_artifact = _llm1_artifact(interaction.id)
    artifacts = _FakeArtifactRepository([ready_artifact])
    client = LocalCallProcessingClient(
        object(),
        service=_FakeService([interaction]),
        artifacts=artifacts,
    )

    rows = client.get_processed_artifacts(_scope(), [RequiredArtifactKind.LLM1_FIRST_PASS])

    assert rows == [ready_artifact]
    assert artifacts.list_latest_active_calls == [
        ([interaction.id], [RequiredArtifactKind.LLM1_FIRST_PASS])
    ]


def test_llm1_artifact_adapter_fails_for_invalid_artifact() -> None:
    interaction_id = uuid.uuid4()
    missing_prompt_version = _llm1_artifact(interaction_id, payload={"provider": "openai", "model": "gpt-test"})
    failed_artifact = _llm1_artifact(interaction_id, status=ArtifactStatus.FAILED.value)

    with pytest.raises(CallProcessingArtifactError, match="invalid llm1_first_pass_v1"):
        llm1_first_pass_payload_from_artifact(missing_prompt_version)

    with pytest.raises(CallProcessingArtifactError, match="not ready"):
        llm1_first_pass_payload_from_artifact(failed_artifact)


def _grant() -> dict:
    return {
        "client_id": "edo-analysis",
        "client_type": "service",
        "role": "admin",
        "allowed_artifact_kinds": ["transcript", "transcript_segments", "llm1_first_pass"],
        "read_surfaces": ["processed_calls_v1", "transcripts_v1", "llm1_artifacts_v1"],
        "created_by_admin": "operator",
    }


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeHttpClient:
    calls: list[tuple[str, str, dict]] = []

    def __init__(self, *, timeout: int) -> None:
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url: str, *, json: dict, headers: dict):
        self.calls.append(("POST", url, {"json": json, "headers": headers}))
        return _FakeResponse(
            200,
            {
                "run_id": "run-http",
                "status": "ready",
                "scope_hash": "hash-http",
                "requested_by": json["requested_by"],
                "planned": {"interactions_total": 1},
                "quota": {"provider_calls_made": 0},
            },
        )

    def get(self, url: str, *, headers: dict, params: dict | None = None):
        self.calls.append(("GET", url, {"headers": headers, "params": params or {}}))
        if url.endswith("/llm1_first_pass"):
            return _FakeResponse(
                200,
                {
                    "artifact_id": str(uuid.uuid4()),
                    "department_id": str(uuid.uuid4()),
                    "interaction_id": url.split("/")[-2],
                    "artifact_kind": "llm1_first_pass",
                    "artifact_version": "llm1_first_pass_v1",
                    "status": "ready",
                    "is_active": True,
                    "payload": {
                        "prompt_version": "llm1_v1",
                        "classification": {"call_type": "sales_primary"},
                        "summary": {"brief": "Client asked for materials."},
                        "follow_up": {"next_step": "Send materials."},
                        "data_quality": {"transcript_quality": "sufficient"},
                        "analysis_focus": ["Verify concrete next step."],
                    },
                    "provider": "openai",
                    "model": "gpt-test",
                    "account_alias": "primary",
                },
            )
        return _FakeResponse(200, {"artifacts": []})


class _FakeAsyncHttpClient(_FakeHttpClient):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url: str, *, json: dict, headers: dict):
        return super().post(url, json=json, headers=headers)


def test_http_client_posts_ensure_and_reads_llm1_artifact(monkeypatch) -> None:
    _FakeHttpClient.calls = []
    monkeypatch.setattr(call_processing_client_module.httpx, "Client", _FakeHttpClient)
    client = HttpCallProcessingClient(
        base_url="http://call-processing.test",
        access_grant=_grant(),
        requested_by="edo-analysis",
    )

    ensure_response = client.ensure_processed_calls(
        _scope(),
        [RequiredArtifactKind.TRANSCRIPT, RequiredArtifactKind.LLM1_FIRST_PASS],
        mode=EnsureMode.DRY_RUN,
    )
    llm1_payload = client.get_llm1_first_pass_artifact(uuid.uuid4())

    assert ensure_response.run_id == "run-http"
    assert llm1_payload is not None
    assert llm1_payload.provider == "openai"
    assert _FakeHttpClient.calls[0][0] == "POST"
    assert _FakeHttpClient.calls[0][1] == "http://call-processing.test/call-processing/ensure"
    assert _FakeHttpClient.calls[1][0] == "GET"
    assert _FakeHttpClient.calls[1][1].endswith("/llm1_first_pass")


@pytest.mark.asyncio
async def test_http_client_posts_ensure_async(monkeypatch) -> None:
    _FakeAsyncHttpClient.calls = []
    monkeypatch.setattr(call_processing_client_module.httpx, "AsyncClient", _FakeAsyncHttpClient)
    client = HttpCallProcessingClient(
        base_url="http://call-processing.test",
        access_grant=_grant(),
        requested_by="edo-analysis",
    )

    ensure_response = await client.ensure_processed_calls_async(
        _scope(),
        [RequiredArtifactKind.TRANSCRIPT, RequiredArtifactKind.LLM1_FIRST_PASS],
        mode=EnsureMode.DRY_RUN,
    )

    assert ensure_response.run_id == "run-http"
    assert len(_FakeAsyncHttpClient.calls) == 1
    assert _FakeAsyncHttpClient.calls[0][0] == "POST"
    assert _FakeAsyncHttpClient.calls[0][1] == "http://call-processing.test/call-processing/ensure"
    assert _FakeAsyncHttpClient.calls[0][2]["json"]["mode"] == "dry_run"
