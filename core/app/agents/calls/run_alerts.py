"""Fail-safe production run email alerts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

import structlog

from app.agents.calls.delivery import send_smtp_email_message
from app.core_shared.config.settings import settings


ALERT_LEVELS = {
    "info": 10,
    "warning": 20,
    "error": 30,
    "critical": 40,
}

RUN_ALERT_EVENTS = {
    "started": {
        "level": "info",
        "status": "running",
        "title": "Production run started",
    },
    "blocked": {
        "level": "warning",
        "status": "blocked",
        "title": "Production run blocked",
    },
    "completed": {
        "level": "info",
        "status": "completed",
        "title": "Production run completed",
    },
    "failed": {
        "level": "error",
        "status": "failed",
        "title": "Production run failed",
    },
}

EmailSender = Callable[..., dict[str, Any]]

logger = structlog.get_logger().bind(module="calls.run_alerts")


@dataclass(frozen=True, slots=True)
class RunAlertEmail:
    """Formatted alert email ready for delivery."""

    event: str
    level: str
    status: str
    recipient: str
    subject: str
    body: str


def build_run_alert_email(
    event: str,
    *,
    run_id: str | None = None,
    status: str | None = None,
    title: str | None = None,
    level: str | None = None,
    requested_by: str | None = None,
    scope: dict[str, Any] | None = None,
    counts: dict[str, Any] | None = None,
    errors: list[Any] | None = None,
    details: dict[str, Any] | None = None,
    app_settings: Any = settings,
    now: datetime | None = None,
) -> RunAlertEmail:
    """Build a deterministic production run alert subject and text body."""
    normalized_event = _normalize_event(event)
    event_defaults = RUN_ALERT_EVENTS[normalized_event]
    resolved_level = _normalize_level(level or str(event_defaults["level"]))
    resolved_status = (status or str(event_defaults["status"])).strip() or "unknown"
    resolved_title = (title or str(event_defaults["title"])).strip()
    timestamp = now or datetime.now(UTC)
    run_label = (run_id or "unknown").strip() or "unknown"
    environment = str(getattr(app_settings, "app_env", "") or "unknown").strip() or "unknown"
    service = str(getattr(app_settings, "app_service", "") or "unknown").strip() or "unknown"
    recipient = str(getattr(app_settings, "alert_email_to", "") or "").strip()

    subject = f"[AI Sales Analyzer][{resolved_level.upper()}] {resolved_title}: {run_label}"
    body_lines = [
        "AI Sales Analyzer production run alert",
        "",
        f"Event: {normalized_event}",
        f"Level: {resolved_level}",
        f"Status: {resolved_status}",
        f"Run ID: {run_label}",
        f"Environment: {environment}",
        f"Service: {service}",
        f"Time UTC: {timestamp.isoformat()}",
    ]
    if requested_by:
        body_lines.append(f"Requested by: {requested_by}")

    body_lines.extend(
        [
            "",
            "Counts:",
            _format_mapping(counts),
            "",
            "Scope:",
            _format_json(scope or {}),
            "",
            "Errors:",
            _format_errors(errors or []),
        ]
    )
    if details:
        body_lines.extend(["", "Details:", _format_json(details)])

    return RunAlertEmail(
        event=normalized_event,
        level=resolved_level,
        status=resolved_status,
        recipient=recipient,
        subject=subject,
        body="\n".join(body_lines),
    )


def send_run_alert(
    event: str,
    *,
    run_id: str | None = None,
    status: str | None = None,
    title: str | None = None,
    level: str | None = None,
    requested_by: str | None = None,
    scope: dict[str, Any] | None = None,
    counts: dict[str, Any] | None = None,
    errors: list[Any] | None = None,
    details: dict[str, Any] | None = None,
    app_settings: Any = settings,
    email_sender: EmailSender | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Send one production run alert, returning an observability-safe attempt result."""
    email = build_run_alert_email(
        event,
        run_id=run_id,
        status=status,
        title=title,
        level=level,
        requested_by=requested_by,
        scope=scope,
        counts=counts,
        errors=errors,
        details=details,
        app_settings=app_settings,
        now=now,
    )
    attempt = _base_attempt(email)
    skip_reason = _alert_skip_reason(email=email, event=email.event, app_settings=app_settings)
    if skip_reason:
        attempt.update({"status": "skipped", "reason": skip_reason})
        return attempt

    sender = email_sender or send_smtp_email_message
    try:
        delivery = sender(email_to=email.recipient, subject=email.subject, text=email.body)
    except Exception as exc:  # noqa: BLE001 - alerting must never break a production run
        error = str(exc)
        logger.warning(
            "run_alert.email_failed",
            alert_event=email.event,
            level=email.level,
            recipient=email.recipient,
            error=error,
            error_class=exc.__class__.__name__,
        )
        attempt.update(
            {
                "status": "failed",
                "error": error,
                "error_class": exc.__class__.__name__,
            }
        )
        return attempt

    attempt.update({"status": "sent", "delivery": delivery})
    logger.info(
        "run_alert.email_sent",
        alert_event=email.event,
        level=email.level,
        recipient=email.recipient,
        run_id=run_id,
    )
    return attempt


