from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.call_processing import EnsureResponse, ProcessingRunStatus, ProcessingScope
from app.core_shared.api.main import app
from app.core_shared.api.routes import call_processing as call_processing_routes


def _grant(role: str = "admin", *, rate_limits: dict[str, int] | None = None) -> str:
    return json.dumps(
        {
            "client_id": "edo-analysis",
            "client_type": "service",
            "role": role,
            "allowed_artifact_kinds": [
                "transcript",
                "transcript_segments",
                "llm1_first_pass",
            ],
            "read_surfaces": [
                "processed_calls_v1",
                "transcripts_v1",
                "llm1_artifacts_v1",
                "processing_runs_v1",
            ],
            "rate_limits": rate_limits or {},
            "created_by_admin": "operator",
            "active": True,
        }
    )


def _scope() -> dict[str, object]:
    return {
        "department_id": str(uuid4()),
        "date_from": date(2026, 6, 1).isoformat(),
        "date_to": date(2026, 6, 1).isoformat(),
        "source": "onlinepbx",
    }


class _FakeCallProcessingService:
    calls: list[dict[str, object]] = []

    def __init__(self, _db: object, *, requested_by: str = "tester") -> None:
        self.requested_by = requested_by

    def ensure(
        self,
        scope: ProcessingScope,
        required_artifacts: list[object],
        mode: object,
        *,
        requested_by: str,
        force_retry_failed: bool = False,
        provider_call_budget: int | None = None,
    ) -> EnsureResponse:
        self.calls.append(
            {
                "requested_by": requested_by,
                "force_retry_failed": force_retry_failed,
                "provider_call_budget": provider_call_budget,
            }
        )
        return EnsureResponse(
            run_id="run-1",
            status=ProcessingRunStatus.READY,
            scope_hash="scope-hash",
            requested_by=requested_by,
            planned={
                "interactions_total": 1,
                "artifact_requirements_total": len(required_artifacts),
            },
            quota={"provider_calls_made": 0},
            costs={
                "schema_version": "split_upstream_ai_costs_v1",
                "total_current_run_cost_usdt": 0.0,
            },
        )

    async def ensure_async(
        self,
        scope: ProcessingScope,
        required_artifacts: list[object],
        mode: object,
        *,
        requested_by: str,
        force_retry_failed: bool = False,
        provider_call_budget: int | None = None,
    ) -> EnsureResponse:
        return self.ensure(
            scope,
            required_artifacts,
            mode,
            requested_by=requested_by,
            force_retry_failed=force_retry_failed,
            provider_call_budget=provider_call_budget,
        )


def _override_session():
    yield object()


def test_call_processing_health_route_is_mounted() -> None:
    client = TestClient(app)

    response = client.get("/call-processing/health")

    assert response.status_code == 200
    assert response.json()["service"] == "call_processing"


