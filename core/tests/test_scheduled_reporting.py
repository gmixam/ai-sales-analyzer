from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

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

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.calls.scheduled_reporting import ScheduledReviewableReportingService  # noqa: E402
from app.core_shared.exceptions import ASAError  # noqa: E402


def _make_service() -> ScheduledReviewableReportingService:
    service = object.__new__(ScheduledReviewableReportingService)
    service.db = SimpleNamespace(add=lambda *_args, **_kwargs: None, flush=lambda: None)
    return service


def _manager_daily_schedule(
    *,
    planned_for: datetime = datetime(2026, 6, 15, 2, 0, tzinfo=UTC),
    business_email_enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        department_id=uuid4(),
        preset="manager_daily",
        mode="report_from_ready_data_only",
        report_period_rule="previous_day",
        enabled=True,
        business_email_enabled=business_email_enabled,
        manager_ids=[str(uuid4())],
        timezone="Asia/Almaty",
        start_date=date(2026, 6, 1),
        start_time="08:00",
        recurrence_type="daily",
        next_run_at=planned_for,
        last_planned_at=None,
    )


def _ready_manager_daily_report(*, report_date: str = "2026-06-12") -> dict:
    return {
        "group_key": f"manager_daily:manager-1:{report_date}",
        "payload": {
            "narrative_day_conclusion": {"text": "Summary"},
            "main_focus_for_tomorrow": {"text": "Focus"},
            "key_problem_of_day": {"description": "Problem"},
            "editorial_recommendations": {"text": "Recommendations"},
            "focus_of_week": {"text": "Note"},
            "meta": {
                "preset": "manager_daily",
                "report_type": "manager_daily",
                "manager_id": "manager-1",
                "report_date": report_date,
            },
        },
        "preview": {"subject": "subject"},
        "artifact": {"filename": "report.pdf"},
        "delivery": {
            "transport": {
                "telegram_test_delivery": {"enabled": False, "status": "skipped"},
                "email_delivery": {"enabled": False, "status": "skipped"},
            }
        },
        "errors": [],
    }


def _interaction_for_day(*, manager_id: str, report_date: str) -> SimpleNamespace:
    return SimpleNamespace(
        manager_id=manager_id,
        metadata_={"call_started_at": f"{report_date}T10:00:00+05:00"},
    )


