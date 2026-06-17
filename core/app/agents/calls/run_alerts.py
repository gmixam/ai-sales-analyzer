"""Fail-safe production run alerts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

import httpx
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

REASON_LABELS = {
    "sla_missed": "отчет не доставлен до SLA",
    "missing_artifacts": "не хватило готовых данных для отчета",
    "email_failed": "ошибка отправки email",
    "manager_email_failed": "письмо менеджеру не отправлено",
    "no_calls": "за день нет звонков в scope",
    "no_audio": "звонки есть, но аудио недоступно",
    "stt_error": "ошибка транскрибации",
    "llm_error": "ошибка анализа",
    "llm2_admission_non_commercial_or_unusable": "звонок не принят в коммерческий разбор",
    "quota": "ограничение бюджета или лимита",
    "budget": "ограничение бюджета или лимита",
    "read_timeout": "таймаут при ожидании сервиса",
    "ReadTimeout": "таймаут при ожидании сервиса",
}

OPERATOR_ALERT_MAX_CHARS = 1500
OPERATOR_ALERT_MAX_ITEMS = 5

EmailSender = Callable[..., dict[str, Any]]
TelegramSender = Callable[[str, str], dict[str, Any]]

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
    operator_summary: str


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
    operator_summary: str | None = None,
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
    summary = _resolve_operator_summary(
        operator_summary=operator_summary,
        event=normalized_event,
        status=resolved_status,
        title=resolved_title,
        level=resolved_level,
        run_id=run_label,
        counts=counts,
        scope=scope,
        errors=errors,
        details=details,
    )
    body_lines = [
        summary,
        "",
        "Технические детали: см. observability/logs.",
        "",
        "Alert metadata:",
        f"- Event: {normalized_event}",
        f"- Level: {resolved_level}",
        f"- Status: {resolved_status}",
        f"- Run ID: {run_label}",
        f"- Environment: {environment}",
        f"- Service: {service}",
        f"- Time UTC: {timestamp.isoformat()}",
    ]
    if requested_by:
        body_lines.append(f"- Requested by: {requested_by}")

    return RunAlertEmail(
        event=normalized_event,
        level=resolved_level,
        status=resolved_status,
        recipient=recipient,
        subject=subject,
        body="\n".join(body_lines),
        operator_summary=summary,
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
    operator_summary: str | None = None,
    app_settings: Any = settings,
    email_sender: EmailSender | None = None,
    telegram_sender: TelegramSender | None = None,
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
        operator_summary=operator_summary,
        app_settings=app_settings,
        now=now,
    )
    if bool(getattr(app_settings, "alert_telegram_enabled", False)):
        return _send_telegram_alert(
            email,
            event=email.event,
            run_id=run_id,
            app_settings=app_settings,
            telegram_sender=telegram_sender,
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


def _send_telegram_alert(
    email: RunAlertEmail,
    *,
    event: str,
    run_id: str | None,
    app_settings: Any,
    telegram_sender: TelegramSender | None,
) -> dict[str, Any]:
    chat_id = str(getattr(app_settings, "alert_telegram_chat_id", "") or "").strip()
    attempt = {
        "channel": "telegram",
        "event": email.event,
        "level": email.level,
        "recipient": chat_id or None,
        "subject": email.subject,
        "status": "pending",
    }
    skip_reason = _alert_telegram_skip_reason(
        email=email,
        event=event,
        chat_id=chat_id,
        app_settings=app_settings,
    )
    if skip_reason:
        attempt.update({"status": "skipped", "reason": skip_reason})
        return attempt

    sender = telegram_sender or _send_telegram_message
    try:
        delivery = sender(chat_id, _format_telegram_alert(email))
    except Exception as exc:  # noqa: BLE001 - alerting must never break a production run
        error = str(exc)
        logger.warning(
            "run_alert.telegram_failed",
            alert_event=email.event,
            level=email.level,
            recipient=chat_id,
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
        "run_alert.telegram_sent",
        alert_event=email.event,
        level=email.level,
        recipient=chat_id,
        run_id=run_id,
    )
    return attempt


def _send_telegram_message(chat_id: str, text: str) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    chunks = _chunk_text(text, max_len=3500)
    with httpx.Client(timeout=30) as client:
        for chunk in chunks:
            response = client.post(url, json={"chat_id": chat_id, "text": chunk})
            response.raise_for_status()
    return {
        "channel": "telegram",
        "target": chat_id,
        "status": "sent",
        "messages_sent": len(chunks),
    }


def _base_attempt(email: RunAlertEmail) -> dict[str, Any]:
    return {
        "channel": "email",
        "event": email.event,
        "level": email.level,
        "recipient": email.recipient or None,
        "subject": email.subject,
        "status": "pending",
    }


def _alert_telegram_skip_reason(
    *,
    email: RunAlertEmail,
    event: str,
    chat_id: str,
    app_settings: Any,
) -> str | None:
    if not bool(getattr(app_settings, "alert_telegram_enabled", False)):
        return "alert_telegram_disabled"
    if event == "started" and not bool(getattr(app_settings, "alert_telegram_on_start", False)):
        return "alert_on_start_disabled"
    if event == "completed" and not bool(getattr(app_settings, "alert_telegram_on_success", False)):
        return "alert_on_success_disabled"
    if not chat_id:
        return "telegram_chat_id_missing"
    if not bool(getattr(app_settings, "has_telegram", False)):
        return "telegram_not_configured"

    min_level = _normalize_level(str(getattr(app_settings, "alert_telegram_min_level", "warning")))
    explicit_event_enabled = (
        event == "started" and bool(getattr(app_settings, "alert_telegram_on_start", False))
    ) or (
        event == "completed" and bool(getattr(app_settings, "alert_telegram_on_success", False))
    )
    if not explicit_event_enabled and ALERT_LEVELS[email.level] < ALERT_LEVELS[min_level]:
        return "below_min_level"
    return None


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


def _resolve_operator_summary(
    *,
    operator_summary: str | None,
    event: str,
    status: str,
    title: str,
    level: str,
    run_id: str,
    counts: dict[str, Any] | None,
    scope: dict[str, Any] | None,
    errors: list[Any] | None,
    details: dict[str, Any] | None,
) -> str:
    if operator_summary is not None and operator_summary.strip():
        return operator_summary
    return build_operator_alert_summary(
        event=event,
        status=status,
        title=title,
        level=level,
        run_id=run_id,
        counts=counts,
        scope=scope,
        errors=errors,
        details=details,
    )


def build_operator_alert_summary(
    *,
    event: str,
    status: str,
    title: str,
    level: str,
    run_id: str,
    counts: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    errors: list[Any] | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    """Build a short deterministic operator-facing alert without raw payloads."""
    title_line = f"{_level_icon(level)} {title}"
    happened = _build_what_happened(event=event, status=status, counts=counts, errors=errors)
    affected_lines, has_people = _build_affected_lines(scope=scope, errors=errors, details=details)
    affected_title = "Кого затронуло" if has_people else "Что затронуто"
    impact = _build_impact(event=event, counts=counts)
    action = _build_action(errors=errors, details=details)

    lines = [
        title_line,
        "",
        "Что случилось:",
        happened,
        "",
        f"{affected_title}:",
    ]
    lines.extend(f"- {line}" for line in affected_lines)
    lines.extend(
        [
            "",
            "На что влияет:",
            impact,
            "",
            "Что проверить:",
            action,
            "",
            f"Run: {run_id}",
        ]
    )
    return _limit_operator_summary("\n".join(lines), run_id=run_id)


def _level_icon(level: str) -> str:
    if level in {"critical", "error"}:
        return "[ERROR]"
    if level == "warning":
        return "[WARN]"
    return "[INFO]"


def _build_what_happened(
    *,
    event: str,
    status: str,
    counts: dict[str, Any] | None,
    errors: list[Any] | None,
) -> str:
    count_summary = _summarize_counts(counts)
    primary_reason = _primary_reason(errors)
    if event == "failed":
        base = "Run завершился с ошибкой."
    elif event == "blocked":
        base = "Run заблокирован и требует проверки."
    elif event == "completed":
        base = "Run завершен."
    elif event == "started":
        base = "Run запущен."
    else:
        base = f"Статус run: {status}."
    if primary_reason:
        base = f"{base} Причина: {primary_reason}."
    if count_summary:
        base = f"{base} Показатели: {count_summary}."
    return _shorten(base, max_chars=260)


def _build_affected_lines(
    *,
    scope: dict[str, Any] | None,
    errors: list[Any] | None,
    details: dict[str, Any] | None,
) -> tuple[list[str], bool]:
    lines: list[str] = []
    has_people = False

    for item in errors or []:
        line, is_person = _summarize_affected_item(item)
        if line:
            lines.append(line)
            has_people = has_people or is_person

    for item in _detail_sequence(details, "blockers"):
        line, is_person = _summarize_affected_item(item)
        if line:
            lines.append(line)
            has_people = has_people or is_person

    if not lines:
        lines.extend(_scope_lines(scope))
    if not lines:
        lines.append("run целиком")

    return (
        _bounded_lines(
            _dedupe(lines),
            max_items=OPERATOR_ALERT_MAX_ITEMS,
            omitted_label="Еще {count} см. в observability/logs.",
        ),
        has_people,
    )


def _summarize_affected_item(item: Any) -> tuple[str | None, bool]:
    if isinstance(item, str):
        return _safe_text_reason(item), False
    if not isinstance(item, dict):
        return _safe_text_reason(str(item)), False

    person = _first_present(
        item,
        "manager",
        "manager_name",
        "employee",
        "employee_name",
        "name",
        "email",
        "manager_email",
    )
    reason = _reason_from_mapping(item)
    if person:
        return f"{_shorten(str(person), max_chars=64)}: {reason}", True
    if reason:
        return reason, False

    primitive_pairs = [
        f"{key}: {_shorten(str(value), max_chars=80)}"
        for key, value in sorted(item.items())
        if _is_safe_scalar(value) and str(key) not in {"details", "scope", "payload"}
    ]
    if primitive_pairs:
        return "; ".join(primitive_pairs[:3]), False
    return "технические детали см. в observability/logs", False


def _reason_from_mapping(item: dict[str, Any]) -> str:
    for key in (
        "reason",
        "reason_code",
        "error_code",
        "error_class",
        "code",
        "status",
        "message",
        "error",
    ):
        value = item.get(key)
        if value:
            return _safe_text_reason(str(value))
    return ""


def _primary_reason(errors: list[Any] | None) -> str:
    for item in errors or []:
        if isinstance(item, dict):
            reason = _reason_from_mapping(item)
        else:
            reason = _safe_text_reason(str(item))
        if reason:
            return reason
    return ""


def _safe_text_reason(value: str) -> str:
    compact = " ".join(value.strip().split())
    if not compact:
        return "неизвестная причина"
    mapped = _human_reason(compact)
    return _shorten(mapped, max_chars=140)


def _human_reason(code_or_message: str) -> str:
    if code_or_message in REASON_LABELS:
        return REASON_LABELS[code_or_message]
    lowered = code_or_message.lower()
    for code, label in REASON_LABELS.items():
        if code.lower() in lowered:
            return label
    if _looks_like_payload(code_or_message):
        return "технические детали см. в observability/logs"
    return code_or_message


def _summarize_counts(counts: dict[str, Any] | None) -> str:
    if not counts:
        return ""
    parts = [
        f"{key}: {value}"
        for key, value in sorted(counts.items())
        if _is_safe_scalar(value)
    ]
    return "; ".join(_bounded_lines(parts, max_items=4, omitted_label="еще {count} показателей"))


def _scope_lines(scope: dict[str, Any] | None) -> list[str]:
    if not scope:
        return []
    lines = [
        f"{key}: {_shorten(str(value), max_chars=80)}"
        for key, value in sorted(scope.items())
        if _is_safe_scalar(value)
    ]
    return _bounded_lines(lines, max_items=3, omitted_label="Еще {count} см. в observability/logs.")


def _build_impact(*, event: str, counts: dict[str, Any] | None) -> str:
    counts = counts or {}
    if any(
        _count_value(counts, key) > 0
        for key in ("failed_reports", "partial_reports", "quota_blocked")
    ):
        return "Часть отчетов или обработок может быть неполной либо не доставленной вовремя."
    if event == "failed":
        return "Зависимые отчеты, доставки или SLA могут не выполниться штатно."
    if event == "blocked":
        return "Автоматический процесс остановлен до устранения причины."
    if event == "completed":
        return "Оператору доступно подтверждение завершения production run."
    return "Оператору доступно состояние production run."


def _build_action(*, errors: list[Any] | None, details: dict[str, Any] | None) -> str:
    reason_text = " ".join(
        filter(
            None,
            [
                _primary_reason(errors),
                *(
                    _safe_text_reason(str(item))
                    for item in _detail_sequence(details, "reason_codes")
                ),
            ],
        )
    ).lower()
    checks = ["observability/logs"]
    if "email" in reason_text:
        checks.insert(0, "email delivery result")
        checks.insert(0, "draft delivery")
    if "sla" in reason_text:
        checks.insert(0, "scheduled reporting batch")
    if "лимит" in reason_text or "budget" in reason_text or "quota" in reason_text:
        checks.insert(0, "provider budget/quota")
    if "таймаут" in reason_text or "timeout" in reason_text:
        checks.insert(0, "service timeout/retry")
    if len(checks) == 1:
        checks.insert(0, "run status")
    return ", ".join(_dedupe(checks)) + "."


def _detail_sequence(details: dict[str, Any] | None, key: str) -> list[Any]:
    if not isinstance(details, dict):
        return []
    value = details.get(key)
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value:
        return [value]
    return []


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _bounded_lines(lines: list[str], *, max_items: int, omitted_label: str) -> list[str]:
    if len(lines) <= max_items:
        return lines
    omitted = len(lines) - max_items
    return [*lines[:max_items], omitted_label.format(count=omitted)]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _shorten(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def _count_value(counts: dict[str, Any], key: str) -> int:
    value = counts.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return int(value)
    return 0


def _is_safe_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _looks_like_payload(value: str) -> bool:
    stripped = value.strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )


def _limit_operator_summary(text: str, *, run_id: str) -> str:
    if len(text) <= OPERATOR_ALERT_MAX_CHARS:
        return text
    suffix = f"\n\nЕще детали см. в observability/logs.\nRun: {run_id}"
    return text[: OPERATOR_ALERT_MAX_CHARS - len(suffix)].rstrip() + suffix


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


def _format_telegram_alert(email: RunAlertEmail) -> str:
    return email.operator_summary


def _chunk_text(text: str, *, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > max_len and current:
            chunks.append(current)
            current = line
        else:
            current += line
        while len(current) > max_len:
            chunks.append(current[:max_len])
            current = current[max_len:]
    if current:
        chunks.append(current)
    return chunks
