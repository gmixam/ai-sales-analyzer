"""Versioned report templates and bounded HTML/PDF rendering."""

from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ASSET_ROOT = Path(__file__).resolve().parent / "report_template_assets"
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
REPORT_RENDER_GENERATOR_PATH = "app.agents.calls.report_templates.render_report_artifact"
DOCX_SOURCE_OF_TRUTH_PATH = "scripts/generate_docx_report.js"
DOCX_PDF_CONVERSION_PATH = "soffice --headless --convert-to pdf"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReportTemplate:
    """Loaded template assets for one preset/version."""

    preset: str
    version: str
    semantic: dict[str, Any]
    visual: dict[str, Any]
    css: str

    @property
    def template_id(self) -> str:
        if self.version.startswith(f"{self.preset}_template_"):
            return self.version
        return f"{self.preset}:{self.version}"


def get_active_template_version(preset: str) -> str:
    """Return the active version string for one preset."""
    active = json.loads((ASSET_ROOT / "active_versions.json").read_text(encoding="utf-8"))
    return str(active[preset])


def load_report_template(preset: str) -> ReportTemplate:
    """Load repo-local semantic and visual assets for one preset."""
    version = get_active_template_version(preset)
    base = ASSET_ROOT / preset / version
    return ReportTemplate(
        preset=preset,
        version=version,
        semantic=json.loads((base / "semantic.json").read_text(encoding="utf-8")),
        visual=json.loads((base / "visual.json").read_text(encoding="utf-8")),
        css=(base / "layout.css").read_text(encoding="utf-8"),
    )


def _section_meta(template: ReportTemplate, section_id: str) -> dict[str, Any]:
    """Return semantic section metadata by id."""
    return next(
        (item for item in template.semantic.get("sections") or [] if item.get("id") == section_id),
        {"id": section_id, "label": section_id, "kind": "text"},
    )


def render_report_artifact(payload: dict[str, Any], *, prefer_docx_first: bool = False) -> dict[str, Any]:
    """Render one final report artifact from normalized payload and active template assets."""
    template = load_report_template(str(payload["meta"]["preset"]))
    payload.setdefault("meta", {})
    payload["meta"]["report_template"] = {
        "preset": template.preset,
        "version": template.version,
        "template_id": template.template_id,
        "render_variant": f"template_pdf_{template.version}",
        "generator_path": REPORT_RENDER_GENERATOR_PATH,
        "source_of_truth_generator_path": DOCX_SOURCE_OF_TRUTH_PATH,
    }
    report = _build_render_model(payload=payload, template=template)
    text = _render_text_report(report)
    html_doc = _render_html_report(report=report, template=template)
    render_variant = f"template_pdf_{template.version}"
    artifact_extras: dict[str, Any] = {}
    template_extras: dict[str, Any] = {}
    if prefer_docx_first and template.preset == "manager_daily" and template.version == "manager_daily_template_v2":
        pdf_bytes, page_count, render_variant, artifact_extras, template_extras = _render_docx_first_pdf_report(
            payload=payload,
            report=report,
            template=template,
        )
    else:
        pdf_bytes, page_count = _render_pdf_report(report=report, template=template)
    safe_group_key = str(payload["meta"].get("group_key") or template.template_id).replace(":", "_")
    filename = f"{safe_group_key}_{template.version}.pdf"
    subject = str(payload["delivery_meta"]["email_subject"])
    return {
        "subject": subject,
        "text": text,
        "html": html_doc,
        "template": {
            "preset": template.preset,
            "version": template.version,
            "template_id": template.template_id,
            "render_variant": render_variant,
            "generator_path": REPORT_RENDER_GENERATOR_PATH,
            "semantic_asset": f"report_template_assets/{template.preset}/{template.version}/semantic.json",
            "visual_asset": f"report_template_assets/{template.preset}/{template.version}/visual.json",
            "layout_asset": f"report_template_assets/{template.preset}/{template.version}/layout.css",
            "source_of_truth_generator_path": DOCX_SOURCE_OF_TRUTH_PATH,
            **template_extras,
        },
        "artifact": {
            "kind": "pdf_report",
            "filename": filename,
            "media_type": "application/pdf",
            "size_bytes": len(pdf_bytes),
            "page_count": page_count,
            "template_version": template.version,
            "template_id": template.template_id,
            "render_variant": render_variant,
            "generator_path": REPORT_RENDER_GENERATOR_PATH,
            **artifact_extras,
        },
        "pdf_bytes": pdf_bytes,
        "morning_card_text": report.get("morning_card_text"),
    }