def _base_attempt(email: RunAlertEmail) -> dict[str, Any]:
    return {
        "channel": "email",
        "event": email.event,
        "level": email.level,
        "recipient": email.recipient or None,
        "subject": email.subject,
        "status": "pending",
    }


def _alert_skip_reason(*, email: RunAlertEmail, event: str, app_settings: Any) -> str | None:
    if not bool(getattr(app_settings, "alert_email_enabled", False)):
        return "alert_email_disabled"
    if event == "started" and not bool(getattr(app_settings, "alert_email_on_start", False)):
        return "alert_on_start_disabled"
    if event == "completed" and not bool(getattr(app_settings, "alert_email_on_success", False)):
        return "alert_on_success_disabled"
    if not email.recipient:
        return "alert_recipient_missing"
    if not bool(getattr(app_settings, "has_smtp", False)):
        return "smtp_not_configured"

    min_level = _normalize_level(str(getattr(app_settings, "alert_email_min_level", "warning")))
    explicit_event_enabled = (
        event == "started" and bool(getattr(app_settings, "alert_email_on_start", False))
    ) or (
        event == "completed" and bool(getattr(app_settings, "alert_email_on_success", False))
    )
    if not explicit_event_enabled and ALERT_LEVELS[email.level] < ALERT_LEVELS[min_level]:
        return "below_min_level"
    return None


def _normalize_event(event: str) -> str:
    normalized = event.strip().lower()
    aliases = {
        "start": "started",
        "success": "completed",
        "complete": "completed",
        "succeeded": "completed",
        "blocked_run": "blocked",
        "failure": "failed",
        "error": "failed",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in RUN_ALERT_EVENTS:
        allowed = ", ".join(sorted(RUN_ALERT_EVENTS))
        raise ValueError(f"Unsupported run alert event '{event}'. Expected one of: {allowed}.")
    return normalized


def _normalize_level(level: str) -> str:
    normalized = level.strip().lower()
    aliases = {"warn": "warning", "fatal": "critical"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in ALERT_LEVELS:
        allowed = ", ".join(sorted(ALERT_LEVELS))
        raise ValueError(f"Unsupported alert level '{level}'. Expected one of: {allowed}.")
    return normalized


def _format_mapping(values: dict[str, Any] | None) -> str:
    if not values:
        return "- none"
    lines = []
    for key in sorted(values):
        lines.append(f"- {key}: {values[key]}")
    return "\n".join(lines)


def _format_errors(errors: list[Any]) -> str:
    if not errors:
        return "- none"
    lines = []
    for item in errors:
        if isinstance(item, str):
            lines.append(f"- {item}")
        else:
            lines.append(_format_json(item))
    return "\n".join(lines)


def _format_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
