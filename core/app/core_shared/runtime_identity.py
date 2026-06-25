"""Runtime identity and code-version markers for operators."""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import CodeType, FunctionType
from typing import Any

STARTED_AT_UTC = datetime.now(UTC)
UNKNOWN = "unknown"

REQUIRED_CODE_MARKERS = (
    "scheduled_rop_daily_digest",
    "deferred_to_scheduled_rop_digest",
    "latest_upstream_handoff",
    "call_processing_latest_route_hardening",
)


def runtime_identity(*, process_type: str | None = None) -> dict[str, Any]:
    """Return a JSON-safe snapshot of the code loaded by this process."""
    git_info = _git_info()
    now = datetime.now(UTC)
    return {
        "service": _service_name(),
        "process_type": _process_type(process_type),
        "pid": os.getpid(),
        "started_at_utc": STARTED_AT_UTC.isoformat(),
        "uptime_sec": max(0, int((now - STARTED_AT_UTC).total_seconds())),
        "git_commit": git_info["git_commit"],
        "git_branch": git_info["git_branch"],
        "git_dirty": git_info["git_dirty"],
        "code_markers": code_markers(),
    }


def code_markers() -> dict[str, bool]:
    """Check whether required feature markers are present in loaded runtime code."""
    return {
        "scheduled_rop_daily_digest": _has_scheduled_rop_daily_digest(),
        "deferred_to_scheduled_rop_digest": _has_deferred_to_scheduled_rop_digest(),
        "latest_upstream_handoff": _has_latest_upstream_handoff(),
        "call_processing_latest_route_hardening": _has_call_processing_latest_route_hardening(),
    }


def _service_name() -> str:
    try:
        from app.core_shared.config.settings import settings

        service = str(settings.app_service or "").strip()
        if service:
            return service
    except Exception:  # noqa: BLE001 - status must survive config/import edge cases.
        pass
    return os.environ.get("APP_SERVICE", "").strip() or UNKNOWN


def _process_type(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_value = (
        os.environ.get("APP_PROCESS_TYPE")
        or os.environ.get("PROCESS_TYPE")
        or os.environ.get("SERVICE_PROCESS_TYPE")
    )
    if env_value:
        normalized = env_value.strip().lower()
        if normalized in {"api", "worker", "beat"}:
            return normalized

    argv = " ".join(sys.argv).lower()
    if "celery" in argv and "beat" in argv:
        return "beat"
    if "celery" in argv or "worker" in argv:
        return "worker"
    if "uvicorn" in argv or "gunicorn" in argv or "fastapi" in argv:
        return "api"
    return UNKNOWN


def _git_info() -> dict[str, Any]:
    repo_root = _repo_root()
    return {
        "git_commit": _git_value(repo_root, ("rev-parse", "HEAD"), _commit_fallbacks()),
        "git_branch": _git_value(
            repo_root,
            ("rev-parse", "--abbrev-ref", "HEAD"),
            _branch_fallbacks(),
        ),
        "git_dirty": _git_dirty(repo_root),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _commit_fallbacks() -> tuple[str, ...]:
    return (
        "APP_GIT_COMMIT",
        "GIT_COMMIT",
        "COMMIT_SHA",
        "SOURCE_VERSION",
        "RENDER_GIT_COMMIT",
    )


def _branch_fallbacks() -> tuple[str, ...]:
    return ("APP_GIT_BRANCH", "GIT_BRANCH", "BRANCH_NAME", "RENDER_GIT_BRANCH")


def _git_value(repo_root: Path, args: tuple[str, ...], env_names: tuple[str, ...]) -> str:
    value = _run_git(repo_root, args)
    if value:
        return value
    for env_name in env_names:
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            return env_value
    return UNKNOWN


def _git_dirty(repo_root: Path) -> bool:
    status = _run_git(repo_root, ("status", "--porcelain"))
    return bool(status)


def _run_git(repo_root: Path, args: tuple[str, ...]) -> str | None:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repo_root), *args),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:  # noqa: BLE001 - .git/git may be absent in containers.
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _has_scheduled_rop_daily_digest() -> bool:
    try:
        from app.agents.calls.scheduled_reporting import ScheduledReviewableReportingService

        method = getattr(
            ScheduledReviewableReportingService,
            "_with_scheduled_rop_daily_digest",
            None,
        )
        return _callable_contains_marker(method, "scheduled_rop_daily_digest")
    except Exception:  # noqa: BLE001 - marker checks must be best effort.
        return False


def _has_deferred_to_scheduled_rop_digest() -> bool:
    try:
        from app.agents.calls.reporting import CallsManualReportingOrchestrator

        return _class_contains_marker(
            CallsManualReportingOrchestrator,
            "deferred_to_scheduled_rop_digest",
        )
    except Exception:  # noqa: BLE001 - marker checks must be best effort.
        return False


def _has_latest_upstream_handoff() -> bool:
    try:
        from app.agents.calls import scheduled_reporting
        from app.agents.calls.reporting import CallsManualReportingOrchestrator

        pending_reasons = getattr(
            scheduled_reporting,
            "MANAGER_DAILY_UPSTREAM_PENDING_REASONS",
            set(),
        )
        required_reasons = {
            "waiting_upstream",
            "upstream_partial",
            "upstream_blocked",
            "upstream_missing",
            "upstream_not_ready",
        }
        has_reasons = required_reasons.issubset(set(pending_reasons or set()))
        has_readiness = hasattr(
            CallsManualReportingOrchestrator,
            "_call_processing_readiness_from_run",
        )
        has_wait_observability = _class_contains_marker(
            getattr(scheduled_reporting, "ScheduledReviewableReportingService"),
            "retry_upstream_readiness",
        )
        return bool(has_reasons and has_readiness and has_wait_observability)
    except Exception:  # noqa: BLE001 - marker checks must be best effort.
        return False


def _has_call_processing_latest_route_hardening() -> bool:
    try:
        from app.core_shared.api.routes.call_processing import router

        paths = [str(getattr(route, "path", "")) for route in router.routes]
        latest_index = _route_path_index(paths, suffix="/runs/latest")
        uuid_index = _route_path_index(paths, suffix="/runs/{run_id:uuid}")
        has_generic_run_id = any(path.endswith("/runs/{run_id}") for path in paths)
        return latest_index is not None and uuid_index is not None and latest_index < uuid_index and not has_generic_run_id
    except Exception:  # noqa: BLE001 - marker checks must be best effort.
        return False


def _route_path_index(paths: list[str], *, suffix: str) -> int | None:
    for index, path in enumerate(paths):
        if path.endswith(suffix):
            return index
    return None


def _class_contains_marker(cls: type[Any], marker: str) -> bool:
    for _, value in inspect.getmembers(cls):
        if _callable_contains_marker(value, marker):
            return True
    return False


def _callable_contains_marker(value: Any, marker: str) -> bool:
    func = _unwrap_function(value)
    if func is None:
        return False
    return _code_contains_marker(func.__code__, marker)


def _unwrap_function(value: Any) -> FunctionType | None:
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    if isinstance(value, FunctionType):
        return value
    if callable(value) and hasattr(value, "__func__"):
        func = getattr(value, "__func__")
        if isinstance(func, FunctionType):
            return func
    return None


def _code_contains_marker(code: CodeType, marker: str) -> bool:
    for const in code.co_consts:
        if const == marker:
            return True
        if isinstance(const, CodeType) and _code_contains_marker(const, marker):
            return True
    return False
