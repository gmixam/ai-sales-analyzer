"""Instruction-version guard tests for manual reporting runs."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
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

from app.agents.calls.manual_reporting_runner import build_parser  # noqa: E402
from app.agents.calls.reporting import (  # noqa: E402
    CallsManualReportingOrchestrator,
    _select_stable_analysis_for_reporting,
    resolve_report_preset,
)


def _analysis(*, instruction_version: str, reusable: bool = True, fail_reason: str | None = None):
    detail = {
        "classification": {
            "call_type": "sales_primary",
            "analysis_eligibility": "eligible",
        },
        "score": {"checklist_score": {"score_percent": 74.0}},
        "score_by_stage": [{"stage_code": "contact_start", "criteria_results": []}],
        "strengths": [{"title": "Contact", "comment": "Contact established."}],
        "gaps": [],
        "recommendations": [],
        "follow_up": {},
    }
    if not reusable:
        detail["score_by_stage"] = []
        detail["strengths"] = []
    return SimpleNamespace(
        id=uuid4(),
        interaction_id=uuid4(),
        instruction_version=instruction_version,
        is_failed=bool(fail_reason),
        fail_reason=fail_reason,
        scores_detail=detail,
    )


def _interaction():
    return SimpleNamespace(
        id=uuid4(),
        manager_id=None,
        text="Manager discussed the contract with the client.",
        metadata_={"call_started_at": "2026-05-08T10:00:00+00:00"},
    )


class ManualReportingInstructionVersionGuardTest(unittest.TestCase):
    def test_parser_accepts_analysis_instruction_version(self) -> None:
        args = build_parser().parse_args(
            [
                "--department-id",
                str(uuid4()),
                "--preset",
                "manager_daily",
                "--date-from",
                "2026-05-08",
                "--analysis-instruction-version",
                "edo_sales_mvp1_call_analysis_v13",
            ]
        )

        self.assertEqual(args.analysis_instruction_version, "edo_sales_mvp1_call_analysis_v13")

    def test_version_guard_keeps_new_not_coachable_instead_of_old_success(self) -> None:
        old_success = _analysis(instruction_version="edo_sales_mvp1_call_analysis_v12")
        new_not_coachable = _analysis(
            instruction_version="edo_sales_mvp1_call_analysis_v13",
            fail_reason="not_coachable_or_reportable",
        )

        unguarded = _select_stable_analysis_for_reporting([new_not_coachable, old_success])
        guarded = _select_stable_analysis_for_reporting(
            [new_not_coachable, old_success],
            analysis_instruction_version="edo_sales_mvp1_call_analysis_v13",
        )

        self.assertIs(unguarded, old_success)
        self.assertIs(guarded, new_not_coachable)

    def test_prepare_artifacts_reports_instruction_version_mismatch_in_ready_only(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction()
        old_success = _analysis(instruction_version="edo_sales_mvp1_call_analysis_v12")
        old_success.interaction_id = interaction.id
        setattr(
            orchestrator,
            "_load_latest_analyses_by_interaction",
            lambda **_kwargs: {interaction.id: old_success},
        )
        setattr(orchestrator, "_load_managers_by_id", lambda **_kwargs: {})

        artifacts, build_summary, build_errors = asyncio.run(
            CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="report_from_ready_data_only",
                analysis_instruction_version="edo_sales_mvp1_call_analysis_v13",
            )
        )

        self.assertIsNone(artifacts[0].analysis)
        self.assertIs(artifacts[0].original_analysis, old_success)
        self.assertEqual(build_summary["analyses_reused"], 0)
        self.assertEqual(build_summary["analyses_rejected_for_instruction_version"], 1)
        self.assertEqual(
            build_summary["analysis_instruction_version"],
            "edo_sales_mvp1_call_analysis_v13",
        )
        self.assertIn(
            f"analysis_reuse_rejected:{interaction.id}:"
            "instruction_version_mismatch:expected=edo_sales_mvp1_call_analysis_v13:"
            "actual=edo_sales_mvp1_call_analysis_v12",
            build_errors,
        )
        reason_codes = CallsManualReportingOrchestrator._build_diagnostics_reason_codes(
            mode="report_from_ready_data_only",
            diagnostics_context={
                "missing_local_manager_ids": [],
                "period_only_interactions_count": 1,
                "manager_filter_logic": "department_scope",
            },
            build_summary=build_summary,
            reports=[],
            selected_interactions_count=1,
            final_selected_interactions_count=0,
            errors=build_errors,
        )
        self.assertIn("analysis_instruction_version_mismatch", reason_codes)


if __name__ == "__main__":
    unittest.main()
