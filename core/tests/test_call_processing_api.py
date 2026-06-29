from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.call_processing import (
    EnsureResponse,
    ProcessingRunStatus,
    ProcessingScope,
    stable_scope_hash,
)
from app.agents.call_processing.repositories import ProcessingRunRepository
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


def test_latest_run_route_missing_uses_latest_handler_not_uuid_route(monkeypatch) -> None:
    client = TestClient(app)

    class FakeProcessingRunRepository:
        latest_calls = 0
        get_calls = 0

        def __init__(self, _db: object) -> None:
            pass

        def latest_for_scope(self, *, scope: ProcessingScope, required_artifacts: list[object]):
            self.__class__.latest_calls += 1
            assert scope.source == "onlinepbx"
            assert [str(item.value if hasattr(item, "value") else item) for item in required_artifacts] == [
                "transcript",
                "llm1_first_pass",
            ]
            return None

        def get(self, run_id: object):
            self.__class__.get_calls += 1
            raise AssertionError(f"latest was routed through generic run_id={run_id!r}")

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

    assert response.status_code == 404
    assert response.json()["detail"] == "run not found"
    assert FakeProcessingRunRepository.latest_calls == 1
    assert FakeProcessingRunRepository.get_calls == 0


def _covering_scope(**overrides: object) -> dict[str, object]:
    scope = {
        "department_id": "dept-1",
        "manager_ids": ["manager-1", "manager-2", "manager-3", "manager-4"],
        "extensions": ["317", "311", "325", "350"],
        "date_from": "2026-06-25",
        "date_to": "2026-06-25",
        "source": "onlinepbx",
    }
    scope.update(overrides)
    return scope


def _requested_manager_scope(**overrides: object) -> ProcessingScope:
    scope = {
        "department_id": "dept-1",
        "manager_ids": ["manager-1"],
        "extensions": ["317"],
        "date_from": "2026-06-25",
        "date_to": "2026-06-25",
        "source": "onlinepbx",
    }
    scope.update(overrides)
    return ProcessingScope.model_validate(scope)


def _run_row(
    *,
    scope_json: dict[str, object],
    status: str = "ready",
    artifacts_missing: int = 0,
    required_artifacts: list[str] | None = None,
) -> SimpleNamespace:
    updated_at = datetime(2026, 6, 26, 0, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        requested_by="scheduled_call_processing_upstream",
        scope_json=scope_json,
        scope_hash=stable_scope_hash(scope_json),
        required_artifacts=required_artifacts
        or ["transcript", "transcript_segments", "llm1_first_pass"],
        mode="ensure",
        status=status,
        started_at=None,
        finished_at=updated_at,
        heartbeat_at=None,
        counts_json={"artifacts_ready": 165, "artifacts_missing": artifacts_missing},
        errors_json=[],
        created_at=updated_at,
        updated_at=updated_at,
    )


class _FakeScalars:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self.rows

    def first(self) -> SimpleNamespace | None:
        return self.rows[0] if self.rows else None


class _FakeRunSession:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def scalars(self, _stmt: object) -> _FakeScalars:
        return _FakeScalars(self.rows)


def test_processing_run_repository_covering_scope_covers_single_manager() -> None:
    requested = _requested_manager_scope()
    covering = _run_row(scope_json=_covering_scope())

    run = ProcessingRunRepository(_FakeRunSession([covering])).latest_covering_for_scope(
        scope=requested,
        required_artifacts=["transcript", "transcript_segments", "llm1_first_pass"],
    )

    assert run is covering


def test_processing_run_repository_covering_scope_rejects_wrong_dimensions() -> None:
    requested = _requested_manager_scope()
    wrong_candidates = [
        _run_row(scope_json=_covering_scope(date_from="2026-06-24", date_to="2026-06-24")),
        _run_row(scope_json=_covering_scope(source="other-source")),
        _run_row(scope_json=_covering_scope(department_id="other-dept")),
        _run_row(scope_json=_covering_scope(manager_ids=["manager-2"], extensions=[])),
        _run_row(scope_json=_covering_scope(), required_artifacts=["transcript"]),
    ]

    for candidate in wrong_candidates:
        run = ProcessingRunRepository(_FakeRunSession([candidate])).latest_covering_for_scope(
            scope=requested,
            required_artifacts=["transcript", "transcript_segments", "llm1_first_pass"],
        )
        assert run is None


def test_processing_run_repository_covering_scope_missing_artifacts_is_diagnostic_not_ready() -> None:
    requested = _requested_manager_scope()
    missing_artifacts = _run_row(scope_json=_covering_scope(), artifacts_missing=1)

    run = ProcessingRunRepository(_FakeRunSession([missing_artifacts])).latest_covering_for_scope(
        scope=requested,
        required_artifacts=["transcript", "transcript_segments", "llm1_first_pass"],
    )

    assert run is missing_artifacts
    assert run.status == "ready"
    assert run.counts_json["artifacts_missing"] == 1


def test_covering_run_route_returns_match_diagnostics(monkeypatch) -> None:
    client = TestClient(app)
    run_id = uuid4()
    requested = _requested_manager_scope()

    class FakeProcessingRunRepository:
        def __init__(self, _db: object) -> None:
            pass

        def latest_covering_for_scope(self, *, scope: ProcessingScope, required_artifacts: list[object]):
            assert scope.manager_ids == ["manager-1"]
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
                    "scope_json": _covering_scope(),
                    "scope_hash": "covering-hash",
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
            "/call-processing/runs/covering",
            headers={"X-Call-Processing-Grant": _grant("reader")},
            params={
                "scope": requested.model_dump_json(exclude_none=True),
                "required_artifacts": "transcript,llm1_first_pass",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == str(run_id)
    assert payload["scope_match"] == "covering"
    assert payload["requested_scope_hash"] == stable_scope_hash(requested)
    assert payload["covering_scope_hash"] == "covering-hash"


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
