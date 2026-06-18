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
        "alert_telegram_enabled": False,
        "alert_telegram_chat_id": "",
        "telegram_bot_token": "",
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
    assert email.body.startswith(email.operator_summary)
    assert "Что случилось:" in email.body
    assert "Кого/что затронуло:" not in email.body
    assert "Что затронуто:" in email.body
    assert "На что влияет:" in email.body
    assert "Что проверить:" in email.body
    assert "Run: run-123" in email.body
    assert "- Event: blocked" in email.body
    assert "- Run ID: run-123" in email.body
    assert "- Time UTC: 2026-06-15T08:30:00+00:00" in email.body
    assert "processed: 7" in email.body
    assert "ограничение бюджета или лимита" in email.body
    assert '"department_id": "sales"' not in email.body
    assert '{"error_class"' not in email.body


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
    assert "Технические детали: см. observability/logs." in sent[0]["text"]


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


def test_blocked_run_sends_telegram_alert_when_enabled() -> None:
    sent: list[dict[str, str]] = []

    def fake_sender(chat_id: str, text: str) -> dict[str, Any]:
        sent.append({"chat_id": chat_id, "text": text})
        return {"channel": "telegram", "target": chat_id, "status": "sent"}

    result = send_run_alert(
        "blocked",
        run_id="run-blocked",
        counts={"quota_blocked": 1},
        app_settings=_settings(
            alert_telegram_enabled=True,
            alert_telegram_chat_id="74665909",
            telegram_bot_token="telegram-token",
        ),
        telegram_sender=fake_sender,
    )

    assert result["channel"] == "telegram"
    assert result["status"] == "sent"
    assert result["recipient"] == "74665909"
    assert sent[0]["chat_id"] == "74665909"
    assert "Production run blocked" in sent[0]["text"]
    assert "quota_blocked" in sent[0]["text"]
    assert "Alert metadata:" not in sent[0]["text"]
    assert sent[0]["text"].endswith("Run: run-blocked")


def test_telegram_alert_respects_min_level() -> None:
    result = send_run_alert(
        "completed",
        run_id="run-success",
        app_settings=_settings(
            alert_telegram_enabled=True,
            alert_telegram_chat_id="74665909",
            telegram_bot_token="telegram-token",
            alert_telegram_min_level="warning",
            alert_telegram_on_success=False,
        ),
        telegram_sender=lambda _chat_id, _text: {"status": "sent"},
    )

    assert result["channel"] == "telegram"
    assert result["status"] == "skipped"
    assert result["reason"] == "alert_on_success_disabled"


def test_operator_summary_is_used_for_email_and_exact_telegram_text() -> None:
    sent_email: list[dict[str, Any]] = []
    sent_telegram: list[dict[str, str]] = []
    summary = "\n".join(
        [
            "Отчеты за 2026-06-15: проблема с доставкой",
            "",
            "Что случилось:",
            "Не доставлены отчеты 2 менеджерам до SLA 10:00.",
            "",
            "Кого затронуло:",
            "- Тимур: ошибка отправки email",
            "",
            "На что влияет:",
            "Менеджеры не получили ежедневный отчет вовремя.",
            "",
            "Что проверить:",
            "scheduled reporting batch, draft delivery, email delivery result.",
            "",
            "Run: manager_daily_sla:2026-06-15:hard",
        ]
    )

    def fake_email_sender(**kwargs: Any) -> dict[str, Any]:
        sent_email.append(kwargs)
        return {"status": "sent"}

    def fake_telegram_sender(chat_id: str, text: str) -> dict[str, Any]:
        sent_telegram.append({"chat_id": chat_id, "text": text})
        return {"status": "sent"}

    email_result = send_run_alert(
        "blocked",
        run_id="manager_daily_sla:2026-06-15:hard",
        operator_summary=summary,
        details={"managers": [{"manager": "Тимур", "payload": {"secret": True}}]},
        app_settings=_settings(alert_email_enabled=True),
        email_sender=fake_email_sender,
    )
    telegram_result = send_run_alert(
        "blocked",
        run_id="manager_daily_sla:2026-06-15:hard",
        operator_summary=summary,
        errors=[{"manager": "Тимур", "error_class": "email_failed"}],
        details={"raw": [{"secret": True}]},
        app_settings=_settings(
            alert_telegram_enabled=True,
            alert_telegram_chat_id="74665909",
            telegram_bot_token="telegram-token",
        ),
        telegram_sender=fake_telegram_sender,
    )

    assert email_result["status"] == "sent"
    assert telegram_result["status"] == "sent"
    assert sent_email[0]["text"].startswith(summary)
    assert "Технические детали: см. observability/logs." in sent_email[0]["text"]
    assert "secret" not in sent_email[0]["text"]
    assert sent_telegram[0]["text"] == summary


