"""Operator CLI for the call-processing service boundary."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agents.call_processing import (
    AccessGrant,
    CallProcessingService,
    EnsureMode,
    ProcessingRunStatus,
    ProcessingScope,
    RequiredArtifactKind,
    is_stale_run,
)
from app.agents.call_processing.repositories import ProcessingRunRepository
from app.core_shared.api.routes.call_processing import _list_artifacts
from app.core_shared.db.session import get_db


def _print_json(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    return exit_code


def _load_json_arg(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text.startswith("{"):
        path = Path(text)
        if path.exists():
            text = path.read_text(encoding="utf-8")
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError("JSON value must be an object")
    return loaded


def _load_scope(value: str) -> ProcessingScope:
    return ProcessingScope.model_validate(_load_json_arg(value))


def _load_grant(value: str | None) -> AccessGrant:
    raw = value or os.getenv("CALL_PROCESSING_ACCESS_GRANT")
    if not raw:
        raise ValueError("missing --grant or CALL_PROCESSING_ACCESS_GRANT")
    return AccessGrant.model_validate(_load_json_arg(raw))


def _required_artifacts(value: str | None) -> list[RequiredArtifactKind]:
    if not value:
        return []
    return [RequiredArtifactKind(item.strip()) for item in value.split(",") if item.strip()]


def _require_admin(grant: AccessGrant) -> None:
    if not grant.can_run_processing:
        raise PermissionError("admin grant required")


def _require_reader(grant: AccessGrant) -> None:
    if not grant.active:
        raise PermissionError("active reader grant required")


def run_ensure(args: argparse.Namespace, mode: EnsureMode) -> int:
    grant = _load_grant(args.grant)
    _require_admin(grant)
    scope = _load_scope(args.scope)
    with get_db() as db:
        response = CallProcessingService(db, requested_by=grant.client_id).ensure(
            scope,
            _required_artifacts(args.required_artifacts),
            mode=mode,
            requested_by=grant.client_id,
            force_retry_failed=getattr(args, "force_retry_failed", False),
            provider_call_budget=grant.provider_call_budget_per_run,
        )
    return _print_json(response.model_dump(mode="json"))


def run_status(args: argparse.Namespace) -> int:
    grant = _load_grant(args.grant)
    _require_reader(grant)
    with get_db() as db:
        run = ProcessingRunRepository(db).get(args.run_id)
        if run is None:
            payload = {"error": "run not found", "run_id": args.run_id}
            return _print_json(payload, exit_code=1)
        payload = {
            "run_id": str(run.id),
            "requested_by": run.requested_by,
            "scope": run.scope_json or {},
            "scope_hash": run.scope_hash,
            "required_artifacts": run.required_artifacts or [],
            "mode": run.mode,
            "status": run.status,
            "counts": run.counts_json or {},
            "errors": run.errors_json or [],
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "heartbeat_at": run.heartbeat_at,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }
    return _print_json(payload)


def run_artifacts(args: argparse.Namespace) -> int:
    grant = _load_grant(args.grant)
    _require_reader(grant)
    scope = _load_scope(args.scope)
    with get_db() as db:
        payload = _list_artifacts(db, scope=scope, grant=grant)
    return _print_json(payload)


def retry_failed(args: argparse.Namespace) -> int:
    grant = _load_grant(args.grant)
    _require_admin(grant)
    with get_db() as db:
        run = ProcessingRunRepository(db).get(args.run_id)
        if run is None:
            return _print_json({"error": "run not found", "run_id": args.run_id}, exit_code=1)
        response = CallProcessingService(db, requested_by=grant.client_id).ensure(
            ProcessingScope.model_validate(run.scope_json or {}),
            [RequiredArtifactKind(item) for item in (run.required_artifacts or [])],
            mode=EnsureMode.ENSURE,
            requested_by=grant.client_id,
            force_retry_failed=True,
            provider_call_budget=grant.provider_call_budget_per_run,
        )
    return _print_json(
        {
            "retried_from_run_id": args.run_id,
            "retry_run": response.model_dump(mode="json"),
        }
    )


def cleanup_stale_runs(args: argparse.Namespace) -> int:
    grant = _load_grant(args.grant)
    _require_admin(grant)
    cleaned: list[dict[str, Any]] = []
    inspected = 0
    with get_db() as db:
        repo = ProcessingRunRepository(db)
        for run in repo.list_open():
            inspected += 1
            if not is_stale_run(run):
                continue
            previous_status = run.status
            errors = list(run.errors_json or [])
            errors.append(
                {
                    "error_class": "stale_processing_run",
                    "error_reason": "Run had no heartbeat/progress inside the approved stale window.",
                    "retryable": False,
                    "previous_status": previous_status,
                    "cleaned_by": grant.client_id,
                }
            )
            if getattr(args, "dry_run", False):
                cleaned.append(
                    {
                        "run_id": str(run.id),
                        "previous_status": previous_status,
                        "new_status": str(ProcessingRunStatus.STALE),
                        "heartbeat_at": run.heartbeat_at,
                        "updated_at": run.updated_at,
                        "dry_run": True,
                    }
                )
                continue
            repo.update_status(
                run,
                ProcessingRunStatus.STALE,
                errors_json=errors,
                finished_at=run.finished_at or datetime.now(UTC),
            )
            cleaned.append(
                {
                    "run_id": str(run.id),
                    "previous_status": previous_status,
                    "new_status": str(ProcessingRunStatus.STALE),
                    "heartbeat_at": run.heartbeat_at,
                    "updated_at": run.updated_at,
                    "dry_run": False,
                }
            )
        if cleaned and not getattr(args, "dry_run", False):
            db.commit()
    return _print_json(
        {
            "status": "ok",
            "inspected_open_runs": inspected,
            "stale_runs_cleaned": len(cleaned),
            "runs": cleaned,
            "dry_run": bool(getattr(args, "dry_run", False)),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="call-processing")
    parser.add_argument(
        "--grant",
        help="AccessGrant JSON object or path; defaults to CALL_PROCESSING_ACCESS_GRANT",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("ensure", "dry-run"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--scope", required=True, help="ProcessingScope JSON object or path")
        subparser.add_argument("--required-artifacts", default="")
        subparser.add_argument("--force-retry-failed", action="store_true")

    status_parser = subparsers.add_parser("run-status")
    status_parser.add_argument("--run-id", required=True)

    artifacts_parser = subparsers.add_parser("artifacts")
    artifacts_parser.add_argument("--scope", required=True, help="ProcessingScope JSON object or path")

    retry_parser = subparsers.add_parser("retry-failed")
    retry_parser.add_argument("--run-id", required=True)

    cleanup_parser = subparsers.add_parser("cleanup-stale-runs")
    cleanup_parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "ensure":
            return run_ensure(args, EnsureMode.ENSURE)
        if args.command == "dry-run":
            return run_ensure(args, EnsureMode.DRY_RUN)
        if args.command == "run-status":
            return run_status(args)
        if args.command == "artifacts":
            return run_artifacts(args)
        if args.command == "retry-failed":
            return retry_failed(args)
        if args.command == "cleanup-stale-runs":
            return cleanup_stale_runs(args)
    except (ValidationError, ValueError, PermissionError, json.JSONDecodeError) as exc:
        return _print_json({"error": str(exc)}, exit_code=1)
    return _print_json({"error": f"unknown command: {args.command}"}, exit_code=1)


if __name__ == "__main__":
    raise SystemExit(main())
