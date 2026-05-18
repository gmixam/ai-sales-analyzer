"""Controlled LLM2 A/B runner for persisted call analyses.

This entrypoint is intentionally narrower than the manual reporting runner:
it never discovers sources, never builds missing transcripts, and never sends
reports. It reuses persisted calls/transcripts, stores experimental analyses as
controlled_sample rows, and renders an operator preview from those rows only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.agents.calls.analysis_purpose import (
    ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
    is_controlled_analysis,
    mark_scores_detail_analysis_purpose,
)
from app.agents.calls.analyzer import (
    EXPERIMENTAL_CONTEXT_EVIDENCE_INSTRUCTION_VERSION,
    CallsAnalyzer,
)
from app.agents.calls.orchestrator import analysis_contract_failure_reason
from app.agents.calls.reporting import (
    CallsManualReportingOrchestrator,
    ReportRunFilters,
    resolve_report_delivery_options,
    resolve_report_preset,
)
from app.core_shared.db.models import Analysis, Interaction, Manager
from app.core_shared.db.session import get_db
from app.core_shared.exceptions import ASAError, LLMResponseError, SemanticAnalysisError


DEFAULT_OUTPUT_ROOT = Path("review_packages")


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for controlled LLM2 quality comparison runs."""
    parser = argparse.ArgumentParser(
        description="Run controlled LLM2 v16 analysis and render preview-only report artifacts.",
    )
    parser.add_argument("--department-id", required=True, help="Department UUID")
    parser.add_argument("--date", required=True, help="Report day in YYYY-MM-DD")
    parser.add_argument("--manager-id", help="Manager UUID")
    parser.add_argument("--manager-name", help="Manager name or unique name fragment")
    parser.add_argument(
        "--instruction-version",
        default=EXPERIMENTAL_CONTEXT_EVIDENCE_INSTRUCTION_VERSION,
        help="Experimental LLM2 instruction version to run.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for manifest/result/preview artifacts. Defaults under review_packages/.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit analyzed interactions.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Create fresh controlled_sample rows even when matching rows already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List selected interactions without calling LLM or writing analyses.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Skip LLM calls and render preview from existing controlled_sample rows.",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Run controlled analyses but skip report preview rendering.",
    )
    return parser


def _json_safe(value: Any) -> Any:
    """Return a JSON-serializable copy for local review artifacts."""
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _resolve_manager(db: Session, *, department_id: str, manager_id: str | None, manager_name: str | None) -> Manager:
    if manager_id:
        manager = (
            db.query(Manager)
            .filter(
                Manager.department_id == UUID(department_id),
                Manager.id == UUID(manager_id),
            )
            .first()
        )
        if manager is None:
            raise ASAError(f"Manager not found: {manager_id}")
        return manager
    if not manager_name:
        raise ASAError("Provide --manager-id or --manager-name.")
    needle = _normalize_name(manager_name)
    managers = db.query(Manager).filter(Manager.department_id == UUID(department_id)).all()
    matches = [item for item in managers if needle in _normalize_name(item.name)]
    if not matches:
        raise ASAError(f"Manager name not found: {manager_name}")
    if len(matches) > 1:
        options = ", ".join(f"{item.name} ({item.id})" for item in matches)
        raise ASAError(f"Manager name is ambiguous: {options}")
    return matches[0]


def _default_output_dir(*, manager: Manager, run_date: str, instruction_version: str) -> Path:
    safe_manager = "_".join(manager.name.strip().split()) or str(manager.id)
    safe_version = instruction_version.replace("/", "_").replace(":", "_")
    return DEFAULT_OUTPUT_ROOT / f"llm2_quality_{safe_version}_{run_date}_{safe_manager}"


def _latest_controlled_analysis(
    db: Session,
    *,
    interaction_id: UUID,
    instruction_version: str,
) -> Analysis | None:
    rows = (
        db.query(Analysis)
        .filter(
            Analysis.interaction_id == interaction_id,
            Analysis.instruction_version == instruction_version,
        )
        .order_by(Analysis.created_at.desc())
        .all()
    )
    return next((row for row in rows if is_controlled_analysis(row)), None)


