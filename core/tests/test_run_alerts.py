from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT if (PROJECT_ROOT / "app").exists() else PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.calls.run_alerts import build_run_alert_email, send_run_alert
from app.core_shared.config.settings import Settings


def _settings(**overrides: object) -> Settings:
    data: dict[str, object] = {
        "database_url": "postgresql://user:pass@localhost:5432/test_db",
        "postgres_db": "test_db",
        "postgres_user": "user",
        "postgres_password": "pass",
        "redis_url": "redis://:pass@localhost:6379/0",
        "redis_password": "pass",
        "app_env": "production",
        "openai_api_key": "test-key",
        "assemblyai_api_key": "test-key",
        "stt_provider": "assemblyai",
        "onlinepbx_domain": "example.onpbx.ru",
        "onlinepbx_api_key": "test-key",
        "smtp_user": "no-reply@example.test",
        "smtp_password": "smtp-pass",
        "smtp_from": "no-reply@example.test",
    }
    data.update(overrides)
    return Settings(**data)


def test_run_alert_subject_and_body_formatting() -> None:
    email = build_run_alert_email(
        "blocked",
        run_id="run-123",
        requested_by="scheduler",
        counts={"processed": 7, "quota_blocked": 1},
        scope={"date": "2026-06-15", "department_id": "sales"},
        errors=[{"error_class": "quota_exhausted", "message": "Provider budget reached"}],
        app_settings=_settings(alert_email_to="ops@example.test"),
        now=datetime(2026, 6, 15, 8, 30, tzinfo=UTC),
    )

    assert email.recipient == "ops@example.test"
    assert email.subject == "[AI Sales Analyzer][WARNING] Production run blocked: run-123"
    assert "Event: blocked" in email.body
    assert "Run ID: run-123" in email.body
    assert "Time UTC: 2026-06-15T08:30:00+00:00" in email.body
    assert "- processed: 7" in email.body
    assert '"department_id": "sales"' in email.body
    assert "Provider budget reached" in email.body


def test_run_alert_uses_default_admin_recipient_config() -> None:
    app_settings = _settings(alert_email_enabled=True)
    email = build_run_alert_email("failed", run_id="run-456", app_settings=app_settings)

    assert email.recipient == "admin@dogovor24.kz"
    assert app_settings.has_alert_email_delivery is True


def test_blocked_run_sends_email_alert() -> None:
    sent: list[dict[str, Any]] = []

    def fake_sender(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs)
        return {"channel": "email", "target": kwargs["email_to"], "status": "sent"}

    result = send_run_alert(
        "blocked",
        run_id="run-blocked",
        counts={"quota_blocked": 1},
        app_settings=_settings(alert_email_enabled=True),
        email_sender=fake_sender,
    )

    assert result["status"] == "sent"
    assert result["recipient"] == "admin@dogovor24.kz"
    assert sent[0]["email_to"] == "admin@dogovor24.kz"
    assert "Production run blocked" in sent[0]["subject"]
    assert "quota_blocked" in sent[0]["text"]


def test_completed_run_sends_only_when_success_alert_enabled() -> None:
    sent: list[dict[str, Any]] = []

    def fake_sender(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs)
        return {"channel": "email", "target": kwargs["email_to"], "status": "sent"}

    disabled_result = send_run_alert(
        "completed",
        run_id="run-success",
        app_settings=_settings(
            alert_email_enabled=True,
            alert_email_min_level="info",
            alert_email_on_success=False,
        ),
        email_sender=fake_sender,
    )
    enabled_result = send_run_alert(
        "completed",
        run_id="run-success",
        app_settings=_settings(
            alert_email_enabled=True,
            alert_email_min_level="warning",
            alert_email_on_success=True,
        ),
        email_sender=fake_sender,
    )

    assert disabled_result["status"] == "skipped"
    assert disabled_result["reason"] == "alert_on_success_disabled"
    assert enabled_result["status"] == "sent"
    assert len(sent) == 1
    assert "Production run completed" in sent[0]["subject"]


def test_started_run_sends_when_start_alert_enabled_despite_warning_threshold() -> None:
    sent: list[dict[str, Any]] = []

    def fake_sender(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs)
        return {"channel": "email", "target": kwargs["email_to"], "status": "sent"}

    result = send_run_alert(
        "started",
        run_id="run-started",
        app_settings=_settings(
            alert_email_enabled=True,
            alert_email_min_level="warning",
            alert_email_on_start=True,
        ),
        email_sender=fake_sender,
    )

    assert result["status"] == "sent"
    assert sent[0]["email_to"] == "admin@dogovor24.kz"
    assert "Production run started" in sent[0]["subject"]


def test_email_failure_is_stored_in_alert_result() -> None:
    def failing_sender(**_: Any) -> dict[str, Any]:
        raise RuntimeError("smtp unavailable")

    result = send_run_alert(
        "failed",
        run_id="run-failed",
        app_settings=_settings(alert_email_enabled=True),
        email_sender=failing_sender,
    )

    assert result["status"] == "failed"
    assert result["error"] == "smtp unavailable"
    assert result["error_class"] == "RuntimeError"