def build_report_render_model(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the runtime render model for one normalized payload without rendering bytes."""
    template = load_report_template(str(payload["meta"]["preset"]))
    payload.setdefault("meta", {})
    payload["meta"]["report_template"] = {
        "preset": template.preset,
        "version": template.version,
        "template_id": template.template_id,
        "render_variant": f"template_pdf_{template.version}",
        "generator_path": REPORT_RENDER_GENERATOR_PATH,
    }
    return _build_render_model(payload=payload, template=template)


def _render_docx_first_pdf_report(
    *,
    payload: dict[str, Any],
    report: dict[str, Any],
    template: ReportTemplate,
) -> tuple[bytes, int, str, dict[str, Any], dict[str, Any]]:
    """Build manager_daily PDF from canonical docx source and convert it to PDF."""
    safe_group_key = str(payload["meta"].get("group_key") or template.template_id).replace(":", "_")
    docx_filename = f"{safe_group_key}_{template.version}.docx"
    render_variant = f"template_docx_first_pdf_{template.version}"
    bundle = {
        "payload": payload,
        "report": report,
    }
    with tempfile.TemporaryDirectory(prefix="asa_manager_daily_docx_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        bundle_path = temp_dir / "bundle.json"
        docx_path = temp_dir / docx_filename
        pdf_path = temp_dir / f"{safe_group_key}_{template.version}.pdf"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        docx_bytes = b""
        try:
            _generate_manager_daily_docx(bundle_path=bundle_path, output_path=docx_path)
            docx_bytes = docx_path.read_bytes()
            _convert_docx_to_pdf(docx_path=docx_path, output_dir=temp_dir)
            pdf_bytes = pdf_path.read_bytes()
            page_count = _count_pdf_pages(pdf_bytes)
            artifact_extras = {
                "build_path": "docx_first_pdf_delivery",
                "conversion_path": DOCX_PDF_CONVERSION_PATH,
                "conversion_status": "converted",
                "source_artifact": {
                    "kind": "docx_report",
                    "filename": docx_filename,
                    "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "size_bytes": len(docx_bytes),
                    "generator_path": DOCX_SOURCE_OF_TRUTH_PATH,
                },
            }
            template_extras = {
                "conversion_path": DOCX_PDF_CONVERSION_PATH,
                "conversion_status": "converted",
            }
            return pdf_bytes, page_count, render_variant, artifact_extras, template_extras
        except Exception as exc:
            logger.warning("manager_daily docx-first conversion failed; falling back to runtime PDF: %s", exc)
            pdf_bytes, page_count = _render_pdf_report(report=report, template=template)
            artifact_extras = {
                "build_path": "docx_first_pdf_delivery",
                "conversion_path": DOCX_PDF_CONVERSION_PATH,
                "conversion_status": "fallback_runtime_pdf",
                "conversion_error": str(exc),
                "source_artifact": {
                    "kind": "docx_report",
                    "filename": docx_filename,
                    "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "size_bytes": len(docx_bytes),
                    "generator_path": DOCX_SOURCE_OF_TRUTH_PATH,
                },
            }
            template_extras = {
                "conversion_path": DOCX_PDF_CONVERSION_PATH,
                "conversion_status": "fallback_runtime_pdf",
                "conversion_error": str(exc),
            }
            return pdf_bytes, page_count, render_variant, artifact_extras, template_extras


def _resolve_docx_generator_script() -> Path:
    """Locate the canonical JS docx generator in repo or mounted runtime paths."""
    env_path = os.environ.get("ASA_MANAGER_DAILY_DOCX_SCRIPT")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("/app/report_scripts/generate_docx_report.js"))
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "scripts" / "generate_docx_report.js")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("manager_daily docx generator script is not available in runtime environment")


def _generate_manager_daily_docx(*, bundle_path: Path, output_path: Path) -> None:
    """Generate one canonical manager_daily docx via the approved JS source."""
    node_path = shutil.which("node")
    if not node_path:
        raise RuntimeError("node binary is not available for manager_daily docx generation")
    script_path = _resolve_docx_generator_script()
    env = dict(os.environ)
    node_path_entries = [
        entry
        for entry in (
            env.get("NODE_PATH"),
            "/usr/local/lib/node_modules",
            "/usr/lib/node_modules",
        )
        if entry
    ]
    env["NODE_PATH"] = ":".join(dict.fromkeys(node_path_entries))
    env["VERIFICATION_BUNDLE_PATH"] = str(bundle_path)
    env["DOCX_OUTPUT_PATH"] = str(output_path)
    completed = subprocess.run(
        [node_path, str(script_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    if not output_path.exists():
        raise RuntimeError(f"docx generator did not create expected output file: {output_path}")
    if completed.stderr.strip():
        logger.debug("manager_daily docx generator stderr: %s", completed.stderr.strip())


def _convert_docx_to_pdf(*, docx_path: Path, output_dir: Path) -> None:
    """Convert one docx artifact into PDF using headless LibreOffice."""
    soffice_path = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice_path:
        raise RuntimeError("soffice/libreoffice binary is not available for manager_daily PDF conversion")
    profile_dir = output_dir / "soffice-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            soffice_path,
            "--headless",
            f"-env:UserInstallation={profile_dir.as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(docx_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    pdf_path = output_dir / f"{docx_path.stem}.pdf"
    if not pdf_path.exists():
        raise RuntimeError(f"docx -> pdf conversion did not create expected file: {pdf_path}")
    if completed.stderr.strip():
        logger.debug("manager_daily docx -> pdf stderr: %s", completed.stderr.strip())


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Best-effort page count for already rendered PDF bytes."""
    matches = re.findall(rb"/Type\s*/Page\b", pdf_bytes)
    return max(1, len(matches))


def _build_render_model(*, payload: dict[str, Any], template: ReportTemplate) -> dict[str, Any]:
    """Convert normalized payload into a generic render model for HTML/PDF/text."""
    if template.preset == "manager_daily":
        return _build_manager_daily_model(payload=payload, template=template)
    return _build_rop_weekly_model(payload=payload, template=template)


def _build_manager_daily_model(*, payload: dict[str, Any], template: ReportTemplate) -> dict[str, Any]:
    header = payload["header"]
    kpi = payload["kpi_overview"]
    empty_state = dict(payload.get("empty_state") or {})
    editorial_recommendations = dict(payload.get("editorial_recommendations") or {})
    verification_overrides = dict(payload.get("verification_overrides") or {})
    total_calls = int(kpi.get("calls_count") or 0)
    narrative = _build_manager_daily_narrative_block(payload)
    call_outcomes = dict(payload.get("call_outcomes_summary") or {})
    call_list_raw = list(payload.get("call_list") or [])
    selection_note = _build_manager_daily_selection_note(payload=payload, total_calls=total_calls)
    warm_pipeline = _build_warm_pipeline_data(call_list_raw=call_list_raw, call_outcomes=call_outcomes)
    money_on_table = _build_money_on_table_data(
        call_list_raw=call_list_raw,
        call_outcomes=call_outcomes,
        override=dict(verification_overrides.get("money_on_table") or payload.get("money_on_table") or {}),
    )
    morning_card = _build_morning_card_data(
        header=header,
        call_outcomes=call_outcomes,
        total_calls=total_calls,
        call_list_raw=call_list_raw,
        focus_of_week=dict(payload.get("focus_of_week") or {}),
    )
    challenge = _build_challenge_data(
        score_by_stage=list(payload.get("score_by_stage") or []),
        key_problem=dict(payload.get("key_problem_of_day") or {}),
        total_calls=total_calls,
    )
    outcome_cols = [
        {"label": "ЗВОНКОВ", "value": total_calls, "tone": "neutral"},
        {"label": "ДОГОВОРЕННОСТЬ", "value": _manager_reader_value(call_outcomes.get("agreed_count"), "0"), "tone": "positive"},
        {"label": "ПЕРЕНОС", "value": _manager_reader_value(call_outcomes.get("rescheduled_count"), "0"), "tone": "focus"},
        {"label": "ОТКАЗ", "value": _manager_reader_value(call_outcomes.get("refusal_count"), "0"), "tone": "problem"},
        {"label": "ОТКРЫТ", "value": _manager_reader_value(call_outcomes.get("open_count"), "0"), "tone": "warning"},
        {"label": "ТЕХ/СЕРВИС", "value": _manager_reader_value(call_outcomes.get("tech_service_count"), "0"), "tone": "neutral"},
    ]
    sections = [
        {
            **_section_meta(template, "report_header"),
            "manager_name": header["manager_name"],
            "report_date": header["report_date"],
            "calls_count": total_calls,
            "day_score": _manager_reader_value(_resolve_manager_day_score(payload=payload), "Нет базы"),
            "selection_note": selection_note,
        },
        {
            **_section_meta(template, "day_summary"),
            "outcome_cols": outcome_cols,
        },
        {
            **_section_meta(template, "money_on_table"),
            **money_on_table,
        },
        {
            **_section_meta(template, "warm_pipeline"),
            **warm_pipeline,
        },
        {
            **_section_meta(template, "review_block"),
            "stage_rows": _build_stage_score_rows(payload.get("score_by_stage") or []),
        },
        {
            **_section_meta(template, "main_focus_for_tomorrow"),
            "situation_title": _build_situation_title(payload.get("score_by_stage") or []),
            "body": _build_situation_body(
                key_problem=dict(payload.get("key_problem_of_day") or {}),
                score_by_stage=list(payload.get("score_by_stage") or []),
            ),
            "pattern_count_label": _build_pattern_count_label(dict(payload.get("key_problem_of_day") or {})),
            "client_need": _build_situation_client_need(dict(payload.get("key_problem_of_day") or {})),
            "manager_task": _build_situation_manager_task(
                score_by_stage=list(payload.get("score_by_stage") or []),
                recommendations=list(payload.get("recommendations") or []),
            ),
            "call_example": dict(payload["key_problem_of_day"].get("call_example") or {}),
            "scripts": _build_situation_scripts(
                key_problem=dict(payload.get("key_problem_of_day") or {}),
                recommendations=list(payload.get("recommendations") or []),
                score_by_stage=list(payload.get("score_by_stage") or []),
            ),
            "why_it_works": _build_situation_why_it_works(
                recommendations=list(payload.get("recommendations") or []),
                score_by_stage=list(payload.get("score_by_stage") or []),
            ),
        },
        {
            **_section_meta(template, "call_breakdown"),
            **_build_v5_call_breakdown_section(
                section=dict(payload.get("call_breakdown") or {}),
                recommendations=list(payload.get("recommendations") or []),
            ),
        },
        {
            **_section_meta(template, "voice_of_customer"),
            **_build_v5_voice_of_customer_section(
                section=dict(payload.get("voice_of_customer") or {}),
                recommendations=list(payload.get("recommendations") or []),
            ),
        },
        {
            **_section_meta(template, "additional_situations"),
            **_build_v5_additional_situations_section(
                section=dict(payload.get("additional_situations") or {}),
            ),
        },
        {
            **_section_meta(template, "challenge"),
            **challenge,
        },
        {
            **_section_meta(template, "call_tomorrow"),
            **_build_v5_call_tomorrow_section(
                section=dict(payload.get("call_tomorrow") or {}),
            ),
        },
        {
            **_section_meta(template, "call_list"),
            "columns": ["#", "Время", "Клиент", "Тема", "Контекст", "Статус"],
            "rows": [
                [
                    str(idx + 1),
                    _short_time(row.get("time")),
                    _manager_reader_value(row.get("client_or_phone"), "Клиент не определён"),
                    _call_topic_label(row.get("call_type"), row.get("scenario_type")),
                    _call_context_label(
                        str(row.get("status") or ""),
                        row.get("deadline"),
                        row.get("reason"),
                    ),
                    _call_status_label(row.get("status")),
                ]
                for idx, row in enumerate(call_list_raw)
            ],
            "note": (
                f"Показаны все {len(call_list_raw)} звонков дня."
                if call_list_raw
                else "Звонки за выбранный день не найдены."
            ),
        },
        {
            **_section_meta(template, "morning_card"),
            "greeting": morning_card["greeting"],
            "summary_line": morning_card["summary_line"],
            "open_calls": morning_card["open_calls"],
            "financial_line": money_on_table["highlight_line"],
            "challenge": morning_card["challenge"],
            "call_tomorrow_contacts": list((_build_v5_call_tomorrow_section(section=dict(payload.get("call_tomorrow") or {}))).get("contacts") or [])[:3],
        },
    ]
    return {
        "template": {
            "preset": template.preset,
            "version": template.version,
            "template_id": template.template_id,
        },
        "metadata_line": (
            "Ежедневный отчёт v5 • "
            f"{header['manager_name']} • {header['report_date']} • "
            f"{header['department_name']}"
            + (
                f" • {header['product_or_business_context']}"
                if header.get("product_or_business_context")
                else ""
            )
        ),
        "title": "ЕЖЕДНЕВНЫЙ ОТЧЁТ МЕНЕДЖЕРА",
        "subtitle": f"{header['manager_name']} • {header['report_date']} • {header['department_name']}",
        "hero_focus": empty_state.get("hero_focus")
        or payload["focus_of_week"].get("text")
        or "На этой неделе держим контроль над конкретным следующим шагом в каждом звонке.",
        "summary_cards": [],
        "morning_card_text": morning_card["text"],
        "sections": sections,
        "footer": empty_state.get("footer") or "Конфиденциально · Только для менеджера и РОПа",
        "generation_note": editorial_recommendations.get("text") or narrative["summary"] or "",
    }


def _build_rop_weekly_model(*, payload: dict[str, Any], template: ReportTemplate) -> dict[str, Any]:
    header = payload["header"]
    dynamics = payload["week_over_week_dynamics"]
    rows = payload.get("dashboard_rows") or []
    editorial = dict(payload.get("editorial_summary") or {})
    sections = [
        {
            **_section_meta(template, "what_is_inside"),
            "items": [str(item) for item in payload.get("what_is_inside") or []],
            "coverage_line": f"Команда в отчёте: {len(rows)} менеджеров • период {header['week_label']}",
        },
        {
            **_section_meta(template, "dashboard_rows"),
            "columns": ["Менеджер", "Отдел", "Звонков", "Avg", "Trend", "% strong", "% problem", "Stop", "Signal"],
            "rows": [
                [
                    _value(row.get("manager_name")),
                    _value(row.get("department")),
                    _value(row.get("calls_count")),
                    _value(row.get("average_score")),
                    _value(row.get("trend_label")),
                    _pct_label(row.get("strong_calls_pct")),
                    _pct_label(row.get("problematic_calls_pct")),
                    _pct_label(row.get("stop_flags_pct")),
                    _value(row.get("status_signal")),
                ]
                for row in rows
            ],
        },
        {
            **_section_meta(template, "dashboard_note"),
            "body": _value(
                editorial.get("executive_summary"),
                (
                    "Dashboard signal combines average score, problematic share and stop-flags. "
                    "Use it as the 30-second control snapshot before diving into risk cards."
                ),
            ),
        },
        {
            **_section_meta(template, "week_over_week_dynamics"),
            "columns": ["Менеджер", "Prev", "Current", "Delta", "Trend", "Stage deltas"],
            "rows": [
                [
                    _value(row.get("manager_name")),
                    _value(dynamics.get("previous_period_score")),
                    _value(dynamics.get("current_period_score")),
                    _value(dynamics.get("delta")),
                    _value(dynamics.get("trend")),
                    _value(", ".join(dynamics.get("stage_level_deltas") or []), "n/a"),
                ]
                for row in rows
            ] or [[
                "Команда",
                _value(dynamics.get("previous_period_score")),
                _value(dynamics.get("current_period_score")),
                _value(dynamics.get("delta")),
                _value(dynamics.get("trend")),
                _value(", ".join(dynamics.get("stage_level_deltas") or []), "n/a"),
            ]],
        },
        {
            **_section_meta(template, "dynamics_lists"),
            "left_title": "Лучшие изменения",
            "right_title": "Тревожные изменения",
            "left_items": [_value(dynamics.get("best_dynamics_commentary"))],
            "right_items": [
                _value(editorial.get("team_risks_wording"))
                if editorial.get("team_risks_wording")
                else _value(dynamics.get("alarming_dynamics_commentary"))
            ],
        },
        {
            **_section_meta(template, "risk_zone_cards"),
            "cards": [
                {
                    "title": item["manager_name"],
                    "body": f"{item['department']} • звонков {item['calls_count']} • средний балл {item['average_score']}",
                    "items": [
                        f"Проблема: {_value(item.get('core_problem_statement'))}",
                        f"Действие для РОПа: {_value(item.get('action_for_rop'))}",
                        "Этапы P2: " + (
                            ", ".join(
                                f"{_value(snapshot.get('label'))}: {_value(snapshot.get('signal'))}"
                                for snapshot in item.get("stage_profile_snapshot") or []
                            ) or "not available"
                        ),
                    ],
                    "tone": "risk",
                }
                for item in payload.get("risk_zone_cards") or []
            ] or [{"title": "Зон риска нет", "body": "В текущей выборке нет менеджеров с immediate-risk profile.", "items": [], "tone": "risk"}],
        },
        {
            **_section_meta(template, "systemic_team_problems"),
            "cards": [
                {
                    "title": item["problem_title"],
                    "body": item["explanation"],
                    "items": [
                        f"{_value(item.get('affected_managers_count'))} из {max(1, len(rows))} менеджеров",
                        f"Действие: {_value(item.get('recommended_systemic_action'))}",
                        f"Timing: {_value(item.get('timing_note'))}",
                    ],
                    "tone": "system",
                }
                for item in payload.get("systemic_team_problems") or []
            ] or [{"title": "Нет системных проблем", "body": "Командных повторяющихся проблем не выявлено.", "items": [], "tone": "system"}],
        },
        {
            **_section_meta(template, "top_vs_anti_top"),
            "left_title": "Лучший период",
            "right_title": "Требует внимания",
            "left_card": {
                "title": _value(payload["top_block"].get("manager"), "Нет данных"),
                "body": _value(payload["top_block"].get("interpretation")),
                "items": [
                    f"Метрики: {_compact_metrics(payload['top_block'].get('supporting_metrics') or {})}",
                    f"Рекомендация РОПу: {_value(payload['top_block'].get('recommendation_to_rop'))}",
                ],
            },
            "right_card": {
                "title": _value(payload["anti_top_block"].get("manager"), "Нет данных"),
                "body": _value(payload["anti_top_block"].get("interpretation")),
                "items": [
                    f"Метрики: {_compact_metrics(payload['anti_top_block'].get('supporting_metrics') or {})}",
                    f"Рекомендация РОПу: {_value(payload['anti_top_block'].get('recommendation_to_rop'))}",
                ],
            },
        },
        {
            **_section_meta(template, "rop_tasks_next_week"),
            "columns": ["Кому", "Приоритет", "Задача", "Проверка", "Deadline"],
            "rows": [
                [
                    _value(item.get("manager")),
                    _value(item.get("priority")),
                    _value(item.get("task_for_next_week")),
                    _value(item.get("how_to_verify")),
                    _value(item.get("deadline")),
                ]
                for item in payload.get("rop_tasks_next_week") or []
            ],
            "note": _value(editorial.get("rop_tasks_wording"), None),
        },
        {
            **_section_meta(template, "business_results_placeholder"),
            "body": _value(
                editorial.get("final_managerial_commentary"),
                (
                    "CRM/business-results block stays present even when data is absent. "
                    f"Status: {_value(payload['business_results_placeholder'].get('status'))}. "
                    f"Reason: {_value(payload['business_results_placeholder'].get('reason'))}."
                ),
            ),
        },
    ]
    return {
        "template": {
            "preset": template.preset,
            "version": template.version,
            "template_id": template.template_id,
        },
        "metadata_line": (
            f"Еженедельный отчёт • {header['week_label']} • {header['department_name']} • "
            f"{_value(header.get('confidentiality_note'))}"
        ),
        "title": "ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ",
        "subtitle": "Качество звонков · Зоны риска · Задачи на неделю",
        "hero_context": f"{header['department_name']} • {header['week_label']}",
        "summary_cards": [],
        "sections": sections,
        "footer": "Конфиденциально. Только для РОП и руководства.",
        "generation_note": (
            f"Собрано из normalized payload. Template {template.template_id}. "
            f"Generated at {payload['meta'].get('generated_at')}."
        ),
    }


def _render_text_report(report: dict[str, Any]) -> str:
    """Render a readable plain-text report from the generic render model."""
    lines = [report["metadata_line"], report["title"], report["subtitle"], ""]
    if report.get("summary_cards"):
        lines.append("Ключевые показатели:")
        lines.extend([f"- {item['label']}: {_value(item.get('value'))}" for item in report["summary_cards"]])
        lines.append("")
    for section in report["sections"]:
        lines.append(section["label"])
        lines.append("-" * len(section["label"]))
        lines.extend(_section_to_text_lines(section))
        lines.append("")
    lines.append(report["footer"])
    if report.get("generation_note"):
        lines.append(report["generation_note"])
    return "\n".join(lines).strip()


def _section_to_text_lines(section: dict[str, Any]) -> list[str]:
    """Render one section as text lines."""
    kind = section["kind"]
    if kind == "header_card":
        lines = [
            f"Менеджер: {section.get('manager_name') or '—'}",
            f"Дата: {section.get('report_date') or '—'}",
            f"Звонков: {_value(section.get('calls_count'))}",
            f"Балл дня: {_value(section.get('day_score'))} / 5",
        ]
        if section.get("selection_note"):
            lines.append(str(section["selection_note"]))
        return lines
    if kind == "outcome_table":
        return [f"- {item['label']}: {_value(item.get('value'))}" for item in section.get("outcome_cols") or []]
    if kind == "money_focus":
        lines = [
            str(section.get("body") or "Открытых возможностей на выбранной выборке не найдено."),
            str(section.get("highlight_line") or ""),
            str(section.get("reason_line") or ""),
            str(section.get("note") or ""),
        ]
        return [line for line in lines if line]
    if kind == "pipeline_summary":
        lines = [
            str(section.get("summary_line") or "Тёплые лиды не выделены."),
            str(section.get("counts_line") or ""),
            str(section.get("conversion_line") or ""),
            str(section.get("average_line") or ""),
        ]
        if section.get("contacts"):
            lines.append("Тёплые лиды без обратного звонка:")
            lines.extend(
                [
                    f"- {item.get('client') or 'Клиент'} | {item.get('phone') or '—'} | {item.get('status') or '—'}"
                    for item in section.get("contacts") or []
                ]
            )
        return [line for line in lines if line]
    if kind == "stage_scores_table":
        lines = ["Этап | Сегодня | Среднее | Шкала | Приоритет"]
        for row in section.get("stage_rows") or []:
            lines.append(
                " | ".join(
                    [
                        f"{row.get('funnel_label', '')} {row.get('stage_name', '')}".strip(),
                        str(row.get("score", "—")),
                        "—",
                        str(row.get("bar_text") or "—"),
                        "●" if row.get("is_priority") else ("✓" if row.get("bar_pct", 0) >= 80 else "—"),
                    ]
                )
            )
            for crit in row.get("criteria_detail") or []:
                lines.append(
                    f"  - {crit.get('name') or 'Критерий'}: {crit.get('score') or '—'}"
                )
        if section.get("note"):
            lines.append(str(section["note"]))
        return lines
    if kind == "situation_card":
        lines = [
            str(section.get("situation_title") or section.get("label") or "Ситуация дня"),
            str(section.get("body") or ""),
            f"Что хотел клиент: {section.get('client_need') or 'Нет данных'}",
            f"Наша задача: {section.get('manager_task') or 'Нет данных'}",
        ]
        example = dict(section.get("call_example") or {})
        if example.get("client_label") or example.get("time_label"):
            lines.append(
                f"Пример из сегодня: {example.get('client_label') or 'Клиент'} · {example.get('time_label') or '—'}"
            )
        if example.get("reason_short"):
            lines.append(str(example["reason_short"]))
        if section.get("scripts"):
            lines.append("Варианты речёвок:")
            lines.extend([f"- {item}" for item in section.get("scripts") or []])
        if section.get("why_it_works"):
            lines.append(f"Почему работает: {section.get('why_it_works')}")
        return [line for line in lines if line]
    if kind == "call_breakdown":
        lines = [str(section.get("summary_line") or "Разбор звонка")]
        rows = section.get("rows") or []
        if rows:
            lines.append("Момент | Что было | Что лучше")
            lines.extend([" | ".join(_value(cell) for cell in row) for row in rows])
        else:
            lines.append("—")
        return lines
    if kind == "voice_of_customer":
        lines = []
        if section.get("intro"):
            lines.append(str(section["intro"]))
        rows = section.get("rows") or []
        if rows:
            lines.append("Паттерн | Подтверждающие цитаты | Смысл → Как ответить")
            lines.extend([" | ".join(_value(cell) for cell in row) for row in rows])
        else:
            lines.append("—")
        return lines
    if kind == "expanded_situations":
        lines = []
        for item in section.get("situations") or []:
            lines.extend(
                [
                    f"{item.get('badge') or 'Ситуация'}: {item.get('title') or '—'}",
                    f"Что сказал клиент: {item.get('client_said') or '—'}",
                    f"Что имел в виду: {item.get('meant') or '—'}",
                    f"Как надо было: {item.get('how_to') or '—'}",
                    f"Почему так: {item.get('why') or '—'}",
                    "",
                ]
            )
        return lines[:-1] if lines else ["—"]
    if kind == "challenge_card":
        return [
            str(section.get("goal_line") or "Челлендж не определён."),
            str(section.get("today_line") or ""),
            str(section.get("record_line") or ""),
            f"Фраза для завтра: {section.get('phrase_line') or 'Нет данных'}",
        ]
    if kind == "call_tomorrow":
        rows = section.get("rows") or []
        if rows:
            return ["Приоритет | Клиент | Срок/повод | Цель звонка | Первая фраза"] + [
                " | ".join(_value(cell) for cell in row) for row in rows
            ]
        return ["Нет открытых контактов для перезвона."]
    if kind == "morning_card":
        lines = [
            str(section.get("greeting") or ""),
            str(section.get("summary_line") or ""),
        ]
        if section.get("financial_line"):
            lines.append(str(section["financial_line"]))
        if section.get("call_tomorrow_contacts"):
            lines.append("Позвони сегодня:")
            lines.extend(
                [
                    f"- {item.get('client_label') or 'Клиент'} — {item.get('opening_script') or 'Скрипт не задан'}"
                    for item in section.get("call_tomorrow_contacts") or []
                ]
            )
        if section.get("challenge"):
            lines.append(f"Челлендж: {section.get('challenge')}")
        return [line for line in lines if line]
    if kind in {"text", "callout", "placeholder"}:
        result = [str(section.get("body") or "—")]
        if section.get("reinforcement"):
            result.append(str(section["reinforcement"]))
        if section.get("progress_line"):
            result.append(str(section["progress_line"]))
        if section.get("note"):
            result.append(str(section["note"]))
        return result
    if kind == "orientation_box":
        lines = [f"- {item}" for item in section.get("items") or []]
        if section.get("coverage_line"):
            lines.append(section["coverage_line"])
        return lines
    if kind == "card":
        lines: list[str] = []
        if section.get("title"):
            lines.append(str(section["title"]))
        if section.get("body"):
            lines.append(str(section["body"]))
        lines.extend([f"- {item}" for item in section.get("items") or []])
        return lines or ["—"]
    if kind == "cards":
        lines = []
        if section.get("editorial_note"):
            lines.append(str(section["editorial_note"]))
            lines.append("")
        for card in section.get("cards") or []:
            lines.append(str(card.get("title") or "Карточка"))
            if card.get("body"):
                lines.append(str(card["body"]))
            lines.extend([f"- {item}" for item in card.get("items") or []])
            lines.append("")
        return lines[:-1] if lines else ["—"]
    if kind == "paired_bullets":
        return [
            str(section.get("left_title") or "Левая колонка"),
            *[f"- {item}" for item in section.get("left_items") or ["—"]],
            str(section.get("right_title") or "Правая колонка"),
            *[f"- {item}" for item in section.get("right_items") or ["—"]],
        ]
    if kind == "paired_cards":
        left = section.get("left_card") or {}
        right = section.get("right_card") or {}
        return [
            str(section.get("left_title") or "Левый блок"),
            str(left.get("title") or "—"),
            str(left.get("body") or "—"),
            *[f"- {item}" for item in left.get("items") or []],
            str(section.get("right_title") or "Правый блок"),
            str(right.get("title") or "—"),
            str(right.get("body") or "—"),
            *[f"- {item}" for item in right.get("items") or []],
        ]
    if kind == "metric_cards":
        metrics = section.get("metrics") or []
        lines = [f"- {item['label']}: {_value(item.get('value'))}" for item in metrics]
        if section.get("note"):
            lines.append(str(section["note"]))
        return lines
    if kind == "bullet_list":
        return [f"- {item}" for item in section.get("items") or ["—"]]
    if kind == "bullet_groups":
        lines = []
        for group in section.get("groups") or []:
            lines.append(str(group.get("title") or "Группа"))
            lines.extend([f"- {item}" for item in group.get("items") or ["—"]])
        return lines
    if kind == "table":
        rows = section.get("rows") or []
        header = " | ".join(section.get("columns") or [])
        lines = [header] + [" | ".join(_value(cell) for cell in row) for row in rows]
        if section.get("note"):
            lines.append(str(section["note"]))
        return lines
    if kind == "key_values":
        lines = [f"- {label}: {_value(value)}" for label, value in section.get("pairs") or []]
        if section.get("interpretation"):
            lines.append(str(section["interpretation"]))
        if section.get("note"):
            lines.append(str(section["note"]))
        return lines
    return ["—"]


def _render_html_report(*, report: dict[str, Any], template: ReportTemplate) -> str:
    """Render HTML from the generic report model and visual asset."""
    if template.preset == "manager_daily" and template.version == "manager_daily_template_v2":
        return _render_manager_daily_html_report(report=report, template=template)
    sections_html = "".join(_render_html_section(section) for section in report["sections"])
    metadata_html = (
        f"<div class=\"metadata-line\"><span>{html.escape(report['metadata_line'])}</span></div>"
    )
    hero_html = (
        "<section class=\"title-page\">"
        f"<h1>{html.escape(report['title'])}</h1>"
        f"<p class=\"subtitle\">{html.escape(report['subtitle'])}</p>"
        "<div class=\"divider\"></div>"
        f"<p>{html.escape(report.get('hero_focus') or report.get('hero_context') or '')}</p>"
        "</section>"
    )
    return (
        "<html><head><meta charset=\"utf-8\">"
        f"<style>{template.css}</style>"
        "</head><body>"
        "<main class=\"page\">"
        f"{metadata_html}"
        f"{hero_html}"
        f"{sections_html}"
        f"<div class=\"footer-note\"><span>{html.escape(report['footer'])}</span></div>"
        "</main></body></html>"
    )


def _render_manager_daily_html_report(*, report: dict[str, Any], template: ReportTemplate) -> str:
    """Render manager_daily in the approved v5 block order."""
    sections = {section["id"]: section for section in report["sections"]}
    page_groups = [
        ["report_header", "day_summary", "money_on_table", "warm_pipeline"],
        ["review_block", "main_focus_for_tomorrow"],
        ["call_breakdown", "voice_of_customer"],
        ["additional_situations", "challenge"],
        ["call_tomorrow"],
        ["call_list"],
        ["morning_card"],
    ]
    pages_html: list[str] = []
    for page_number, page_group in enumerate(page_groups, start=1):
        body_parts = []
        if page_number == 1:
            body_parts.append(
                "<section class=\"hero\">"
                f"<div class=\"hero-title\">{html.escape(report['title'])}"
                f"<span class=\"hero-sub\">· {html.escape(report['subtitle'])}</span></div>"
                f"<div class=\"focus-week\">{html.escape(report.get('hero_focus') or '')}</div>"
                "</section>"
            )
        body_parts.extend(_render_html_section(sections[section_id]) for section_id in page_group if section_id in sections)
        pages_html.append(
            "<section class=\"page\">"
            f"{_manager_daily_page_header(report['metadata_line'])}"
            f"{''.join(body_parts)}"
            f"{_manager_daily_page_footer(report['footer'], page_number)}"
            "</section>"
        )
    return (
        "<html><head><meta charset=\"utf-8\">"
        f"<style>{template.css}</style>"
        "</head><body><div class=\"workspace\">"
        f"{''.join(pages_html)}"
        "</div></body></html>"
    )


def _render_html_section(section: dict[str, Any]) -> str:
    """Render one HTML section."""
    kind = section["kind"]
    title = f"<div class=\"section-bar\">{html.escape(section['label'])}</div>"
    classes = ["section"]
    if section.get("page_break_before"):
        classes.append("page-break")
    if section["id"] == "risk_zone_cards":
        title = f"<div class=\"section-bar risk\">{html.escape(section['label'])}</div>"
    if section["id"] == "business_results_placeholder":
        title = f"<div class=\"section-bar business\">{html.escape(section['label'])}</div>"
    if kind == "header_card":
        selection_note = (
            f"<div class=\"header-selection-note\">{html.escape(str(section['selection_note']))}</div>"
            if section.get("selection_note") else ""
        )
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
            "<article class=\"header-card\">"
            f"<div class=\"header-manager\">{html.escape(str(section.get('manager_name') or '—'))}</div>"
            f"<div class=\"header-meta\">{html.escape(str(section.get('report_date') or '—'))} · "
            f"{html.escape(_value(section.get('calls_count')))} звонков</div>"
            f"<div class=\"header-score\">Балл дня: {html.escape(_value(section.get('day_score')))} / 5</div>"
            f"{selection_note}</article></div></section>"
        )
    if kind == "outcome_table":
        header = "".join(
            (
                f"<td class=\"outcome-cell {_outcome_col_class(item)}\">"
                f"<div class=\"outcome-value\">{html.escape(_manager_reader_value(item.get('value'), '—'))}</div>"
                f"<div class=\"outcome-label\">{html.escape(str(item['label']))}</div>"
                "</td>"
            )
            for item in section.get("outcome_cols") or []
        )
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><table class=\"outcome-table\"><tbody><tr>{header}</tr></tbody></table></div></section>"
    if kind == "money_focus":
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><article class=\"focus-panel warning\">"
            f"<p>{html.escape(str(section.get('body') or ''))}</p>"
            f"<p><strong>{html.escape(str(section.get('highlight_line') or ''))}</strong></p>"
            f"<p>{html.escape(str(section.get('reason_line') or ''))}</p>"
            f"<p class=\"muted\">{html.escape(str(section.get('note') or ''))}</p>"
            "</article></div></section>"
        )
    if kind == "pipeline_summary":
        contacts = "".join(
            f"<tr><td>{html.escape(str(item.get('client') or '—'))}</td><td>{html.escape(str(item.get('phone') or '—'))}</td><td>{html.escape(str(item.get('status') or '—'))}</td></tr>"
            for item in section.get("contacts") or []
        ) or "<tr><td colspan=\"3\">Тёплые лиды без обратного звонка не найдены.</td></tr>"
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
            f"<p>{html.escape(str(section.get('summary_line') or ''))}</p>"
            f"<p>{html.escape(str(section.get('counts_line') or ''))}</p>"
            f"<p><strong>{html.escape(str(section.get('conversion_line') or ''))}</strong></p>"
            f"<p class=\"muted\">{html.escape(str(section.get('average_line') or ''))}</p>"
            "<table><thead><tr><th>Клиент</th><th>Телефон</th><th>Статус</th></tr></thead>"
            f"<tbody>{contacts}</tbody></table></div></section>"
        )
    if kind == "stage_scores_table":
        rows = []
        for row in section.get("stage_rows") or []:
            rows.append(
                "<tr>"
                f"<td>{html.escape((str(row.get('funnel_label') or '') + ' ' + str(row.get('stage_name') or '')).strip())}</td>"
                f"<td>{html.escape(str(row.get('score') or '—'))}</td>"
                "<td>—</td>"
                f"<td>{html.escape(str(row.get('bar_text') or '—'))}</td>"
                f"<td>{'●' if row.get('is_priority') else ('✓' if row.get('bar_pct', 0) >= 80 else '—')}</td>"
                "</tr>"
            )
            for crit in row.get("criteria_detail") or []:
                rows.append(
                    "<tr class=\"sub-row\">"
                    f"<td colspan=\"5\">{html.escape(str(crit.get('name') or 'Критерий'))}: {html.escape(str(crit.get('score') or '—'))}</td>"
                    "</tr>"
                )
        body = "".join(rows) or "<tr><td colspan=\"5\">Данные по этапам появятся после накопления базы.</td></tr>"
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
            "<table><thead><tr><th>Этап</th><th>Сегодня</th><th>Среднее</th><th>Шкала</th><th>Приоритет</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div></section>"
        )
    if kind == "situation_card":
        scripts = "".join(f"<li>{html.escape(str(item))}</li>" for item in section.get("scripts") or [])
        example = dict(section.get("call_example") or {})
        example_html = (
            "<div class=\"mini-card\">"
            f"<strong>Пример из сегодня:</strong> {html.escape(str(example.get('client_label') or 'Клиент'))} · {html.escape(str(example.get('time_label') or '—'))}"
            + (
                f"<div class=\"muted\">{html.escape(str(example.get('reason_short') or ''))}</div>"
                if example.get("reason_short") else ""
            )
            + "</div>"
            if example.get("client_label") or example.get("time_label")
            else ""
        )
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><article class=\"focus-panel\">"
            f"<h3>{html.escape(str(section.get('situation_title') or section.get('label') or 'СИТУАЦИЯ ДНЯ'))}</h3>"
            f"<p>{html.escape(str(section.get('body') or ''))}</p>"
            f"<p><strong>Что хотел клиент:</strong> {html.escape(str(section.get('client_need') or 'Нет данных'))}</p>"
            f"<p><strong>Наша задача:</strong> {html.escape(str(section.get('manager_task') or 'Нет данных'))}</p>"
            f"{example_html}"
            "<div class=\"mini-card\"><strong>Варианты речёвок</strong><ol>"
            f"{scripts}</ol></div>"
            f"<p><strong>Почему работает:</strong> {html.escape(str(section.get('why_it_works') or ''))}</p>"
            "</article></div></section>"
        )
    if kind == "call_breakdown":
        rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(_value(cell))}</td>" for cell in row) + "</tr>"
            for row in section.get("rows") or []
        )
        intro = (
            f"<p class=\"muted\">{html.escape(str(section.get('summary_line') or ''))}</p>"
            if section.get("summary_line") else ""
        )
        if not rows:
            return (
                f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">{intro}"
                "<p class=\"muted\">Недостаточно данных для детального разбора звонка.</p>"
                "</div></section>"
            )
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">{intro}"
            "<table><thead><tr><th>Момент</th><th>Что было</th><th>Что лучше</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    if kind == "voice_of_customer":
        intro = (
            f"<p class=\"muted\">{html.escape(str(section.get('intro') or ''))}</p>"
            if section.get("intro") else ""
        )
        rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(_value(cell))}</td>" for cell in row) + "</tr>"
            for row in section.get("rows") or []
        )
        if not rows:
            return (
                f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">{intro}"
                "<p class=\"muted\">Клиентские цитаты появятся после накопления материала по звонкам.</p>"
                "</div></section>"
            )
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">{intro}"
            "<table><thead><tr><th>Паттерн</th><th>Подтверждающие цитаты</th><th>Смысл → Как ответить</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    if kind == "expanded_situations":
        cards = "".join(
            "<article class=\"card\">"
            f"<h3>{html.escape(str(item.get('badge') or 'Ситуация'))} · {html.escape(str(item.get('title') or '—'))}</h3>"
            f"<p><strong>Что сказал клиент:</strong> {html.escape(str(item.get('client_said') or '—'))}</p>"
            f"<p><strong>Что имел в виду:</strong> {html.escape(str(item.get('meant') or '—'))}</p>"
            f"<p><strong>Как надо было:</strong> {html.escape(str(item.get('how_to') or '—'))}</p>"
            f"<p><strong>Почему так:</strong> {html.escape(str(item.get('why') or '—'))}</p>"
            "</article>"
            for item in section.get("situations") or []
        )
        if not cards:
            return (
                f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
                "<p class=\"muted\">Дополнительные ситуации появятся после накопления данных по звонкам.</p>"
                "</div></section>"
            )
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><div class=\"cards-grid\">{cards}</div></div></section>"
    if kind == "challenge_card":
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><article class=\"focus-panel\">"
            f"<p><strong>{html.escape(str(section.get('goal_line') or ''))}</strong></p>"
            f"<p>{html.escape(str(section.get('today_line') or ''))}</p>"
            f"<p>{html.escape(str(section.get('record_line') or ''))}</p>"
            f"<p><strong>Фраза для завтра:</strong> {html.escape(str(section.get('phrase_line') or ''))}</p>"
            "</article></div></section>"
        )
    if kind == "call_tomorrow":
        rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(_value(cell))}</td>" for cell in row) + "</tr>"
            for row in section.get("rows") or []
        )
        if not rows:
            return (
                f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
                "<p class=\"muted\">Нет открытых контактов для перезвона.</p>"
                "</div></section>"
            )
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
            "<table><thead><tr><th>Приоритет</th><th>Клиент</th><th>Срок/повод</th><th>Цель звонка</th><th>Первая фраза</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    if kind == "morning_card":
        calls = "".join(
            f"<li>{html.escape(str(item.get('client_label') or 'Клиент'))} — {html.escape(str(item.get('opening_script') or 'Скрипт не задан'))}</li>"
            for item in section.get("call_tomorrow_contacts") or []
        ) or "".join(
            f"<li>{html.escape(str(call.get('time', '—')))} · {html.escape(str(call.get('client', '—')))} · {html.escape(str(call.get('status', '—')))}</li>"
            for call in section.get("open_calls") or []
        ) or "<li>Открытых звонков нет.</li>"
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><article class=\"focus-panel\">"
            f"<h3>{html.escape(str(section.get('greeting') or ''))}</h3>"
            f"<p>{html.escape(str(section.get('summary_line') or ''))}</p>"
            + (
                f"<p><strong>{html.escape(str(section.get('financial_line') or ''))}</strong></p>"
                if section.get("financial_line") else ""
            )
            + "<p><strong>Позвони сегодня:</strong></p>"
            + f"<ul>{calls}</ul>"
            + f"<p><strong>Челлендж:</strong> {html.escape(str(section.get('challenge') or ''))}</p>"
            + "</article></div></section>"
        )
    if kind in {"text", "callout", "placeholder"}:
        note = (
            f"<p class=\"muted\">{html.escape(str(section['note']))}</p>"
            if section.get("note")
            else ""
        )
        reinforcement = (
            f"<p><strong>{html.escape(str(section['reinforcement']))}</strong></p>"
            if section.get("reinforcement")
            else ""
        )
        body_class = (
            "placeholder-card" if kind == "placeholder"
            else "focus-banner" if section.get("tone") == "focus" or kind == "callout"
            else "note-box"
        )
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><div class=\"{body_class}\"><p>{html.escape(str(section.get('body') or '—'))}</p>{reinforcement}{note}</div></div></section>"
    if kind == "orientation_box":
        items = "".join(f"<li>{html.escape(str(item))}</li>" for item in section.get("items") or [])
        coverage = f"<p class=\"coverage-line\">{html.escape(str(section.get('coverage_line') or ''))}</p>"
        return f"<section class=\"{' '.join(classes)}\"><div class=\"orientation-box\"><h2>{html.escape(section['label'])}</h2><ul>{items}</ul>{coverage}</div></section>"
    if kind == "card":
        items = "".join(f"<li>{html.escape(str(item))}</li>" for item in section.get("items") or [])
        body = f"<p>{html.escape(str(section.get('body')))}</p>" if section.get("body") else ""
        card_title = f"<h3>{html.escape(str(section.get('title') or '—'))}</h3>" if section.get("title") else ""
        card_class = "problem-card" if section.get("tone") == "problem" else "signal-card" if section.get("tone") == "positive" else "card"
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><article class=\"{card_class}\">{card_title}{body}<ul>{items}</ul></article></div></section>"
    if kind == "cards":
        cards = []
        for card in section.get("cards") or []:
            items = "".join(f"<li>{html.escape(str(item))}</li>" for item in card.get("items") or [])
            card_class = "risk-card" if card.get("tone") == "risk" else "system-card" if card.get("tone") == "system" else "card"
            cards.append(
                f"<article class=\"{card_class}\">"
                f"<h3>{html.escape(str(card.get('title') or 'Карточка'))}</h3>"
                f"<p>{html.escape(str(card.get('body') or ''))}</p>"
                f"<ul>{items}</ul>"
                "</article>"
            )
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><div class=\"cards-grid\">{''.join(cards)}</div></div></section>"
    if kind == "paired_bullets":
        left = "".join(f"<li>{html.escape(str(item))}</li>" for item in section.get("left_items") or ["—"])
        right = "".join(f"<li>{html.escape(str(item))}</li>" for item in section.get("right_items") or ["—"])
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><div class=\"paired-grid\">"
            f"<article class=\"paired-col positive\"><h3>{html.escape(str(section.get('left_title') or 'Левый блок'))}</h3><ul>{left}</ul></article>"
            f"<article class=\"paired-col risk\"><h3>{html.escape(str(section.get('right_title') or 'Правый блок'))}</h3><ul>{right}</ul></article>"
            "</div></div></section>"
        )
    if kind == "paired_cards":
        left = section.get("left_card") or {}
        right = section.get("right_card") or {}
        left_items = "".join(f"<li>{html.escape(str(item))}</li>" for item in left.get("items") or [])
        right_items = "".join(f"<li>{html.escape(str(item))}</li>" for item in right.get("items") or [])
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><div class=\"paired-grid\">"
            f"<article class=\"card best-card\"><h3>{html.escape(str(section.get('left_title') or 'Лучший блок'))}</h3><h4>{html.escape(str(left.get('title') or '—'))}</h4><p>{html.escape(str(left.get('body') or ''))}</p><ul>{left_items}</ul></article>"
            f"<article class=\"card anti-card\"><h3>{html.escape(str(section.get('right_title') or 'Блок внимания'))}</h3><h4>{html.escape(str(right.get('title') or '—'))}</h4><p>{html.escape(str(right.get('body') or ''))}</p><ul>{right_items}</ul></article>"
            "</div></div></section>"
        )
    if kind == "metric_cards":
        metrics = section.get("metrics") or []
        cards = "".join(
            (
                f"<article class=\"metric {html.escape(str(item.get('tone') or ''))}\">"
                f"<strong>{html.escape(str(item['label']))}</strong>"
                f"<span>{html.escape(_value(item.get('value')))}</span>"
                "</article>"
            )
            for item in metrics
        )
        note = (
            f"<p class=\"muted\">{html.escape(str(section['note']))}</p>"
            if section.get("note")
            else ""
        )
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><div class=\"summary-grid\">{cards}</div>{note}</div></section>"
    if kind == "bullet_list":
        items = "".join(f"<li>{html.escape(str(item))}</li>" for item in section.get("items") or ["—"])
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><ul>{items}</ul></div></section>"
    if kind == "bullet_groups":
        groups_html = []
        for group in section.get("groups") or []:
            items = "".join(f"<li>{html.escape(str(item))}</li>" for item in group.get("items") or ["—"])
            groups_html.append(
                "<article class=\"card\">"
                f"<h3>{html.escape(str(group.get('title') or 'Группа'))}</h3>"
                f"<ul>{items}</ul>"
                "</article>"
            )
        memo_class = "memo-page" if section.get("page_break_before") else ""
        return f"<section class=\"{' '.join(classes)} {memo_class}\">{title}<div class=\"section-body\"><div class=\"cards-grid\">{''.join(groups_html)}</div></div></section>"
    if kind == "table":
        header = "".join(f"<th>{html.escape(str(item))}</th>" for item in section.get("columns") or [])
        rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(_value(cell))}</td>" for cell in row) + "</tr>"
            for row in section.get("rows") or []
        )
        note = (
            f"<p class=\"call-table-note\">{html.escape(str(section['note']))}</p>"
            if section.get("note")
            else ""
        )
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>{note}</div></section>"
    if kind == "key_values":
        items = "".join(
            (
                "<article class=\"metric\">"
                f"<strong>{html.escape(str(label))}</strong>"
                f"<span>{html.escape(_value(value))}</span>"
                "</article>"
            )
            for label, value in section.get("pairs") or []
        )
        note = (
            f"<p class=\"muted\">{html.escape(str(section['note']))}</p>"
            if section.get("note")
            else ""
        )
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><div class=\"summary-grid\">{items}</div>{note}</div></section>"
    return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><p>—</p></div></section>"