def _persist_controlled_analysis(
    db: Session,
    *,
    interaction: Interaction,
    result: dict[str, Any],
) -> Analysis:
    """Persist one controlled analysis without replacing agreements/insights."""
    marked = mark_scores_detail_analysis_purpose(
        result,
        analysis_purpose=ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        write_default=True,
    )
    forensics = CallsAnalyzer.consume_analysis_forensics(interaction)
    score = dict(marked.get("score") or {})
    checklist_score = dict(score.get("checklist_score") or {})
    summary = dict(marked.get("summary") or {})
    analysis = Analysis(
        id=uuid4(),
        department_id=interaction.department_id,
        interaction_id=interaction.id,
        manager_id=interaction.manager_id,
        instruction_version=str(marked["instruction_version"]),
        score_total=checklist_score.get("score_percent"),
        scores_detail=marked,
        strengths=list(marked.get("strengths") or []),
        weaknesses=list(marked.get("gaps") or []),
        recommendations=list(marked.get("recommendations") or []),
        call_topic=summary.get("call_goal") or summary.get("short_summary"),
        topics=list(marked.get("analytics_tags") or []),
        is_failed=False,
        fail_reason=None,
        raw_llm_response=str(
            forensics.get("raw_llm_response") or json.dumps(marked, ensure_ascii=False)
        ),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def _persist_controlled_failed_analysis(
    db: Session,
    *,
    interaction: Interaction,
    error: LLMResponseError,
    instruction_version: str,
    fail_reason: str | None = None,
) -> Analysis:
    """Persist failed controlled attempt without replacing production derivatives."""
    forensics = CallsAnalyzer.consume_analysis_forensics(interaction)
    normalized_result = dict(
        getattr(error, "normalized_result", None)
        or forensics.get("normalized_result")
        or {}
    )
    if normalized_result:
        normalized_result.setdefault("instruction_version", instruction_version)
    marked = mark_scores_detail_analysis_purpose(
        normalized_result,
        analysis_purpose=ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        write_default=True,
    ) if normalized_result else {
        "instruction_version": instruction_version,
        "analysis_purpose": ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        "meta": {"analysis_purpose": ANALYSIS_PURPOSE_CONTROLLED_SAMPLE},
    }
    checklist_score = dict(dict(marked.get("score") or {}).get("checklist_score") or {})
    summary = dict(marked.get("summary") or {})
    analysis = Analysis(
        id=uuid4(),
        department_id=interaction.department_id,
        interaction_id=interaction.id,
        manager_id=interaction.manager_id,
        instruction_version=instruction_version,
        score_total=checklist_score.get("score_percent"),
        scores_detail=marked,
        strengths=list(marked.get("strengths") or []),
        weaknesses=list(marked.get("gaps") or []),
        recommendations=list(marked.get("recommendations") or []),
        call_topic=summary.get("call_goal") or summary.get("short_summary"),
        topics=list(marked.get("analytics_tags") or []),
        is_failed=True,
        fail_reason=fail_reason or getattr(error, "reason_code", None) or str(error),
        raw_llm_response=str(forensics.get("raw_llm_response") or error.raw_response or ""),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def _interaction_summary(interaction: Interaction) -> dict[str, Any]:
    metadata = dict(interaction.metadata_ or {})
    return {
        "interaction_id": str(interaction.id),
        "external_id": interaction.external_id,
        "manager_id": str(interaction.manager_id) if interaction.manager_id else None,
        "duration_sec": interaction.duration_sec,
        "has_transcript": bool(interaction.text),
        "transcript_chars": len(interaction.text or ""),
        "call_started_at": metadata.get("call_started_at") or metadata.get("started_at"),
        "phone": metadata.get("phone") or metadata.get("client_phone"),
        "extension": metadata.get("extension"),
        "status": interaction.status,
    }


async def _render_preview(
    *,
    db: Session,
    department_id: str,
    manager: Manager,
    run_date: str,
    instruction_version: str,
) -> dict[str, Any]:
    orchestrator = CallsManualReportingOrchestrator(department_id=department_id, db=db)
    preset = resolve_report_preset("manager_daily")
    filters = ReportRunFilters(
        manager_ids={str(manager.id)},
        date_from=run_date,
        date_to=run_date,
        include_controlled_samples=True,
        analysis_instruction_version=instruction_version,
    )
    period = orchestrator._build_period(filters=filters, preset=preset)
    manager_daily_windows = orchestrator._build_manager_daily_windows(anchor_day=period["date_from"])
    source_period = manager_daily_windows[-1].period
    interactions = orchestrator._select_interactions(filters=filters, period=source_period)
    artifacts, build_summary, build_errors = await orchestrator._prepare_artifacts(
        interactions=interactions,
        preset=preset,
        mode="report_from_ready_data_only",
        include_controlled_samples=True,
        analysis_instruction_version=instruction_version,
    )
    reports = orchestrator._group_and_build_reports(
        preset=preset,
        artifacts=artifacts,
        period=period,
        source_period=source_period,
        filters=filters,
        mode="report_from_ready_data_only",
        model_override=None,
        delivery_options=resolve_report_delivery_options(delivery_mode="preview_only"),
        manager_daily_windows=manager_daily_windows,
    )
    return {
        "period": period,
        "source_period": source_period,
        "build_summary": build_summary,
        "build_errors": build_errors,
        "selected_interactions": [_interaction_summary(item) for item in interactions],
        "reports": reports,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    with get_db() as db:
        manager = _resolve_manager(
            db,
            department_id=args.department_id,
            manager_id=args.manager_id,
            manager_name=args.manager_name,
        )
        orchestrator = CallsManualReportingOrchestrator(
            department_id=args.department_id,
            db=db,
        )
        preset = resolve_report_preset("manager_daily")
        filters = ReportRunFilters(
            manager_ids={str(manager.id)},
            date_from=args.date,
            date_to=args.date,
        )
        period = orchestrator._build_period(filters=filters, preset=preset)
        interactions = orchestrator._select_interactions(filters=filters, period=period)
        transcript_interactions = [item for item in interactions if item.text]
        if args.limit is not None:
            transcript_interactions = transcript_interactions[: args.limit]

        output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(
            manager=manager,
            run_date=args.date,
            instruction_version=args.instruction_version,
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "department_id": args.department_id,
            "manager": {
                "id": str(manager.id),
                "name": manager.name,
                "extension": manager.extension,
            },
            "date": args.date,
            "instruction_version": args.instruction_version,
            "analysis_purpose": ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
            "dry_run": bool(args.dry_run),
            "report_only": bool(args.report_only),
            "analyze_only": bool(args.analyze_only),
            "force": bool(args.force),
            "selected_interactions": [_interaction_summary(item) for item in interactions],
            "analysis_candidates": [_interaction_summary(item) for item in transcript_interactions],
        }
        _write_json(output_dir / "manifest.json", manifest)

        analysis_results: list[dict[str, Any]] = []
        if not args.dry_run and not args.report_only:
            for interaction in transcript_interactions:
                existing = None if args.force else _latest_controlled_analysis(
                    db,
                    interaction_id=interaction.id,
                    instruction_version=args.instruction_version,
                )
                if existing is not None:
                    analysis_results.append(
                        {
                            "interaction_id": str(interaction.id),
                            "status": "skipped_existing",
                            "analysis_id": str(existing.id),
                            "is_failed": bool(existing.is_failed),
                            "fail_reason": existing.fail_reason,
                        }
                    )
                    continue
                try:
                    result = orchestrator.analyzer.analyze_call(
                        interaction,
                        instruction_version=args.instruction_version,
                    )
                    analysis = _persist_controlled_analysis(
                        db,
                        interaction=interaction,
                        result=result,
                    )
                    analysis_results.append(
                        {
                            "interaction_id": str(interaction.id),
                            "status": "created",
                            "analysis_id": str(analysis.id),
                            "is_failed": False,
                            "score_total": analysis.score_total,
                        }
                    )
                except SemanticAnalysisError as exc:
                    analysis = _persist_controlled_failed_analysis(
                        db,
                        interaction=interaction,
                        error=exc,
                        instruction_version=args.instruction_version,
                    )
                    analysis_results.append(
                        {
                            "interaction_id": str(interaction.id),
                            "status": "created_failed",
                            "analysis_id": str(analysis.id),
                            "is_failed": True,
                            "fail_reason": analysis.fail_reason,
                        }
                    )
                except LLMResponseError as exc:
                    analysis = _persist_controlled_failed_analysis(
                        db,
                        interaction=interaction,
                        error=exc,
                        instruction_version=args.instruction_version,
                        fail_reason=analysis_contract_failure_reason(exc),
                    )
                    analysis_results.append(
                        {
                            "interaction_id": str(interaction.id),
                            "status": "created_failed",
                            "analysis_id": str(analysis.id),
                            "is_failed": True,
                            "fail_reason": analysis.fail_reason,
                        }
                    )

        preview_result: dict[str, Any] | None = None
        if not args.dry_run and not args.analyze_only:
            preview_result = await _render_preview(
                db=db,
                department_id=args.department_id,
                manager=manager,
                run_date=args.date,
                instruction_version=args.instruction_version,
            )
            _write_json(output_dir / "run_result.json", preview_result)
            for index, report in enumerate(preview_result.get("reports") or [], start=1):
                report_dir = output_dir / f"report_{index:02d}"
                _write_json(report_dir / "report.json", report)
                if report.get("payload") is not None:
                    _write_json(report_dir / "payload.json", report.get("payload"))
                if report.get("preview") is not None:
                    _write_json(report_dir / "preview.json", report.get("preview"))
                    preview = dict(report.get("preview") or {})
                    if preview.get("text"):
                        (report_dir / "report_preview.txt").write_text(
                            str(preview["text"]),
                            encoding="utf-8",
                        )
                    if preview.get("html"):
                        (report_dir / "report_preview.html").write_text(
                            str(preview["html"]),
                            encoding="utf-8",
                        )

        result = {
            "status": "dry_run" if args.dry_run else "done",
            "output_dir": str(output_dir),
            "manifest_path": str(output_dir / "manifest.json"),
            "selected_interactions": len(interactions),
            "analysis_candidates": len(transcript_interactions),
            "analysis_results": analysis_results,
            "preview_written": bool(preview_result is not None),
            "report_count": len((preview_result or {}).get("reports") or []),
            "report_statuses": [
                item.get("status") for item in (preview_result or {}).get("reports") or []
            ],
        }
        _write_json(output_dir / "summary.json", result)
        return result


def main() -> None:
    """Run the CLI and print JSON result."""
    parser = build_parser()
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