def test_ensure_requires_admin_grant() -> None:
    client = TestClient(app)

    response = client.post(
        "/call-processing/ensure",
        headers={"X-Call-Processing-Grant": _grant("reader")},
        json={
            "scope": _scope(),
            "required_artifacts": ["transcript"],
            "mode": "dry_run",
            "requested_by": "edo-analysis",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "admin grant required"


def test_ensure_uses_service_and_requires_requested_by_match(monkeypatch) -> None:
    _FakeCallProcessingService.calls = []
    client = TestClient(app)
    app.dependency_overrides[call_processing_routes.get_session] = _override_session
    monkeypatch.setattr(
        call_processing_routes,
        "CallProcessingService",
        _FakeCallProcessingService,
    )
    try:
        response = client.post(
            "/call-processing/ensure",
            headers={"X-Call-Processing-Grant": _grant("admin")},
            json={
                "scope": _scope(),
                "required_artifacts": ["transcript", "llm1_first_pass"],
                "mode": "dry_run",
                "requested_by": "edo-analysis",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["requested_by"] == "edo-analysis"
    assert payload["planned"]["artifact_requirements_total"] == 2
    assert payload["costs"]["schema_version"] == "split_upstream_ai_costs_v1"


def test_ensure_passes_provider_call_budget_from_grant_rate_limits(monkeypatch) -> None:
    _FakeCallProcessingService.calls = []
    client = TestClient(app)
    app.dependency_overrides[call_processing_routes.get_session] = _override_session
    monkeypatch.setattr(
        call_processing_routes,
        "CallProcessingService",
        _FakeCallProcessingService,
    )
    try:
        response = client.post(
            "/call-processing/ensure",
            headers={
                "X-Call-Processing-Grant": _grant(
                    "admin",
                    rate_limits={"provider_calls_per_run": 3},
                )
            },
            json={
                "scope": _scope(),
                "required_artifacts": ["transcript"],
                "mode": "ensure",
                "requested_by": "edo-analysis",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert _FakeCallProcessingService.calls[0]["provider_call_budget"] == 3


def test_ensure_rejects_requested_by_different_from_grant() -> None:
    client = TestClient(app)

    response = client.post(
        "/call-processing/ensure",
        headers={"X-Call-Processing-Grant": _grant("admin")},
        json={
            "scope": _scope(),
            "required_artifacts": ["transcript"],
            "mode": "dry_run",
            "requested_by": "other-client",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "requested_by must match access grant client_id"


def test_artifacts_route_allows_reader_and_filters_allowed_kinds(monkeypatch) -> None:
    client = TestClient(app)
    app.dependency_overrides[call_processing_routes.get_session] = _override_session

    def fake_list_artifacts(_db: object, *, scope: ProcessingScope, grant: object, artifact_kinds: list[object]):
        return {
            "scope_hash": "scope-hash",
            "artifact_kinds": [str(item.value if hasattr(item, "value") else item) for item in artifact_kinds],
            "artifacts": [],
            "department_id": scope.department_id,
        }

    monkeypatch.setattr(call_processing_routes, "_list_artifacts", fake_list_artifacts)
    try:
        response = client.get(
            "/call-processing/artifacts",
            headers={"X-Call-Processing-Grant": _grant("reader")},
            params={
                "scope": json.dumps(_scope()),
                "artifact_kinds": "transcript,llm1_first_pass",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["artifact_kinds"] == ["transcript", "llm1_first_pass"]


def test_latest_run_route_returns_exact_scope_readiness(monkeypatch) -> None:
    client = TestClient(app)
    run_id = uuid4()

    class FakeProcessingRunRepository:
        def __init__(self, _db: object) -> None:
            pass

        def latest_for_scope(self, *, scope: ProcessingScope, required_artifacts: list[object]):
            assert scope.source == "onlinepbx"
            assert [str(item.value if hasattr(item, "value") else item) for item in required_artifacts] == [
                "transcript",
                "llm1_first_pass",
            ]
            return type(
                "Run",
                (),
                {
                    "id": run_id,
                    "requested_by": "scheduled_call_processing_upstream",
                    "scope_json": _scope(),
                    "scope_hash": "scope-hash",
                    "required_artifacts": ["transcript", "llm1_first_pass"],
                    "mode": "ensure",
                    "status": "ready",
                    "started_at": None,
                    "finished_at": None,
                    "heartbeat_at": None,
                    "counts_json": {"artifacts_ready": 4, "artifacts_missing": 0},
                    "errors_json": [],
                    "created_at": None,
                    "updated_at": None,
                },
            )()

    app.dependency_overrides[call_processing_routes.get_session] = _override_session
    monkeypatch.setattr(call_processing_routes, "ProcessingRunRepository", FakeProcessingRunRepository)
    try:
        response = client.get(
            "/call-processing/runs/latest",
            headers={"X-Call-Processing-Grant": _grant("reader")},
            params={
                "scope": json.dumps(_scope()),
                "required_artifacts": "transcript,llm1_first_pass",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == str(run_id)
    assert payload["status"] == "ready"
    assert payload["counts"]["artifacts_missing"] == 0


def test_single_artifact_route_returns_latest_active_for_reader(monkeypatch) -> None:
    client = TestClient(app)
    interaction_id = uuid4()

    class FakeArtifactRepository:
        def __init__(self, _db: object) -> None:
            pass

        def latest_active(self, requested_interaction_id: str, artifact_kind: object):
            assert requested_interaction_id == str(interaction_id)
            assert str(artifact_kind.value if hasattr(artifact_kind, "value") else artifact_kind) == "llm1_first_pass"
            return type(
                "Artifact",
                (),
                {
                    "id": uuid4(),
                    "department_id": uuid4(),
                    "interaction_id": interaction_id,
                    "artifact_kind": "llm1_first_pass",
                    "artifact_version": "llm1_first_pass_v1",
                    "status": "ready",
                    "is_active": True,
                    "payload_json": {"prompt_version": "llm1_v1"},
                    "text_value": None,
                    "provider": "openai",
                    "model": "gpt-test",
                    "account_alias": "primary",
                    "raw_response_ref": None,
                    "error_class": None,
                    "error_reason": None,
                    "retryable": None,
                    "source_updated_at": None,
                    "created_at": None,
                    "updated_at": None,
                },
            )()

    app.dependency_overrides[call_processing_routes.get_session] = _override_session
    monkeypatch.setattr(call_processing_routes, "ArtifactRepository", FakeArtifactRepository)
    try:
        response = client.get(
            f"/call-processing/artifacts/{interaction_id}/llm1_first_pass",
            headers={"X-Call-Processing-Grant": _grant("reader")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction_id"] == str(interaction_id)
    assert payload["artifact_kind"] == "llm1_first_pass"