def _render_pdf_report(*, report: dict[str, Any], template: ReportTemplate) -> tuple[bytes, int]:
    """Render a bounded PDF report with embedded Unicode font."""
    font = _TrueTypeFont(FONT_PATH)
    theme = template.visual["theme"]
    accent = tuple(_hex_to_rgb(theme.get("dark_blue") or theme.get("accent")))
    muted = tuple(_hex_to_rgb(theme["muted"]))
    black = tuple(_hex_to_rgb(theme["ink"]))
    green = tuple(_hex_to_rgb(theme.get("green", "#2f8b57")))
    amber = tuple(_hex_to_rgb(theme.get("amber", "#c58a1d")))
    red = tuple(_hex_to_rgb(theme.get("red", "#bf4c4c")))
    surface_alt = tuple(_hex_to_rgb(theme.get("surface_alt", "#f4f7fb")))
    width = 595
    height = 842
    margin = 42
    if template.preset == "manager_daily" and template.version == "manager_daily_template_v2":
        return _render_manager_daily_pdf_report(
            report=report,
            font=font,
            width=width,
            height=height,
            margin=margin,
            accent=accent,
            muted=muted,
            black=black,
            green=green,
            amber=amber,
            red=red,
            surface_alt=surface_alt,
        )
    line_gap = 4
    pages: list[list[dict[str, Any]]] = []
    y = height - margin

    def add_page() -> None:
        nonlocal y
        pages.append([])
        pages[-1].append({"type": "text", "x": margin, "y": height - 24, "size": 8.5, "color": muted, "text": report["metadata_line"]})
        pages[-1].append({"type": "line", "x1": margin, "y1": height - 30, "x2": width - margin, "y2": height - 30, "color": surface_alt, "stroke": 1})
        y = height - 58

    def ensure_space(required: float) -> None:
        nonlocal y
        if not pages:
            add_page()
        if y - required < margin + 24:
            add_page()

    def add_line(text: str, *, size: float = 10.0, color: tuple[int, int, int] = black, gap: float | None = None) -> None:
        nonlocal y
        wrapped = _wrap_text(text=text, font=font, font_size=size, max_width=width - (margin * 2))
        for line in wrapped:
            ensure_space(size + 6)
            y -= size + 2
            pages[-1].append({"type": "text", "x": margin, "y": y, "size": size, "color": color, "text": line})
        y -= gap if gap is not None else line_gap

    def add_bar(title: str, *, color: tuple[int, int, int] = accent) -> None:
        nonlocal y
        ensure_space(26)
        y -= 18
        pages[-1].append({"type": "rect", "x": margin, "y": y - 4, "w": width - (margin * 2), "h": 20, "fill": color})
        pages[-1].append({"type": "text", "x": margin + 10, "y": y + 1, "size": 11.5, "color": (255, 255, 255), "text": title})
        y -= 10

    add_page()
    add_line(report["title"], size=24, color=accent, gap=2)
    add_line(report["subtitle"], size=11, color=muted, gap=4)
    add_line(report.get("hero_focus") or report.get("hero_context") or "", size=10, color=black, gap=12)

    for section in report["sections"]:
        if section.get("page_break_before"):
            add_page()
        bar_color = accent
        if section["id"] in {"risk_zone_cards", "key_problem_of_day"}:
            bar_color = red
        if section["id"] == "main_focus_for_tomorrow":
            bar_color = amber
        if section["id"] == "business_results_placeholder":
            bar_color = green
        if section["kind"] != "orientation_box":
            add_bar(section["label"], color=bar_color)
        for line in _section_to_text_lines(section):
            add_line(line, size=9.5, color=black, gap=1)
        y -= 6

    for page_number, page in enumerate(pages, start=1):
        page.append({"type": "line", "x1": margin, "y1": 36, "x2": width - margin, "y2": 36, "color": surface_alt, "stroke": 1})
        page.append({"type": "text", "x": margin, "y": 22, "size": 8.5, "color": muted, "text": report["footer"]})
        page.append({"type": "text", "x": width - margin - 8, "y": 22, "size": 8.5, "color": muted, "text": str(page_number)})
    return _build_pdf_bytes(pages=pages, font=font, page_width=width, page_height=height), len(pages)


