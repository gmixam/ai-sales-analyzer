#!/usr/bin/env python3
"""Run layered LLM2 only for already-transcribed calls.

This runner is intentionally narrow:
- no source discovery;
- no STT rebuild;
- no LLM1 call;
- no LLM3/report rendering/delivery.

It reuses a persisted previous analysis as the LLM1 first-pass snapshot and
executes only CallsAnalyzer._analyze_call_with_layered_llm2.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.agents.calls.analysis_purpose import ANALYSIS_PURPOSE_CONTROLLED_SAMPLE
from app.agents.calls.analyzer import CallsAnalyzer
from app.agents.calls.llm2_ab_runner import (
    _interaction_summary,
    _json_safe,
    _latest_controlled_analysis,
    _persist_controlled_analysis,
    _persist_controlled_failed_analysis,
    _resolve_manager,
    _write_json,
)
from app.agents.calls.llm_simulation import count_subagent_artifacts
from app.agents.calls.orchestrator import analysis_contract_failure_reason
from app.core_shared.db.models import Analysis, Interaction
from app.core_shared.db.session import get_db
from app.core_shared.exceptions import AnalysisError, LLMResponseError, SemanticAnalysisError


DEFAULT_PREVIOUS_VERSIONS = [
    "codex_full_day_ru_v3_20260528",
    "codex_full_day_v1_20260528",
    "subagent_layered_full_day_v1",
    "codex_full_day_ru_v4_20260601",
    "edo_sales_mvp1_call_analysis_v15_block_ready",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run only layered LLM2 over ready STT calls using persisted LLM1 snapshot.",
    )
    parser.add_argument("--department-id", required=True)
    parser.add_argument("--date", required=True, help="Call day in YYYY-MM-DD.")
    parser.add_argument("--manager-id")
    parser.add_argument("--manager-name")
    parser.add_argument("--instruction-version", default="llm2_gate_v1_20260601")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--previous-analysis-version",
        action="append",
        default=[],
        help="Preferred persisted analysis version to reuse as LLM1 snapshot. Repeatable.",
    )
    return parser


def _call_date(interaction: Interaction) -> str:
    metadata = dict(interaction.metadata_ or {})
    for key in ("call_date", "call_started_at", "started_at", "date"):
        value = metadata.get(key)
        if value:
            return str(value)[:10]
    return ""


def _call_started_at(interaction: Interaction) -> str:
    metadata = dict(interaction.metadata_ or {})
    for key in ("call_date", "call_started_at", "started_at"):
        value = metadata.get(key)
        if value:
            return str(value)
    return ""


def _ready_stt_interactions(
    db: Session,
    *,
    department_id: str,
    manager_id: str,
    run_date: str,
    limit: int | None,
) -> list[Interaction]:
    rows = (
        db.query(Interaction)
        .filter(
            Interaction.department_id == UUID(department_id),
            Interaction.manager_id == UUID(manager_id),
        )
        .all()
    )
    selected = [
        item
        for item in rows
        if _call_date(item) == run_date and bool(str(item.text or "").strip())
    ]
    selected.sort(key=_call_started_at)
    return selected[:limit] if limit is not None else selected


def _latest_previous_analysis(
    db: Session,
    *,
    interaction_id: UUID,
    preferred_versions: list[str],
    target_instruction_version: str,
) -> Analysis | None:
    for version in preferred_versions:
        analysis = (
            db.query(Analysis)
            .filter(
                Analysis.interaction_id == interaction_id,
                Analysis.instruction_version == version,
            )
            .order_by(Analysis.created_at.desc())
            .first()
        )
        if analysis is not None and isinstance(analysis.scores_detail, dict):
            return analysis
    return (
        db.query(Analysis)
        .filter(
            Analysis.interaction_id == interaction_id,
            Analysis.instruction_version != target_instruction_version,
            Analysis.scores_detail.isnot(None),
        )
        .order_by(Analysis.created_at.desc())
        .first()
    )


def _llm1_snapshot_from_previous(
    *,
    analyzer: CallsAnalyzer,
    interaction: Interaction,
    previous_analysis: Analysis | None,
    instruction_version: str,
) -> dict[str, Any]:
    template = analyzer.build_contract_template(
        interaction=interaction,
        instruction_version=instruction_version,
    )
    detail = dict(getattr(previous_analysis, "scores_detail", None) or {})
    snapshot = {
        "classification": dict(detail.get("classification") or template["classification"]),
        "summary": dict(detail.get("summary") or template["summary"]),
        "follow_up": dict(detail.get("follow_up") or template["follow_up"]),
        "data_quality": dict(detail.get("data_quality") or template["data_quality"]),
        "analysis_focus": list(detail.get("analysis_focus") or []),
        "_source": {
            "kind": "persisted_previous_analysis",
            "analysis_id": str(previous_analysis.id) if previous_analysis is not None else None,
            "instruction_version": (
                previous_analysis.instruction_version if previous_analysis is not None else None
            ),
        },
    }
    return snapshot


def _persist_runtime_failed_analysis(
    db: Session,
    *,
    interaction: Interaction,
    analyzer: CallsAnalyzer,
    instruction_version: str,
    error: Exception,
) -> Analysis:
    forensics = CallsAnalyzer.consume_analysis_forensics(interaction)
    scores_detail = {
        "instruction_version": instruction_version,
        "analysis_purpose": ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        "meta": {"analysis_purpose": ANALYSIS_PURPOSE_CONTROLLED_SAMPLE},
        "diagnostics": {
            "runtime_failure": {
                "type": type(error).__name__,
                "message": str(error),
                "failure_reason": forensics.get("failure_reason"),
            }
        },
    }
    analysis = Analysis(
        id=uuid4(),
        department_id=interaction.department_id,
        interaction_id=interaction.id,
        manager_id=interaction.manager_id,
        instruction_version=instruction_version,
        scores_detail=scores_detail,
        strengths=[],
        weaknesses=[],
        recommendations=[],
        topics=[],
        is_failed=True,
        fail_reason=str(forensics.get("failure_reason") or type(error).__name__),
        raw_llm_response=str(forensics.get("raw_llm_response") or str(error)),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def _analysis_diagnostics(analysis: Analysis | None) -> dict[str, Any]:
    detail = dict(getattr(analysis, "scores_detail", None) or {})
    classification = dict(detail.get("classification") or {})
    diagnostics = dict(detail.get("diagnostics") or {})
    gate = dict(diagnostics.get("llm2_admission_gate") or {})
    runtime = dict(detail.get("llm2_layered_runtime") or {})
    artifacts = dict(detail.get("llm2_layered_artifacts") or {})
    return {
        "analysis_id": str(analysis.id) if analysis is not None else None,
        "is_failed": bool(getattr(analysis, "is_failed", False)) if analysis else None,
        "fail_reason": getattr(analysis, "fail_reason", None) if analysis else None,
        "score_total": getattr(analysis, "score_total", None) if analysis else None,
        "classification": classification,
        "llm2_admission_gate": gate,
        "score_by_stage_count": len(detail.get("score_by_stage") or []),
        "criteria_results_count": len(detail.get("criteria_results") or []),
        "pass_artifact_keys": list(artifacts.keys()),
        "runtime": {
            "enabled": runtime.get("enabled"),
            "validation_valid": runtime.get("validation_valid"),
            "pass_artifact_keys": runtime.get("pass_artifact_keys"),
        },
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    preferred_versions = args.previous_analysis_version or DEFAULT_PREVIOUS_VERSIONS
    output_dir = Path(args.output_dir or "review_packages/llm2_ready_stt_layered_runner")
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = Path(
        __import__("os").environ.get("AI_LLM_SUBAGENT_ARTIFACT_DIR")
        or "/tmp/asa_llm_subagent_runs"
    )
    run_id = (
        __import__("os").environ.get("AI_LLM_SUBAGENT_RUN_ID")
        or "llm2-ready-stt-layered"
    )

    with get_db() as db:
        manager = _resolve_manager(
            db,
            department_id=args.department_id,
            manager_id=args.manager_id,
            manager_name=args.manager_name,
        )
        analyzer = CallsAnalyzer(department_id=args.department_id, db=db)
        interactions = _ready_stt_interactions(
            db,
            department_id=args.department_id,
            manager_id=str(manager.id),
            run_date=args.date,
            limit=args.limit,
        )
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "department_id": args.department_id,
            "manager": {"id": str(manager.id), "name": manager.name},
            "date": args.date,
            "instruction_version": args.instruction_version,
            "analysis_purpose": ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
            "mode": "llm2_layered_only_ready_stt",
            "does_not_run": ["source_discovery", "stt", "llm1", "llm3", "report_delivery"],
            "previous_analysis_versions": preferred_versions,
            "force": bool(args.force),
            "dry_run": bool(args.dry_run),
            "analysis_candidates": [_interaction_summary(item) for item in interactions],
        }
        _write_json(output_dir / "manifest.json", manifest)

        results: list[dict[str, Any]] = []
        if not args.dry_run:
            for index, interaction in enumerate(interactions, start=1):
                existing = None if args.force else _latest_controlled_analysis(
                    db,
                    interaction_id=interaction.id,
                    instruction_version=args.instruction_version,
                )
                if existing is not None:
                    results.append(
                        {
                            "index": index,
                            "interaction": _interaction_summary(interaction),
                            "status": "skipped_existing",
                            **_analysis_diagnostics(existing),
                        }
                    )
                    continue

                previous = _latest_previous_analysis(
                    db,
                    interaction_id=interaction.id,
                    preferred_versions=preferred_versions,
                    target_instruction_version=args.instruction_version,
                )
                llm1_snapshot = _llm1_snapshot_from_previous(
                    analyzer=analyzer,
                    interaction=interaction,
                    previous_analysis=previous,
                    instruction_version=args.instruction_version,
                )
                try:
                    result = analyzer._analyze_call_with_layered_llm2(
                        interaction=interaction,
                        instruction_version=args.instruction_version,
                        llm1_first_pass=llm1_snapshot,
                    )
                    analysis = _persist_controlled_analysis(
                        db,
                        interaction=interaction,
                        result=result,
                    )
                    status = "created"
                except SemanticAnalysisError as exc:
                    analysis = _persist_controlled_failed_analysis(
                        db,
                        interaction=interaction,
                        error=exc,
                        instruction_version=args.instruction_version,
                    )
                    status = "created_failed"
                except LLMResponseError as exc:
                    analysis = _persist_controlled_failed_analysis(
                        db,
                        interaction=interaction,
                        error=exc,
                        instruction_version=args.instruction_version,
                        fail_reason=analysis_contract_failure_reason(exc),
                    )
                    status = "created_failed"
                except AnalysisError as exc:
                    analysis = _persist_runtime_failed_analysis(
                        db,
                        interaction=interaction,
                        analyzer=analyzer,
                        instruction_version=args.instruction_version,
                        error=exc,
                    )
                    status = "created_runtime_failed"

                result_item = {
                    "index": index,
                    "interaction": _interaction_summary(interaction),
                    "status": status,
                    "previous_analysis": {
                        "analysis_id": str(previous.id) if previous is not None else None,
                        "instruction_version": (
                            previous.instruction_version if previous is not None else None
                        ),
                    },
                    **_analysis_diagnostics(analysis),
                }
                results.append(result_item)
                _write_json(output_dir / "results" / f"{index:02d}_{interaction.id}.json", result_item)

        statuses: dict[str, int] = {}
        fail_reasons: dict[str, int] = {}
        admitted = 0
        rejected = 0
        scored = 0
        for item in results:
            statuses[item["status"]] = statuses.get(item["status"], 0) + 1
            reason = item.get("fail_reason")
            if reason:
                fail_reasons[str(reason)] = fail_reasons.get(str(reason), 0) + 1
            gate = dict(item.get("llm2_admission_gate") or {})
            if gate.get("admitted") is True:
                admitted += 1
            elif gate.get("admitted") is False:
                rejected += 1
            if int(item.get("score_by_stage_count") or 0) > 0:
                scored += 1

        summary = {
            "status": "dry_run" if args.dry_run else "done",
            "output_dir": str(output_dir),
            "manifest_path": str(output_dir / "manifest.json"),
            "department_id": args.department_id,
            "manager_id": str(manager.id),
            "manager_name": manager.name,
            "date": args.date,
            "instruction_version": args.instruction_version,
            "analysis_candidates": len(interactions),
            "results_count": len(results),
            "statuses": statuses,
            "admitted": admitted,
            "rejected": rejected,
            "scored_with_stage_scores": scored,
            "fail_reasons": fail_reasons,
            "subagent_artifacts": count_subagent_artifacts(artifact_dir / run_id),
            "results": results,
        }
        _write_json(output_dir / "summary.json", summary)
        print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))
        return summary


def main() -> None:
    _run(build_parser().parse_args())


if __name__ == "__main__":
    main()
