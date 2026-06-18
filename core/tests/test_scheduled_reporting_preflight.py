from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT if (PROJECT_ROOT / "app").exists() else PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

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

from report_scripts import scheduled_reporting_preflight as preflight  # noqa: E402


MANAGER_IDS = [
    "5638c619-8732-435c-9664-a7188f13effd",
    "cfba5067-d356-4c8b-895a-0f5808647978",
    "656abe58-7c23-476a-a9f6-d76305cf42e0",
    "d42e8246-772e-4a04-bbe7-2b88f45db695",
]
DEPARTMENT_ID = "472cda28-ce71-494c-9068-25d3ffbf7399"


def _sla_row(
    manager_id: str,
    *,
    manager_name: str,
    reason: str,
    email_status: str = "planned",
    extra: dict | None = None,
) -> dict:
    row = {
        "schedule_id": "schedule-1",
        "department_id": DEPARTMENT_ID,
        "manager_id": manager_id,
        "manager_name": manager_name,
        "manager_email": f"{manager_name.lower()}@example.com",
        "calls": {"total": 1, "with_audio": 1, "no_audio": 0, "presence": True},
        "sla": {"sla_status": "missed_pending", "reason": reason},
        "manager_email": {"status": email_status},
        "batch": {"id": f"batch-{manager_id[:8]}"},
    }
    if extra:
        row.update(extra)
    return row


def _production_args(*extra: str) -> list[str]:
    args = [
        "--json",
        "create-production-manager-daily",
        "--department-id",
        DEPARTMENT_ID,
        "--first-report-date",
        "2026-06-15",
    ]
    for manager_id in MANAGER_IDS:
        args.extend(["--manager-id", manager_id])
    args.extend(extra)
    return args


class FakeScheduleService:
    existing_schedules: list[dict] = []
    created: list[dict] = []

    def __init__(self, db) -> None:
        self.db = db

    def list_schedules(self) -> list[dict]:
        return list(self.existing_schedules)

    def create_schedule(self, **kwargs) -> dict:
        self.created.append(kwargs)
        return {"id": "schedule-1", **kwargs}


@contextmanager
def fake_db():
    yield SimpleNamespace()