def _render_manager_daily_pdf_report(
    *,
    report: dict[str, Any],
    font: "_TrueTypeFont",
    width: int,
    height: int,
    margin: int,
    accent: tuple[int, int, int],
    muted: tuple[int, int, int],
    black: tuple[int, int, int],
    green: tuple[int, int, int],
    amber: tuple[int, int, int],
    red: tuple[int, int, int],
    surface_alt: tuple[int, int, int],
) -> tuple[bytes, int]:
    """Render manager_daily PDF with the approved v5 block composition."""
    white = (255, 255, 255)
    light_blue = (232, 240, 254)
    light_green = (231, 240, 223)
    light_yellow = (246, 234, 201)
    light_red = (249, 236, 236)
    light_orange = (247, 232, 220)
    light_gray = (243, 245, 247)
    pages: list[list[dict[str, Any]]] = []
    sections = {section["id"]: section for section in report["sections"]}

    def add_page() -> list[dict[str, Any]]:
        page: list[dict[str, Any]] = []
        page.append({"type": "text", "x": margin, "y": height - 24, "size": 8.8, "color": muted, "text": report["metadata_line"]})
        page.append({"type": "line", "x1": margin, "y1": height - 30, "x2": width - margin, "y2": height - 30, "color": surface_alt, "stroke": 1})
        pages.append(page)
        return page

    def footer(page: list[dict[str, Any]], number: int) -> None:
        page.append({"type": "line", "x1": margin, "y1": 36, "x2": width - margin, "y2": 36, "color": surface_alt, "stroke": 1})
        page.append({"type": "text", "x": margin, "y": 22, "size": 8.5, "color": muted, "text": report["footer"]})
        page.append({"type": "text", "x": width - margin - 8, "y": 22, "size": 8.5, "color": muted, "text": str(number)})

    def draw_rect(page: list[dict[str, Any]], *, left: float, top: float, box_width: float, box_height: float, fill: tuple[int, int, int]) -> None:
        page.append({"type": "rect", "x": left, "y": height - top - box_height, "w": box_width, "h": box_height, "fill": fill})

    def draw_line(page: list[dict[str, Any]], *, left: float, top: float, line_width: float, color: tuple[int, int, int], stroke: float = 1.0) -> None:
        y = height - top
        page.append({"type": "line", "x1": left, "y1": y, "x2": left + line_width, "y2": y, "color": color, "stroke": stroke})

    def draw_text(
        page: list[dict[str, Any]],
        *,
        left: float,
        top: float,
        text: str,
        size: float,
        color: tuple[int, int, int] = black,
        max_width: float | None = None,
        leading: float = 1.28,
    ) -> float:
        lines = _wrap_text(text=text, font=font, font_size=size, max_width=max_width or (width - left - margin))
        line_height = size * leading
        for index, line in enumerate(lines):
            y = height - top - (index * line_height) - size
            page.append({"type": "text", "x": left, "y": y, "size": size, "color": color, "text": line})
        return len(lines) * line_height

    def draw_centered_text(
        page: list[dict[str, Any]],
        *,
        left: float,
        top: float,
        box_width: float,
        text: str,
        size: float,
        color: tuple[int, int, int] = black,
    ) -> None:
        text_width = font.measure(text, size)
        x = left + max(8.0, (box_width - text_width) / 2)
        page.append({"type": "text", "x": x, "y": height - top - size, "size": size, "color": color, "text": text})

    def draw_section_bar(page: list[dict[str, Any]], *, top: float, title: str, color: tuple[int, int, int]) -> None:
        draw_rect(page, left=margin, top=top, box_width=width - (margin * 2), box_height=22, fill=color)
        draw_text(page, left=margin + 14, top=top + 5, text=title, size=11.5, color=white)

    def measure_height(text: str, size: float, mw: float, leading: float = 1.28) -> float:
        lines = _wrap_text(text=text, font=font, font_size=size, max_width=mw)
        return len(lines) * size * leading

    def draw_table(
        page: list[dict[str, Any]],
        *,
        top: float,
        columns: list[str],
        rows: list[list[str]],
        col_widths: list[float],
        header_fill: tuple[int, int, int] = accent,
        row_fill: tuple[int, int, int] = white,
        alt_row_fill: tuple[int, int, int] = light_gray,
        header_size: float = 7.8,
        body_size: float = 7.7,
        lefts: list[float] | None = None,
    ) -> float:
        x_positions = lefts or []
        if not x_positions:
            x = margin
            for col_width in col_widths:
                x_positions.append(x)
                x += col_width
        header_height = 22
        for idx, column in enumerate(columns):
            draw_rect(page, left=x_positions[idx], top=top, box_width=col_widths[idx], box_height=header_height, fill=header_fill)
            draw_text(page, left=x_positions[idx] + 4, top=top + 6, text=str(column), size=header_size, color=white, max_width=col_widths[idx] - 8)
        cursor = top + header_height + 2
        for row_index, row in enumerate(rows):
            cell_heights = [
                measure_height(str(cell), body_size, col_widths[idx] - 8, leading=1.18)
                for idx, cell in enumerate(row)
            ]
            row_height = max(24, int(max(cell_heights, default=12) + 10))
            fill = row_fill if row_index % 2 == 0 else alt_row_fill
            for idx, cell in enumerate(row):
                draw_rect(page, left=x_positions[idx], top=cursor, box_width=col_widths[idx], box_height=row_height, fill=fill)
                draw_text(page, left=x_positions[idx] + 4, top=cursor + 5, text=str(cell), size=body_size, color=black, max_width=col_widths[idx] - 8, leading=1.18)
            cursor += row_height + 2
        return cursor

    header = sections["report_header"]
    day_summary = sections["day_summary"]
    money_on_table = sections["money_on_table"]
    warm_pipeline = sections["warm_pipeline"]
    review = sections["review_block"]
    focus = sections["main_focus_for_tomorrow"]
    call_breakdown = sections["call_breakdown"]
    voice = sections["voice_of_customer"]
    additional = sections["additional_situations"]
    challenge = sections["challenge"]
    call_tomorrow = sections["call_tomorrow"]
    call_list = sections["call_list"]
    morning_card = sections["morning_card"]

    page1 = add_page()
    draw_section_bar(page1, top=58, title=header["label"], color=accent)
    draw_rect(page1, left=margin, top=88, box_width=width - (margin * 2), box_height=78, fill=accent)
    draw_text(page1, left=margin + 18, top=102, text=report["title"], size=18.4, color=white, max_width=width - (margin * 2) - 36)
    draw_text(page1, left=margin + 18, top=126, text=report["subtitle"], size=10.0, color=(198, 215, 243), max_width=width - (margin * 2) - 36)
    draw_text(page1, left=margin + 18, top=144, text=f"Фокус недели: {report.get('hero_focus') or ''}", size=10.0, color=white, max_width=width - (margin * 2) - 36)
    draw_text(
        page1,
        left=width - margin - 150,
        top=102,
        text=f"Звонков: {_manager_reader_value(header.get('calls_count'), '0')}",
        size=10.5,
        color=white,
        max_width=132,
    )
    draw_text(
        page1,
        left=width - margin - 150,
        top=122,
        text=f"Балл дня: {_manager_reader_value(header.get('day_score'), 'Нет базы')} / 5",
        size=10.5,
        color=white,
        max_width=132,
    )
    if header.get("selection_note"):
        draw_text(
            page1,
            left=margin,
            top=168,
            text=str(header.get("selection_note") or ""),
            size=7.4,
            color=muted,
            max_width=width - (margin * 2),
        )

    draw_section_bar(page1, top=184, title=day_summary["label"], color=accent)
    outcome_gap = 6
    outcome_width = (width - (margin * 2) - (outcome_gap * 5)) / 6
    outcome_left = margin
    tone_fill = {
        "neutral": light_blue,
        "positive": light_green,
        "focus": light_yellow,
        "problem": light_red,
        "warning": light_orange,
    }
    tone_accent = {
        "neutral": accent,
        "positive": green,
        "focus": amber,
        "problem": red,
        "warning": amber,
    }
    for item in day_summary.get("outcome_cols") or []:
        tone = str(item.get("tone") or "neutral")
        draw_rect(page1, left=outcome_left, top=214, box_width=outcome_width, box_height=58, fill=tone_fill.get(tone, light_blue))
        draw_rect(page1, left=outcome_left, top=214, box_width=outcome_width, box_height=4, fill=tone_accent.get(tone, accent))
        draw_centered_text(page1, left=outcome_left, top=231, box_width=outcome_width, text=_manager_reader_value(item.get("value"), "—"), size=15.5, color=tone_accent.get(tone, accent))
        draw_centered_text(page1, left=outcome_left, top=252, box_width=outcome_width, text=str(item.get("label") or ""), size=7.2, color=muted)
        outcome_left += outcome_width + outcome_gap

    draw_section_bar(page1, top=288, title=money_on_table["label"], color=amber)
    money_box_h = max(
        82,
        int(
            20
            + measure_height(str(money_on_table.get("body") or ""), 9.2, width - (margin * 2) - 24)
            + measure_height(str(money_on_table.get("highlight_line") or ""), 9.0, width - (margin * 2) - 24)
            + measure_height(str(money_on_table.get("reason_line") or ""), 8.6, width - (margin * 2) - 24)
            + 18
        ),
    )
    draw_rect(page1, left=margin, top=318, box_width=width - (margin * 2), box_height=money_box_h, fill=light_yellow)
    draw_rect(page1, left=margin, top=318, box_width=4, box_height=money_box_h, fill=amber)
    draw_text(page1, left=margin + 12, top=330, text=str(money_on_table.get("body") or ""), size=9.2, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=352, text=str(money_on_table.get("highlight_line") or ""), size=9.0, color=accent, max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=372, text=str(money_on_table.get("reason_line") or ""), size=8.6, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=390, text=str(money_on_table.get("note") or ""), size=7.8, color=muted, max_width=width - (margin * 2) - 24)

    pipeline_top = 318 + money_box_h + 16
    draw_section_bar(page1, top=pipeline_top, title=warm_pipeline["label"], color=accent)
    draw_rect(page1, left=margin, top=pipeline_top + 30, box_width=width - (margin * 2), box_height=104, fill=light_gray)
    draw_rect(page1, left=margin, top=pipeline_top + 30, box_width=4, box_height=104, fill=accent)
    draw_text(page1, left=margin + 12, top=pipeline_top + 42, text=str(warm_pipeline.get("summary_line") or ""), size=9.4, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=pipeline_top + 60, text=str(warm_pipeline.get("counts_line") or ""), size=8.8, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=pipeline_top + 78, text=str(warm_pipeline.get("conversion_line") or ""), size=8.8, color=accent, max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=pipeline_top + 96, text=str(warm_pipeline.get("average_line") or ""), size=8.4, color=muted, max_width=width - (margin * 2) - 24)
    footer(page1, 1)

    page2 = add_page()
    draw_section_bar(page2, top=58, title=review["label"], color=accent)
    review_rows = [
        [
            f"{row.get('funnel_label', '')} {row.get('stage_name', '')}".strip(),
            str(row.get("score") or "—"),
            "—",
            str(row.get("bar_text") or "—"),
            "Приоритет" if row.get("is_priority") else "Норма",
        ]
        for row in review.get("stage_rows") or []
    ] or [["Данные по этапам появятся после накопления базы.", "", "", "", ""]]
    review_col_widths = [216, 46, 54, 150, 45]
    review_bottom = draw_table(
        page2,
        top=88,
        columns=["Этап", "Сегодня", "Среднее", "Шкала", "Статус"],
        rows=review_rows,
        col_widths=review_col_widths,
        body_size=7.5,
    )
    focus_top = review_bottom + 10
    draw_section_bar(page2, top=focus_top, title=focus["label"], color=amber)
    draw_rect(page2, left=margin, top=focus_top + 30, box_width=width - (margin * 2), box_height=230, fill=light_blue)
    draw_rect(page2, left=margin, top=focus_top + 30, box_width=4, box_height=230, fill=accent)
    draw_text(page2, left=margin + 12, top=focus_top + 42, text=str(focus.get("situation_title") or focus["label"]), size=10.2, color=accent, max_width=width - (margin * 2) - 24)
    draw_text(page2, left=margin + 12, top=focus_top + 62, text=str(focus.get("body") or ""), size=9.0, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page2, left=margin + 12, top=focus_top + 94, text=f"Что хотел клиент: {focus.get('client_need') or 'Нет данных'}", size=8.5, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page2, left=margin + 12, top=focus_top + 120, text=f"Наша задача: {focus.get('manager_task') or 'Нет данных'}", size=8.5, color=black, max_width=width - (margin * 2) - 24)
    example = dict(focus.get("call_example") or {})
    example_line = ""
    if example.get("client_label") or example.get("time_label"):
        example_line = f"Пример: {example.get('client_label') or 'Клиент'} · {example.get('time_label') or '—'}"
    if example_line:
        draw_text(page2, left=margin + 12, top=focus_top + 150, text=example_line, size=8.3, color=accent, max_width=width - (margin * 2) - 24)
    script_top = focus_top + 170
    for idx, script in enumerate((focus.get("scripts") or [])[:3], start=1):
        draw_text(page2, left=margin + 12, top=script_top + ((idx - 1) * 16), text=f"{idx}. {script}", size=8.2, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page2, left=margin + 12, top=focus_top + 220, text=f"Почему работает: {focus.get('why_it_works') or ''}", size=8.0, color=muted, max_width=width - (margin * 2) - 24)
    footer(page2, 2)

    page3 = add_page()
    draw_section_bar(page3, top=58, title=call_breakdown["label"], color=accent)
    draw_text(page3, left=margin, top=86, text=str(call_breakdown.get("summary_line") or ""), size=9.5, color=black, max_width=width - (margin * 2))
    if call_breakdown.get("rows"):
        breakdown_bottom = draw_table(
            page3,
            top=104,
            columns=["Момент", "Что было", "Что лучше"],
            rows=[list(map(str, row)) for row in (call_breakdown.get("rows") or [])],
            col_widths=[56, 208, 247],
            body_size=7.5,
        )
    else:
        draw_text(page3, left=margin, top=106, text="Недостаточно данных для детального разбора звонка.", size=8.6, color=muted, max_width=width - (margin * 2))
        breakdown_bottom = 128
    voice_top = breakdown_bottom + 10
    draw_section_bar(page3, top=voice_top, title=voice["label"], color=(70, 90, 140))
    if voice.get("intro"):
        draw_text(page3, left=margin, top=voice_top + 30, text=str(voice.get("intro") or ""), size=8.2, color=muted, max_width=width - (margin * 2))
        voice_table_top = voice_top + 48
    else:
        voice_table_top = voice_top + 30
    if voice.get("rows"):
        draw_table(
            page3,
            top=voice_table_top,
            columns=["Паттерн", "Подтверждающие цитаты", "Смысл → Как ответить"],
            rows=[list(map(str, row)) for row in (voice.get("rows") or [])],
            col_widths=[116, 170, 225],
            body_size=7.2,
        )
    else:
        draw_text(page3, left=margin, top=voice_table_top, text="Клиентские цитаты появятся после накопления материала по звонкам.", size=8.6, color=muted, max_width=width - (margin * 2))
    footer(page3, 3)

    page4 = add_page()
    draw_section_bar(page4, top=58, title=additional["label"], color=accent)
    additional_top = 92
    if not (additional.get("situations") or []):
        draw_text(page4, left=margin, top=92, text="Дополнительные ситуации появятся после накопления данных по звонкам.", size=8.8, color=muted, max_width=width - (margin * 2))
        additional_top = 120
    for item in (additional.get("situations") or [])[:3]:
        card_fill = light_green if str(item.get("badge") or "").lower().startswith("силь") else light_orange
        card_color = green if str(item.get("badge") or "").lower().startswith("силь") else amber
        card_h = 92
        draw_rect(page4, left=margin, top=additional_top, box_width=width - (margin * 2), box_height=card_h, fill=card_fill)
        draw_rect(page4, left=margin, top=additional_top, box_width=4, box_height=card_h, fill=card_color)
        draw_text(page4, left=margin + 12, top=additional_top + 8, text=f"{item.get('badge') or 'Ситуация'} · {item.get('title') or ''}", size=9.2, color=card_color, max_width=width - (margin * 2) - 24)
        draw_text(page4, left=margin + 12, top=additional_top + 26, text=f"Что сказал клиент: {item.get('client_said') or '—'}", size=7.9, color=black, max_width=width - (margin * 2) - 24)
        draw_text(page4, left=margin + 12, top=additional_top + 42, text=f"Что имел в виду: {item.get('meant') or '—'}", size=7.9, color=black, max_width=width - (margin * 2) - 24)
        draw_text(page4, left=margin + 12, top=additional_top + 58, text=f"Как надо было: {item.get('how_to') or '—'}", size=7.9, color=black, max_width=width - (margin * 2) - 24)
        draw_text(page4, left=margin + 12, top=additional_top + 74, text=f"Почему так: {item.get('why') or '—'}", size=7.6, color=muted, max_width=width - (margin * 2) - 24)
        additional_top += card_h + 10
    challenge_top = additional_top + 2
    draw_section_bar(page4, top=challenge_top, title=challenge["label"], color=accent)
    draw_rect(page4, left=margin, top=challenge_top + 30, box_width=width - (margin * 2), box_height=106, fill=light_blue)
    draw_rect(page4, left=margin, top=challenge_top + 30, box_width=4, box_height=106, fill=accent)
    draw_text(page4, left=margin + 12, top=challenge_top + 42, text=str(challenge.get("goal_line") or ""), size=9.2, color=accent, max_width=width - (margin * 2) - 24)
    draw_text(page4, left=margin + 12, top=challenge_top + 62, text=str(challenge.get("today_line") or ""), size=8.5, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page4, left=margin + 12, top=challenge_top + 80, text=str(challenge.get("record_line") or ""), size=8.5, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page4, left=margin + 12, top=challenge_top + 98, text=f"Фраза для завтра: {challenge.get('phrase_line') or ''}", size=8.5, color=black, max_width=width - (margin * 2) - 24)
    footer(page4, 4)

    page5 = add_page()
    draw_section_bar(page5, top=58, title=call_tomorrow["label"], color=accent)
    if call_tomorrow.get("rows"):
        draw_table(
            page5,
            top=92,
            columns=["Приоритет", "Клиент", "Срок/повод", "Цель звонка", "Первая фраза"],
            rows=[list(map(str, row)) for row in (call_tomorrow.get("rows") or [])],
            col_widths=[66, 96, 90, 120, 139],
            body_size=6.9,
        )
    else:
        draw_text(page5, left=margin, top=94, text="Нет открытых контактов для перезвона.", size=9.0, color=muted, max_width=width - (margin * 2))
    footer(page5, 5)

    page6 = add_page()
    draw_section_bar(page6, top=58, title=call_list["label"], color=accent)
    draw_table(
        page6,
        top=92,
        columns=[str(column) for column in (call_list.get("columns") or [])],
        rows=[list(map(str, row)) for row in (call_list.get("rows") or [])] or [["—"] * max(1, len(call_list.get("columns") or []))],
        col_widths=[22, 44, 112, 110, 126, 97],
        body_size=7.2,
    )
    if call_list.get("note"):
        draw_text(page6, left=margin, top=744, text=str(call_list.get("note") or ""), size=8.0, color=muted, max_width=width - (margin * 2))
    footer(page6, 6)

    page7 = add_page()
    draw_section_bar(page7, top=58, title=morning_card["label"], color=accent)
    draw_rect(page7, left=margin, top=92, box_width=width - (margin * 2), box_height=250, fill=light_blue)
    draw_rect(page7, left=margin, top=92, box_width=4, box_height=250, fill=accent)
    draw_text(page7, left=margin + 16, top=114, text=str(morning_card.get("greeting") or ""), size=16.0, color=black, max_width=width - (margin * 2) - 32)
    draw_text(page7, left=margin + 16, top=146, text=str(morning_card.get("summary_line") or ""), size=11.0, color=accent, max_width=width - (margin * 2) - 32)
    if morning_card.get("financial_line"):
        draw_text(page7, left=margin + 16, top=176, text=str(morning_card.get("financial_line") or ""), size=8.8, color=black, max_width=width - (margin * 2) - 32)
    draw_text(page7, left=margin + 16, top=208, text="Позвони сегодня:", size=9.2, color=accent, max_width=width - (margin * 2) - 32)
    contact_top = 228
    contacts = morning_card.get("call_tomorrow_contacts") or []
    if contacts:
        for item in contacts[:3]:
            draw_rect(page7, left=margin + 16, top=contact_top, box_width=width - (margin * 2) - 32, box_height=34, fill=white)
            draw_text(page7, left=margin + 24, top=contact_top + 7, text=f"{item.get('client_label') or 'Клиент'}", size=8.8, color=black, max_width=150)
            draw_text(page7, left=margin + 160, top=contact_top + 7, text=str(item.get("opening_script") or "Скрипт не задан"), size=7.8, color=muted, max_width=width - (margin * 2) - 200)
            contact_top += 40
    else:
        draw_text(page7, left=margin + 16, top=contact_top, text="Открытых звонков нет — отличный результат!", size=9.2, color=green, max_width=width - (margin * 2) - 32)
    draw_rect(page7, left=margin + 16, top=360, box_width=width - (margin * 2) - 32, box_height=70, fill=white)
    draw_rect(page7, left=margin + 16, top=360, box_width=4, box_height=70, fill=amber)
    draw_text(page7, left=margin + 28, top=374, text="Челлендж:", size=9.2, color=accent, max_width=width - (margin * 2) - 56)
    draw_text(page7, left=margin + 28, top=394, text=str(morning_card.get("challenge") or ""), size=9.2, color=black, max_width=width - (margin * 2) - 56)
    footer(page7, 7)

    return _build_pdf_bytes(pages=pages, font=font, page_width=width, page_height=height), len(pages)


