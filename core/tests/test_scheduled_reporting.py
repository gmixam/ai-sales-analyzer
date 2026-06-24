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

from app.agents.calls.reporting import CallsManualReportingOrchestrator, resolve_report_preset  # noqa: E402
from app.agents.calls.scheduled_reporting import ScheduledReviewableReportingService  # noqa: E402
from app.core_shared.config.settings import settings  # noqa: E402
from app.core_shared.db.models import Manager  # noqa: E402
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

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeManagerDb:
    def __init__(self, managers: list[SimpleNamespace]):
        self._managers = managers

    def query(self, model):
        if model is Manager:
            return _FakeQuery(self._managers)
        return _FakeQuery([])


class _FakeLockResult:
    def __init__(self, acquired: bool):
        self._acquired = acquired

    def scalar(self):
        return self._acquired


class _FakeGuardDb:
    def __init__(self, rows: list[SimpleNamespace] | None = None, *, lock_acquired: bool = True):
        self._rows = list(rows or [])
        self.lock_acquired = lock_acquired
        self.added: list[object] = []
        self.lock_params: list[dict] = []

    def query(self, _model):
        return _FakeQuery(self._rows)

    def add(self, item):
        self.added.append(item)

    def flush(self):
        return None

    def execute(self, _statement, params):
        self.lock_params.append(dict(params))
        return _FakeLockResult(self.lock_acquired)


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
    def test_scheduled_manager_daily_rop_digest_sends_partial_status_summary(self) -> None:
        service = _make_service()
        department_id = uuid4()
        manager_1 = uuid4()
        manager_2 = uuid4()
        service.db = _FakeManagerDb(
            [
                SimpleNamespace(id=manager_1, department_id=department_id, name="Толеген"),
                SimpleNamespace(id=manager_2, department_id=department_id, name="Тимур"),
            ]
        )
        schedule = _manager_daily_schedule(
            planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC),
            business_email_enabled=True,
            review_required=False,
        )
        schedule.department_id = department_id
        schedule.manager_ids = [str(manager_1), str(manager_2)]
        sent_messages: list[dict] = []

        class FakeCallsDelivery:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def send_email_message(self, **kwargs):
                sent_messages.append(kwargs)
                return {"status": "sent", "target": kwargs["email_to"]}

        run_summary = {
            "report_date": "2026-06-15",
            "selection_summary": [
                {
                    "manager_id": str(manager_1),
                    "manager_name": "Толеген",
                    "report_date": "2026-06-15",
                    "selection_status": "selected",
                    "reason": "selected",
                },
                {
                    "manager_id": str(manager_2),
                    "manager_name": "Тимур",
                    "report_date": "2026-06-15",
                    "selection_status": "skipped",
                    "reason": "analysis_not_ready",
                },
            ],
        }
        report_items = [
            {
                "manager_id": str(manager_1),
                "manager_name": "Толеген",
                "report_date": "2026-06-15",
                "email_status": "delivered",
                "attachment": {"filename": "tolegen.pdf", "content": b"pdf"},
            }
        ]

        with (
            patch.object(settings, "manager_daily_rop_email_enabled", True),
            patch.object(settings, "manager_daily_rop_email_to", "edo.rop@dogovor24.kz"),
            patch.object(settings, "smtp_user", "smtp-user"),
            patch("app.agents.calls.scheduled_reporting.CallsDelivery", FakeCallsDelivery),
        ):
            summary = service._send_scheduled_manager_daily_rop_digest(
                schedule=schedule,
                planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC),
                run_summary=run_summary,
                batches=[],
                report_items=report_items,
            )

        self.assertEqual(summary["status"], "sent")
        self.assertEqual(summary["attachments_count"], 1)
        self.assertEqual(len(summary["rows"]), 2)
        self.assertEqual([row["status"] for row in summary["rows"]], ["delivered", "not_ready"])
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0]["email_to"], "edo.rop@dogovor24.kz")
        self.assertEqual(sent_messages[0]["attachments"][0]["filename"], "tolegen.pdf")
        self.assertIn("Толеген: delivered", sent_messages[0]["text"])
        self.assertIn("Тимур: not_ready", sent_messages[0]["text"])

    def test_manager_daily_recipient_resolver_uses_manager_email_from_db(self) -> None:
        department_id = uuid4()
        manager_id = uuid4()
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        orchestrator.department_id = department_id
        orchestrator.db = _FakeManagerDb(
            [
                SimpleNamespace(
                    id=manager_id,
                    department_id=department_id,
                    name="Alisher",
                    email="g.alisher@dogovor24.kz",
                )
            ]
        )
        artifact = SimpleNamespace(
            interaction=SimpleNamespace(manager_id=manager_id),
            manager=None,
        )

        targets = orchestrator._resolve_delivery_targets(
            preset=resolve_report_preset("manager_daily"),
            artifacts=[artifact],
            payload={"meta": {"manager_id": str(manager_id)}},
        )

        self.assertEqual(targets["primary_email"], "g.alisher@dogovor24.kz")
        self.assertIn("sales@dogovor24.kz", targets["cc_emails"])

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
        self.assertEqual(batch.observability["created_batches_count"], 1)
        self.assertEqual(batch.observability["report_batches_created"], 1)
        self.assertEqual(batch.observability["batches_created"], 1)
        self.assertEqual(batch.observability["diagnostic_batches_created"], 0)
        self.assertEqual(batch.observability["expected_managers"], 1)
        self.assertEqual(batch.observability["selected_manager_days"], 1)
        self.assertEqual(batch.observability["selected_manager_days_count"], 1)
        self.assertEqual(batch.observability["skipped_manager_days"], 0)
        self.assertEqual(batch.observability["failed_batches_count"], 0)
        self.assertEqual(batch.observability["review_required_batches_count"], 1)
        self.assertEqual(batch.observability["report_ready_batches_count"], 1)
        self.assertEqual(batch.observability["status"], "ok")
        self.assertIsNone(batch.observability["failure_reason"])
        summary = batch.observability["scheduled_manager_daily_run"]
        self.assertEqual(summary["schedule_id"], str(schedule.id))
        self.assertEqual(summary["report_date"], "2026-06-15")
        self.assertEqual(summary["planned_for"], "2026-06-16T03:00:00+00:00")
        self.assertEqual(summary["expected_managers"], 1)
        self.assertEqual(summary["selected_manager_days"], 1)
        self.assertEqual(summary["skipped_manager_days"], 0)
        self.assertEqual(summary["report_batches_created"], 1)
        self.assertEqual(summary["batches_created"], 1)
        self.assertEqual(summary["diagnostic_batches_created"], 0)
        self.assertEqual(summary["failed_batches_count"], 0)
        self.assertEqual(summary["review_required_batches_count"], 1)
        self.assertEqual(summary["report_ready_batches_count"], 1)
        self.assertEqual(summary["status"], "ok")
        self.assertIsNone(summary["failure_reason"])
        self.assertEqual(summary["selection_summary"][0]["selection_status"], "selected")
        self.assertEqual(summary["selection_summary"][0]["reason"], "selected")

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

    def test_busy_manager_day_idempotency_lock_skips_without_batch_or_pipeline(self) -> None:
        service = _make_service()
        schedule = _manager_daily_schedule(planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC))
        db = _FakeGuardDb(lock_acquired=False)
        service.db = db
        service._advance_schedule = lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("lock-busy scan must not advance the schedule")
        )
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [
                _interaction_for_day(
                    manager_id=schedule.manager_ids[0],
                    report_date="2026-06-15",
                )
            ],
        }

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                raise AssertionError("lock-busy manager-day must not run the report pipeline")

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            with patch("app.agents.calls.scheduled_reporting.send_run_alert") as send_alert:
                service._run_due_schedule(
                    schedule=schedule,
                    now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC),
                )

        self.assertEqual(db.added, [])
        self.assertEqual(len(db.lock_params), 1)
        self.assertFalse(send_alert.called)
        self.assertIsNone(schedule.last_planned_at)
        self.assertEqual(schedule.next_run_at, datetime(2026, 6, 16, 3, 0, tzinfo=UTC))

    def test_repeat_scan_for_existing_manager_day_does_not_create_working_batch(self) -> None:
        for status in ("running", "review_required", "delivered"):
            with self.subTest(status=status):
                service = _make_service()
                schedule = _manager_daily_schedule(
                    planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC)
                )
                manager_id = schedule.manager_ids[0]
                existing = _manager_day_batch(
                    schedule_id=schedule.id,
                    department_id=schedule.department_id,
                    manager_id=manager_id,
                    report_date="2026-06-15",
                    status=status,
                )
                db = _FakeGuardDb([existing])
                service.db = db
                service._advance_schedule = lambda **_kwargs: datetime(
                    2026, 6, 17, 3, 0, tzinfo=UTC
                )
                service._load_batch_drafts = lambda _batch_id: []
                service._load_manager_interactions_by_day = lambda **_kwargs: {
                    "2026-06-15": [
                        _interaction_for_day(
                            manager_id=manager_id,
                            report_date="2026-06-15",
                        )
                    ],
                }

                class FakeOrchestrator:
                    def __init__(self, *args, **kwargs) -> None:
                        self.delivery = SimpleNamespace()

                    async def run_report(self, **kwargs):
                        raise AssertionError("duplicate manager-day must not run pipeline")

                with patch(
                    "app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator",
                    FakeOrchestrator,
                ):
                    with patch("app.agents.calls.scheduled_reporting.send_run_alert") as send_alert:
                        send_alert.return_value = {
                            "channel": "email",
                            "recipient": "admin@dogovor24.kz",
                            "status": "skipped",
                            "subject": "reports not ready",
                            "reason": "alert_email_disabled",
                        }
                        service._run_due_schedule(
                            schedule=schedule,
                            now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC),
                        )

                working_statuses = {
                    "planned",
                    "queued",
                    "running",
                    "review_required",
                    "approved_for_delivery",
                    "delivered",
                }
                self.assertFalse(
                    any(
                        item.__class__.__name__ == "ScheduledReportBatch"
                        and item.status in working_statuses
                        for item in db.added
                    )
                )
                self.assertFalse(
                    any(item.__class__.__name__ == "ScheduledReportDraft" for item in db.added)
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
            with patch("app.agents.calls.scheduled_reporting.send_run_alert") as send_alert:
                send_alert.return_value = {
                    "channel": "email",
                    "recipient": "admin@dogovor24.kz",
                    "status": "skipped",
                    "subject": "reports not ready",
                    "reason": "alert_email_disabled",
                }
                service._run_due_schedule(
                    schedule=schedule,
                    now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC),
                )

        self.assertEqual(run_calls, [])
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].observability["selected_report_date"], None)
        self.assertEqual(added[0].observability["candidate_dates"], ["2026-06-15"])
        self.assertEqual(added[0].errors, ["no_candidate_empty_previous_day"])
        self.assertEqual(added[0].observability["created_batches_count"], 1)
        self.assertEqual(added[0].observability["report_batches_created"], 1)
        self.assertEqual(added[0].observability["batches_created"], 1)
        self.assertEqual(added[0].observability["diagnostic_batches_created"], 0)
        self.assertEqual(added[0].observability["expected_managers"], 1)
        self.assertEqual(added[0].observability["selected_manager_days"], 0)
        self.assertEqual(added[0].observability["selected_manager_days_count"], 0)
        self.assertEqual(added[0].observability["skipped_manager_days"], 1)
        self.assertEqual(added[0].observability["failed_batches_count"], 1)
        self.assertEqual(added[0].observability["review_required_batches_count"], 0)
        self.assertEqual(added[0].observability["report_ready_batches_count"], 0)
        self.assertEqual(added[0].observability["status"], "failed")
        self.assertEqual(
            added[0].observability["failure_reason"],
            "manager_daily_failed_batches_without_report_ready_batches",
        )
        summary = added[0].observability["scheduled_manager_daily_run"]
        self.assertEqual(summary["report_date"], "2026-06-15")
        self.assertEqual(summary["report_batches_created"], 1)
        self.assertEqual(summary["batches_created"], 1)
        self.assertEqual(summary["failed_batches_count"], 1)
        self.assertEqual(summary["review_required_batches_count"], 0)
        self.assertEqual(summary["report_ready_batches_count"], 0)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(
            summary["failure_reason"],
            "manager_daily_failed_batches_without_report_ready_batches",
        )
        self.assertEqual(summary["skipped"][0]["reason"], "no_calls")
        self.assertEqual(summary["skipped"][0]["calls_total"], 0)
        self.assertEqual(summary["alerts"][0]["kind"], "manager_daily_scheduled_failed_no_ready_batch")
        self.assertEqual(send_alert.call_args.args[0], "blocked")
        alert_kwargs = send_alert.call_args.kwargs
        self.assertEqual(alert_kwargs["counts"]["failed_batches"], 1)
        self.assertEqual(alert_kwargs["counts"]["report_ready_batches"], 0)
        self.assertIn("reports are not ready", alert_kwargs["operator_summary"])
        self.assertIn("managers may not receive daily emails", alert_kwargs["operator_summary"])
        self.assertNotIn("[{", alert_kwargs["operator_summary"])

    def test_manager_daily_zero_batch_guard_creates_failed_batch_and_alerts(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(planned_for=datetime(2026, 6, 17, 23, 0, tzinfo=UTC))
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 18, 23, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **kwargs: {
            item: [] for item in kwargs["candidate_dates"]
        }
        service._has_manager_day_duplicate = lambda **_kwargs: False
        service._record_skipped_manager_day_selection = lambda **_kwargs: None

        with patch("app.agents.calls.scheduled_reporting.send_run_alert") as send_alert:
            send_alert.return_value = {
                "channel": "email",
                "recipient": "admin@dogovor24.kz",
                "status": "skipped",
                "subject": "zero batch",
                "reason": "alert_email_disabled",
            }
            service._run_due_schedule(
                schedule=schedule,
                now_utc=datetime(2026, 6, 17, 23, 30, tzinfo=UTC),
            )

        self.assertEqual(len(added), 1)
        batch = added[0]
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.errors, ["manager_daily_zero_batches_after_candidate_selection"])
        self.assertEqual(batch.observability["created_batches_count"], 1)
        self.assertEqual(batch.observability["report_batches_created"], 0)
        self.assertEqual(batch.observability["batches_created"], 0)
        self.assertEqual(batch.observability["diagnostic_batches_created"], 1)
        self.assertEqual(batch.observability["expected_managers"], 1)
        self.assertEqual(batch.observability["selected_manager_days"], 0)
        self.assertEqual(batch.observability["selected_manager_days_count"], 0)
        self.assertEqual(batch.observability["skipped_manager_days"], 1)
        self.assertEqual(batch.observability["failed_batches_count"], 0)
        self.assertEqual(batch.observability["review_required_batches_count"], 0)
        self.assertEqual(batch.observability["report_ready_batches_count"], 0)
        self.assertEqual(batch.observability["status"], "failed")
        self.assertEqual(
            batch.observability["failure_reason"],
            "manager_daily_zero_batches_after_candidate_selection",
        )
        summary = batch.observability["scheduled_manager_daily_run"]
        self.assertEqual(summary["schedule_id"], str(schedule.id))
        self.assertEqual(summary["report_date"], "2026-06-17")
        self.assertEqual(summary["expected_managers"], 1)
        self.assertEqual(summary["selected_manager_days"], 0)
        self.assertEqual(summary["skipped_manager_days"], 1)
        self.assertEqual(summary["report_batches_created"], 0)
        self.assertEqual(summary["batches_created"], 0)
        self.assertEqual(summary["diagnostic_batches_created"], 1)
        self.assertEqual(summary["failed_batches_count"], 0)
        self.assertEqual(summary["review_required_batches_count"], 0)
        self.assertEqual(summary["report_ready_batches_count"], 0)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(
            summary["failure_reason"],
            "manager_daily_zero_batches_after_candidate_selection",
        )
        self.assertEqual(summary["skipped"][0]["reason"], "no_calls")
        self.assertEqual(
            summary["created_batches_before_guard_count"],
            0,
        )
        self.assertEqual(batch.observability["alerts"][0]["status"], "skipped")
        self.assertEqual(send_alert.call_args.args[0], "blocked")
        alert_kwargs = send_alert.call_args.kwargs
        self.assertEqual(
            alert_kwargs["run_id"],
            f"manager_daily:{schedule.id}:2026-06-17",
        )
        self.assertEqual(alert_kwargs["counts"]["created_batches"], 0)
        self.assertIn("Daily reports: batches were not created", alert_kwargs["operator_summary"])
        self.assertIn("batches_created=0", alert_kwargs["operator_summary"])
        self.assertNotIn("[{", alert_kwargs["operator_summary"])
        self.assertEqual(schedule.last_planned_at, datetime(2026, 6, 17, 23, 0, tzinfo=UTC))
        self.assertEqual(schedule.next_run_at, datetime(2026, 6, 18, 23, 0, tzinfo=UTC))

    def test_manager_daily_selected_failed_batch_without_draft_alerts_immediately(self) -> None:
        service = _make_service()
        added = []
        schedule = _manager_daily_schedule(planned_for=datetime(2026, 6, 16, 3, 0, tzinfo=UTC))
        service.db = SimpleNamespace(add=lambda item: added.append(item), flush=lambda: None)
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 6, 17, 23, 0, tzinfo=UTC)
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [
                _interaction_for_day(
                    manager_id=schedule.manager_ids[0],
                    report_date="2026-06-15",
                )
            ],
        }
        service._has_manager_day_duplicate = lambda **_kwargs: False

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                return {
                    "reports": [],
                    "observability": {"pipeline": "ready_data_only"},
                    "diagnostics": {},
                    "errors": ["no_deliverable_report"],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            with patch("app.agents.calls.scheduled_reporting.send_run_alert") as send_alert:
                send_alert.return_value = {
                    "channel": "email",
                    "recipient": "admin@dogovor24.kz",
                    "status": "skipped",
                    "subject": "reports not ready",
                    "reason": "alert_email_disabled",
                }
                service._run_due_schedule(
                    schedule=schedule,
                    now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC),
                )

        self.assertEqual(len(added), 1)
        batch = added[0]
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.observability["report_batches_created"], 1)
        self.assertEqual(batch.observability["batches_created"], 1)
        self.assertEqual(batch.observability["diagnostic_batches_created"], 0)
        self.assertEqual(batch.observability["failed_batches_count"], 1)
        self.assertEqual(batch.observability["review_required_batches_count"], 0)
        self.assertEqual(batch.observability["report_ready_batches_count"], 0)
        self.assertEqual(batch.observability["status"], "failed")
        self.assertEqual(
            batch.observability["failure_reason"],
            "manager_daily_failed_batches_without_report_ready_batches",
        )
        summary = batch.observability["scheduled_manager_daily_run"]
        self.assertEqual(summary["selected_manager_days"], 1)
        self.assertEqual(summary["skipped_manager_days"], 0)
        self.assertEqual(summary["report_batches_created"], 1)
        self.assertEqual(summary["failed_batches_count"], 1)
        self.assertEqual(summary["report_ready_batches_count"], 0)
        self.assertEqual(summary["alerts"][0]["kind"], "manager_daily_scheduled_failed_no_ready_batch")
        self.assertEqual(send_alert.call_count, 1)
        alert_kwargs = send_alert.call_args.kwargs
        self.assertEqual(alert_kwargs["counts"]["created_batches"], 1)
        self.assertEqual(alert_kwargs["counts"]["failed_batches"], 1)
        self.assertEqual(alert_kwargs["counts"]["report_ready_batches"], 0)
        self.assertIn("Daily reports: reports are not ready", alert_kwargs["operator_summary"])
        self.assertIn("report_ready=0", alert_kwargs["operator_summary"])
        self.assertNotIn("[{", alert_kwargs["operator_summary"])

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
        self.assertEqual(batch.status, "failed")
        self.assertEqual(draft.status, "failed")
        self.assertNotEqual(draft.delivery["transport"]["email_delivery"]["status"], "delivered")
        self.assertEqual(draft.delivery["transport"]["email_delivery"]["status"], "blocked")
        self.assertEqual(batch.observability["sla_status"], "blocked")
        self.assertEqual(batch.observability["sla_missed_reason"], "missing_recipient")
        self.assertEqual(batch.observability["manager_email_status"], "blocked")
        self.assertIsNone(batch.observability["primary_email"])
        self.assertEqual(batch.observability["recipient_resolve_status"], "missing")
        self.assertIn("missing_recipient", draft.errors)

    def test_production_schedule_marks_email_exception_as_delivery_failed(self) -> None:
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

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                report = _ready_manager_daily_report(report_date="2026-06-15")
                report["delivery"] = {
                    "transport": {
                        "email_delivery": {
                            "enabled": True,
                            "status": "failed",
                            "primary_email": "manager@example.com",
                            "error": "SMTP timeout",
                        },
                        "resolved_email": {
                            "primary_email": "manager@example.com",
                            "cc_emails": ["sales@dogovor24.kz"],
                        },
                    }
                }
                report["errors"] = ["SMTP timeout"]
                return {
                    "reports": [report],
                    "rop_daily_delivery": {"status": "skipped"},
                    "observability": {},
                    "diagnostics": {},
                    "errors": ["SMTP timeout"],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            with patch("app.agents.calls.scheduled_reporting.datetime", _OnTimeSlaDateTime):
                service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 6, 16, 3, 30, tzinfo=UTC))

        batch = added[0]
        draft = added[1]
        self.assertEqual(batch.status, "failed")
        self.assertEqual(draft.status, "failed")
        self.assertEqual(batch.observability["sla_status"], "blocked")
        self.assertEqual(batch.observability["sla_missed_reason"], "delivery_failed:SMTP timeout")
        self.assertEqual(batch.observability["primary_email"], "manager@example.com")
        self.assertEqual(batch.observability["recipient_resolve_status"], "resolved")
        self.assertIn("delivery_failed:SMTP timeout", draft.errors)

    def test_production_waiting_upstream_schedules_hourly_retry_without_draft(self) -> None:
        service = _make_service()
        schedule = _manager_daily_schedule(
            planned_for=datetime(2026, 6, 15, 23, 0, tzinfo=UTC),
            business_email_enabled=True,
            review_required=False,
        )
        schedule.mode = "build_missing_and_report"
        db = _FakeGuardDb()
        service.db = db
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [
                _interaction_for_day(
                    manager_id=schedule.manager_ids[0],
                    report_date="2026-06-15",
                )
            ],
        }

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                assert kwargs["send_email"] is True
                return {
                    "status": "waiting_upstream",
                    "reports": [],
                    "rop_daily_delivery": {"status": "skipped"},
                    "observability": {
                        "summary": {
                            "source": {
                                "call_processing_run_id": "run-running",
                                "call_processing_scope_hash": "hash-running",
                                "call_processing_status": "running",
                                "call_processing_readiness": "waiting_upstream",
                                "call_processing_waiting_upstream": True,
                                "call_processing_artifacts_ready": 4,
                                "call_processing_artifacts_missing": 5,
                            }
                        }
                    },
                    "diagnostics": {},
                    "errors": ["waiting_upstream"],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(
                schedule=schedule,
                now_utc=datetime(2026, 6, 15, 23, 10, tzinfo=UTC),
            )

        batches = [item for item in db.added if item.__class__.__name__ == "ScheduledReportBatch"]
        drafts = [item for item in db.added if item.__class__.__name__ == "ScheduledReportDraft"]
        self.assertEqual(len(batches), 1)
        self.assertEqual(drafts, [])
        self.assertEqual(batches[0].status, "paused")
        self.assertTrue(batches[0].observability["upstream_waiting"])
        self.assertEqual(batches[0].observability["upstream_waiting_reason"], "waiting_upstream")
        self.assertEqual(
            schedule.next_run_at,
            datetime(2026, 6, 16, 0, 0, tzinfo=UTC),
        )

    def test_production_upstream_retry_reuses_existing_batch_when_ready(self) -> None:
        service = _make_service()
        schedule = _manager_daily_schedule(
            planned_for=datetime(2026, 6, 15, 23, 0, tzinfo=UTC),
            business_email_enabled=True,
            review_required=False,
        )
        schedule.mode = "build_missing_and_report"
        db = _FakeGuardDb()
        service.db = db
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [
                _interaction_for_day(
                    manager_id=schedule.manager_ids[0],
                    report_date="2026-06-15",
                )
            ],
        }
        calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    return {
                        "status": "waiting_upstream",
                        "reports": [],
                        "rop_daily_delivery": {"status": "skipped"},
                        "observability": {
                            "summary": {
                                "source": {
                                    "call_processing_run_id": "run-running",
                                    "call_processing_scope_hash": "hash-running",
                                    "call_processing_status": "running",
                                    "call_processing_readiness": "waiting_upstream",
                                    "call_processing_waiting_upstream": True,
                                }
                            }
                        },
                        "diagnostics": {},
                        "errors": ["waiting_upstream"],
                    }
                return {
                    "reports": [_delivered_manager_daily_report(report_date="2026-06-15")],
                    "rop_daily_delivery": {"status": "delivered", "target": "edo.rop@dogovor24.kz"},
                    "observability": {},
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(
                schedule=schedule,
                now_utc=datetime(2026, 6, 15, 23, 10, tzinfo=UTC),
            )
            pending_batch = next(
                item for item in db.added if item.__class__.__name__ == "ScheduledReportBatch"
            )
            db._rows = [pending_batch]
            service._run_due_schedule(
                schedule=schedule,
                now_utc=datetime(2026, 6, 16, 0, 5, tzinfo=UTC),
            )

        batches = [item for item in db.added if item.__class__.__name__ == "ScheduledReportBatch"]
        drafts = [item for item in db.added if item.__class__.__name__ == "ScheduledReportDraft"]
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(batches[0].status, "delivered")
        self.assertEqual(drafts[0].status, "delivered")

    def test_production_upstream_waiting_at_last_checkpoint_becomes_terminal(self) -> None:
        service = _make_service()
        schedule = _manager_daily_schedule(
            planned_for=datetime(2026, 6, 16, 4, 0, tzinfo=UTC),
            business_email_enabled=True,
            review_required=False,
        )
        schedule.mode = "build_missing_and_report"
        db = _FakeGuardDb()
        service.db = db
        service._load_manager_interactions_by_day = lambda **_kwargs: {
            "2026-06-15": [
                _interaction_for_day(
                    manager_id=schedule.manager_ids[0],
                    report_date="2026-06-15",
                )
            ],
        }

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                return {
                    "status": "waiting_upstream",
                    "reports": [],
                    "rop_daily_delivery": {"status": "skipped"},
                    "observability": {"summary": {"source": {"call_processing_readiness": "waiting_upstream"}}},
                    "diagnostics": {},
                    "errors": ["waiting_upstream"],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(
                schedule=schedule,
                now_utc=datetime(2026, 6, 16, 4, 5, tzinfo=UTC),
            )

        batch = next(item for item in db.added if item.__class__.__name__ == "ScheduledReportBatch")
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.observability["upstream_waiting_reason"], "upstream_not_ready_before_deadline")
        self.assertIn("upstream_not_ready_before_deadline", batch.errors)
        self.assertEqual(schedule.next_run_at, datetime(2026, 6, 17, 3, 0, tzinfo=UTC))

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