def _run_with_fake_service(args: list[str]) -> tuple[int, str, str]:
    FakeScheduleService.created = []
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(preflight, "get_db", fake_db):
        with patch.object(preflight, "ScheduledReviewableReportingService", FakeScheduleService):
            with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
                exit_code = preflight.main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class ScheduledReportingPreflightCliTests(unittest.TestCase):
    def test_production_manager_daily_dry_run_derives_safe_schedule_payload(self) -> None:
        FakeScheduleService.existing_schedules = []

        exit_code, stdout, stderr = _run_with_fake_service(
            _production_args("--dry-run"),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(FakeScheduleService.created, [])
        payload = json.loads(stdout)
        self.assertEqual(payload["action"], "dry_run_create_schedule")
        self.assertFalse(payload["production_smoke"]["billable_pipeline_started"])
        self.assertEqual(payload["production_smoke"]["derived_schedule_start_date"], "2026-06-16")
        self.assertEqual(payload["would_create"]["preset"], "manager_daily")
        self.assertEqual(payload["would_create"]["manager_ids"], MANAGER_IDS)
        self.assertEqual(payload["would_create"]["timezone"], "Asia/Almaty")
        self.assertEqual(payload["would_create"]["start_time"], "04:00")
        self.assertEqual(payload["would_create"]["report_period_rule"], "previous_day")
        self.assertTrue(payload["would_create"]["business_email_enabled"])
        self.assertFalse(payload["would_create"]["review_required"])

    def test_production_manager_daily_blocks_active_overlapping_schedule(self) -> None:
        FakeScheduleService.existing_schedules = [
            {
                "id": "existing-schedule",
                "deleted": False,
                "enabled": True,
                "department_id": DEPARTMENT_ID,
                "preset": "manager_daily",
                "manager_ids": [MANAGER_IDS[0]],
                "recurrence_type": "daily",
                "report_period_rule": "previous_day",
                "start_time": "08:00",
                "timezone": "Asia/Almaty",
                "mode": "build_missing_and_report",
                "business_email_enabled": False,
                "next_run_at": "2026-06-16T03:00:00+00:00",
            }
        ]

        exit_code, stdout, stderr = _run_with_fake_service(_production_args())

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(FakeScheduleService.created, [])
        self.assertIn("active schedule conflict detected", stderr)
        self.assertIn("existing-schedule", stderr)

    def test_production_manager_daily_requires_four_manager_ids(self) -> None:
        FakeScheduleService.existing_schedules = []
        args = _production_args()
        first_manager_flag = args.index("--manager-id")
        del args[first_manager_flag : first_manager_flag + 2]

        exit_code, stdout, stderr = _run_with_fake_service(args)

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(FakeScheduleService.created, [])
        self.assertIn("Expected 4 manager_ids, got 3", stderr)

    def test_sla_status_command_dispatches_without_running_pipeline(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        payload = {"status": "ok", "action": "sla_status", "report_date": "2026-06-15"}

        with patch.object(preflight, "sla_status", return_value=payload) as sla_status:
            with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
                exit_code = preflight.main(["--json", "sla-status", "--date", "2026-06-15"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(json.loads(stdout.getvalue()), payload)
        sla_status.assert_called_once()
        self.assertEqual(sla_status.call_args.args[0].date, "2026-06-15")

    def test_sla_check_command_dispatches_phase_without_running_pipeline(self) -> None:
        stdout = StringIO()
        payload = {
            "status": "ok",
            "action": "sla_check",
            "phase": "precheck",
            "report_date": "2026-06-15",
        }

        with patch.object(preflight, "sla_check", return_value=payload) as sla_check:
            with patch.object(sys, "stdout", stdout):
                exit_code = preflight.main(
                    ["--json", "sla-check", "--date", "2026-06-15", "--phase", "precheck"]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), payload)
        sla_check.assert_called_once()
        self.assertEqual(sla_check.call_args.args[0].phase, "precheck")

    def test_sla_check_date_defaults_to_auto_for_scheduler_use(self) -> None:
        stdout = StringIO()
        payload = {
            "status": "ok",
            "action": "sla_check",
            "phase": "hard",
            "report_date": "2026-06-16",
        }

        with patch.object(preflight, "sla_check", return_value=payload) as sla_check:
            with patch.object(sys, "stdout", stdout):
                exit_code = preflight.main(["--json", "sla-check", "--phase", "hard"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), payload)
        sla_check.assert_called_once()
        self.assertEqual(sla_check.call_args.args[0].date, "auto")

    def test_sla_report_date_auto_uses_previous_day_in_almaty_timezone(self) -> None:
        report_date = preflight._resolve_sla_report_date(
            "auto",
            now_utc=datetime(2026, 6, 17, 20, 0, tzinfo=UTC),
        )

        self.assertEqual(report_date, date.fromisoformat("2026-06-17"))

    def test_sla_report_date_accepts_explicit_iso_date(self) -> None:
        report_date = preflight._resolve_sla_report_date(
            "2026-06-15",
            now_utc=datetime(2026, 6, 17, 20, 0, tzinfo=UTC),
        )

        self.assertEqual(report_date, date.fromisoformat("2026-06-15"))

    def test_sla_state_marks_no_calls_as_not_applicable(self) -> None:
        state = preflight._derive_sla_state(
            report_date=date.fromisoformat("2026-06-15"),
            calls_total=0,
            with_audio_calls=0,
            upstream={"stt_ready": True, "llm1_ready": True},
            analysis={"analysis_ready": True},
            batch=None,
            drafts=[],
            manager_email={"status": "not_started"},
            rop={"status": "not_started"},
            now_utc=datetime.fromisoformat("2026-06-15T05:00:00+00:00"),
        )

        self.assertEqual(state["sla_status"], "not_applicable")
        self.assertEqual(state["reason"], "no_calls_for_report_day")
        self.assertFalse(state["sla_missed"])

    def test_sla_state_marks_missing_delivery_after_deadline_as_missed(self) -> None:
        state = preflight._derive_sla_state(
            report_date=date.fromisoformat("2026-06-15"),
            calls_total=1,
            with_audio_calls=1,
            upstream={"stt_ready": True, "llm1_ready": True},
            analysis={"analysis_ready": True},
            batch=SimpleNamespace(delivered_at=None, observability={}),
            drafts=[SimpleNamespace(artifact={"filename": "manager.pdf"}, delivery={})],
            manager_email={"status": "planned"},
            rop={"status": "not_started"},
            now_utc=datetime.fromisoformat("2026-06-15T05:00:00+00:00"),
        )

        self.assertEqual(state["sla_status"], "missed_pending")
        self.assertEqual(state["reason"], "manager_email_planned")
        self.assertTrue(state["sla_missed"])

    def test_sla_precheck_alert_sends_concise_warning_summary(self) -> None:
        rows = [
            _sla_row(MANAGER_IDS[0], manager_name="Timur", reason="manager_email_planned"),
            _sla_row(MANAGER_IDS[1], manager_name="Alisher", reason="scheduled_draft_missing"),
        ]

        with patch.object(
            preflight,
            "send_run_alert",
            return_value={"status": "sent", "channel": "telegram"},
        ) as send_run_alert:
            result = preflight._send_sla_alert(
                phase="precheck",
                report_date=date.fromisoformat("2026-06-15"),
                rows=rows,
            )

        self.assertEqual(result, {"status": "sent", "channel": "telegram"})
        send_run_alert.assert_called_once()
        args, kwargs = send_run_alert.call_args
        self.assertEqual(args, ("blocked",))
        self.assertEqual(kwargs["level"], "warning")
        self.assertEqual(kwargs["run_id"], "manager_daily_sla:2026-06-15:precheck")
        self.assertEqual(kwargs["counts"], {"affected_managers": 2})
        self.assertNotIn("details", kwargs)
        self.assertTrue(all(isinstance(item, str) for item in kwargs["errors"]))

        summary = kwargs["operator_summary"]
        self.assertIn("Что случилось:", summary)
        self.assertIn("К 09:30 есть отчеты не в delivered-состоянии.", summary)
        self.assertIn("Кого затронуло:", summary)
        self.assertIn("- Timur: отправка письма менеджеру еще не завершена", summary)
        self.assertIn("- Alisher: нет готового черновика отчета", summary)
        self.assertIn("На что влияет:", summary)
        self.assertIn("Что проверить:", summary)
        self.assertIn("Run: manager_daily_sla:2026-06-15:precheck", summary)
        self.assertNotIn("{", summary)
        self.assertNotIn(MANAGER_IDS[0], summary)

    def test_sla_hard_alert_sends_concise_critical_summary_with_truncation(self) -> None:
        rows = [
            _sla_row(MANAGER_IDS[0], manager_name="Manager 1", reason="manager_email_failed"),
            _sla_row(MANAGER_IDS[1], manager_name="Manager 2", reason="scheduled_batch_missing"),
            _sla_row(MANAGER_IDS[2], manager_name="Manager 3", reason="pdf_not_ready"),
            _sla_row(MANAGER_IDS[3], manager_name="Manager 4", reason="analysis_not_ready"),
            _sla_row(
                "0b8305ec-a74d-4a62-8df1-43177dec2739",
                manager_name="Manager 5",
                reason="read_timeout",
            ),
            _sla_row(
                "542f9079-67ac-4e86-a05a-6b3ffb4807c3",
                manager_name="Manager 6",
                reason='{"raw": "should not leak"}',
            ),
        ]

        with patch.object(
            preflight,
            "send_run_alert",
            return_value={"status": "skipped", "reason": "alert_telegram_disabled"},
        ) as send_run_alert:
            preflight._send_sla_alert(
                phase="hard",
                report_date=date.fromisoformat("2026-06-15"),
                rows=rows,
            )

        args, kwargs = send_run_alert.call_args
        self.assertEqual(args, ("failed",))
        self.assertEqual(kwargs["level"], "critical")
        self.assertEqual(kwargs["run_id"], "manager_daily_sla:2026-06-15:hard")
        self.assertEqual(kwargs["errors"][-1], "Еще 1 см. в observability/logs.")
        self.assertTrue(all(isinstance(item, str) for item in kwargs["errors"]))
        self.assertNotIn("details", kwargs)

        summary = kwargs["operator_summary"]
        self.assertIn("К 10:00 отчеты не доставлены.", summary)
        self.assertIn("Менеджеры не получили ежедневный отчет вовремя.", summary)
        self.assertIn("Еще 1 см. в observability/logs.", summary)
        self.assertNotIn("Manager 6", summary)
        self.assertNotIn('{"raw"', summary)

    def test_sla_check_keeps_full_affected_rows_in_result_observability(self) -> None:
        full_row = _sla_row(
            MANAGER_IDS[0],
            manager_name="Timur",
            reason="manager_email_failed",
            extra={"diagnostics": {"raw_manager_payload": {"kept": True}}},
        )

        with patch.object(preflight, "get_db", fake_db):
            with patch.object(preflight, "_active_manager_daily_schedules", return_value=["schedule"]):
                with patch.object(preflight, "_manager_scope_from_schedules", return_value=["scope"]):
                    with patch.object(preflight, "_build_manager_sla_row", return_value=full_row):
                        with patch.object(
                            preflight,
                            "_send_sla_alert",
                            return_value={"status": "sent"},
                        ):
                            result = preflight.sla_check(
                                SimpleNamespace(date="2026-06-15", phase="precheck")
                            )

        self.assertEqual(result["affected_managers_count"], 1)
        self.assertEqual(result["affected_managers"][0]["manager_id"], MANAGER_IDS[0])
        self.assertEqual(result["affected_manager_statuses"], [full_row])
        self.assertEqual(result["manager_statuses"], [full_row])
        self.assertEqual(
            result["affected_manager_statuses"][0]["diagnostics"],
            {"raw_manager_payload": {"kept": True}},
        )

    def test_sla_beat_entries_and_routes_are_registered_for_analysis_runtime(self) -> None:
        from app.core_shared.workers.celery_app import (
            ANALYSIS_QUEUE,
            MANAGER_DAILY_SLA_HARDCHECK_TASK,
            MANAGER_DAILY_SLA_PRECHECK_TASK,
            MANAGER_DAILY_SLA_TIMEZONE,
            build_beat_schedule,
            build_task_routes,
        )

        schedule = build_beat_schedule("analysis")
        routes = build_task_routes("analysis")

        self.assertEqual(MANAGER_DAILY_SLA_TIMEZONE, "Asia/Almaty")
        precheck = schedule["manager_daily_sla_precheck"]
        hardcheck = schedule["manager_daily_sla_hardcheck"]
        self.assertEqual(precheck["task"], MANAGER_DAILY_SLA_PRECHECK_TASK)
        self.assertEqual(hardcheck["task"], MANAGER_DAILY_SLA_HARDCHECK_TASK)
        self.assertEqual(precheck["kwargs"], {"report_date": "auto"})
        self.assertEqual(hardcheck["kwargs"], {"report_date": "auto"})
        self.assertEqual(precheck["options"], {"queue": ANALYSIS_QUEUE})
        self.assertEqual(hardcheck["options"], {"queue": ANALYSIS_QUEUE})
        self.assertEqual(routes[MANAGER_DAILY_SLA_PRECHECK_TASK], {"queue": ANALYSIS_QUEUE})
        self.assertEqual(routes[MANAGER_DAILY_SLA_HARDCHECK_TASK], {"queue": ANALYSIS_QUEUE})

        precheck_cron = precheck["schedule"]
        hardcheck_cron = hardcheck["schedule"]
        self.assertEqual(str(precheck_cron._orig_hour), "9")
        self.assertEqual(str(precheck_cron._orig_minute), "30")
        self.assertEqual(str(precheck_cron._orig_day_of_week), "1-5")
        self.assertEqual(str(hardcheck_cron._orig_hour), "10")
        self.assertEqual(str(hardcheck_cron._orig_minute), "0")
        self.assertEqual(str(hardcheck_cron._orig_day_of_week), "1-5")

    def test_sla_worker_tasks_are_registered_without_billable_pipeline(self) -> None:
        from app.core_shared.workers import tasks  # noqa: F401
        from app.core_shared.workers.celery_app import (
            MANAGER_DAILY_SLA_HARDCHECK_TASK,
            MANAGER_DAILY_SLA_PRECHECK_TASK,
            celery_app,
        )

        self.assertIn(MANAGER_DAILY_SLA_PRECHECK_TASK, celery_app.tasks)
        self.assertIn(MANAGER_DAILY_SLA_HARDCHECK_TASK, celery_app.tasks)

        with patch.object(preflight, "sla_check", return_value={"status": "ok"}) as sla_check:
            precheck_result = celery_app.tasks[MANAGER_DAILY_SLA_PRECHECK_TASK].run(
                report_date="auto"
            )
            hardcheck_result = celery_app.tasks[MANAGER_DAILY_SLA_HARDCHECK_TASK].run(
                report_date="auto"
            )

        self.assertFalse(precheck_result["billable_pipeline_started"])
        self.assertFalse(hardcheck_result["billable_pipeline_started"])
        self.assertEqual(precheck_result["phase"], "precheck")
        self.assertEqual(hardcheck_result["phase"], "hard")
        self.assertEqual(sla_check.call_count, 2)

    def test_open_batch_diagnostics_formats_operator_text_and_marks_blocker(self) -> None:
        payload = {
            "status": "ok",
            "action": "open_batch_diagnostics",
            "active_schedules_count": 1,
            "potential_manager_daily_blockers_count": 1,
            "open_batches": [
                {
                    "schedule_id": "schedule-1",
                    "schedule_preset": "manager_daily",
                    "batch_id": "batch-1",
                    "status": "review_required",
                    "period": {"date_from": "2026-06-15", "date_to": "2026-06-15"},
                    "manager_ids": [MANAGER_IDS[0]],
                    "business_email_enabled": False,
                    "review_required": True,
                    "potential_manager_daily_blocker": True,
                    "blocker_reasons": [
                        "open batch on active manager_daily schedule",
                        "review_required=true",
                        "business_email_enabled=false",
                    ],
                    "blocked_by_batch_id": "batch-1",
                    "blocked_by_batch_status": "review_required",
                    "blocked_by_draft_ids": ["draft-1"],
                    "blocked_by_draft_statuses": {"draft-1": "review_required"},
                    "blocker_scope": "open_batch_visibility",
                    "recovery_hint": (
                        "scheduled_reporting_preflight.py recover-open-batches "
                        "--batch-id batch-1 --target-status paused --apply"
                    ),
                }
            ],
        }

        stdout = StringIO()
        with patch.object(preflight, "open_batches", return_value=payload):
            with patch.object(sys, "stdout", stdout):
                exit_code = preflight.main(["open-batches"])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Scheduled reporting open batch diagnostics", output)
        self.assertIn("Potential manager_daily blockers: 1", output)
        self.assertIn("BLOCKER", output)
        self.assertIn("business_email_enabled=no", output)
        self.assertIn("review_required=yes", output)
        self.assertIn("blocked_by: batch=batch-1 status=review_required drafts=draft-1", output)
        self.assertIn("recovery_hint:", output)
        self.assertNotIn("{", output)

    def test_open_batch_row_includes_concrete_blocker_ids_and_recovery_hint(self) -> None:
        schedule = SimpleNamespace(
            id="schedule-1",
            preset="manager_daily",
            enabled=True,
            next_run_at=None,
        )
        batch = SimpleNamespace(
            id="11111111-1111-4111-8111-111111111111",
            schedule_id="schedule-1",
            status="review_required",
            period={"date_from": "2026-06-15", "date_to": "2026-06-15"},
            filters={"manager_ids": [MANAGER_IDS[0]]},
            business_email_enabled=False,
            review_required=True,
            planned_for=None,
            created_at=None,
            observability={},
        )
        draft = SimpleNamespace(
            id="22222222-2222-4222-8222-222222222222",
            batch_id=batch.id,
            status="review_required",
        )

        row = preflight._open_batch_row(schedule, batch, drafts=[draft])

        self.assertTrue(row["potential_manager_daily_blocker"])
        self.assertEqual(row["blocked_by_batch_id"], str(batch.id))
        self.assertEqual(row["blocked_by_batch_status"], "review_required")
        self.assertEqual(row["blocked_by_draft_ids"], [str(draft.id)])
        self.assertEqual(
            row["blocked_by_draft_statuses"],
            {str(draft.id): "review_required"},
        )
        self.assertEqual(row["blocker_scope"], "open_batch_visibility")
        self.assertIn(str(batch.id), row["recovery_hint"])

    def test_paused_manager_daily_batch_is_not_a_blocker(self) -> None:
        schedule = SimpleNamespace(
            id="schedule-1",
            preset="manager_daily",
            enabled=True,
            next_run_at=None,
        )
        batch = SimpleNamespace(
            id="11111111-1111-4111-8111-111111111111",
            schedule_id="schedule-1",
            status="paused",
            period={"date_from": "2026-06-15", "date_to": "2026-06-15"},
            filters={"manager_ids": [MANAGER_IDS[0]]},
            business_email_enabled=False,
            review_required=True,
            planned_for=None,
            created_at=None,
            observability={},
        )

        row = preflight._open_batch_row(schedule, batch)

        self.assertFalse(row["potential_manager_daily_blocker"])
        self.assertEqual(row["blocker_reasons"], [])
        self.assertIsNone(row["blocked_by_batch_id"])
        self.assertEqual(row["blocked_by_draft_ids"], [])
        self.assertIsNone(row["recovery_hint"])

    def test_recover_open_batches_is_dry_run_by_default_and_does_not_apply(self) -> None:
        schedule = SimpleNamespace(
            id="schedule-1",
            preset="manager_daily",
            enabled=True,
            next_run_at=None,
        )
        batch = SimpleNamespace(
            id="11111111-1111-4111-8111-111111111111",
            schedule_id="schedule-1",
            status="review_required",
            period={"date_from": "2026-06-15", "date_to": "2026-06-15"},
            filters={"manager_ids": [MANAGER_IDS[0]]},
            business_email_enabled=False,
            review_required=True,
            planned_for=None,
            created_at=None,
            observability={},
        )
        args = SimpleNamespace(
            batch_id=[],
            before_date="2026-06-16",
            preset="manager_daily",
            schedule_id=None,
            status=None,
            target_status="paused",
            reason=preflight.DEFAULT_RECOVERY_REASON,
            apply=False,
        )

        with patch.object(preflight, "get_db", fake_db):
            with patch.object(
                preflight,
                "_load_recovery_targets",
                return_value=([schedule], [batch]),
            ):
                with patch.object(preflight, "_apply_recovery_plan") as apply_plan:
                    result = preflight.recover_open_batches(args)

        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["matched_batches_count"], 1)
        self.assertEqual(result["planned_transitions_count"], 1)
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(result["plan"][0]["action"], "transition")
        self.assertEqual(result["plan"][0]["current_status"], "review_required")
        self.assertEqual(result["plan"][0]["target_status"], "paused")
        apply_plan.assert_not_called()

        text = preflight._format_recovery_plan(result)
        self.assertIn("Dry run only: no database rows were changed.", text)
        self.assertIn("transition=review_required->paused", text)
        self.assertNotIn("{", text)

    def test_recover_open_batches_default_statuses_exclude_paused(self) -> None:
        args = SimpleNamespace(
            batch_id=[],
            before_date="2026-06-16",
            preset="manager_daily",
            schedule_id=None,
            status=None,
            target_status="paused",
            reason=preflight.DEFAULT_RECOVERY_REASON,
            apply=False,
        )

        with patch.object(preflight, "get_db", fake_db):
            with patch.object(
                preflight,
                "_load_recovery_targets",
                return_value=([], []),
            ) as load_targets:
                preflight.recover_open_batches(args)

        statuses = load_targets.call_args.kwargs["statuses"]
        self.assertNotIn("paused", statuses)

    def test_recover_open_batches_allows_explicit_paused_status(self) -> None:
        args = SimpleNamespace(
            batch_id=[],
            before_date="2026-06-16",
            preset="manager_daily",
            schedule_id=None,
            status=["paused"],
            target_status="failed",
            reason=preflight.DEFAULT_RECOVERY_REASON,
            apply=False,
        )

        with patch.object(preflight, "get_db", fake_db):
            with patch.object(
                preflight,
                "_load_recovery_targets",
                return_value=([], []),
            ) as load_targets:
                preflight.recover_open_batches(args)

        self.assertEqual(load_targets.call_args.kwargs["statuses"], ["paused"])


if __name__ == "__main__":
    unittest.main()