class ScheduledReportingSplitComplete04Tests(unittest.TestCase):
    def test_analysis_scan_selects_oldest_unreported_call_day_inside_lookback(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule()
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 16, 2, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-08": [],
            "2026-06-09": [],
            "2026-06-10": [],
            "2026-06-11": [],
            "2026-06-12": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-12")],
            "2026-06-13": [],
            "2026-06-14": [],
        }
        service._has_manager_day_duplicate = lambda **_kwargs: False

        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                return {
                    "reports": [_ready_manager_daily_report(report_date="2026-06-12")],
                    "observability": {
                        "scheduled_timezone": "Asia/Almaty",
                        "lookback_days": 7,
                        "candidate_dates": ["2026-06-12"],
                        "selected_report_date": "2026-06-12",
                        "skipped_empty_dates": ["2026-06-13", "2026-06-14"],
                        "skipped_already_reported_dates": [],
                        "skipped_not_ready_dates": [],
                        "selection_reason": "oldest_unreported_ready_call_day",
                    },
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 15, 2, 30, tzinfo=UTC))

        filters = run_calls[0]["filters"]
        self.assertEqual((filters.date_from, filters.date_to), ("2026-06-12", "2026-06-12"))
        batch = added[0]
        self.assertEqual(batch.observability["selected_report_date"], "2026-06-12")
        self.assertIn("2026-06-13", batch.observability["skipped_empty_dates"])
        self.assertIn("2026-06-14", batch.observability["skipped_empty_dates"])

    def test_empty_weekend_or_holiday_days_create_no_manager_facing_draft_or_report(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule()
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 16, 2, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **kwargs: {
            item: [] for item in kwargs["candidate_dates"]
        }
        service._has_manager_day_duplicate = lambda **_kwargs: False

        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                return {
                    "reports": [],
                    "observability": {
                        "scheduled_timezone": "Asia/Almaty",
                        "lookback_days": 7,
                        "candidate_dates": [],
                        "selected_report_date": None,
                        "skipped_empty_dates": ["2026-06-14"],
                        "skipped_already_reported_dates": [],
                        "skipped_not_ready_dates": [],
                        "selection_reason": "no_call_or_ready_artifact_days_in_lookback",
                    },
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 15, 2, 30, tzinfo=UTC))

        self.assertEqual(run_calls, [])
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].observability["selected_report_date"], None)

    def test_duplicate_manager_day_report_key_is_skipped_before_orchestrator_run(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule()
        service.db = SimpleNamespace(
            add=lambda item: added.append(item),
            flush=lambda: None,
            existing_report_keys={
                (
                    "manager_daily",
                    schedule.manager_ids[0],
                    "2026-06-12",
                    "manager_daily",
                )
            },
        )
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 16, 2, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-08": [],
            "2026-06-09": [],
            "2026-06-10": [],
            "2026-06-11": [],
            "2026-06-12": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-12")],
            "2026-06-13": [],
            "2026-06-14": [],
        }
        service._has_manager_day_duplicate = (
            lambda **kwargs: kwargs["report_date"] == "2026-06-12"
        )
        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                return {
                    "reports": [_ready_manager_daily_report(report_date="2026-06-12")],
                    "observability": {},
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 15, 2, 30, tzinfo=UTC))

        self.assertEqual(run_calls, [])
        self.assertFalse(any(item.__class__.__name__ == "ScheduledReportDraft" for item in added))
        self.assertEqual(schedule.next_run_at, datetime(2026, 6, 16, 2, 0, tzinfo=UTC))

    def test_scan_creates_review_draft_without_business_email_delivery(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(business_email_enabled=True)
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 16, 2, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-08": [],
            "2026-06-09": [],
            "2026-06-10": [],
            "2026-06-11": [],
            "2026-06-12": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-12")],
            "2026-06-13": [],
            "2026-06-14": [],
        }
        service._has_manager_day_duplicate = lambda **_kwargs: False

        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace(
                    deliver_operator_report=lambda **_kwargs: (_ for _ in ()).throw(
                        AssertionError("scan/draft must not call delivery")
                    )
                )

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                return {
                    "reports": [_ready_manager_daily_report(report_date="2026-06-12")],
                    "observability": {},
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 15, 2, 30, tzinfo=UTC))

        batch = added[0]
        draft = added[1]
        self.assertTrue(batch.business_email_enabled)
        self.assertEqual(batch.status, "review_required")
        self.assertEqual(draft.status, "review_required")
        self.assertEqual(run_calls[0]["send_email"], False)
        self.assertEqual(draft.delivery["transport"]["email_delivery"]["status"], "skipped")

    def test_approve_with_business_email_disabled_keeps_manager_email_gate_closed(self) -> None:
        service = _make_service()
        batch = SimpleNamespace(
            id=uuid4(),
            status="review_required",
            department_id=uuid4(),
            business_email_enabled=False,
            approved_at=None,
            approved_by=None,
            delivered_at=None,
            failed_at=None,
            errors=[],
        )
        draft = SimpleNamespace(
            id=uuid4(),
            preset="manager_daily",
            status="review_required",
            generated_payload={
                "narrative_day_conclusion": {"text": "Summary"},
                "main_focus_for_tomorrow": {"text": "Focus"},
                "key_problem_of_day": {"description": "Problem"},
                "editorial_recommendations": {"text": "Recommendations"},
                "focus_of_week": {"text": "Note"},
            },
            edited_blocks={},
            delivery={"transport": {"resolved_email": {"primary_email": "manager@example.com"}}},
            preview={},
            artifact={},
            errors=[],
        )
        service._get_batch = lambda _batch_id: batch
        service._load_batch_drafts = lambda _batch_id: [draft]
        service._serialize_batch = lambda item: {"id": str(item.id), "status": item.status, "errors": item.errors}
        delivery_calls = []

        class FakeDelivery:
            def deliver_operator_report(self, **kwargs):
                delivery_calls.append(kwargs)
                return {
                    "transport": {
                        "telegram_test_delivery": {"status": "delivered"},
                        "email_delivery": {"status": "skipped"},
                    }
                }

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = FakeDelivery()

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            with patch(
                "app.agents.calls.scheduled_reporting.render_report_email",
                return_value={
                    "subject": "Subject",
                    "text": "Text",
                    "html": "<p>Html</p>",
                    "pdf_bytes": b"pdf",
                    "artifact": {"filename": "report.pdf"},
                    "template": {"version": "v1"},
                },
            ):
                result = service.approve_batch(batch_id=str(batch.id), editor="tester")

        self.assertEqual(result["status"], "delivered")
        self.assertEqual(delivery_calls[0]["primary_email"], "manager@example.com")
        self.assertFalse(delivery_calls[0]["send_business_email"])

    def test_approve_rejects_batches_before_review_gate(self) -> None:
        service = _make_service()
        batch = SimpleNamespace(id=uuid4(), status="running")
        service._get_batch = lambda _batch_id: batch

        with self.assertRaises(ASAError):
            service.approve_batch(batch_id=str(batch.id), editor="tester")


if __name__ == "__main__":
    unittest.main()