def _build_pdf_bytes(
    *,
    pages: list[list[dict[str, Any]]],
    font: "_TrueTypeFont",
    page_width: int,
    page_height: int,
) -> bytes:
    """Build a minimal PDF with embedded TrueType font and multipage text content."""
    used_chars = sorted({char for page in pages for item in page if item["type"] == "text" for char in item["text"]})
    cid_to_gid = font.build_cid_to_gid_map(used_chars)
    widths = font.build_widths(used_chars)
    to_unicode = _build_to_unicode_cmap(used_chars)
    objects: list[bytes] = []

    def add_object(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_file_id = add_object(_stream_object(font.font_bytes))
    font_descriptor_id = add_object(
        (
            b"<< /Type /FontDescriptor /FontName /F1 /Flags 32 "
            + f"/FontBBox [{font.font_bbox[0]} {font.font_bbox[1]} {font.font_bbox[2]} {font.font_bbox[3]}] ".encode()
            + f"/ItalicAngle {font.italic_angle} /Ascent {font.ascent} /Descent {font.descent} /CapHeight {font.cap_height} ".encode()
            + f"/StemV {font.stem_v} /FontFile2 {font_file_id} 0 R >>".encode()
        )
    )
    cid_to_gid_id = add_object(_stream_object(cid_to_gid))
    to_unicode_id = add_object(_stream_object(to_unicode))
    cid_font_id = add_object(
        (
            b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /F1 /CIDSystemInfo "
            b"<< /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            + f"/FontDescriptor {font_descriptor_id} 0 R ".encode()
            + f"/DW {font.default_width} ".encode()
            + f"/W [ {widths} ] ".encode()
            + f"/CIDToGIDMap {cid_to_gid_id} 0 R >>".encode()
        )
    )
    type0_font_id = add_object(
        (
            b"<< /Type /Font /Subtype /Type0 /BaseFont /F1 /Encoding /Identity-H "
            + f"/DescendantFonts [ {cid_font_id} 0 R ] /ToUnicode {to_unicode_id} 0 R >>".encode()
        )
    )

    page_ids: list[int] = []
    content_ids: list[int] = []
    pages_root_placeholder = len(objects) + 1
    for page in pages:
        content_stream = _build_page_stream(page)
        content_ids.append(add_object(_stream_object(content_stream)))
        page_ids.append(0)
    pages_root_id = add_object(b"")  # replaced below
    for index, content_id in enumerate(content_ids):
        page_ids[index] = add_object(
            (
                b"<< /Type /Page "
                + f"/Parent {pages_root_id} 0 R ".encode()
                + f"/MediaBox [0 0 {page_width} {page_height}] ".encode()
                + f"/Resources << /Font << /F1 {type0_font_id} 0 R >> >> ".encode()
                + f"/Contents {content_id} 0 R >>".encode()
            )
        )
    objects[pages_root_id - 1] = (
        b"<< /Type /Pages "
        + f"/Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] ".encode()
        + f"/Count {len(page_ids)} >>".encode()
    )
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_root_id} 0 R >>".encode())

    chunks = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets = [0]
    cursor = len(chunks[0])
    for idx, body in enumerate(objects, start=1):
        offsets.append(cursor)
        obj = f"{idx} 0 obj\n".encode() + body + b"\nendobj\n"
        chunks.append(obj)
        cursor += len(obj)
    xref_offset = cursor
    xref_lines = [f"0 {len(objects) + 1}\n".encode(), b"0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref_lines.append(f"{offset:010d} 00000 n \n".encode())
    xref = b"xref\n" + b"".join(xref_lines)
    trailer = (
        b"trailer\n"
        + f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n".encode()
        + b"startxref\n"
        + f"{xref_offset}\n".encode()
        + b"%%EOF"
    )
    return b"".join(chunks) + xref + trailer


def _build_page_stream(page: list[dict[str, Any]]) -> bytes:
    """Build content stream for one page."""
    commands: list[str] = []
    for item in page:
        if item["type"] == "text":
            r, g, b = item["color"]
            commands.append(
                f"BT {r/255:.4f} {g/255:.4f} {b/255:.4f} rg /F1 {item['size']:.2f} Tf 1 0 0 1 {item['x']:.2f} {item['y']:.2f} Tm <{_encode_pdf_text(item['text'])}> Tj ET"
            )
        elif item["type"] == "rect":
            r, g, b = item["fill"]
            commands.append(
                f"q {r/255:.4f} {g/255:.4f} {b/255:.4f} rg {item['x']:.2f} {item['y']:.2f} {item['w']:.2f} {item['h']:.2f} re f Q"
            )
        elif item["type"] == "line":
            r, g, b = item["color"]
            commands.append(
                f"q {r/255:.4f} {g/255:.4f} {b/255:.4f} RG {item.get('stroke', 1):.2f} w {item['x1']:.2f} {item['y1']:.2f} m {item['x2']:.2f} {item['y2']:.2f} l S Q"
            )
    return "\n".join(commands).encode("utf-8")


def _encode_pdf_text(text: str) -> str:
    """Encode Unicode text as UTF-16BE hex string for Identity-H font."""
    return "".join(f"{ord(char):04X}" for char in text)


def _build_to_unicode_cmap(chars: list[str]) -> bytes:
    """Build ToUnicode CMap stream for used chars."""
    mappings = "".join(
        f"<{ord(char):04X}> <{ord(char):04X}>\n"
        for char in chars
    )
    cmap = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\n"
        "begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n"
        "/CMapType 2 def\n"
        "1 begincodespacerange\n"
        "<0000> <FFFF>\n"
        "endcodespacerange\n"
        f"{len(chars)} beginbfchar\n"
        f"{mappings}"
        "endbfchar\n"
        "endcmap\n"
        "CMapName currentdict /CMap defineresource pop\n"
        "end\n"
        "end"
    )
    return cmap.encode("utf-8")


def _stream_object(data: bytes) -> bytes:
    """Wrap raw bytes in a PDF stream object."""
    return b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream"