def test_manager_daily_zero_batch_operator_summary_hides_structured_payloads() -> None:
    sent_email: list[dict[str, Any]] = []
    sent_telegram: list[dict[str, str]] = []
    summary = "\n".join(
        [
            "[WARN] Daily reports: отчеты не созданы за 2026-06-17",
            "",
            "Что случилось:",
            "Scheduled analysis обработал расписание, но не создал report batches.",
            "",
            "Кого затронуло:",
            "- Тимур: analysis_ready=8, batch не создан",
            "- Толеген: analysis_ready=27, batch не создан",
            "",
            "На что влияет:",
            "Менеджеры и РОП не получат ежедневные отчеты автоматически.",
            "",
            "Что проверить:",
            "scheduled_candidate_selection, open-batches, analysis_worker logs.",
            "",
            "Run: manager_daily:schedule-1:2026-06-17",
        ]
    )
    structured_details = {
        "reason": "manager_daily_zero_batches_after_candidate_selection",
        "managers": [
            {"manager_name": "Тимур", "analysis_ready": 8, "raw_payload": {"hidden": True}},
            {"manager_name": "Толеген", "analysis_ready": 27, "raw_payload": {"hidden": True}},
        ],
    }

    def fake_email_sender(**kwargs: Any) -> dict[str, Any]:
        sent_email.append(kwargs)
        return {"status": "sent"}

    def fake_telegram_sender(chat_id: str, text: str) -> dict[str, Any]:
        sent_telegram.append({"chat_id": chat_id, "text": text})
        return {"status": "sent"}

    send_run_alert(
        "blocked",
        run_id="manager_daily:schedule-1:2026-06-17",
        title="manager_daily zero batches",
        level="warning",
        scope={"report_date": "2026-06-17", "manager_scope": structured_details["managers"]},
        counts={"expected_managers": 2, "batches_created": 0},
        errors=[structured_details],
        details=structured_details,
        operator_summary=summary,
        app_settings=_settings(alert_email_enabled=True),
        email_sender=fake_email_sender,
    )
    send_run_alert(
        "blocked",
        run_id="manager_daily:schedule-1:2026-06-17",
        title="manager_daily zero batches",
        level="warning",
        scope={"report_date": "2026-06-17", "manager_scope": structured_details["managers"]},
        counts={"expected_managers": 2, "batches_created": 0},
        errors=[structured_details],
        details=structured_details,
        operator_summary=summary,
        app_settings=_settings(
            alert_telegram_enabled=True,
            alert_telegram_chat_id="74665909",
            telegram_bot_token="telegram-token",
        ),
        telegram_sender=fake_telegram_sender,
    )

    email_text = sent_email[0]["text"]
    telegram_text = sent_telegram[0]["text"]
    assert email_text.startswith(summary)
    assert telegram_text == summary
    for text in (email_text, telegram_text):
        assert "manager_daily_zero_batches_after_candidate_selection" not in text
        assert "raw_payload" not in text
        assert "{'manager_name'" not in text
        assert '"manager_name"' not in text
        assert "hidden" not in text


def test_fallback_operator_summary_bounds_dict_errors_without_raw_payloads() -> None:
    errors = [
        {"manager": f"Manager {index}", "error_class": "email_failed", "details": {"raw": index}}
        for index in range(1, 9)
    ]

    email = build_run_alert_email(
        "failed",
        run_id="manager_daily_sla:2026-06-15:hard",
        counts={"failed_reports": 8, "partial_reports": 2, "nested": {"raw": True}},
        scope={"date": "2026-06-15", "managers": [{"name": "hidden"}]},
        errors=errors,
        details={"blockers": [{"manager": "Hidden", "payload": {"raw": True}}]},
        app_settings=_settings(alert_email_to="ops@example.test"),
        now=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
    )

    assert len(email.operator_summary) <= 1500
    assert "Manager 1: ошибка отправки email" in email.operator_summary
    assert "Manager 5: ошибка отправки email" in email.operator_summary
    assert "Manager 6: ошибка отправки email" not in email.operator_summary
    assert "Еще 4 см. в observability/logs." in email.operator_summary
    assert "failed_reports: 8" in email.operator_summary
    assert "partial_reports: 2" in email.operator_summary
    assert "{'raw':" not in email.body
    assert '"raw"' not in email.body
    assert "hidden" not in email.body
