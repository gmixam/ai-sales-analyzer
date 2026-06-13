from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from app.agents.calls.orchestrator import CallsManualPilotOrchestrator
from app.core_shared.exceptions import ASAError


def test_manual_live_pilot_is_legacy_only_in_external_service_mode() -> None:
    orchestrator = object.__new__(CallsManualPilotOrchestrator)
    orchestrator.department_id = uuid4()

    previous = os.environ.get("CALL_PROCESSING_MODE")
    os.environ["CALL_PROCESSING_MODE"] = "external_service"
    try:
        with pytest.raises(ASAError, match="available only in CALL_PROCESSING_MODE=legacy"):
            asyncio.run(
                CallsManualPilotOrchestrator.run_live(
                    orchestrator,
                    date="2026-06-03",
                    external_ids=["call-1"],
                    send_notification=False,
                )
            )
    finally:
        if previous is None:
            os.environ.pop("CALL_PROCESSING_MODE", None)
        else:
            os.environ["CALL_PROCESSING_MODE"] = previous