def _wrap_text(*, text: str, font: "_TrueTypeFont", font_size: float, max_width: float) -> list[str]:
    """Wrap text to a target width using simple font metrics."""
    if not text:
        return [""]
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.measure(candidate, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class _TrueTypeFont:
    """Very small TrueType reader sufficient for bounded PDF rendering."""

    def __init__(self, path: Path):
        self.font_bytes = path.read_bytes()
        self.tables = self._read_table_directory()
        self.units_per_em = self._read_u16("head", 18)
        self.ascent = self._scaled(self._read_s16("hhea", 4))
        self.descent = self._scaled(self._read_s16("hhea", 6))
        self.italic_angle = self._read_fixed("post", 4) if "post" in self.tables else 0
        self.cap_height = self.ascent
        self.stem_v = 80
        self.font_bbox = (
            self._scaled(self._read_s16("head", 36)),
            self._scaled(self._read_s16("head", 38)),
            self._scaled(self._read_s16("head", 40)),
            self._scaled(self._read_s16("head", 42)),
        )
        self.number_of_h_metrics = self._read_u16("hhea", 34)
        self.num_glyphs = self._read_u16("maxp", 4)
        self.advance_widths = self._read_hmtx()
        self.cmap = self._read_cmap()
        self.default_width = self._scaled(self.advance_widths[0] if self.advance_widths else 1000)

    def _read_table_directory(self) -> dict[str, tuple[int, int]]:
        num_tables = struct.unpack(">H", self.font_bytes[4:6])[0]
        tables: dict[str, tuple[int, int]] = {}
        offset = 12
        for _ in range(num_tables):
            tag = self.font_bytes[offset:offset + 4].decode("ascii")
            _, table_offset, length = struct.unpack(">III", self.font_bytes[offset + 4:offset + 16])
            tables[tag] = (table_offset, length)
            offset += 16
        return tables

    def _table_slice(self, tag: str, relative_offset: int = 0, length: int | None = None) -> bytes:
        offset, table_length = self.tables[tag]
        start = offset + relative_offset
        end = offset + table_length if length is None else start + length
        return self.font_bytes[start:end]

    def _read_u16(self, tag: str, offset: int) -> int:
        return struct.unpack(">H", self._table_slice(tag, offset, 2))[0]

    def _read_s16(self, tag: str, offset: int) -> int:
        return struct.unpack(">h", self._table_slice(tag, offset, 2))[0]

    def _read_fixed(self, tag: str, offset: int) -> float:
        raw = struct.unpack(">i", self._table_slice(tag, offset, 4))[0]
        return raw / 65536

    def _scaled(self, value: int) -> int:
        return round((value / self.units_per_em) * 1000)

    def _read_hmtx(self) -> list[int]:
        hmtx = self._table_slice("hmtx")
        widths: list[int] = []
        cursor = 0
        last_advance = 0
        for index in range(self.num_glyphs):
            if index < self.number_of_h_metrics:
                advance, _ = struct.unpack(">Hh", hmtx[cursor:cursor + 4])
                cursor += 4
                last_advance = advance
            else:
                cursor += 2
                advance = last_advance
            widths.append(advance)
        return widths

    def _read_cmap(self) -> dict[int, int]:
        table = self._table_slice("cmap")
        _, num_tables = struct.unpack(">HH", table[:4])
        preferred_offset = None
        for index in range(num_tables):
            platform_id, encoding_id, subtable_offset = struct.unpack(">HHI", table[4 + index * 8:12 + index * 8])
            if (platform_id, encoding_id) in {(3, 10), (3, 1), (0, 3)}:
                preferred_offset = subtable_offset
                if (platform_id, encoding_id) == (3, 10):
                    break
        if preferred_offset is None:
            return {}
        fmt = struct.unpack(">H", table[preferred_offset:preferred_offset + 2])[0]
        if fmt == 12:
            _, _, _, _, groups = struct.unpack(">HHLLL", table[preferred_offset:preferred_offset + 16])
            mapping: dict[int, int] = {}
            cursor = preferred_offset + 16
            for _ in range(groups):
                start_char, end_char, start_gid = struct.unpack(">LLL", table[cursor:cursor + 12])
                for codepoint in range(start_char, end_char + 1):
                    mapping[codepoint] = start_gid + (codepoint - start_char)
                cursor += 12
            return mapping
        if fmt != 4:
            return {}
        length, _, seg_count_x2, _, _, _, _ = struct.unpack(">HHHHHHH", table[preferred_offset + 2:preferred_offset + 16])
        seg_count = seg_count_x2 // 2
        cursor = preferred_offset + 14
        end_codes = struct.unpack(f">{seg_count}H", table[cursor:cursor + seg_count * 2])
        cursor += seg_count * 2 + 2
        start_codes = struct.unpack(f">{seg_count}H", table[cursor:cursor + seg_count * 2])
        cursor += seg_count * 2
        id_deltas = struct.unpack(f">{seg_count}h", table[cursor:cursor + seg_count * 2])
        cursor += seg_count * 2
        id_range_offset_pos = cursor
        id_range_offsets = struct.unpack(f">{seg_count}H", table[cursor:cursor + seg_count * 2])
        mapping: dict[int, int] = {}
        for index in range(seg_count):
            start = start_codes[index]
            end = end_codes[index]
            delta = id_deltas[index]
            range_offset = id_range_offsets[index]
            for codepoint in range(start, end + 1):
                if codepoint == 0xFFFF:
                    continue
                if range_offset == 0:
                    glyph_id = (codepoint + delta) & 0xFFFF
                else:
                    entry_offset = (
                        id_range_offset_pos
                        + index * 2
                        + range_offset
                        + (codepoint - start) * 2
                    )
                    glyph_id = struct.unpack(">H", table[entry_offset:entry_offset + 2])[0]
                    if glyph_id != 0:
                        glyph_id = (glyph_id + delta) & 0xFFFF
                if glyph_id:
                    mapping[codepoint] = glyph_id
        return mapping

    def measure(self, text: str, font_size: float) -> float:
        total = 0.0
        for char in text:
            total += self._scaled(self.advance_widths[self.cmap.get(ord(char), 0)] if self.cmap.get(ord(char), 0) < len(self.advance_widths) else self.advance_widths[0])
        return (total / 1000.0) * font_size

    def build_cid_to_gid_map(self, chars: list[str]) -> bytes:
        max_cid = max((ord(char) for char in chars), default=0)
        mapping = bytearray((max_cid + 1) * 2)
        for char in chars:
            cid = ord(char)
            gid = self.cmap.get(cid, 0)
            mapping[cid * 2: cid * 2 + 2] = struct.pack(">H", gid)
        return bytes(mapping)

    def build_widths(self, chars: list[str]) -> str:
        entries = []
        for char in chars:
            cid = ord(char)
            gid = self.cmap.get(cid, 0)
            width = self._scaled(self.advance_widths[gid] if gid < len(self.advance_widths) else self.advance_widths[0])
            entries.append(f"{cid} [{width}]")
        return " ".join(entries)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Convert #RRGGBB to integers."""
    stripped = value.lstrip("#")
    return tuple(int(stripped[index:index + 2], 16) for index in (0, 2, 4))


def _value(value: Any, default: str = "not available") -> str:
    """Render one scalar value safely."""
    if value is None or value == "":
        return default
    return str(value)


def _pct_label(value: Any) -> str:
    """Render percentage-like values."""
    if value is None:
        return "not available"
    return f"{value}%"


def _compact_metrics(metrics: dict[str, Any]) -> str:
    """Render a compact metric dictionary."""
    if not metrics:
        return "not available"
    return ", ".join(f"{key}={_value(value)}" for key, value in metrics.items())


def _placeholder_note(block: dict[str, Any]) -> str | None:
    """Render placeholder note when block is marked as placeholder."""
    if block.get("is_placeholder"):
        return "placeholder"
    return None


def _source_note(block: dict[str, Any]) -> str | None:
    """Render bounded source note for model-dependent blocks."""
    parts = []
    if block.get("source"):
        parts.append(f"source={block['source']}")
    if block.get("model_dependent"):
        parts.append("model_dependent")
    return ", ".join(parts) if parts else None


def _short_time(value: Any) -> str:
    """Return short HH:MM for ISO datetime-ish strings."""
    text = _value(value, "—")
    if "T" in text and len(text) >= 16:
        return text[11:16]
    return text


_MONTH_SHORT_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _format_deadline_human(value: str | None) -> str | None:
    """Convert ISO datetime/date string to a short Russian human-readable form.

    '2026-04-29T11:00:00+00:00' → '29 апр 11:00'
    '2026-04-29'                → '29 апр'
    Any other non-empty string  → returned unchanged.
    """
    if not value:
        return None
    text = str(value).strip()
    import re as _re
    m = _re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", text)
    if m:
        month = int(m.group(2))
        day = int(m.group(3))
        hour = int(m.group(4))
        minute = int(m.group(5))
        mon = _MONTH_SHORT_RU[month - 1] if 1 <= month <= 12 else str(month)
        return f"{day} {mon} {hour:02d}:{minute:02d}"
    m = _re.match(r"(\d{4})-(\d{2})-(\d{2})$", text)
    if m:
        month = int(m.group(2))
        day = int(m.group(3))
        mon = _MONTH_SHORT_RU[month - 1] if 1 <= month <= 12 else str(month)
        return f"{day} {mon}"
    return text


def _resolve_manager_day_score(*, payload: dict[str, Any]) -> float | None:
    """Return the visible day score on a 0-5 scale, with optional parity override."""
    verification_overrides = dict(payload.get("verification_overrides") or {})
    override = verification_overrides.get("day_score")
    if override is not None:
        try:
            return round(float(override), 1)
        except (TypeError, ValueError):
            return None
    score_by_stage = list(payload.get("score_by_stage") or [])
    if score_by_stage:
        values = []
        for item in score_by_stage:
            score = item.get("score")
            if score is None:
                continue
            try:
                values.append(float(score) / 2.0)
            except (TypeError, ValueError):
                continue
        if values:
            return round(sum(values) / len(values), 1)
    average_score = payload.get("kpi_overview", {}).get("average_score")
    if average_score is None:
        return None
    try:
        return round(float(average_score) / 20.0, 1)
    except (TypeError, ValueError):
        return None


def _build_manager_daily_selection_note(*, payload: dict[str, Any], total_calls: int) -> str | None:
    """Build a compact manager-facing sampling note for signal and full reports."""
    readiness = dict((payload.get("meta") or {}).get("readiness") or {})
    outcome = readiness.get("readiness_outcome")
    if outcome not in {"signal_report", "full_report"}:
        return None
    found = int(readiness.get("relevant_calls") or 0)
    ready = int(readiness.get("ready_analyses") or 0)
    in_report = int(total_calls or 0)
    window_days = int(readiness.get("window_days_used") or 1)

    parts: list[str] = []
    if found:
        parts.append(f"Найдено в телефонии: {found}")
    if ready and ready != found:
        parts.append(f"с готовым разбором: {ready}")
    parts.append(f"вошло в отчёт: {in_report}")
    line1 = " · ".join(parts)

    excluded = max(0, found - in_report) if found else 0
    lines = [line1]
    if excluded > 0:
        lines.append(
            f"Не вошло {excluded}: нет готового транскрипта/анализа или звонки не подходят для управленческого вывода."
        )
    if window_days > 1:
        lines.append(f"Данные за {window_days} раб. дн. (скользящее окно для набора базы).")
    if outcome == "signal_report":
        lines[0] = "Сигнальный отчёт · " + lines[0]
    return " ".join(lines)


def _priority_stage_row(score_by_stage: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return render-ready priority stage. Uses explicit is_priority flag; falls back to lowest-scoring stage."""
    rows = _build_stage_score_rows(score_by_stage)
    explicit = next((row for row in rows if row.get("is_priority")), None)
    if explicit is not None:
        return explicit
    scored = [row for row in rows if row.get("score_float") is not None]
    if not scored:
        return None
    return min(scored, key=lambda r: float(r.get("score_float") or 999))


def _build_situation_title(score_by_stage: list[dict[str, Any]]) -> str:
    """Build СИТУАЦИЯ ДНЯ heading from the priority stage."""
    row = _priority_stage_row(score_by_stage)
    if row is not None:
        name = str(row.get("stage_name") or "этап")
        score = str(row.get("score") or "—")
        return f"СИТУАЦИЯ ДНЯ · {name} — {score}/5"
    return "СИТУАЦИЯ ДНЯ"


def _build_pattern_count_label(key_problem: dict[str, Any]) -> str | None:
    """Build 'Паттерн повторился в N из M звонков' label, None if data unavailable."""
    count = key_problem.get("pattern_count")
    total = key_problem.get("total_calls")
    if count is None or not total:
        return None
    return f"Паттерн повторился в {count} из {total} звонков"


def _render_voice_of_customer_html(section: dict[str, Any]) -> str:
    """Render ГОЛОС КЛИЕНТА block with up to 3 client situation cards."""
    label = html.escape(str(section.get("label") or "ГОЛОС КЛИЕНТА"))
    situations = list(section.get("situations") or [])
    if section.get("is_placeholder") or not situations:
        return (
            f"<div class=\"section-bar navy\">{label}</div>"
            "<section class=\"voice-of-customer\">"
            "<div class=\"voice-placeholder\">Ситуации появятся после накопления материала по звонкам.</div>"
            "</section>"
        )
    cards = "".join(
        f"<article class=\"voice-card\">"
        f"<blockquote class=\"voice-quote\">«{html.escape(str(s.get('quote') or ''))}»</blockquote>"
        f"<div class=\"voice-meta\">{html.escape(str(s.get('client_label') or 'Клиент'))} · {html.escape(str(s.get('time_label') or '—'))}</div>"
        + (
            f"<div class=\"voice-context\">{html.escape(str(s['context']))}</div>"
            if s.get("context")
            else ""
        )
        + "</article>"
        for s in situations
    )
    return (
        f"<div class=\"section-bar navy\">{label}</div>"
        f"<section class=\"voice-of-customer\"><div class=\"voice-grid\">{cards}</div></section>"
    )


def _render_situation_call_example_html(call_example: dict[str, Any]) -> str:
    """Render one representative call example inside СИТУАЦИЯ ДНЯ block."""
    client = str(call_example.get("client_label") or "").strip()
    time_label = str(call_example.get("time_label") or "").strip()
    reason = str(call_example.get("reason_short") or "").strip()
    if not client and not time_label:
        return ""
    header_parts = []
    if client:
        header_parts.append(html.escape(client))
    if time_label and time_label != "—":
        header_parts.append(html.escape(time_label))
    header_line = " · ".join(header_parts)
    reason_html = f"<div class=\"situation-example-reason\">{html.escape(reason)}</div>" if reason else ""
    return (
        f"<div class=\"situation-example\">"
        f"<span class=\"situation-example-label\">Пример: </span>"
        f"<span class=\"situation-example-contact\">{header_line}</span>"
        f"{reason_html}"
        f"</div>"
    )


def _render_additional_situations_html(section: dict[str, Any]) -> str:
    """Render ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ block with up to 3 gap/strength cards."""
    label = html.escape(str(section.get("label") or "ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ"))
    situations = list(section.get("situations") or [])
    if section.get("is_placeholder") or not situations:
        return (
            f"<div class=\"section-bar\">{label}</div>"
            "<section class=\"add-situations\">"
            "<div class=\"add-sit-placeholder\">Дополнительные ситуации появятся после накопления данных по звонкам.</div>"
            "</section>"
        )
    cards = ""
    for s in situations:
        kind = str(s.get("kind") or "gap")
        kind_class = "add-sit-gap" if kind == "gap" else "add-sit-strength"
        kind_label = "Зона роста" if kind == "gap" else "Сильная сторона"
        signal = int(s.get("signal") or 0)
        signal_html = f"<span class=\"add-sit-signal\">{signal} зв.</span>" if signal else ""
        interp = html.escape(str(s.get("interpretation") or ""))
        title = html.escape(str(s.get("title") or ""))
        cards += (
            f"<article class=\"add-sit-card {kind_class}\">"
            f"<div class=\"add-sit-header\">"
            f"<span class=\"add-sit-kind-badge\">{kind_label}</span>"
            f"{signal_html}"
            f"</div>"
            f"<div class=\"add-sit-title\">{title}</div>"
            f"<div class=\"add-sit-interp\">{interp}</div>"
            f"</article>"
        )
    return (
        f"<div class=\"section-bar\">{label}</div>"
        f"<section class=\"add-situations\">{cards}</section>"
    )


_CALL_TOMORROW_STATUS_LABEL: dict[str, str] = {
    "rescheduled": "Перезвон",
    "agreed": "Договорённость",
    "open": "Открытый",
}


def _render_call_tomorrow_html(section: dict[str, Any]) -> str:
    """Render ПОЗВОНИ ЗАВТРА block with follow-up contacts and opening scripts."""
    label = html.escape(str(section.get("label") or "ПОЗВОНИ ЗАВТРА"))
    contacts = list(section.get("contacts") or [])
    if section.get("is_placeholder") or not contacts:
        return (
            f"<div class=\"section-bar\">{label}</div>"
            "<section class=\"call-tomorrow\">"
            "<div class=\"ct-placeholder\">Нет открытых контактов для перезвона — все звонки завершены с результатом.</div>"
            "</section>"
        )
    rows = ""
    for c in contacts:
        status = str(c.get("status") or "open")
        status_label = _CALL_TOMORROW_STATUS_LABEL.get(status, status)
        status_class = f"ct-status-{status}"
        client = html.escape(str(c.get("client_label") or "Клиент"))
        time_lbl = html.escape(str(c.get("time_label") or "—"))
        script = html.escape(str(c.get("opening_script") or ""))
        deadline = c.get("deadline")
        deadline_html = (
            f"<span class=\"ct-deadline\"> · до {html.escape(str(deadline))}</span>"
            if deadline else ""
        )
        rows += (
            f"<article class=\"ct-row\">"
            f"<div class=\"ct-row-header\">"
            f"<span class=\"ct-client\">{client}</span>"
            f"<span class=\"ct-time\">{time_lbl}</span>"
            f"<span class=\"ct-badge {status_class}\">{html.escape(status_label)}</span>"
            f"{deadline_html}"
            f"</div>"
            f"<div class=\"ct-script\">«{script}»</div>"
            f"</article>"
        )
    return (
        f"<div class=\"section-bar\">{label}</div>"
        f"<section class=\"call-tomorrow\">{rows}</section>"
    )


_STAGE_SCRIPT_FALLBACKS: dict[str, list[str]] = {
    "contact_start": [
        "Доброе утро! Удобно ли сейчас 2 минуты — я кратко.",
        "Меня зовут [имя], компания Договор24. Вы оставляли заявку — хочу уточнить детали.",
        "Подскажите, вы сейчас рассматриваете варианты или уже определились?",
    ],
    "qualification_primary": [
        "Чем занимается ваша компания? Хочу понять, как лучше подобрать вариант.",
        "Сколько сотрудников работает с документами — это поможет точнее рассчитать.",
        "Вы уже пробовали электронный документооборот или пока всё на бумаге?",
    ],
    "needs_discovery": [
        "Расскажите, какая задача сейчас самая болезненная — я запишу.",
        "Если убрать одну проблему с документами — что было бы важнее всего?",
        "Что сейчас занимает больше всего времени при работе с договорами?",
    ],
    "presentation": [
        "Смотрите, под вашу задачу подходит вот это — объясняю за 1 минуту.",
        "У нас есть два варианта; скажите, что важнее — скорость или цена?",
        "Вот конкретный кейс схожей компании — покажу, как они сэкономили.",
    ],
    "objection_handling": [
        "Понял вас. Это распространённое сомнение — давайте разберём по шагам.",
        "Если убрать этот вопрос — в целом решение подходит?",
        "Что именно смущает — цена, сроки или что-то другое?",
    ],
    "completion_next_step": [
        "Итак, договорились: [дата/время] — я пришлю детали на почту. Верно?",
        "Давайте зафиксируем следующий шаг: что именно вы сделаете до [дата]?",
        "Хорошо, тогда я звоню в [время]. Вам удобно или лучше перенести?",
    ],
    "cross_stage_transition": [
        "Прежде чем перейти к деталям — уточните, как вы в целом принимаете такие решения?",
        "Хочу убедиться, что мы говорим об одном и том же — сформулируйте своими словами.",
        "На каком этапе сейчас находится ваш вопрос — вы уже сравниваете варианты?",
    ],
}

_STAGE_SCRIPT_GENERIC: list[str] = [
    "Подведём итог: что конкретно мы договорились сделать к следующему разговору?",
    "Что для вас сейчас важнее — скорость решения или детальный разбор вариантов?",
    "Давайте зафиксируем следующий шаг — когда вам удобно созвониться ещё раз?",
]


def _build_situation_scripts(
    key_problem: dict[str, Any],
    recommendations: list[dict[str, Any]],
    score_by_stage: list[dict[str, Any]],
) -> list[str]:
    """Build 3 situation scripts from existing payload: better_phrasing from recommendations
    filtered/ranked by relevance to priority stage, with deterministic stage fallbacks."""
    # Collect better_phrasing from non-trivial recommendation cards (already LLM-generated)
    scripts: list[str] = []
    problem_title = str(key_problem.get("title") or "").strip().lower()
    for card in recommendations:
        phrase = str(card.get("better_phrasing") or "").strip()
        title = str(card.get("title") or "").strip()
        if not phrase or phrase in {"Уточнить формулировку и закрепить следующий шаг.", "Проверить полноту анализов и повторить запуск при необходимости."}:
            continue
        if phrase not in scripts:
            scripts.append(phrase)
        if len(scripts) >= 3:
            break

    # Fill remaining slots with stage-specific fallback templates
    if len(scripts) < 3:
        priority_stage_code = next(
            (item.get("stage_code") or item.get("funnel_label") or "" for item in score_by_stage if item.get("is_priority")),
            "",
        )
        fallbacks = _STAGE_SCRIPT_FALLBACKS.get(str(priority_stage_code), _STAGE_SCRIPT_GENERIC)
        for fb in fallbacks:
            if fb not in scripts:
                scripts.append(fb)
            if len(scripts) >= 3:
                break

    if len(scripts) < 3:
        for fb in _STAGE_SCRIPT_GENERIC:
            if fb not in scripts:
                scripts.append(fb)
            if len(scripts) >= 3:
                break

    return scripts[:3]


def _build_stage_score_rows(score_by_stage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert aggregated score_by_stage payload into render-ready table rows with visual bars."""
    rows = []
    for item in score_by_stage:
        score = item.get("score")
        score_float = float(score) if score is not None else None
        score_on_5 = round(score_float / 2.0, 1) if score_float is not None else None
        bar_pct = round((score_on_5 / 5.0) * 100) if score_on_5 is not None else 0
        bar_pct = max(0, min(100, bar_pct))
        rows.append({
            "funnel_label": str(item.get("funnel_label") or ""),
            "stage_name": str(item.get("stage_name") or ""),
            "score": _value(score_on_5),
            "score_float": score_float,
            "bar_pct": bar_pct,
            "bar_text": _progress_bar_20(score_on_5),
            "is_priority": bool(item.get("is_priority")),
            "criteria_detail": list(item.get("criteria_detail") or []) or None,
        })
    return rows


def _progress_bar_20(score: float | None) -> str:
    """Return the v5-style 20-char progress bar on a 0-5 scale."""
    if score is None:
        return "—"
    filled = max(0, min(20, round((score / 5.0) * 20)))
    return ("█" * filled) + ("░" * (20 - filled))


def _build_money_on_table_data(
    *,
    call_list_raw: list[dict[str, Any]],
    call_outcomes: dict[str, Any],
    override: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build the fixed-structure v5 block 'ДЕНЬГИ НА СТОЛЕ' with honest fallbacks."""
    override = dict(override or {})
    if any(override.get(key) for key in ("body", "highlight_line", "reason_line", "note")):
        return {
            "body": str(override.get("body") or ""),
            "highlight_line": str(override.get("highlight_line") or ""),
            "reason_line": str(override.get("reason_line") or ""),
            "note": str(override.get("note") or ""),
        }
    open_rows = [row for row in call_list_raw if str(row.get("status") or "") == "open"]
    open_count = int(call_outcomes.get("open_count") or len(open_rows) or 0)
    if open_rows:
        first_open = open_rows[0]
        client = _manager_reader_value(first_open.get("client_or_phone"), "клиент")
        context = _call_context_label(
            str(first_open.get("status") or ""),
            first_open.get("deadline"),
            first_open.get("reason"),
        )
        return {
            "body": f"{open_count} открытых звонк(ов). Ближайшая незакрытая возможность: {client}.",
            "highlight_line": "Потенциал в деньгах не определён текущим runtime contract и требует внешней CRM/прайсинговой логики.",
            "reason_line": f"Причина: звонок остался без зафиксированного следующего шага. Контекст: {context}.",
            "note": "Блок сохранён в формате v5; при отсутствии revenue-данных runtime честно показывает structural fallback.",
        }
    return {
        "body": "Открытых возможностей на выбранной выборке не найдено.",
        "highlight_line": "Денежный потенциал не зафиксирован.",
        "reason_line": "Причина: все звонки либо доведены до статуса, либо не содержат открытого follow-up.",
        "note": "При появлении CRM/pricing-данных сюда будет подставляться сумма без изменения формата блока.",
    }


def _build_warm_pipeline_data(
    *,
    call_list_raw: list[dict[str, Any]],
    call_outcomes: dict[str, Any],
) -> dict[str, Any]:
    """Build the fixed-structure v5 block 'PIPELINE' from existing call list/classification."""
    warm_rows = [
        row
        for row in call_list_raw
        if str(row.get("call_type") or "").lower() in {"warm", "hot"}
        or str(row.get("scenario_type") or "").lower() in {"warm", "hot", "warm_lead", "inbound_hot"}
    ]
    total = len(warm_rows)
    agreed = sum(1 for row in warm_rows if str(row.get("status") or "") == "agreed")
    rescheduled = sum(1 for row in warm_rows if str(row.get("status") or "") == "rescheduled")
    refusal = sum(1 for row in warm_rows if str(row.get("status") or "") == "refusal")
    open_count = sum(1 for row in warm_rows if str(row.get("status") or "") == "open")
    contacts = [
        {
            "client": _manager_reader_value(row.get("client_or_phone"), "Клиент"),
            "phone": _manager_reader_value(row.get("client_or_phone"), "—"),
            "status": _call_context_label(
                str(row.get("status") or ""),
                row.get("deadline"),
                row.get("reason"),
            ),
        }
        for row in warm_rows
        if str(row.get("status") or "") == "open"
    ][:5]
    conversion = round((agreed / total) * 100) if total else 0
    if total <= 0:
        return {
            "summary_line": "Тёплые и горячие лиды в текущем срезе не выделены.",
            "counts_line": "0 → Договорились · 0 → Перенос · 0 → Отказ · 0 → Открыт",
            "conversion_line": "Конверсия тёплых: нет базы для расчёта.",
            "average_line": "Среднее: нет базы для сравнения.",
            "contacts": [],
        }
    return {
        "summary_line": f"{total} повторных/тёплых звонков сегодня.",
        "counts_line": f"{agreed} → Договорились · {rescheduled} → Перенос · {refusal} → Отказ · {open_count} → Открыт",
        "conversion_line": f"Конверсия тёплых: {conversion}% ({agreed} из {total})",
        "average_line": (
            "Среднее: нет базы для сравнения."
            if int(call_outcomes.get("tech_service_count") or 0) >= 0
            else "Среднее: нет данных."
        ),
        "contacts": contacts,
    }


def _build_situation_client_need(key_problem: dict[str, Any]) -> str:
    """Return a deterministic 'Что хотел клиент' line for v5 situation block."""
    client_need = str(key_problem.get("client_need") or key_problem.get("customer_need") or "").strip()
    if client_need:
        return _clean_reader_text(client_need)
    return "Клиент ждал конкретики под свой контекст и понятного следующего шага."


def _build_situation_body(*, key_problem: dict[str, Any], score_by_stage: list[dict[str, Any]]) -> str:
    """Return a compact non-repetitive intro for СИТУАЦИЯ ДНЯ."""
    row = _priority_stage_row(score_by_stage)
    title = str(key_problem.get("title") or "").strip()
    if row is not None:
        stage = str(row.get("stage_name") or "приоритетный этап")
        score = str(row.get("score") or "—")
        if title and title.lower() not in stage.lower():
            return f"Главный сигнал дня: {title}. Он проявился на этапе «{stage}» ({score}/5)."
        return f"Главный сигнал дня проявился на этапе «{stage}» ({score}/5)."
    description = _clean_reader_text(str(key_problem.get("description") or ""))
    if description:
        return description
    return "На этой выборке нет доминирующей проблемы по этапу воронки. Держим фокус на конкретном следующем шаге."


def _build_situation_manager_task(
    *,
    score_by_stage: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
) -> str:
    """Return a deterministic 'Наша задача' line for v5 situation block."""
    priority_row = _priority_stage_row(score_by_stage)
    if priority_row is not None:
        return (
            f"Поднять этап '{priority_row.get('stage_name') or 'приоритетный этап'}' до 4.0+ "
            "и до презентации фиксировать 2–3 уточняющих вопроса."
        )
    if recommendations:
        return _clean_reader_text(str(recommendations[0].get("better_phrasing") or ""))
    return "Доводить каждый разговор до понятной договорённости и фиксированного следующего шага."


def _build_situation_why_it_works(
    *,
    recommendations: list[dict[str, Any]],
    score_by_stage: list[dict[str, Any]],
) -> str:
    """Return the v5 'Почему работает' explanation."""
    if recommendations:
        return _clean_reader_text(
            str(recommendations[0].get("why_this_works") or recommendations[0].get("reason") or "")
        ) or "Конкретика переводит разговор из намерения в договорённость."
    priority_row = _priority_stage_row(score_by_stage)
    if priority_row is not None:
        return (
            f"Когда менеджер усиливает этап '{priority_row.get('stage_name') or 'приоритетный этап'}', "
            "клиент слышит решение под свой контекст, а не шаблонную подачу."
        )
    return "Фокус на одном повторяющемся паттерне ускоряет улучшение качества звонков."


def _build_v5_call_breakdown_section(
    *,
    section: dict[str, Any],
    recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map legacy call_breakdown payload to the approved v5 3-column structure."""
    explicit_rows = [list(map(str, row)) for row in (section.get("rows") or []) if isinstance(row, (list, tuple))]
    if explicit_rows:
        return {
            "summary_line": str(
                section.get("summary_line")
                or (
                    f"{section.get('client_label') or 'Клиент'} · {section.get('time_label') or '—'}"
                    if section.get("client_label") or section.get("time_label")
                    else "Звонок выбран как наиболее показательный для основного паттерна дня."
                )
            ),
            "rows": explicit_rows[:5],
        }
    rows: list[list[str]] = []
    for idx, item in enumerate(section.get("to_fix") or []):
        better = ""
        if idx < len(recommendations):
            better = _clean_reader_text(
                str(recommendations[idx].get("better_phrasing") or recommendations[idx].get("title") or "")
            )
        if not better:
            better = _clean_reader_text(str((section.get("recommendation") or {}).get("better_phrasing") or "Следующий шаг нужно формулировать конкретнее."))
        rows.append(
            [
                "—",
                f"{item.get('label') or 'Момент разговора'}: {item.get('interpretation') or 'Требует уточнения.'}",
                better,
            ]
        )
    if not rows:
        rows.append(
            [
                "—",
                "Недостаточно данных для детального покадрового разбора звонка.",
                _clean_reader_text(str((section.get("recommendation") or {}).get("better_phrasing") or "Повторите разбор после следующего полного запуска.")),
            ]
        )
    return {
        "summary_line": (
            f"{section.get('client_label') or 'Клиент'} · {section.get('time_label') or '—'}"
            if section.get("client_label") or section.get("time_label")
            else "Звонок выбран как наиболее показательный для основного паттерна дня."
        ),
        "rows": rows[:5],
    }


def _build_voice_reply_line(context: str | None, quote: str | None) -> str:
    """Build a safe fallback reply suggestion for voice-of-customer."""
    context_text = _clean_reader_text(str(context or ""))
    if context_text:
        return f"{context_text} Ответить: уточнить задачу клиента и привязать предложение к его процессу."
    quote_text = _clean_reader_text(str(quote or ""))
    if quote_text:
        return "Смысл: клиенту не хватило конкретики. Ответить: сначала уточнить контекст, затем давать решение."
    return "Смысл: нужен более точный ответ под ситуацию клиента."


def _normalize_pattern_key(text: str) -> str:
    """Return a stable key for grouping repeated coaching intent."""
    cleaned = re.sub(r"\s+", " ", _clean_reader_text(text).lower()).strip()
    cleaned = re.sub(r"[^\wа-яё ]+", "", cleaned)
    return cleaned[:120]


def _group_voice_rows_by_intent(rows: list[list[str]]) -> list[list[str]]:
    """Group several customer quotes when they lead to the same coaching intent."""
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        client = str(row[0] if len(row) > 0 else "Клиент")
        quote = str(row[1] if len(row) > 1 else "—")
        intent = str(row[2] if len(row) > 2 else "")
        key = _normalize_pattern_key(intent or quote)
        if key not in grouped:
            grouped[key] = {"clients": [], "quotes": [], "intent": intent}
            order.append(key)
        if client and client not in grouped[key]["clients"]:
            grouped[key]["clients"].append(client)
        if quote and quote != "—" and quote not in grouped[key]["quotes"]:
            grouped[key]["quotes"].append(quote)
        if intent and not grouped[key]["intent"]:
            grouped[key]["intent"] = intent
    result: list[list[str]] = []
    for index, key in enumerate(order, start=1):
        item = grouped[key]
        clients = "; ".join(item["clients"][:3]) or "Клиенты"
        quotes = " / ".join(item["quotes"][:3]) or "—"
        result.append([f"Паттерн {index}: {clients}", quotes, item["intent"] or "Смысл требует уточнения на разборе."])
    return result


def _build_v5_voice_of_customer_section(
    *,
    section: dict[str, Any],
    recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map legacy voice payload to the approved v5 3-column structure."""
    explicit_rows = [list(map(str, row)) for row in (section.get("rows") or []) if isinstance(row, (list, tuple))]
    if explicit_rows:
        return {
            "intro": str(
                section.get("intro")
                or "Сгруппированы повторяющиеся клиентские сигналы: один смысл и один способ ответа на несколько похожих цитат."
            ),
            "rows": _group_voice_rows_by_intent(explicit_rows)[:3],
        }
    reply_seed = _clean_reader_text(
        str(recommendations[0].get("better_phrasing") or "")
    ) if recommendations else ""
    rows = [
        [
            f"{item.get('client_label') or 'Клиент'} · {item.get('time_label') or '—'}",
            item.get("quote") or "—",
            str(item.get("interpretation") or "").strip()
            or (
                _build_voice_reply_line(item.get("context"), item.get("quote"))
                + (f" База ответа: {reply_seed}" if reply_seed else "")
            ),
        ]
        for item in section.get("situations") or []
    ]
    return {
        "intro": "Сгруппированы повторяющиеся клиентские сигналы: один смысл и один способ ответа на несколько похожих цитат.",
        "rows": _group_voice_rows_by_intent(rows)[:3],
    }


def _build_v5_additional_situations_section(*, section: dict[str, Any]) -> dict[str, Any]:
    """Expand compact additional situations into the v5 four-row card structure."""
    situations: list[dict[str, Any]] = []
    for item in section.get("situations") or []:
        title = _clean_reader_text(str(item.get("title") or "Ситуация"))
        interpretation = _clean_reader_text(str(item.get("interpretation") or ""))
        kind = str(item.get("kind") or "gap")
        situations.append(
            {
                "badge": "Сильная сторона" if kind == "strength" else "Зона роста",
                "title": title,
                "client_said": _clean_reader_text(str(item.get("client_said") or "")) or interpretation or "Ситуация повторяется в нескольких звонках.",
                "meant": _clean_reader_text(str(item.get("meant") or "")) or (
                    "За этим стоит устойчивый рабочий паттерн, который стоит сохранить."
                    if kind == "strength"
                    else "Клиент не получил достаточно конкретики или фиксации следующего шага."
                ),
                "how_to": _clean_reader_text(str(item.get("how_to") or "")) or (
                    "Повторять удачную формулировку и усиливать её короткой привязкой к задаче клиента."
                    if kind == "strength"
                    else "Задать уточняющий вопрос, затем зафиксировать конкретный следующий шаг и дедлайн."
                ),
                "why": _clean_reader_text(str(item.get("why") or "")) or (
                    "Такой паттерн помогает удерживать доверие и ускоряет движение к договорённости."
                    if kind == "strength"
                    else "Конкретика снижает зависание звонка и переводит разговор в управляемый follow-up."
                ),
            }
        )
    return {"situations": situations[:3]}


def _build_challenge_data(
    *,
    score_by_stage: list[dict[str, Any]],
    key_problem: dict[str, Any],
    total_calls: int,
) -> dict[str, str]:
    """Build the fixed-structure v5 challenge block."""
    priority_row = _priority_stage_row(score_by_stage)
    stage_name = priority_row.get("stage_name") if priority_row else "приоритетный этап"
    calls_basis = max(total_calls, 1)
    target = max(1, round(calls_basis * 0.75))
    today_count = int(key_problem.get("pattern_count") or 0)
    return {
        "goal_line": f"Из следующих {calls_basis} звонков — отработать '{stage_name}' минимум в {target} случаях.",
        "today_line": f"Сегодня: {today_count} звонк(ов) с повторением основного паттерна дня.",
        "record_line": "Рекорд: нет базы (первый период отслеживания).",
        "phrase_line": "Сначала уточняем контекст клиента, затем даём решение и фиксируем следующий шаг.",
    }


def _priority_icon_for_contact(status: str) -> str:
    """Return v5 priority icon for call_tomorrow row."""
    return {"agreed": "🔴", "rescheduled": "🟡", "open": "🔵"}.get(status, "🔵")


def _priority_label_for_contact(status: str) -> str:
    """Return v5 priority label for call_tomorrow row."""
    return {"agreed": "Горячий", "rescheduled": "Тёплый", "open": "Открытый"}.get(status, "Открытый")


def _deadline_label_for_contact(item: dict[str, Any]) -> str:
    """Return manager-facing timing/reason label for a follow-up row."""
    status = str(item.get("status") or "open")
    deadline = _format_deadline_human(str(item.get("deadline") or "").strip() or None)
    if deadline:
        return f"Срок: {deadline}"
    if status == "rescheduled":
        return "Повод: вернуться к разговору"
    if status == "agreed":
        return "Повод: подтвердить договорённость"
    return "Повод: закрыть неопределённость"


def _call_goal_for_contact(item: dict[str, Any]) -> str:
    """Return a concrete goal for a call-tomorrow action card."""
    status = str(item.get("status") or "open")
    if status == "rescheduled":
        return "Вернуть разговор и зафиксировать следующий шаг."
    if status == "agreed":
        return "Подтвердить договорённость и снять оставшиеся вопросы."
    return "Понять текущий интерес клиента и договориться о конкретном следующем шаге."


def _first_phrase_for_contact(item: dict[str, Any]) -> str:
    """Return a usable first phrase, not a next-step recap."""
    status = str(item.get("status") or "open")
    deadline = _format_deadline_human(str(item.get("deadline") or "").strip() or None)
    if status == "rescheduled" and deadline:
        return f"Добрый день! Договаривались вернуться {deadline}; удобно сейчас коротко продолжить?"
    if status == "rescheduled":
        return "Добрый день! Возвращаюсь к нашему разговору; удобно сейчас коротко продолжить?"
    if status == "agreed":
        return "Добрый день! Хочу подтвердить нашу договорённость и уточнить один следующий шаг."
    return "Добрый день! Хочу коротко понять, актуален ли вопрос, и договориться о следующем шаге."


def _build_v5_call_tomorrow_section(*, section: dict[str, Any]) -> dict[str, Any]:
    """Map legacy call_tomorrow payload to the approved v5 table structure."""
    contacts = list(section.get("contacts") or [])
    rows = [
        [
            f"{_priority_icon_for_contact(str(item.get('status') or 'open'))} {_priority_label_for_contact(str(item.get('status') or 'open'))}",
            _manager_reader_value(item.get("client_label"), "Клиент"),
            _deadline_label_for_contact(item),
            _call_goal_for_contact(item),
            _first_phrase_for_contact(item),
        ]
        for item in contacts
    ]
    return {
        "contacts": contacts,
        "rows": rows[:5],
    }


def _build_morning_card_data(
    *,
    header: dict[str, Any],
    call_outcomes: dict[str, Any],
    total_calls: int,
    call_list_raw: list[dict[str, Any]],
    focus_of_week: dict[str, Any],
) -> dict[str, Any]:
    """Build structured morning card data from existing payload fields. No LLM, no history."""
    manager_name = str(header.get("manager_name") or "")
    first_name = manager_name.split()[0] if manager_name.split() else "Коллега"
    agreed = int(call_outcomes.get("agreed_count") or 0)
    open_count = int(call_outcomes.get("open_count") or 0)
    summary_line = f"{total_calls} звонков → {agreed} договорённостей, {open_count} открытых"
    open_calls_raw = [row for row in call_list_raw if str(row.get("status") or "") == "open"][:3]
    open_calls = [
        {
            "time": _short_time(row.get("time")),
            "client": _manager_reader_value(row.get("client_or_phone"), "Клиент не определён"),
            "status": "Открыт",
        }
        for row in open_calls_raw
    ]
    challenge = str(
        focus_of_week.get("text")
        or "Каждый звонок должен заканчиваться конкретным следующим шагом."
    )
    lines = [f"{first_name}, доброе утро!", summary_line, ""]
    if open_calls:
        lines.append("Открытые звонки (нет договорённости):")
        for call in open_calls:
            lines.append(f"• {call['time']} · {call['client']} · {call['status']}")
    else:
        lines.append("Открытых звонков нет — отличный результат!")
    lines += ["", f"Фокус: {challenge}"]
    return {
        "greeting": f"{first_name}, доброе утро!",
        "summary_line": summary_line,
        "open_calls": open_calls,
        "challenge": challenge,
        "text": "\n".join(lines),
    }


def _build_manager_daily_narrative_block(payload: dict[str, Any]) -> dict[str, str]:
    """Build reader-facing executive summary and progress line."""
    kpi = payload["kpi_overview"]
    interpretation = _manager_reader_value(kpi.get("interpretation_label"), "День требует дополнительной калибровки")
    narrative = (
        (payload.get("narrative_day_conclusion") or {}).get("text")
        or f"{interpretation}. Главная задача дня — удержать сильные паттерны и довести завершение звонков до конкретной договорённости."
    )
    narrative = _clean_reader_text(narrative).replace("без полного полный прогон", "без повторного полного прогона")
    avg = _manager_reader_value(kpi.get("average_score"), "нет данных")
    period_avg = _manager_reader_value(kpi.get("score_vs_period_avg"), "нет базы сравнения")
    delta = _manager_reader_value(kpi.get("delta_vs_period_avg"), "нет базы сравнения")
    progress = f"Прогресс: {avg} сегодня vs {period_avg} среднее за период · delta {delta}."
    if period_avg == "нет базы сравнения":
        progress = "Прогресс: база для сравнения по периоду ещё не накоплена, поэтому следим за устойчивостью паттернов внутри дня."
    return {"summary": narrative, "progress": progress}


def _manager_reader_value(value: Any, fallback: str) -> str:
    """Return reader-friendly value for manager_daily without raw service placeholders."""
    text = _value(value, fallback)
    if text == "not available":
        return fallback
    return text


def _manager_tile_class(item: dict[str, Any]) -> str:
    """Map manager_daily summary card tone to reference tile class."""
    tone = str(item.get("tone") or "blue")
    if tone == "positive":
        return "green"
    if tone == "focus":
        return "yellow"
    if tone == "problem":
        return "red"
    return "blue"


def _outcome_col_class(item: dict[str, Any]) -> str:
    """Map outcome column tone to CSS class for the outcome-table."""
    tone = str(item.get("tone") or "neutral")
    if tone == "positive":
        return "green"
    if tone == "focus":
        return "yellow"
    if tone == "problem":
        return "red-danger"
    if tone == "warning":
        return "orange"
    return "blue"


def _manager_outcome_tile_class(item: dict[str, Any]) -> str:
    """Map call outcome card to reference tile tint."""
    label = str(item.get("label") or "").lower()
    if "отказ" in label:
        return "red-danger"
    if "открыт" in label:
        return "yellow-open"
    if "перен" in label:
        return "yellow"
    return "green"


def _render_review_item_html(text: str, *, positive: bool) -> str:
    """Highlight metric prefix in review bullets close to the reference layout."""
    if ":" not in text:
        return html.escape(text)
    prefix, suffix = text.split(":", 1)
    metric_class = "green" if positive else "red"
    if not positive and ("2." in prefix or "3." in prefix):
        metric_class = "orange"
    return f"<span class=\"metric {metric_class}\">{html.escape(prefix)}:</span>{html.escape(suffix)}"


def _render_manager_daily_recommendation_card(card: dict[str, Any], index: int) -> str:
    """Render one recommendation card close to the approved reference."""
    tone = " orange" if card.get("tone") == "orange" else ""
    priority_tone = str(card.get("priority_tone") or "tomorrow")
    return (
        f"<article class=\"recommendation-card{tone}\">"
        f"<div class=\"priority-pill {html.escape(priority_tone)}\">{html.escape(str(card.get('priority_tag') or 'Сделай завтра'))}</div>"
        f"<div class=\"rec-title\">{index}. {html.escape(str(card.get('title') or 'Рекомендация'))}</div>"
        f"<div class=\"rec-context\">{html.escape(str(card.get('context') or card.get('body') or 'Контекст будет уточнён на разборе.'))}</div>"
        "<div class=\"example-grid\">"
        "<div class=\"example-box before\">"
        "<div class=\"example-title\">Как звучало:</div>"
        f"<p>{html.escape(str(card.get('how_it_sounded') or 'Формулировка была слишком общей.'))}</p>"
        "</div>"
        "<div class=\"example-box after\">"
        "<div class=\"example-title\">Как лучше:</div>"
        f"<p>{html.escape(str(card.get('better_phrasing') or 'Сформулируй следующий шаг конкретно.'))}</p>"
        "</div>"
        "</div>"
        f"<div class=\"why-line\"><strong>Почему это работает:</strong> {html.escape(str(card.get('why_this_works') or 'Конкретика помогает клиенту увидеть следующий шаг.'))}</div>"
        "</article>"
    )


def _manager_signal_reason(section: dict[str, Any]) -> str:
    """Flatten signal explanation into one reader-facing sentence."""
    items = section.get("items") or []
    if not items:
        return "Этот эпизод можно использовать как модель для следующих звонков."
    return _clean_reader_text(str(items[0]).replace("Почему это правильная модель:", "").strip())


def _manager_daily_page_header(metadata_line: str) -> str:
    """Render manager_daily page header."""
    return (
        "<header>"
        f"<div class=\"meta-line\">{html.escape(metadata_line)}</div>"
        "<div class=\"meta-rule\"></div>"
        "</header>"
    )


def _manager_daily_page_footer(footer: str, page_number: int) -> str:
    """Render manager_daily page footer."""
    return (
        "<footer class=\"footer\">"
        "<div class=\"footer-rule\"></div>"
        "<div class=\"footer-content\">"
        f"<div>{html.escape(footer)}</div>"
        f"<div>{page_number}</div>"
        "</div></footer>"
    )


def _clean_reader_text(text: str) -> str:
    """Clean leftover service wording from reader-facing text."""
    cleaned = text.replace("not available", "нет данных").replace("Note:", "").strip()
    return (
        cleaned.replace("persisted payload", "текущей выборке")
        .replace("rerun pipeline", "полный прогон")
        .replace("full rerun", "полный прогон")
        .replace("rerun", "повторный прогон")
        .replace("без полного полный прогон", "без повторного полного прогона")
        .replace("без полного rerun", "без повторного полного прогона")
        .replace("coaching takeaway", "ориентир")
    )


_CALL_TYPE_SHORT: dict[str, str] = {
    "sales_primary": "Продажи",
    "sales_repeat": "Повторный",
    "mixed": "Смешанный",
    "support": "Поддержка",
    "internal": "Внутренний",
    "other": "Другое",
}

_SCENARIO_TYPE_SHORT: dict[str, str] = {
    "cold_outbound": "Холодный",
    "hot_incoming_contact": "Горячий",
    "warm_webinar_or_lead": "Тёплый/заявка",
    "repeat_contact": "Повторный",
    "after_signed_document": "После подписания",
    "post_sale_follow_up": "Постпродажный",
    "mixed_scenario": "Смешанный",
    "other": "Другое",
}


def _call_topic_label(call_type: str | None, scenario_type: str | None) -> str:
    """Build short topic string for call list Тема column from classification fields."""
    type_label = _CALL_TYPE_SHORT.get(str(call_type or ""), "")
    scenario_label = _SCENARIO_TYPE_SHORT.get(str(scenario_type or ""), "")
    if type_label and scenario_label:
        return f"{type_label} · {scenario_label}"
    return type_label or scenario_label or "—"


def _call_context_label(status: str, deadline: str | None, reason: str | None) -> str:
    """Build short Контекст for a call list row from follow_up outcome data."""
    dl = _format_deadline_human(deadline) if deadline else None
    if status == "agreed":
        return f"до {dl}" if dl else "—"
    if status == "rescheduled":
        return f"→ {dl}" if dl else "перезвон"
    if reason and status in ("open", "refusal"):
        short = reason[:28].rstrip()
        return short + "…" if len(reason) > 28 else short
    return "—"


def _call_status_label(value: Any) -> str:
    """Map internal call status to reader-facing Russian label."""
    mapping = {
        "agreed": "Договорённость",
        "rescheduled": "Перенесли",
        "refusal": "Отказ",
        "open": "Открыт",
    }
    text = _manager_reader_value(value, "Статус не определён")
    return mapping.get(text, text)


def _call_level_label(value: Any) -> str:
    """Map internal quality level to reader-facing label."""
    mapping = {
        "strong": "Сильный",
        "baseline": "Базовый",
        "problematic": "Проблемный",
    }
    text = _manager_reader_value(value, "Уровень не определён")
    return mapping.get(text, text)


def _manager_status_class(value: Any) -> str:
    """Return CSS class for a reader-facing status label."""
    text = _call_status_label(value).lower()
    if "договор" in text:
        return "agreed"
    if "перен" in text:
        return "rescheduled"
    if "отказ" in text:
        return "refusal"
    if "открыт" in text:
        return "open"
    return "open"


def _manager_status_fill(value: Any) -> tuple[int, int, int]:
    """Return PDF fill color for call status cell."""
    mapping = {
        "agreed": (219, 231, 211),
        "rescheduled": (239, 226, 185),
        "refusal": (244, 221, 221),
        "open": (246, 223, 207),
    }
    return mapping[_manager_status_class(value)]


def _manager_status_text_color(
    value: Any,
    black: tuple[int, int, int],
    green: tuple[int, int, int],
    amber: tuple[int, int, int],
    red: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Return PDF text color for call status cell."""
    status = _manager_status_class(value)
    if status == "agreed":
        return green
    if status == "rescheduled":
        return (138, 107, 9)
    if status == "refusal":
        return red
    if status == "open":
        return amber
    return black
    if kind == "header_card":
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
            "<article class=\"header-card\">"
            f"<div class=\"header-manager\">{html.escape(str(section.get('manager_name') or '—'))}</div>"
            f"<div class=\"header-meta\">{html.escape(str(section.get('report_date') or '—'))} · "
            f"{html.escape(_value(section.get('calls_count')))} звонков</div>"
            f"<div class=\"header-score\">Балл дня: {html.escape(_value(section.get('day_score')))} / 5</div>"
            "</article></div></section>"
        )
    if kind == "outcome_table":
        header = "".join(
            (
                f"<td class=\"outcome-cell {_outcome_col_class(item)}\">"
                f"<div class=\"outcome-value\">{html.escape(_manager_reader_value(item.get('value'), '—'))}</div>"
                f"<div class=\"outcome-label\">{html.escape(str(item['label']))}</div>"
                "</td>"
            )
            for item in section.get("outcome_cols") or []
        )
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><table class=\"outcome-table\"><tbody><tr>{header}</tr></tbody></table></div></section>"
    if kind == "money_focus":
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><article class=\"focus-panel warning\">"
            f"<p>{html.escape(str(section.get('body') or ''))}</p>"
            f"<p><strong>{html.escape(str(section.get('highlight_line') or ''))}</strong></p>"
            f"<p>{html.escape(str(section.get('reason_line') or ''))}</p>"
            f"<p class=\"muted\">{html.escape(str(section.get('note') or ''))}</p>"
            "</article></div></section>"
        )
    if kind == "pipeline_summary":
        contacts = "".join(
            f"<tr><td>{html.escape(str(item.get('client') or '—'))}</td><td>{html.escape(str(item.get('phone') or '—'))}</td><td>{html.escape(str(item.get('status') or '—'))}</td></tr>"
            for item in section.get("contacts") or []
        ) or "<tr><td colspan=\"3\">Тёплые лиды без обратного звонка не найдены.</td></tr>"
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
            f"<p>{html.escape(str(section.get('summary_line') or ''))}</p>"
            f"<p>{html.escape(str(section.get('counts_line') or ''))}</p>"
            f"<p><strong>{html.escape(str(section.get('conversion_line') or ''))}</strong></p>"
            f"<p class=\"muted\">{html.escape(str(section.get('average_line') or ''))}</p>"
            "<table><thead><tr><th>Клиент</th><th>Телефон</th><th>Статус</th></tr></thead>"
            f"<tbody>{contacts}</tbody></table></div></section>"
        )
    if kind == "stage_scores_table":
        rows = []
        for row in section.get("stage_rows") or []:
            rows.append(
                "<tr>"
                f"<td>{html.escape((str(row.get('funnel_label') or '') + ' ' + str(row.get('stage_name') or '')).strip())}</td>"
                f"<td>{html.escape(str(row.get('score') or '—'))}</td>"
                "<td>—</td>"
                f"<td>{html.escape(str(row.get('bar_text') or '—'))}</td>"
                f"<td>{'●' if row.get('is_priority') else ('✓' if row.get('bar_pct', 0) >= 80 else '—')}</td>"
                "</tr>"
            )
            for crit in row.get("criteria_detail") or []:
                rows.append(
                    "<tr class=\"sub-row\">"
                    f"<td colspan=\"5\">{html.escape(str(crit.get('name') or 'Критерий'))}: {html.escape(str(crit.get('score') or '—'))}</td>"
                    "</tr>"
                )
        body = "".join(rows) or "<tr><td colspan=\"5\">Данные по этапам появятся после накопления базы.</td></tr>"
        note = (
            f"<p class=\"muted\">{html.escape(str(section.get('note') or ''))}</p>"
            if section.get("note") else ""
        )
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
            "<table><thead><tr><th>Этап</th><th>Сегодня</th><th>Среднее</th><th>Шкала</th><th>Приоритет</th></tr></thead>"
            f"<tbody>{body}</tbody></table>{note}</div></section>"
        )
    if kind == "situation_card":
        scripts = "".join(f"<li>{html.escape(str(item))}</li>" for item in section.get("scripts") or [])
        example = dict(section.get("call_example") or {})
        example_html = (
            "<div class=\"mini-card\">"
            f"<strong>Пример из сегодня:</strong> {html.escape(str(example.get('client_label') or 'Клиент'))} · {html.escape(str(example.get('time_label') or '—'))}"
            + (
                f"<div class=\"muted\">{html.escape(str(example.get('reason_short') or ''))}</div>"
                if example.get("reason_short") else ""
            )
            + "</div>"
            if example.get("client_label") or example.get("time_label")
            else ""
        )
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><article class=\"focus-panel\">"
            f"<h3>{html.escape(str(section.get('situation_title') or section.get('label') or 'СИТУАЦИЯ ДНЯ'))}</h3>"
            f"<p>{html.escape(str(section.get('body') or ''))}</p>"
            f"<p><strong>Что хотел клиент:</strong> {html.escape(str(section.get('client_need') or 'Нет данных'))}</p>"
            f"<p><strong>Наша задача:</strong> {html.escape(str(section.get('manager_task') or 'Нет данных'))}</p>"
            f"{example_html}"
            "<div class=\"mini-card\"><strong>Варианты речёвок</strong><ol>"
            f"{scripts}</ol></div>"
            f"<p><strong>Почему работает:</strong> {html.escape(str(section.get('why_it_works') or ''))}</p>"
            "</article></div></section>"
        )
    if kind == "call_breakdown":
        rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(_value(cell))}</td>" for cell in row) + "</tr>"
            for row in section.get("rows") or []
        ) or "<tr><td colspan=\"3\">Недостаточно данных для разбора звонка.</td></tr>"
        intro = (
            f"<p class=\"muted\">{html.escape(str(section.get('summary_line') or ''))}</p>"
            if section.get("summary_line") else ""
        )
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">{intro}"
            "<table><thead><tr><th>Момент</th><th>Что было</th><th>Что лучше</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    if kind == "voice_of_customer":
        intro = (
            f"<p class=\"muted\">{html.escape(str(section.get('intro') or ''))}</p>"
            if section.get("intro") else ""
        )
        rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(_value(cell))}</td>" for cell in row) + "</tr>"
            for row in section.get("rows") or []
        ) or "<tr><td colspan=\"3\">Ситуации появятся после накопления материала по звонкам.</td></tr>"
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">{intro}"
            "<table><thead><tr><th>Клиент</th><th>Что сказал</th><th>Смысл → Как ответить</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    if kind == "expanded_situations":
        cards = "".join(
            "<article class=\"card\">"
            f"<h3>{html.escape(str(item.get('badge') or 'Ситуация'))} · {html.escape(str(item.get('title') or '—'))}</h3>"
            f"<p><strong>Что сказал клиент:</strong> {html.escape(str(item.get('client_said') or '—'))}</p>"
            f"<p><strong>Что имел в виду:</strong> {html.escape(str(item.get('meant') or '—'))}</p>"
            f"<p><strong>Как надо было:</strong> {html.escape(str(item.get('how_to') or '—'))}</p>"
            f"<p><strong>Почему так:</strong> {html.escape(str(item.get('why') or '—'))}</p>"
            "</article>"
            for item in section.get("situations") or []
        ) or "<article class=\"card\"><p>Дополнительные ситуации появятся после накопления данных по звонкам.</p></article>"
        return f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><div class=\"cards-grid\">{cards}</div></div></section>"
    if kind == "challenge_card":
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><article class=\"focus-panel\">"
            f"<p><strong>{html.escape(str(section.get('goal_line') or ''))}</strong></p>"
            f"<p>{html.escape(str(section.get('today_line') or ''))}</p>"
            f"<p>{html.escape(str(section.get('record_line') or ''))}</p>"
            f"<p><strong>Фраза для завтра:</strong> {html.escape(str(section.get('phrase_line') or ''))}</p>"
            "</article></div></section>"
        )
    if kind == "call_tomorrow":
        rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(_value(cell))}</td>" for cell in row) + "</tr>"
            for row in section.get("rows") or []
        ) or "<tr><td colspan=\"4\">Нет открытых контактов для перезвона.</td></tr>"
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\">"
            "<table><thead><tr><th>Приоритет</th><th>Клиент</th><th>Контекст</th><th>Скрипт открытия</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    if kind == "morning_card":
        calls = "".join(
            f"<li>{html.escape(str(item.get('client_label') or 'Клиент'))} — {html.escape(str(item.get('opening_script') or 'Скрипт не задан'))}</li>"
            for item in section.get("call_tomorrow_contacts") or []
        ) or "".join(
            f"<li>{html.escape(str(call.get('time', '—')))} · {html.escape(str(call.get('client', '—')))} · {html.escape(str(call.get('status', '—')))}</li>"
            for call in section.get("open_calls") or []
        ) or "<li>Открытых звонков нет.</li>"
        return (
            f"<section class=\"{' '.join(classes)}\">{title}<div class=\"section-body\"><article class=\"focus-panel\">"
            f"<h3>{html.escape(str(section.get('greeting') or ''))}</h3>"
            f"<p>{html.escape(str(section.get('summary_line') or ''))}</p>"
            + (
                f"<p><strong>{html.escape(str(section.get('financial_line') or ''))}</strong></p>"
                if section.get("financial_line") else ""
            )
            + "<p><strong>Позвони сегодня:</strong></p>"
            + f"<ul>{calls}</ul>"
            + f"<p><strong>Челлендж:</strong> {html.escape(str(section.get('challenge') or ''))}</p>"
            + "</article></div></section>"
        )
