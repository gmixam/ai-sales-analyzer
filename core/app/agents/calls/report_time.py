"""Shared report-facing time labels."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

REPORT_TIMEZONE = timezone(timedelta(hours=5), name="UTC+5")

_MONTH_FULL_RU_REP = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def as_report_timezone(value: datetime | None) -> datetime | None:
    """Return a datetime converted to the report display timezone."""
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(REPORT_TIMEZONE)


def parse_report_datetime(value: Any) -> datetime | None:
    """Parse an ISO-like datetime and normalize it to the report timezone."""
    if isinstance(value, datetime):
        return as_report_timezone(value)
    if isinstance(value, date):
        return None
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return as_report_timezone(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def report_date_label_iso(value: datetime | None) -> str | None:
    dt = as_report_timezone(value)
    return dt.date().isoformat() if dt is not None else None


def report_time_label(value: Any) -> str | None:
    dt = parse_report_datetime(value)
    if dt is not None:
        return dt.strftime("%H:%M")
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) >= 16 and raw[10] in {"T", " "}:
        return raw[11:16]
    return raw


def report_date_time_labels(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat(), None
    dt = parse_report_datetime(value)
    if dt is not None:
        return dt.date().isoformat(), dt.strftime("%H:%M")
    raw = str(value or "").strip()
    if not raw:
        return None, None
    return raw[:10] or None, raw[11:16] if len(raw) >= 16 else None


def report_human_datetime_ru(value: datetime | None) -> str | None:
    dt = as_report_timezone(value)
    if dt is None:
        return None
    month = dt.month
    month_label = _MONTH_FULL_RU_REP[month - 1] if 1 <= month <= 12 else str(month)
    return f"{dt.day} {month_label} {dt.year}, {dt.strftime('%H:%M')}"
