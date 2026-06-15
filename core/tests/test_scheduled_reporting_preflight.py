from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import contextmanager
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
        return {"id": "schedule-1", **kwargs, "review_required": True}


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
        self.assertEqual(payload["would_create"]["report_period_rule"], "previous_day")
        self.assertFalse(payload["would_create"]["business_email_enabled"])
        self.assertTrue(payload["would_create"]["review_required"])

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


if __name__ == "__main__":
    unittest.main()
