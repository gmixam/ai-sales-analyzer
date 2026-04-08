"""Status routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/status", tags=["status"])


@router.get("")
async def get_status_snapshot() -> dict[str, str]:
    """Return a lightweight service status snapshot."""
    return {"service": "ok"}
