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


class _OnTimeSlaDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 6, 16, 3, 20, tzinfo=UTC)
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)


def _manager_daily_schedule(
    *,
    planned_for: datetime = datetime(2026, 6, 15, 2, 0, tzinfo=UTC),
    business_email_enabled: bool = True,
    review_required: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        department_id=uuid4(),
        preset="manager_daily",
        mode="report_from_ready_data_only",
        report_period_rule="previous_day",
        enabled=True,
        business_email_enabled=business_email_enabled,
        review_required=review_required,
        manager_ids=[str(uuid4())],
        timezone="Asia/Almaty",
        start_date=date(2026, 6, 1),
        start_time="08:00",
        recurrence_type="daily",
        next_run_at=planned_for,
        last_planned_at=None,
    )


def _ready_manager_daily_report(*, report_date: str = "2026-06-15") -> dict:
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


def _delivered_manager_daily_report(*, report_date: str = "2026-06-15") -> dict:
    report = _ready_manager_daily_report(report_date=report_date)
    report["delivery"] = {
        "transport": {
            "telegram_test_delivery": {"enabled": False, "status": "skipped"},
            "email_delivery": {
                "enabled": True,
                "status": "delivered",
                "primary_email": "manager@example.com",
            },
        },
        "sla": {
            "sla_deadline_at": f"{report_date}T10:00:00+05:00",
            "delivered_at": f"{report_date}T09:20:00+05:00",
            "sla_status": "on_time",
            "sla_missed": False,
            "manager_email_status": "delivered",
            "rop_email_status": "delivered",
        },
        "rop_daily_package": {"status": "delivered", "target": "edo.rop@dogovor24.kz"},
    }
    return report


def _interaction_for_day(*, manager_id: str, report_date: str) -> SimpleNamespace:
    return SimpleNamespace(
        manager_id=manager_id,
        metadata_={"call_started_at": f"{report_date}T10:00:00+05:00"},
    )


class _FakeQuery:
    def __init__(self, rows: list[SimpleNamespace]):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


def _manager_day_batch(
    *,
    schedule_id,
    department_id,
    manager_id: str,
    report_date: str,
    status: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        schedule_id=schedule_id,
        department_id=department_id,
        preset="manager_daily",
        status=status,
        observability={
            "scheduled_candidate_selection": {
                "manager_id": manager_id,
                "selected_report_date": report_date,
            }
        },
        period={"date_from": report_date, "date_to": report_date},
        filters={"manager_ids": [manager_id], "manager_extensions": []},
    )


