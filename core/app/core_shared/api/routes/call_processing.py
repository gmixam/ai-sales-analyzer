"""Call-processing service API routes."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import ValidationError

from app.agents.call_processing import (
    AccessGrant,
    ArtifactKind,
    CallProcessingService,
    EnsureRequest,
    ProcessingClientRole,
    ProcessingScope,
    RequiredArtifactKind,
    stable_scope_hash,
)
from app.agents.call_processing.repositories import ArtifactRepository, ProcessingRunRepository
from app.core_shared.db.session import get_db

router = APIRouter(prefix="/call-processing", tags=["call-processing"])


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value


def _load_access_grant(raw_grant: str | None) -> AccessGrant:
    if not raw_grant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-Call-Processing-Grant header",
        )
    try:
        payload = json.loads(raw_grant)
        grant = AccessGrant.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid X-Call-Processing-Grant header",
        ) from exc
    if not grant.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="inactive access grant")
    return grant


def get_access_grant(
    x_call_processing_grant: str | None = Header(default=None, alias="X-Call-Processing-Grant"),
) -> AccessGrant:
    """Parse the simple header-based AccessGrant contract."""
    return _load_access_grant(x_call_processing_grant)


def require_admin(grant: AccessGrant = Depends(get_access_grant)) -> AccessGrant:
    if not grant.can_run_processing:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin grant required")
    return grant


def require_reader(grant: AccessGrant = Depends(get_access_grant)) -> AccessGrant:
    if ProcessingClientRole(grant.role) not in {ProcessingClientRole.ADMIN, ProcessingClientRole.READER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reader grant required")
    return grant


def get_session() -> Iterator[Any]:
    with get_db() as db:
        yield db


def _allowed_artifact_kinds(
    grant: AccessGrant,
    requested: list[ArtifactKind | RequiredArtifactKind | str] | None = None,
) -> list[ArtifactKind]:
    allowed = {ArtifactKind(item) for item in grant.allowed_artifact_kinds}
    if requested:
        wanted = {ArtifactKind(str(item.value if hasattr(item, "value") else item)) for item in requested}
        allowed &= wanted
    return sorted(allowed, key=lambda item: item.value)


def _parse_scope(raw_scope: str) -> ProcessingScope:
    try:
        return ProcessingScope.model_validate_json(raw_scope)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _parse_artifact_kinds(raw: str | None) -> list[ArtifactKind]:
    if not raw:
        return []
    try:
        return [ArtifactKind(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _run_to_dict(run: Any) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "requested_by": run.requested_by,
        "scope": run.scope_json or {},
        "scope_hash": run.scope_hash,
        "required_artifacts": run.required_artifacts or [],
        "mode": run.mode,
        "status": run.status,
        "started_at": _jsonable(run.started_at),
        "finished_at": _jsonable(run.finished_at),
        "heartbeat_at": _jsonable(run.heartbeat_at),
        "counts": run.counts_json or {},
        "errors": run.errors_json or [],
        "created_at": _jsonable(run.created_at),
        "updated_at": _jsonable(run.updated_at),
    }


def _artifact_to_dict(artifact: Any) -> dict[str, Any]:
    return {
        "artifact_id": str(artifact.id),
        "department_id": str(artifact.department_id),
        "interaction_id": str(artifact.interaction_id),
        "artifact_kind": artifact.artifact_kind,
        "artifact_version": artifact.artifact_version,
        "status": artifact.status,
        "is_active": artifact.is_active,
        "payload": artifact.payload_json,
        "text": artifact.text_value,
        "provider": artifact.provider,
        "model": artifact.model,
        "account_alias": artifact.account_alias,
        "raw_response_ref": artifact.raw_response_ref,
        "error_class": artifact.error_class,
        "error_reason": artifact.error_reason,
        "retryable": artifact.retryable,
        "source_updated_at": _jsonable(artifact.source_updated_at),
        "created_at": _jsonable(artifact.created_at),
        "updated_at": _jsonable(artifact.updated_at),
    }


def _list_artifacts(
    db: Any,
    *,
    scope: ProcessingScope,
    grant: AccessGrant,
    artifact_kinds: list[ArtifactKind] | None = None,
) -> dict[str, Any]:
    kinds = _allowed_artifact_kinds(grant, artifact_kinds)
    if not kinds:
        return {"scope_hash": None, "artifact_kinds": [], "artifacts": []}

    service = CallProcessingService(db)
    interactions = service._find_interactions(scope)
    interaction_ids = [interaction.id for interaction in interactions]
    artifacts = ArtifactRepository(db).list_latest_active(interaction_ids, kinds)
    return {
        "scope_hash": stable_scope_hash(scope),
        "artifact_kinds": [kind.value for kind in kinds],
        "artifacts": [_artifact_to_dict(artifact) for artifact in artifacts],
    }


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "call_processing",
        "auth": "X-Call-Processing-Grant",
    }


@router.post("/ensure")
async def ensure_call_processing(
    request: EnsureRequest,
    grant: AccessGrant = Depends(require_admin),
    db: Any = Depends(get_session),
) -> dict[str, Any]:
    if request.requested_by != grant.client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="requested_by must match access grant client_id",
        )
    service = CallProcessingService(db, requested_by=grant.client_id)
    response = await service.ensure_async(
        request.scope,
        request.required_artifacts,
        request.mode,
        requested_by=request.requested_by,
        force_retry_failed=request.force_retry_failed,
    )
    return response.model_dump(mode="json")


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    _grant: AccessGrant = Depends(require_reader),
    db: Any = Depends(get_session),
) -> dict[str, Any]:
    run = ProcessingRunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return _run_to_dict(run)


@router.get("/artifacts")
async def get_artifacts(
    scope: str = Query(..., description="ProcessingScope JSON"),
    artifact_kinds: str | None = Query(default=None),
    grant: AccessGrant = Depends(require_reader),
    db: Any = Depends(get_session),
) -> dict[str, Any]:
    return _list_artifacts(
        db,
        scope=_parse_scope(scope),
        grant=grant,
        artifact_kinds=_parse_artifact_kinds(artifact_kinds),
    )


@router.get("/artifacts/{interaction_id}/{artifact_kind}")
async def get_interaction_artifact(
    interaction_id: str,
    artifact_kind: ArtifactKind,
    grant: AccessGrant = Depends(require_reader),
    db: Any = Depends(get_session),
) -> dict[str, Any]:
    allowed = _allowed_artifact_kinds(grant, [artifact_kind])
    if artifact_kind not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="artifact kind not allowed")
    artifact = ArtifactRepository(db).latest_active(interaction_id, artifact_kind)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    return _artifact_to_dict(artifact)
