"""Status routes."""

from fastapi import APIRouter

from app.core_shared.runtime_identity import runtime_identity

router = APIRouter(prefix="/status", tags=["status"])


@router.get("")
async def get_status_snapshot() -> dict[str, object]:
    """Return a lightweight service status snapshot."""
    return {"service": "ok", "runtime": runtime_identity(process_type="api")}
