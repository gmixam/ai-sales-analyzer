from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "user")
os.environ.setdefault("POSTGRES_PASSWORD", "pass")
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("REDIS_PASSWORD", "pass")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("ASSEMBLYAI_API_KEY", "test-key")
os.environ.setdefault("ONLINEPBX_DOMAIN", "example.onpbx.ru")
os.environ.setdefault("ONLINEPBX_API_KEY", "test-key")

from app.core_shared import runtime_identity as runtime_identity_module  # noqa: E402
from app.core_shared.api.main import app  # noqa: E402
from app.core_shared.api.routes import status as status_routes  # noqa: E402
from app.core_shared.workers import tasks  # noqa: E402
from app.core_shared.workers.celery_app import RUNTIME_IDENTITY_TASK, build_task_routes  # noqa: E402
from report_scripts import scheduled_reporting_preflight as preflight  # noqa: E402


def _runtime(commit: str = "abc123", *, marker: bool = True) -> dict[str, object]:
    return {
        "service": "analysis",
        "process_type": "worker",
        "pid": 123,
        "started_at_utc": "2026-06-25T00:00:00+00:00",
        "uptime_sec": 5,
        "git_commit": commit,
        "git_branch": "main",
        "git_dirty": False,
        "code_markers": {
            "scheduled_rop_daily_digest": True,
            "deferred_to_scheduled_rop_digest": marker,
            "latest_upstream_handoff": True,
            "call_processing_latest_route_hardening": True,
        },
    }


def test_runtime_identity_survives_unknown_git(monkeypatch) -> None:
    monkeypatch.setattr(runtime_identity_module, "_run_git", lambda *_args: None)
    for env_name in (
        "APP_GIT_COMMIT",
        "GIT_COMMIT",
        "COMMIT_SHA",
        "SOURCE_VERSION",
        "RENDER_GIT_COMMIT",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(runtime_identity_module, "code_markers", lambda: {})

    payload = runtime_identity_module.runtime_identity(process_type="api")

    assert payload["process_type"] == "api"
    assert payload["git_commit"] == "unknown"
    assert payload["git_dirty"] is False
    assert isinstance(payload["uptime_sec"], int)


def test_status_endpoint_includes_runtime_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        status_routes,
        "runtime_identity",
        lambda process_type=None: {**_runtime(), "process_type": process_type},
    )
    client = TestClient(app)

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "ok"
    assert payload["runtime"]["process_type"] == "api"
    assert payload["runtime"]["code_markers"]["latest_upstream_handoff"] is True


def test_runtime_identity_task_is_registered_and_safe(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "runtime_identity",
        lambda process_type=None: {**_runtime(), "process_type": process_type},
    )

    result = tasks.get_runtime_identity()

    assert result["process_type"] == "worker"
    assert RUNTIME_IDENTITY_TASK in tasks.get_registered_tasks()
    assert build_task_routes("analysis")[RUNTIME_IDENTITY_TASK]["queue"] == "analysis"
    assert build_task_routes("call_processing")[RUNTIME_IDENTITY_TASK]["queue"] == "call_processing"


def test_runtime_status_preflight_blocks_commit_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_repo_head", lambda: "expected")
    monkeypatch.setattr(
        preflight,
        "_fetch_api_runtime",
        lambda *_args: {"target": "api", "probe_status": "ok", "runtime": _runtime("expected")},
    )
    monkeypatch.setattr(
        preflight,
        "_fetch_worker_runtime",
        lambda *_args: {"target": "worker", "probe_status": "ok", "runtime": _runtime("old")},
    )

    result = preflight.runtime_status(
        SimpleNamespace(
            expected_commit=None,
            required_marker=None,
            target="both",
            timeout=1,
            api_url="http://api/status",
            worker_queue="analysis",
        )
    )

    assert result["status"] == "blocked"
    assert result["billable_pipeline_started"] is False
    assert result["targets"][1]["status"] == "blocked"
    assert "commit mismatch" in result["targets"][1]["problems"][0]
    assert "restart analysis_worker/worker service" in result["operator_summary"]


def test_runtime_status_preflight_warns_on_unknown_commit_with_markers(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_repo_head", lambda: "expected")
    monkeypatch.setattr(
        preflight,
        "_fetch_api_runtime",
        lambda *_args: {
            "target": "api",
            "probe_status": "ok",
            "runtime": _runtime("unknown"),
        },
    )
    monkeypatch.setattr(
        preflight,
        "_fetch_worker_runtime",
        lambda *_args: {
            "target": "worker",
            "probe_status": "ok",
            "runtime": _runtime("expected"),
        },
    )

    result = preflight.runtime_status(
        SimpleNamespace(
            expected_commit=None,
            required_marker=None,
            target="both",
            timeout=1,
            api_url="http://api/status",
            worker_queue="analysis",
        )
    )

    assert result["status"] == "warning"
    assert result["targets"][0]["warnings"] == ["runtime git_commit is unknown"]


def test_runtime_status_preflight_blocks_missing_marker(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_repo_head", lambda: "expected")
    monkeypatch.setattr(
        preflight,
        "_fetch_api_runtime",
        lambda *_args: {"target": "api", "probe_status": "ok", "runtime": _runtime("expected")},
    )
    monkeypatch.setattr(
        preflight,
        "_fetch_worker_runtime",
        lambda *_args: {
            "target": "worker",
            "probe_status": "ok",
            "runtime": _runtime("expected", marker=False),
        },
    )

    result = preflight.runtime_status(
        SimpleNamespace(
            expected_commit=None,
            required_marker=None,
            target="both",
            timeout=1,
            api_url="http://api/status",
            worker_queue="analysis",
        )
    )

    assert result["status"] == "blocked"
    assert "deferred_to_scheduled_rop_digest" in result["targets"][1]["problems"][0]


def test_runtime_status_can_probe_call_processing_worker_marker_subset(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_repo_head", lambda: "expected")
    monkeypatch.setattr(
        preflight,
        "_fetch_api_runtime",
        lambda *_args: (_ for _ in ()).throw(AssertionError("api probe should be skipped")),
    )
    monkeypatch.setattr(
        preflight,
        "_fetch_worker_runtime",
        lambda queue, *_args: {
            "target": "worker",
            "probe_status": "ok",
            "queue": queue,
            "runtime": {
                **_runtime("expected"),
                "service": "call_processing",
                "code_markers": {"call_processing_latest_route_hardening": True},
            },
        },
    )

    result = preflight.runtime_status(
        SimpleNamespace(
            expected_commit=None,
            required_marker=["call_processing_latest_route_hardening"],
            target="worker",
            timeout=1,
            api_url="http://call_processing_api:8000/status",
            worker_queue="call_processing",
        )
    )

    assert result["status"] == "ok"
    assert result["target"] == "worker"
    assert result["worker_queue"] == "call_processing"
    assert result["required_markers"] == ["call_processing_latest_route_hardening"]
    assert len(result["targets"]) == 1
    assert result["targets"][0]["runtime"]["service"] == "call_processing"