class ScheduledReportingSplitComplete04Tests(unittest.TestCase):
    def test_previous_day_manager_daily_selects_only_computed_previous_day(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC))
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 16, 2, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-09": [],
            "2026-06-10": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-10")],
            "2026-06-15": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-15")],
        }
        service._has_manager_day_duplicate = lambda **_kwargs: False

        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                return {
                    "reports": [_ready_manager_daily_report(report_date="2026-06-15")],
                    "observability": {
                        "scheduled_timezone": "Asia/Almaty",
                        "lookback_days": 1,
                        "candidate_dates": ["2026-06-15"],
                        "selected_report_date": "2026-06-15",
                        "skipped_empty_dates": [],
                        "skipped_already_reported_dates": [],
                        "skipped_not_ready_dates": [],
                        "selection_reason": "selected_previous_day_with_calls",
                    },
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC))

        filters = run_calls[0]["filters"]
        self.assertEqual((filters.date_from, filters.date_to), ("2026-06-15", "2026-06-15"))
        batch = added[0]
        self.assertEqual(batch.period, {"date_from": "2026-06-15", "date_to": "2026-06-15"})
        self.assertEqual(batch.observability["candidate_dates"], ["2026-06-15"])
        self.assertEqual(batch.observability["selected_report_date"], "2026-06-15")
        self.assertEqual(batch.observability["lookback_days"], 1)
        self.assertEqual(batch.observability["selection_reason"], "selected_previous_day_with_calls")

    def test_running_manager_day_batch_blocks_duplicate_batch_creation(self) -> None:
        service = _make_service()
        schedule_id = uuid4()
        department_id = uuid4()
        manager_id = str(uuid4())
        batch = _manager_day_batch(
            schedule_id=schedule_id,
            department_id=department_id,
            manager_id=manager_id,
            report_date="2026-06-15",
            status="running",
        )
        service.db = SimpleNamespace(query=lambda _model: _FakeQuery([batch]))
        service._load_batch_drafts = lambda _batch_id: []

        self.assertTrue(
            service._has_manager_day_duplicate(
                schedule_id=schedule_id,
                department_id=department_id,
                preset="manager_daily",
                manager_id=manager_id,
                report_date="2026-06-15",
            )
        )

    def test_review_required_same_manager_day_blocks_duplicate_batch_creation(self) -> None:
        service = _make_service()
        schedule_id = uuid4()
        department_id = uuid4()
        manager_id = str(uuid4())
        batch = _manager_day_batch(
            schedule_id=schedule_id,
            department_id=department_id,
            manager_id=manager_id,
            report_date="2026-06-15",
            status="review_required",
        )
        service.db = SimpleNamespace(query=lambda _model: _FakeQuery([batch]))
        service._load_batch_drafts = lambda _batch_id: []

        self.assertTrue(
            service._has_manager_day_duplicate(
                schedule_id=schedule_id,
                department_id=department_id,
                preset="manager_daily",
                manager_id=manager_id,
                report_date="2026-06-15",
            )
        )

    def test_open_and_reported_manager_day_batch_diagnostics_include_blocker(self) -> None:
        service = _make_service()
        schedule_id = uuid4()
        department_id = uuid4()
        manager_id = str(uuid4())
        for status, reason in (
            ("running", "matching_open_batch"),
            ("delivered", "matching_reported_batch"),
        ):
            with self.subTest(status=status):
                batch = _manager_day_batch(
                    schedule_id=schedule_id,
                    department_id=department_id,
                    manager_id=manager_id,
                    report_date="2026-06-15",
                    status=status,
                )
                service.db = SimpleNamespace(query=lambda _model: _FakeQuery([batch]))
                service._load_batch_drafts = lambda _batch_id: []

                diagnostics = service._manager_day_duplicate_diagnostics(
                    schedule_id=schedule_id,
                    department_id=department_id,
                    preset="manager_daily",
                    manager_id=manager_id,
                    report_date="2026-06-15",
                )

                self.assertTrue(diagnostics["has_duplicate"])
                self.assertEqual(diagnostics["blocked_by_batch_id"], str(batch.id))
                self.assertEqual(diagnostics["blocked_by_batch_status"], status)
                self.assertIsNone(diagnostics["blocked_by_draft_id"])
                self.assertEqual(diagnostics["blocked_by_reason"], reason)
                self.assertEqual(diagnostics["manager_id"], manager_id)
                self.assertEqual(diagnostics["report_date"], "2026-06-15")
                self.assertEqual(diagnostics["schedule_id"], str(schedule_id))
                self.assertEqual(diagnostics["match_source"], "batch_key")

    def test_review_required_previous_day_batch_does_not_block_next_manager_day(self) -> None:
        service = _make_service()
        schedule_id = uuid4()
        department_id = uuid4()
        manager_id = str(uuid4())
        batch = _manager_day_batch(
            schedule_id=schedule_id,
            department_id=department_id,
            manager_id=manager_id,
            report_date="2026-06-15",
            status="review_required",
        )
        service.db = SimpleNamespace(query=lambda _model: _FakeQuery([batch]))
        service._load_batch_drafts = lambda _batch_id: []

        self.assertFalse(
            service._has_manager_day_duplicate(
                schedule_id=schedule_id,
                department_id=department_id,
                preset="manager_daily",
                manager_id=manager_id,
                report_date="2026-06-16",
            )
        )

    def test_review_required_batch_for_one_manager_does_not_block_another_manager(self) -> None:
        service = _make_service()
        schedule_id = uuid4()
        department_id = uuid4()
        blocked_manager_id = str(uuid4())
        candidate_manager_id = str(uuid4())
        batch = _manager_day_batch(
            schedule_id=schedule_id,
            department_id=department_id,
            manager_id=blocked_manager_id,
            report_date="2026-06-15",
            status="review_required",
        )
        service.db = SimpleNamespace(query=lambda _model: _FakeQuery([batch]))
        service._load_batch_drafts = lambda _batch_id: []

        self.assertFalse(
            service._has_manager_day_duplicate(
                schedule_id=schedule_id,
                department_id=department_id,
                preset="manager_daily",
                manager_id=candidate_manager_id,
                report_date="2026-06-15",
            )
        )

    def test_failed_manager_day_batch_without_draft_does_not_block_retry(self) -> None:
        service = _make_service()
        schedule_id = uuid4()
        department_id = uuid4()
        manager_id = str(uuid4())
        batch = _manager_day_batch(
            schedule_id=schedule_id,
            department_id=department_id,
            manager_id=manager_id,
            report_date="2026-06-15",
            status="failed",
        )
        service.db = SimpleNamespace(query=lambda _model: _FakeQuery([batch]))
        service._load_batch_drafts = lambda _batch_id: []

        diagnostics = service._manager_day_duplicate_diagnostics(
            schedule_id=schedule_id,
            department_id=department_id,
            preset="manager_daily",
            manager_id=manager_id,
            report_date="2026-06-15",
        )

        self.assertFalse(
            service._has_manager_day_duplicate(
                schedule_id=schedule_id,
                department_id=department_id,
                preset="manager_daily",
                manager_id=manager_id,
                report_date="2026-06-15",
            )
        )
        self.assertFalse(diagnostics["has_duplicate"])
        self.assertIsNone(diagnostics["blocked_by_batch_id"])
        self.assertIsNone(diagnostics["blocked_by_reason"])

    def test_delivered_manager_day_draft_blocks_late_duplicate_delivery(self) -> None:
        service = _make_service()
        schedule_id = uuid4()
        department_id = uuid4()
        manager_id = str(uuid4())
        batch = _manager_day_batch(
            schedule_id=schedule_id,
            department_id=department_id,
            manager_id=manager_id,
            report_date="2026-06-15",
            status="failed",
        )
        draft = SimpleNamespace(
            id=uuid4(),
            status="delivered",
            group_key=f"manager_daily:{manager_id}:2026-06-15",
            generated_payload={},
        )
        service.db = SimpleNamespace(query=lambda _model: _FakeQuery([batch]))
        service._load_batch_drafts = lambda _batch_id: [draft]

        self.assertTrue(
            service._has_manager_day_duplicate(
                schedule_id=schedule_id,
                department_id=department_id,
                preset="manager_daily",
                manager_id=manager_id,
                report_date="2026-06-15",
            )
        )

    def test_reported_manager_day_draft_diagnostics_include_draft_blocker(self) -> None:
        service = _make_service()
        schedule_id = uuid4()
        department_id = uuid4()
        manager_id = str(uuid4())
        batch = _manager_day_batch(
            schedule_id=schedule_id,
            department_id=department_id,
            manager_id=manager_id,
            report_date="2026-06-15",
            status="failed",
        )
        draft = SimpleNamespace(
            id=uuid4(),
            status="delivered",
            group_key=f"manager_daily:{manager_id}:2026-06-15",
            generated_payload={},
        )
        service.db = SimpleNamespace(query=lambda _model: _FakeQuery([batch]))
        service._load_batch_drafts = lambda _batch_id: [draft]

        diagnostics = service._manager_day_duplicate_diagnostics(
            schedule_id=schedule_id,
            department_id=department_id,
            preset="manager_daily",
            manager_id=manager_id,
            report_date="2026-06-15",
        )

        self.assertTrue(diagnostics["has_duplicate"])
        self.assertEqual(diagnostics["blocked_by_batch_id"], str(batch.id))
        self.assertEqual(diagnostics["blocked_by_batch_status"], "failed")
        self.assertEqual(diagnostics["blocked_by_draft_id"], str(draft.id))
        self.assertEqual(diagnostics["blocked_by_draft_status"], "delivered")
        self.assertEqual(diagnostics["blocked_by_reason"], "matching_reported_draft")
        self.assertEqual(diagnostics["match_source"], "draft_group_key")

    def test_selection_dict_includes_already_reported_skip_details(self) -> None:
        service = _make_service()
        schedule = _manager_daily_schedule(planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC))
        manager_id = schedule.manager_ids[0]
        batch = _manager_day_batch(
            schedule_id=schedule.id,
            department_id=schedule.department_id,
            manager_id=manager_id,
            report_date="2026-06-15",
            status="running",
        )
        service.db = SimpleNamespace(query=lambda _model: _FakeQuery([batch]))
        service._load_batch_drafts = lambda _batch_id: []
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [_interaction_for_day(manager_id=manager_id, report_date="2026-06-15")],
        }

        selection = service._select_manager_day_candidate(
            schedule=schedule,
            manager_id=manager_id,
            candidate_dates=["2026-06-15"],
            lookback_days=1,
            scan_started_at="2026-06-16T03:00:00+00:00",
        )
        selection_payload = selection.to_dict()
        observability = service._with_candidate_selection_observability(
            observability={},
            selection=selection,
        )

        self.assertIsNone(selection.selected_report_date)
        self.assertEqual(selection_payload["skipped_already_reported_dates"], ["2026-06-15"])
        self.assertEqual(len(selection_payload["skipped_already_reported_details"]), 1)
        detail = selection_payload["skipped_already_reported_details"][0]
        self.assertEqual(detail["report_date"], "2026-06-15")
        self.assertEqual(detail["manager_id"], manager_id)
        self.assertEqual(detail["blocked_by_batch_id"], str(batch.id))
        self.assertEqual(detail["blocked_by_batch_status"], "running")
        self.assertEqual(detail["blocked_by_reason"], "matching_open_batch")
        self.assertEqual(detail["match_source"], "batch_key")
        self.assertEqual(
            observability["scheduled_candidate_selection"]["skipped_already_reported_details"],
            selection_payload["skipped_already_reported_details"],
        )

    def test_manager_daily_open_batch_from_previous_day_does_not_skip_candidate_selection(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC))
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: True
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 17, 3, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-15")],
        }
        service._has_manager_day_duplicate = lambda **_kwargs: False
        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                return {
                    "reports": [_ready_manager_daily_report(report_date="2026-06-15")],
                    "observability": {},
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC))

        self.assertEqual(len(run_calls), 1)
        self.assertTrue(any(item.__class__.__name__ == "ScheduledReportBatch" for item in added))
        self.assertEqual(schedule.next_run_at, datetime(2026, 6, 17, 3, 0, tzinfo=UTC))

    def test_non_manager_daily_existing_open_batch_still_skips_batch_creation(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC))
        schedule.preset = "rop_weekly"
        schedule.manager_ids = []
        schedule.recurrence_type = "weekly"
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: True
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 17, 3, 0, tzinfo=UTC)
        service._get_batch_for_occurrence = lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("open batch guard should skip non-manager_daily occurrence creation")
        )

        service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC))

        self.assertEqual(added, [])
        self.assertEqual(schedule.next_run_at, datetime(2026, 6, 17, 3, 0, tzinfo=UTC))

    def test_empty_weekend_or_holiday_days_create_no_manager_facing_draft_or_report(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC))
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
                        "lookback_days": 1,
                        "candidate_dates": [],
                        "selected_report_date": None,
                        "skipped_empty_dates": ["2026-06-15"],
                        "skipped_already_reported_dates": [],
                        "skipped_not_ready_dates": [],
                        "selection_reason": "no_candidate_empty_previous_day",
                    },
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC))

        self.assertEqual(run_calls, [])
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].observability["selected_report_date"], None)
        self.assertEqual(added[0].observability["candidate_dates"], ["2026-06-15"])
        self.assertEqual(added[0].errors, ["no_candidate_empty_previous_day"])

    def test_duplicate_manager_day_report_key_is_skipped_before_orchestrator_run(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC))
        service.db = SimpleNamespace(
            add=lambda item: added.append(item),
            flush=lambda: None,
            existing_report_keys={
                (
                    "manager_daily",
                    schedule.manager_ids[0],
                    "2026-06-15",
                    "manager_daily",
                )
            },
        )
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 16, 2, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-15")],
        }
        service._has_manager_day_duplicate = (
            lambda **kwargs: kwargs["report_date"] == "2026-06-15"
        )
        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                return {
                    "reports": [_ready_manager_daily_report(report_date="2026-06-15")],
                    "observability": {},
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC))

        self.assertEqual(run_calls, [])
        self.assertFalse(any(item.__class__.__name__ == "ScheduledReportDraft" for item in added))
        self.assertEqual(schedule.next_run_at, datetime(2026, 6, 16, 2, 0, tzinfo=UTC))

    def test_scan_creates_review_draft_without_business_email_delivery(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(
            planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC),
            business_email_enabled=True,
            review_required=True,
        )
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 16, 2, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-15")],
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
                    "reports": [_ready_manager_daily_report(report_date="2026-06-15")],
                    "observability": {},
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC))

        batch = added[0]
        draft = added[1]
        self.assertTrue(batch.business_email_enabled)
        self.assertEqual(batch.status, "review_required")
        self.assertEqual(draft.status, "review_required")
        self.assertEqual(run_calls[0]["send_email"], False)
        self.assertEqual(draft.delivery["transport"]["email_delivery"]["status"], "skipped")

    def test_production_schedule_auto_delivers_ready_manager_daily_report(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(
            planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC),
            business_email_enabled=True,
            review_required=False,
        )
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 17, 23, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-15")],
        }
        service._has_manager_day_duplicate = lambda **_kwargs: False

        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace(
                    deliver_operator_report=lambda **_kwargs: (_ for _ in ()).throw(
                        AssertionError("production schedule should delegate delivery through run_report")
                    )
                )

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                return {
                    "reports": [_delivered_manager_daily_report(report_date="2026-06-15")],
                    "rop_daily_delivery": {"status": "delivered", "target": "edo.rop@dogovor24.kz"},
                    "observability": {
                        "sla_deadline_at": "2026-06-16T10:00:00+05:00",
                        "delivered_at": "2026-06-16T09:20:00+05:00",
                        "sla_status": "on_time",
                        "sla_missed": False,
                        "manager_email_status": "delivered",
                        "rop_email_status": "delivered",
                    },
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            with patch("app.agents.calls.scheduled_reporting.datetime", _OnTimeSlaDateTime):
                service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC))

        batch = added[0]
        draft = added[1]
        self.assertEqual(run_calls[0]["send_email"], True)
        self.assertFalse(batch.review_required)
        self.assertEqual(batch.status, "delivered")
        self.assertEqual(draft.status, "delivered")
        self.assertEqual(draft.delivery["transport"]["email_delivery"]["status"], "delivered")
        self.assertEqual(batch.observability["sla_status"], "on_time")
        self.assertFalse(batch.observability["sla_missed"])
        self.assertEqual(batch.observability["rop_email_status"], "delivered")

    def test_production_schedule_blocks_missing_recipient_without_raw_report_delivery(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(
            planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC),
            business_email_enabled=True,
            review_required=False,
        )
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 17, 23, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [_interaction_for_day(manager_id=schedule.manager_ids[0], report_date="2026-06-15")],
        }
        service._has_manager_day_duplicate = lambda **_kwargs: False

        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                report = _ready_manager_daily_report(report_date="2026-06-15")
                report["delivery"] = {
                    "transport": {
                        "email_delivery": {
                            "enabled": True,
                            "status": "blocked",
                            "error": "missing business recipient",
                        }
                    }
                }
                report["errors"] = ["missing business recipient"]
                return {
                    "reports": [report],
                    "rop_daily_delivery": {"status": "blocked", "target": "edo.rop@dogovor24.kz"},
                    "observability": {
                        "sla_status": "blocked",
                        "sla_missed": True,
                        "sla_missed_reason": "missing_recipient",
                        "manager_email_status": "blocked",
                        "rop_email_status": "blocked",
                    },
                    "diagnostics": {},
                    "errors": ["missing business recipient"],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            with patch("app.agents.calls.scheduled_reporting.datetime", _OnTimeSlaDateTime):
                service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC))

        batch = added[0]
        draft = added[1]
        self.assertEqual(run_calls[0]["send_email"], True)
        self.assertNotEqual(draft.delivery["transport"]["email_delivery"]["status"], "delivered")
        self.assertEqual(draft.delivery["transport"]["email_delivery"]["status"], "blocked")
        self.assertEqual(batch.observability["sla_status"], "blocked")
        self.assertEqual(batch.observability["sla_missed_reason"], "missing_recipient")
        self.assertEqual(batch.observability["manager_email_status"], "blocked")

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
