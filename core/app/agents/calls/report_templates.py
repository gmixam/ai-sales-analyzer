"""Versioned report templates and bounded HTML/PDF rendering."""

from __future__ import annotations

import html
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ASSET_ROOT = Path(__file__).resolve().parent / "report_template_assets"
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
REPORT_RENDER_GENERATOR_PATH = "app.agents.calls.report_templates.render_report_artifact"


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


def render_report_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    """Render one final report artifact from normalized payload and active template assets."""
    template = load_report_template(str(payload["meta"]["preset"]))
    payload.setdefault("meta", {})
    payload["meta"]["report_template"] = {
        "preset": template.preset,
        "version": template.version,
        "template_id": template.template_id,
        "render_variant": f"template_pdf_{template.version}",
        "generator_path": REPORT_RENDER_GENERATOR_PATH,
    }
    report = _build_render_model(payload=payload, template=template)
    text = _render_text_report(report)
    html_doc = _render_html_report(report=report, template=template)
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
            "render_variant": f"template_pdf_{template.version}",
            "generator_path": REPORT_RENDER_GENERATOR_PATH,
            "semantic_asset": f"report_template_assets/{template.preset}/{template.version}/semantic.json",
            "visual_asset": f"report_template_assets/{template.preset}/{template.version}/visual.json",
            "layout_asset": f"report_template_assets/{template.preset}/{template.version}/layout.css",
        },
        "artifact": {
            "kind": "pdf_report",
            "filename": filename,
            "media_type": "application/pdf",
            "size_bytes": len(pdf_bytes),
            "page_count": page_count,
            "template_version": template.version,
            "template_id": template.template_id,
            "render_variant": f"template_pdf_{template.version}",
            "generator_path": REPORT_RENDER_GENERATOR_PATH,
        },
        "pdf_bytes": pdf_bytes,
        "morning_card_text": report.get("morning_card_text"),
    }


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
    total_calls = int(kpi.get("calls_count") or 0)
    narrative = _build_manager_daily_narrative_block(payload)
    call_outcomes = dict(payload.get("call_outcomes_summary") or {})
    call_list_raw = list(payload.get("call_list") or [])
    warm_pipeline = _build_warm_pipeline_data(call_list_raw=call_list_raw, call_outcomes=call_outcomes)
    money_on_table = _build_money_on_table_data(call_list_raw=call_list_raw, call_outcomes=call_outcomes)
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
            "day_score": _manager_reader_value(
                round(float(kpi.get("average_score")) / 20.0, 1) if kpi.get("average_score") is not None else None,
                "Нет базы",
            ),
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
            "body": _value(
                payload["key_problem_of_day"].get("description"),
                "На этой выборке нет доминирующей проблемы по этапу воронки. Держим фокус на завершении звонков с конкретным следующим шагом.",
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
        return [
            f"Менеджер: {section.get('manager_name') or '—'}",
            f"Дата: {section.get('report_date') or '—'}",
            f"Звонков: {_value(section.get('calls_count'))}",
            f"Балл дня: {_value(section.get('day_score'))} / 5",
        ]
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
            lines.append("Клиент | Что сказал | Смысл → Как ответить")
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
            return ["Приоритет | Клиент | Контекст | Скрипт открытия"] + [
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
    """Render manager_daily close to the approved HTML reference layout."""
    sections = {section["id"]: section for section in report["sections"]}
    day_summary = sections["day_summary"]
    executive = sections["executive_narrative"]
    signal = sections["signal_of_day"]
    focus = sections["main_focus_for_tomorrow"]
    review = sections["review_block"]
    problem = sections["key_problem_of_day"]
    recommendations = sections["recommendations"]
    outcomes = sections["call_outcomes_summary"]
    call_list = sections["call_list"]
    dynamics = sections["focus_criterion_dynamics"]
    morning_card = sections["morning_card"]
    call_breakdown = sections["call_breakdown"]
    voice_of_customer = sections["voice_of_customer"]
    additional_situations = sections["additional_situations"]
    call_tomorrow = sections["call_tomorrow"]
    outcome_summary_cells = "".join(
        f"<td class=\"outcome-cell {_outcome_col_class(item)}\">"
        f"<div class=\"outcome-value\">{html.escape(_manager_reader_value(item.get('value'), '—'))}</div>"
        f"<div class=\"outcome-label\">{html.escape(str(item['label']))}</div>"
        "</td>"
        for item in day_summary.get("outcome_cols") or []
    )
    summary_table = (
        f"<table class=\"outcome-table\"><tbody><tr>{outcome_summary_cells}</tr></tbody></table>"
        if outcome_summary_cells else ""
    )
    _stage_rows_list = review.get("stage_rows") or []
    _stage_rows_parts: list[str] = []
    for _srow in _stage_rows_list:
        _srow_html = (
            f"<tr class=\"{'stage-priority-row' if _srow.get('is_priority') else ''}\">"
            f"<td class=\"stage-label\">"
            f"<span class=\"stage-funnel-label\">{html.escape(str(_srow.get('funnel_label', '')))}</span>"
            f" {html.escape(str(_srow.get('stage_name', '')))}"
            f"</td>"
            f"<td class=\"stage-score {'stage-priority-score' if _srow.get('is_priority') else ''}\">"
            f"{html.escape(str(_srow.get('score', '—')))}"
            f"</td>"
            f"<td class=\"stage-bar-cell\">"
            f"<div class=\"stage-bar-wrap\">"
            f"<div class=\"stage-bar-fill {'stage-bar-priority' if _srow.get('is_priority') else ''}\" style=\"width:{_srow.get('bar_pct', 0)}%\"></div>"
            f"</div>"
            f"</td>"
            f"<td class=\"stage-priority-col\">"
            + (
                "<span class=\"stage-priority-flag\">★ приоритет</span>"
                if _srow.get("is_priority")
                else ""
            )
            + "</td></tr>"
        )
        _stage_rows_parts.append(_srow_html)
        if _srow.get("is_priority") and _srow.get("criteria_detail"):
            _chips = "".join(
                f"<span class=\"crit-chip {'crit-weak' if c.get('is_weak') else 'crit-ok'}\">"
                f"{html.escape(str(c.get('name') or ''))} "
                f"<span class=\"crit-score\">{html.escape(str(c.get('score', '—')))}</span>"
                f"</span>"
                for c in (_srow.get("criteria_detail") or [])
            )
            _stage_rows_parts.append(
                f"<tr class=\"stage-criteria-row\"><td colspan=\"4\">"
                f"<div class=\"stage-criteria\">{_chips}</div>"
                f"</td></tr>"
            )
    stage_rows_html = "".join(_stage_rows_parts) or (
        "<tr><td colspan=\"4\" class=\"stage-empty\">Данные по этапам появятся после накопления базы.</td></tr>"
    )
    recommendation_cards = "".join(
        _render_manager_daily_recommendation_card(card, index + 1)
        for index, card in enumerate(recommendations.get("cards") or [])
    ) or (
        "<article class=\"recommendation-card orange\">"
        "<div class=\"priority-pill week\">На неделе</div>"
        "<div class=\"rec-title\">Рекомендации появятся после следующего полного ручного запуска</div>"
        "<div class=\"rec-context\">Пока в выборке недостаточно материала для отдельных coaching-карточек.</div>"
        "</article>"
    )
    outcome_tiles = "".join(
        (
            f"<article class=\"tile {_manager_outcome_tile_class(item)}\">"
            f"<div class=\"tile-value\">{html.escape(_manager_reader_value(item.get('value'), '0'))}</div>"
            f"<div class=\"tile-label\">{html.escape(str(item['label']))}</div>"
            "</article>"
        )
        for item in outcomes.get("metrics") or []
    )
    table_head = "".join(f"<th>{html.escape(str(item))}</th>" for item in call_list.get("columns") or [])
    table_rows = "".join(
        "<tr>"
        + "".join(
            (
                f"<td><span class=\"status {html.escape(_manager_status_class(cell))}\">{html.escape(_manager_reader_value(cell, '—'))}</span></td>"
                if index == 4
                else f"<td>{html.escape(_manager_reader_value(cell, '—'))}</td>"
            )
            for index, cell in enumerate(row)
        )
        + "</tr>"
        for row in call_list.get("rows") or []
    ) or (
        "<tr><td colspan=\"7\">По выбранным фильтрам нет звонков, готовых к включению в таблицу.</td></tr>"
    )
    dynamics_bars = "".join(
        (
            f"<div>{html.escape(str(item['label']))}</div>"
            f"<div class=\"bars\"><div class=\"bar {html.escape(str(item.get('tone') or 'ghost'))}\"></div>"
            f"<span class=\"bar-value {html.escape(str(item.get('tone') or 'ghost'))}\">"
            f"{html.escape(_manager_reader_value(item.get('value'), '—'))}</span></div>"
        )
        for item in dynamics.get("bars") or []
    )
    page_one = (
        _manager_daily_page_header(report["metadata_line"])
        + "<section class=\"hero\">"
        f"<div class=\"hero-title\">{html.escape(report['title'])}"
        f"<span class=\"hero-sub\">· {html.escape(report['subtitle'])}</span></div>"
        f"<div class=\"focus-week\">{html.escape(report.get('hero_focus') or '')}</div>"
        "</section>"
        f"<div class=\"section-bar\">{html.escape(day_summary['label'])}</div>"
        + summary_table
        + "<section class=\"summary-box\">"
        f"<p>{html.escape(str(executive.get('body') or 'Итог дня будет сформирован после следующего запуска.'))}</p>"
        f"<div class=\"progress\">{html.escape(str(executive.get('progress_line') or 'Сравнение с базой пока недоступно.'))}</div>"
        "</section>"
        "<section class=\"banner green\">"
        f"<span class=\"label\">✓ {html.escape(signal['label'])}:</span> "
        f"{html.escape(str(signal.get('body') or 'Опорный пример будет выбран после накопления базы.'))} "
        f"<strong>{html.escape(str(signal.get('time_line') or ''))}</strong>. "
        f"{html.escape(_manager_signal_reason(signal))}"
        "</section>"
        "<section class=\"situation-day\">"
        f"<div class=\"situation-title\">{html.escape(str(focus.get('situation_title') or 'СИТУАЦИЯ ДНЯ'))}</div>"
        f"<div class=\"situation-body\">{html.escape(str(focus.get('body') or 'Описание ситуации будет сформировано после следующего запуска.'))}</div>"
        + (
            f"<div class=\"situation-count\">{html.escape(str(focus['pattern_count_label']))}</div>"
            if focus.get("pattern_count_label")
            else ""
        )
        + _render_situation_call_example_html(focus.get("call_example") or {})
        + (
            "<ol class=\"situation-scripts\">"
            + "".join(f"<li>{html.escape(str(s))}</li>" for s in (focus.get("scripts") or []))
            + "</ol>"
            if focus.get("scripts")
            else ""
        )
        + "</section>"
        f"<div class=\"section-bar navy\">{html.escape(review['label'])}</div>"
        "<section class=\"stage-scores-section\">"
        "<table class=\"stage-scores-table\">"
        "<thead><tr>"
        "<th class=\"stage-th-label\">Этап</th>"
        "<th class=\"stage-th-score\">Сегодня</th>"
        "<th class=\"stage-th-bar\">Шкала</th>"
        "<th class=\"stage-th-priority\">Приоритет</th>"
        "</tr></thead>"
        f"<tbody>{stage_rows_html}</tbody>"
        "</table>"
        "</section>"
        "<section class=\"problem-card\">"
        f"<h3>{html.escape(problem['label'])}: <span>{html.escape(str(problem.get('title') or 'Требует уточнения'))}</span></h3>"
        f"<div>{html.escape(str(problem.get('body') or 'Описание будет уточнено после следующего запуска.'))}</div>"
        "</section>"
        + _manager_daily_page_footer(report["footer"], 1)
    )
    page_two = (
        _manager_daily_page_header(report["metadata_line"]) +
        f"<div class=\"section-bar navy\">{html.escape(recommendations['label'])}</div>"
        + (
            f"<section class=\"summary-box\"><p>{html.escape(str(recommendations.get('editorial_note') or ''))}</p></section>"
            if recommendations.get("editorial_note")
            else ""
        )
        + f"{recommendation_cards}"
        + _manager_daily_page_footer(report["footer"], 2)
    )
    page_three = (
        _manager_daily_page_header(report["metadata_line"]) +
        f"<div class=\"section-bar navy\">{html.escape(outcomes['label'])}</div>"
        "<section class=\"tiles tiles-4\">"
        f"{outcome_tiles}"
        "</section>"
        "<table class=\"call-table\"><thead><tr>"
        f"{table_head}"
        "</tr></thead><tbody>"
        f"{table_rows}"
        "</tbody></table>"
        f"<div class=\"table-note\">{html.escape(str(call_list.get('note') or ''))}</div>"
        f"<div class=\"section-bar teal\">{html.escape(dynamics['label'])}</div>"
        f"<div class=\"dynamics-title\">{html.escape(_manager_reader_value((dynamics.get('pairs') or [['', '']])[0][1], 'Критерий будет определён'))}</div>"
        f"<div class=\"period-bars\">{dynamics_bars}</div>"
        f"<div class=\"stage-line\">{html.escape(str(dynamics.get('stage_line') or dynamics.get('interpretation') or ''))}</div>"
        + _manager_daily_page_footer(report["footer"], 3)
    )
    _bd_stage_rows = "".join(
        (
            f"<tr class=\"{'bd-stage-weak' if row.get('is_weak') else ''}\">"
            f"<td class=\"bd-stage-label\">"
            f"<span class=\"stage-funnel-label\">{html.escape(str(row.get('funnel_label', '')))}</span>"
            f" {html.escape(str(row.get('stage_name', '')))}</td>"
            f"<td class=\"bd-stage-score\">{html.escape(str(row.get('score', '—')))}</td>"
            f"<td class=\"bd-stage-flag\">"
            + ("<span class=\"bd-weak-flag\">слабо</span>" if row.get("is_weak") else "")
            + "</td></tr>"
        )
        for row in call_breakdown.get("stage_steps") or []
    ) or "<tr><td colspan=\"3\">Нет данных по этапам.</td></tr>"
    _bd_worked = "".join(
        f"<li><strong>{html.escape(str(item['label']))}</strong> — {html.escape(str(item['interpretation']))}</li>"
        for item in (call_breakdown.get("worked") or [])
    ) or "<li>Нет данных.</li>"
    _bd_to_fix = "".join(
        f"<li><strong>{html.escape(str(item['label']))}</strong> — {html.escape(str(item['interpretation']))}</li>"
        for item in (call_breakdown.get("to_fix") or [])
    ) or "<li>Нет данных.</li>"
    _bd_rec = (
        f"<div class=\"bd-rec\">"
        f"<span class=\"bd-rec-label\">Попробуй так: </span>"
        f"<span class=\"bd-rec-text\">{html.escape(str((call_breakdown.get('recommendation') or {}).get('better_phrasing') or ''))}</span>"
        f"</div>"
        if call_breakdown.get("recommendation") and (call_breakdown["recommendation"] or {}).get("better_phrasing")
        else ""
    )
    _bd_header = (
        f"{html.escape(str(call_breakdown.get('client_label') or 'Клиент'))} · {html.escape(str(call_breakdown.get('time_label') or '—'))}"
        if not call_breakdown.get("is_placeholder")
        else "Недостаточно данных для разбора"
    )
    page_four = (
        _manager_daily_page_header(report["metadata_line"])
        + f"<div class=\"section-bar navy\">{html.escape(call_breakdown['label'])}</div>"
        f"<div class=\"bd-header\">{_bd_header}</div>"
        "<section class=\"call-breakdown\">"
        "<table class=\"bd-stage-table\"><thead><tr>"
        "<th>Этап</th><th>Балл</th><th></th>"
        f"</tr></thead><tbody>{_bd_stage_rows}</tbody></table>"
        "<div class=\"bd-analysis-grid\">"
        f"<div class=\"bd-col bd-worked\"><div class=\"bd-col-title\">✓ Что сработало</div><ul>{_bd_worked}</ul></div>"
        f"<div class=\"bd-col bd-to-fix\"><div class=\"bd-col-title\">✗ Что исправить</div><ul>{_bd_to_fix}</ul></div>"
        "</div>"
        f"{_bd_rec}"
        "</section>"
        + _render_voice_of_customer_html(voice_of_customer)
        + _manager_daily_page_footer(report["footer"], 4)
    )
    page_five = (
        _manager_daily_page_header(report["metadata_line"])
        + _render_additional_situations_html(additional_situations)
        + _render_call_tomorrow_html(call_tomorrow)
        + _manager_daily_page_footer(report["footer"], 5)
    )
    mc_open_items = "".join(
        f"<li>{html.escape(str(call.get('time', '—')))} · {html.escape(str(call.get('client', '—')))} · {html.escape(str(call.get('status', '—')))}</li>"
        for call in morning_card.get("open_calls") or []
    ) or "<li>Открытых звонков нет — отличный результат!</li>"
    page_six = (
        _manager_daily_page_header(report["metadata_line"])
        + f"<div class=\"section-bar\">{html.escape(morning_card['label'])}</div>"
        "<section class=\"morning-card\">"
        f"<div class=\"morning-greeting\">{html.escape(str(morning_card.get('greeting') or ''))}</div>"
        f"<div class=\"morning-summary\">{html.escape(str(morning_card.get('summary_line') or ''))}</div>"
        "<div class=\"morning-open-label\">Открытые звонки:</div>"
        f"<ul class=\"morning-open-list\">{mc_open_items}</ul>"
        "<div class=\"morning-challenge\">"
        "<span class=\"morning-challenge-label\">Фокус: </span>"
        f"{html.escape(str(morning_card.get('challenge') or ''))}"
        "</div>"
        "</section>"
        + _manager_daily_page_footer(report["footer"], 6)
    )
    return (
        "<html><head><meta charset=\"utf-8\">"
        f"<style>{template.css}</style>"
        "</head><body><div class=\"workspace\">"
        f"<section class=\"page\">{page_one}</section>"
        f"<section class=\"page\">{page_two}</section>"
        f"<section class=\"page\">{page_three}</section>"
        f"<section class=\"page\">{page_four}</section>"
        f"<section class=\"page\">{page_five}</section>"
        f"<section class=\"page\">{page_six}</section>"
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
    """Render manager_daily PDF with a fixed reference-like composition."""
    white = (255, 255, 255)
    light_blue = (215, 228, 239)
    light_green = (223, 233, 215)
    light_yellow = (243, 229, 184)
    light_red = (248, 230, 230)
    light_orange = (246, 223, 207)
    soft_green = (231, 240, 223)
    soft_yellow = (246, 234, 201)
    soft_problem = (249, 236, 236)
    soft_week = (247, 232, 220)
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

    def draw_bullets(
        page: list[dict[str, Any]],
        *,
        left: float,
        top: float,
        items: list[str],
        width_limit: float,
        color: tuple[int, int, int] = black,
        bullet_color: tuple[int, int, int] | None = None,
        size: float = 10.2,
    ) -> float:
        cursor = top
        for item in items:
            draw_text(page, left=left, top=cursor, text="•", size=size, color=bullet_color or color, max_width=10)
            used = draw_text(page, left=left + 10, top=cursor, text=item, size=size, color=color, max_width=width_limit - 10)
            cursor += max(used, size * 1.4)
        return cursor - top

    def measure_height(text: str, size: float, mw: float, leading: float = 1.28) -> float:
        lines = _wrap_text(text=text, font=font, font_size=size, max_width=mw)
        return len(lines) * size * leading

    day_summary = sections["day_summary"]
    executive = sections["executive_narrative"]
    signal = sections["signal_of_day"]
    focus = sections["main_focus_for_tomorrow"]
    review = sections["review_block"]
    problem = sections["key_problem_of_day"]
    recommendations = sections["recommendations"]
    outcomes = sections["call_outcomes_summary"]
    call_list = sections["call_list"]
    dynamics = sections["focus_criterion_dynamics"]
    morning_card_section = sections["morning_card"]
    call_breakdown_section = sections["call_breakdown"]
    voice_section = sections["voice_of_customer"]
    add_sit_section = sections["additional_situations"]
    call_tomorrow_section = sections["call_tomorrow"]

    page1 = add_page()
    draw_rect(page1, left=margin, top=58, box_width=width - (margin * 2), box_height=72, fill=accent)
    draw_text(page1, left=margin + 18, top=72, text=report["title"], size=19, color=white, max_width=300)
    draw_text(page1, left=margin + 18, top=95, text=report["subtitle"], size=10.2, color=(198, 215, 243), max_width=340)
    draw_text(page1, left=margin + 18, top=112, text=f"Фокус недели: {report.get('hero_focus') or ''}", size=10.4, color=white, max_width=460)

    draw_section_bar(page1, top=150, title=day_summary["label"], color=(47, 97, 170))
    _outcome_col_gap = 6
    _num_outcome_cols = 6
    _outcome_col_width = (width - (margin * 2) - (_outcome_col_gap * (_num_outcome_cols - 1))) / _num_outcome_cols
    _outcome_col_left = margin
    _outcome_col_top = 183
    _outcome_col_height = 64
    _outcome_fills = {
        "neutral": light_blue,
        "positive": light_green,
        "focus": light_yellow,
        "problem": light_red,
        "warning": light_orange,
    }
    _outcome_accent_colors = {
        "neutral": (47, 97, 170),
        "positive": green,
        "focus": (138, 107, 9),
        "problem": red,
        "warning": (186, 88, 22),
    }
    for item in day_summary.get("outcome_cols") or []:
        _tone = str(item.get("tone") or "neutral")
        _fill = _outcome_fills.get(_tone, light_blue)
        _accent = _outcome_accent_colors.get(_tone, accent)
        draw_rect(page1, left=_outcome_col_left, top=_outcome_col_top, box_width=_outcome_col_width, box_height=_outcome_col_height, fill=_fill)
        draw_rect(page1, left=_outcome_col_left, top=_outcome_col_top, box_width=_outcome_col_width, box_height=4, fill=_accent)
        draw_centered_text(page1, left=_outcome_col_left, top=_outcome_col_top + 20, box_width=_outcome_col_width, text=_manager_reader_value(item.get("value"), "—"), size=16.0, color=_accent)
        draw_centered_text(page1, left=_outcome_col_left, top=_outcome_col_top + 44, box_width=_outcome_col_width, text=str(item["label"]), size=7.8, color=muted)
        _outcome_col_left += _outcome_col_width + _outcome_col_gap

    # Executive block — dynamic height prevents progress_line from overlapping the signal card
    _exec_max_w = width - (margin * 2) - 24
    _exec_body_text = str(executive.get("body") or "Итог дня будет сформирован после следующего запуска.")
    _exec_progress_text = str(executive.get("progress_line") or "Сравнение с базой пока недоступно.")
    _exec_body_h = measure_height(_exec_body_text, 10.4, _exec_max_w)
    _exec_progress_h = measure_height(_exec_progress_text, 9.4, _exec_max_w)
    _exec_box_h = max(78, int(13 + _exec_body_h + 6 + _exec_progress_h + 12))
    _exec_top = 273
    draw_rect(page1, left=margin, top=_exec_top, box_width=width - (margin * 2), box_height=_exec_box_h, fill=(243, 245, 247))
    draw_rect(page1, left=margin, top=_exec_top, box_width=4, box_height=_exec_box_h, fill=(47, 97, 170))
    draw_text(page1, left=margin + 12, top=_exec_top + 13, text=_exec_body_text, size=10.4, color=black, max_width=_exec_max_w)
    draw_text(page1, left=margin + 12, top=_exec_top + 13 + _exec_body_h + 6, text=_exec_progress_text, size=9.4, color=muted, max_width=_exec_max_w)

    # Signal card — follows executive block bottom so wrapped body text cannot overlap it
    _signal_top = _exec_top + _exec_box_h + 8
    _signal_max_w = width - (margin * 2) - 24
    signal_text = (
        f"✓ {signal['label']}: {str(signal.get('body') or 'Опорный пример будет выбран после накопления базы.')} "
        f"Время: {str(signal.get('time_line') or 'не зафиксировано')}. {_manager_signal_reason(signal)}"
    )
    _signal_text_h = measure_height(signal_text, 10.2, _signal_max_w)
    _signal_box_h = max(54, int(16 + _signal_text_h + 10))
    draw_rect(page1, left=margin, top=_signal_top, box_width=width - (margin * 2), box_height=_signal_box_h, fill=soft_green)
    draw_rect(page1, left=margin, top=_signal_top, box_width=4, box_height=_signal_box_h, fill=green)
    draw_text(page1, left=margin + 12, top=_signal_top + 16, text=signal_text, size=10.2, color=black, max_width=_signal_max_w)

    situation_title_text = str(focus.get("situation_title") or "СИТУАЦИЯ ДНЯ")
    situation_body_text = str(focus.get("body") or "Описание ситуации будет сформировано после следующего запуска.")
    situation_count_label = str(focus.get("pattern_count_label") or "")
    situation_call_ex = dict(focus.get("call_example") or {})
    situation_scripts = list(focus.get("scripts") or [])
    _has_call_ex = bool(situation_call_ex.get("client_label") or situation_call_ex.get("time_label"))

    # СИТУАЦИЯ ДНЯ — follows signal card; height sized to contain all script lines without overflow
    _sit_top = _signal_top + _signal_box_h + 8
    _sit_h = 116 if _has_call_ex else 96
    _stage_bar_top = _sit_top + _sit_h
    _st_top_init = _stage_bar_top + 24
    _stage_rows = review.get("stage_rows") or []
    draw_rect(page1, left=margin, top=_sit_top, box_width=width - (margin * 2), box_height=_sit_h, fill=(232, 240, 254))
    draw_rect(page1, left=margin, top=_sit_top, box_width=4, box_height=_sit_h, fill=(30, 80, 180))
    draw_text(page1, left=margin + 12, top=_sit_top + 8, text=situation_title_text, size=9.5, color=(20, 50, 140), max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=_sit_top + 24, text=situation_body_text, size=9.5, color=black, max_width=width - (margin * 2) - 24)
    if situation_count_label:
        draw_text(page1, left=margin + 12, top=_sit_top + 36, text=situation_count_label, size=8.0, color=(100, 110, 150), max_width=width - (margin * 2) - 24)
    if _has_call_ex:
        _ex_client = str(situation_call_ex.get("client_label") or "Клиент")
        _ex_time = str(situation_call_ex.get("time_label") or "")
        _ex_reason = str(situation_call_ex.get("reason_short") or "")
        _ex_contact_line = f"{_ex_client} · {_ex_time}" if _ex_time and _ex_time != "—" else _ex_client
        draw_text(page1, left=margin + 12, top=_sit_top + 48, text=f"Пример: {_ex_contact_line}", size=8.5, color=(20, 50, 140), max_width=width - (margin * 2) - 24)
        if _ex_reason:
            draw_text(page1, left=margin + 12, top=_sit_top + 60, text=_ex_reason, size=7.8, color=(100, 110, 150), max_width=width - (margin * 2) - 24)
    _script_top = _sit_top + (73 if _has_call_ex else (48 if situation_count_label else 40))
    _script_gap = 13
    for _si, _script in enumerate(situation_scripts[:3]):
        draw_text(page1, left=margin + 12, top=_script_top + _si * _script_gap, text=f"{_si + 1}. {_script}", size=8.5, color=(70, 70, 130), max_width=width - (margin * 2) - 24)

    draw_section_bar(page1, top=_stage_bar_top, title=review["label"], color=accent)
    _st_top = _st_top_init
    _st_name_w = 190
    _st_score_w = 45
    _st_bar_w = 208
    _st_prio_w = 68
    _st_row_h = 18
    _st_header_fill = (232, 237, 245)
    draw_rect(page1, left=margin, top=_st_top, box_width=width - (margin * 2), box_height=16, fill=_st_header_fill)
    draw_text(page1, left=margin + 4, top=_st_top + 3, text="ЭТАП", size=7.5, color=muted, max_width=_st_name_w)
    draw_text(page1, left=margin + _st_name_w + 4, top=_st_top + 3, text="СЕГОДНЯ", size=7.5, color=muted, max_width=_st_score_w)
    draw_text(page1, left=margin + _st_name_w + _st_score_w + 4, top=_st_top + 3, text="ШКАЛА", size=7.5, color=muted, max_width=_st_bar_w)
    draw_text(page1, left=margin + _st_name_w + _st_score_w + _st_bar_w + 4, top=_st_top + 3, text="ПРИОРИТЕТ", size=7.5, color=muted, max_width=_st_prio_w)
    _st_top += 18
    if not _stage_rows:
        draw_text(page1, left=margin + 4, top=_st_top + 4, text="Данные по этапам появятся после накопления базы.", size=8.5, color=muted, max_width=width - (margin * 2))
    # Guard: stop adding rows before the problem card area (90px card + 6px gap + footer 36px)
    _max_st_row_end = height - 36 - 90 - 6
    for _sr in _stage_rows:
        _is_prio = bool(_sr.get("is_priority"))
        _sr_crits = list(_sr.get("criteria_detail") or []) if _is_prio else []
        _this_row_h = 28 if _sr_crits else _st_row_h
        if _st_top + _this_row_h > _max_st_row_end:
            break
        _row_fill = (255, 242, 230) if _is_prio else (248, 250, 252)
        draw_rect(page1, left=margin, top=_st_top, box_width=width - (margin * 2), box_height=_this_row_h, fill=_row_fill)
        _label_text = f"{_sr.get('funnel_label', '')} {_sr.get('stage_name', '')}"
        draw_text(page1, left=margin + 4, top=_st_top + 4, text=_label_text, size=8.0, color=red if _is_prio else black, max_width=_st_name_w - 8)
        draw_text(page1, left=margin + _st_name_w + 4, top=_st_top + 4, text=str(_sr.get("score", "—")), size=8.5, color=red if _is_prio else accent, max_width=_st_score_w - 4)
        _bar_track_left = margin + _st_name_w + _st_score_w + 4
        _bar_track_w = _st_bar_w - 12
        draw_rect(page1, left=_bar_track_left, top=_st_top + 5, box_width=_bar_track_w, box_height=8, fill=(220, 228, 238))
        _bar_fill_w = round(_bar_track_w * ((_sr.get("bar_pct") or 0) / 100))
        if _bar_fill_w > 0:
            draw_rect(page1, left=_bar_track_left, top=_st_top + 5, box_width=_bar_fill_w, box_height=8, fill=red if _is_prio else accent)
        if _is_prio:
            draw_text(page1, left=margin + _st_name_w + _st_score_w + _st_bar_w + 4, top=_st_top + 4, text="★ приоритет", size=7.5, color=red, max_width=_st_prio_w - 4)
        if _sr_crits:
            _weak_parts = [f"{c['name']}: {c['score']}" for c in _sr_crits if c.get("is_weak")][:3]
            _ok_parts = [f"{c['name']}: {c['score']}" for c in _sr_crits if not c.get("is_weak")][:2]
            _crit_line = "  ".join(_weak_parts) or "  ".join(_ok_parts) or ""
            if _crit_line:
                draw_text(page1, left=margin + 4, top=_st_top + 18, text=_crit_line, size=7.0, color=red, max_width=width - (margin * 2) - 8)
        _st_top += _this_row_h

    # Problem card position follows the actual stage table bottom (fixes overlap with tall tables)
    _problem_card_top = _st_top + 6
    draw_rect(page1, left=margin, top=_problem_card_top, box_width=width - (margin * 2), box_height=90, fill=light_red)
    draw_rect(page1, left=margin, top=_problem_card_top, box_width=4, box_height=90, fill=red)
    draw_text(page1, left=margin + 12, top=_problem_card_top + 15, text=f"{problem['label']}: {str(problem.get('title') or 'Критичный провал дня не выделился')}", size=11.0, color=red, max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=_problem_card_top + 37, text=str(problem.get("body") or ""), size=9.8, color=black, max_width=width - (margin * 2) - 24)
    footer(page1, 1)

    page2 = add_page()
    draw_section_bar(page2, top=58, title=recommendations["label"], color=accent)
    rec_top = 92
    for index, card in enumerate(recommendations.get("cards") or []):
        card_fill = soft_week if card.get("tone") == "orange" else soft_problem
        card_edge = amber if card.get("tone") == "orange" else red
        example_width = (width - (margin * 2) - 40) / 2
        _ex_max_w = example_width - 16
        _card_max_w = width - (margin * 2) - 28
        _how_text = str(card.get("how_it_sounded") or "Формулировка была слишком общей.")
        _better_text = str(card.get("better_phrasing") or "Сформулируй следующий шаг конкретно.")
        _context_text = str(card.get("context") or card.get("body") or "")
        _context_h = measure_height(_context_text, 9.5, _card_max_w)
        # Example boxes: tall enough to contain both before/after texts without overflow
        _ex_box_h = max(44, int(22 + max(measure_height(_how_text, 8.5, _ex_max_w), measure_height(_better_text, 8.5, _ex_max_w)) + 10))
        _why_text = f"Почему это работает: {str(card.get('why_this_works') or '')}"
        _example_top_offset = max(68, int(40 + _context_h + 8))
        _why_top_offset = _example_top_offset + _ex_box_h + 8
        _why_h = measure_height(_why_text, 8.9, _card_max_w)
        card_height = max(152, int(_why_top_offset + _why_h + 14))
        draw_rect(page2, left=margin, top=rec_top, box_width=width - (margin * 2), box_height=card_height, fill=card_fill)
        draw_rect(page2, left=margin, top=rec_top, box_width=4, box_height=card_height, fill=card_edge)
        pill_width = 86
        draw_rect(page2, left=width - margin - pill_width, top=rec_top + 12, box_width=pill_width, box_height=20, fill=(194, 103, 17) if card.get("priority_tone") == "week" else (196, 12, 0))
        draw_centered_text(page2, left=width - margin - pill_width, top=rec_top + 18, box_width=pill_width, text=str(card.get("priority_tag") or "Сделай завтра"), size=7.8, color=white)
        draw_text(page2, left=margin + 14, top=rec_top + 18, text=f"{index + 1}. {str(card.get('title') or 'Рекомендация')}", size=11.4, color=accent, max_width=360)
        draw_text(page2, left=margin + 14, top=rec_top + 40, text=_context_text, size=9.5, color=black, max_width=_card_max_w)
        example_top = rec_top + _example_top_offset
        draw_rect(page2, left=margin + 14, top=example_top, box_width=example_width, box_height=_ex_box_h, fill=(250, 239, 239))
        draw_rect(page2, left=margin + 14, top=example_top, box_width=2, box_height=_ex_box_h, fill=(227, 167, 164))
        draw_rect(page2, left=margin + 26 + example_width, top=example_top, box_width=example_width, box_height=_ex_box_h, fill=(238, 247, 238))
        draw_rect(page2, left=margin + 26 + example_width, top=example_top, box_width=2, box_height=_ex_box_h, fill=green)
        draw_text(page2, left=margin + 22, top=example_top + 8, text="Как звучало:", size=8.8, color=red, max_width=_ex_max_w)
        draw_text(page2, left=margin + 22, top=example_top + 22, text=_how_text, size=8.5, color=muted, max_width=_ex_max_w)
        draw_text(page2, left=margin + 34 + example_width, top=example_top + 8, text="Как лучше:", size=8.8, color=green, max_width=_ex_max_w)
        draw_text(page2, left=margin + 34 + example_width, top=example_top + 22, text=_better_text, size=8.5, color=muted, max_width=_ex_max_w)
        draw_text(page2, left=margin + 14, top=rec_top + _why_top_offset, text=_why_text, size=8.9, color=black, max_width=_card_max_w)
        rec_top += card_height + 18
    footer(page2, 2)

    page3 = add_page()
    draw_section_bar(page3, top=58, title=outcomes["label"], color=accent)
    outcome_gap = 12
    outcome_width = (width - (margin * 2) - (outcome_gap * 3)) / 4
    outcome_left = margin
    outcome_top = 92
    outcome_fills = {
        "green": light_green,
        "yellow": light_yellow,
        "red-danger": light_red,
        "yellow-open": light_orange,
    }
    outcome_value_colors = {
        "green": green,
        "yellow": (138, 107, 9),
        "red-danger": red,
        "yellow-open": amber,
    }
    for item in outcomes.get("metrics") or []:
        tile_class = _manager_outcome_tile_class(item)
        draw_rect(page3, left=outcome_left, top=outcome_top, box_width=outcome_width, box_height=70, fill=outcome_fills.get(tile_class, light_green))
        draw_rect(page3, left=outcome_left, top=outcome_top, box_width=outcome_width, box_height=4, fill=outcome_value_colors.get(tile_class, accent))
        draw_centered_text(page3, left=outcome_left, top=outcome_top + 24, box_width=outcome_width, text=_manager_reader_value(item.get("value"), "0"), size=18.0, color=outcome_value_colors.get(tile_class, accent))
        draw_centered_text(page3, left=outcome_left, top=outcome_top + 47, box_width=outcome_width, text=str(item["label"]), size=8.6, color=muted)
        outcome_left += outcome_width + outcome_gap

    table_top = 182
    columns = call_list.get("columns") or []
    rows = call_list.get("rows") or []
    _cl_num = 22
    _cl_time = 42
    _cl_client = 72
    _cl_topic = 76
    _cl_status = 62
    _cl_context = 72
    _cl_next = width - (margin * 2) - _cl_num - _cl_time - _cl_client - _cl_topic - _cl_status - _cl_context
    col_widths = [_cl_num, _cl_time, _cl_client, _cl_topic, _cl_status, _cl_context, _cl_next]
    x = margin
    for column, col_width in zip(columns, col_widths, strict=False):
        draw_rect(page3, left=x, top=table_top, box_width=col_width, box_height=22, fill=accent)
        draw_text(page3, left=x + 4, top=table_top + 6, text=str(column), size=8.0, color=white, max_width=col_width - 8)
        x += col_width
    row_top = table_top + 24
    for row in rows[:8]:
        x = margin
        status_value = str(row[4]) if len(row) > 4 else ""
        for index, (cell, col_width) in enumerate(zip(row, col_widths, strict=False)):
            fill = (248, 248, 248)
            if index == 4:
                fill = _manager_status_fill(status_value)
            draw_rect(page3, left=x, top=row_top, box_width=col_width, box_height=24, fill=fill)
            draw_text(page3, left=x + 4, top=row_top + 7, text=str(cell), size=7.7, color=black if index != 4 else _manager_status_text_color(status_value, black, green, amber, red), max_width=col_width - 8)
            x += col_width
        row_top += 24
    draw_text(page3, left=margin, top=row_top + 8, text=str(call_list.get("note") or ""), size=8.8, color=muted, max_width=width - (margin * 2))

    dynamics_top = row_top + 34
    draw_section_bar(page3, top=dynamics_top, title=dynamics["label"], color=(33, 122, 133))
    draw_text(page3, left=margin, top=dynamics_top + 32, text=str((dynamics.get("pairs") or [["", ""]])[0][1]), size=10.5, color=(33, 122, 133), max_width=width - (margin * 2))
    bars_top = dynamics_top + 58
    for index, item in enumerate(dynamics.get("bars") or []):
        base_top = bars_top + (index * 26)
        draw_text(page3, left=margin, top=base_top, text=str(item["label"]), size=8.8, color=black, max_width=110)
        bar_left = margin + 116
        bar_width = 120 if item.get("tone") == "blue" else 86 if item.get("tone") == "orange" else 42
        draw_rect(page3, left=bar_left, top=base_top + 2, box_width=bar_width, box_height=14, fill=(47, 97, 170) if item.get("tone") == "blue" else amber if item.get("tone") == "orange" else (214, 214, 214))
        draw_text(page3, left=bar_left + bar_width + 8, top=base_top, text=_manager_reader_value(item.get("value"), "—"), size=9.0, color=(47, 97, 170) if item.get("tone") == "blue" else amber, max_width=140)
    draw_text(page3, left=margin, top=bars_top + 62, text=str(dynamics.get("stage_line") or dynamics.get("interpretation") or ""), size=9.6, color=black, max_width=width - (margin * 2))
    footer(page3, 3)

    page4 = add_page()
    _bd = call_breakdown_section
    _bd_client = str(_bd.get("client_label") or "Клиент")
    _bd_time = str(_bd.get("time_label") or "—")
    _bd_header_text = (
        f"{_bd_client} · {_bd_time}" if not _bd.get("is_placeholder") else "Недостаточно данных для разбора"
    )
    draw_section_bar(page4, top=58, title=_bd["label"], color=accent)
    draw_text(page4, left=margin, top=82, text=_bd_header_text, size=10.5, color=black, max_width=width - (margin * 2))
    # Stage breakdown table
    _bd_st_top = 104
    _bd_st_name_w = 210
    _bd_st_score_w = 46
    _bd_st_flag_w = 60
    draw_rect(page4, left=margin, top=_bd_st_top, box_width=width - (margin * 2), box_height=15, fill=(232, 237, 245))
    draw_text(page4, left=margin + 4, top=_bd_st_top + 3, text="ЭТАП", size=7.5, color=muted, max_width=_bd_st_name_w)
    draw_text(page4, left=margin + _bd_st_name_w + 4, top=_bd_st_top + 3, text="БАЛЛ", size=7.5, color=muted, max_width=_bd_st_score_w)
    draw_text(page4, left=margin + _bd_st_name_w + _bd_st_score_w + 4, top=_bd_st_top + 3, text="ОЦЕНКА", size=7.5, color=muted, max_width=_bd_st_flag_w)
    _bd_st_top += 17
    _bd_stage_steps = list(_bd.get("stage_steps") or [])
    if not _bd_stage_steps:
        draw_text(page4, left=margin + 4, top=_bd_st_top + 4, text="Нет данных по этапам.", size=8.5, color=muted, max_width=width - (margin * 2))
        _bd_st_top += 20
    for _bds in _bd_stage_steps:
        _is_weak = bool(_bds.get("is_weak"))
        _row_fill = (255, 242, 230) if _is_weak else (248, 250, 252)
        draw_rect(page4, left=margin, top=_bd_st_top, box_width=width - (margin * 2), box_height=16, fill=_row_fill)
        draw_text(page4, left=margin + 4, top=_bd_st_top + 3, text=f"{_bds.get('funnel_label', '')} {_bds.get('stage_name', '')}", size=7.8, color=red if _is_weak else black, max_width=_bd_st_name_w - 8)
        draw_text(page4, left=margin + _bd_st_name_w + 4, top=_bd_st_top + 3, text=str(_bds.get("score", "—")), size=8.0, color=red if _is_weak else accent, max_width=_bd_st_score_w - 4)
        if _is_weak:
            draw_text(page4, left=margin + _bd_st_name_w + _bd_st_score_w + 4, top=_bd_st_top + 3, text="слабо", size=7.5, color=red, max_width=_bd_st_flag_w - 4)
        _bd_st_top += 16
    # Worked / To-fix two-column analysis
    _analysis_top = _bd_st_top + 18
    _col_w = (width - (margin * 2) - 12) // 2
    draw_rect(page4, left=margin, top=_analysis_top, box_width=_col_w, box_height=14, fill=(220, 238, 220))
    draw_text(page4, left=margin + 4, top=_analysis_top + 2, text="✓ Что сработало", size=8.5, color=green, max_width=_col_w - 8)
    draw_rect(page4, left=margin + _col_w + 12, top=_analysis_top, box_width=_col_w, box_height=14, fill=(255, 232, 232))
    draw_text(page4, left=margin + _col_w + 16, top=_analysis_top + 2, text="✗ Что исправить", size=8.5, color=red, max_width=_col_w - 8)
    _item_top = _analysis_top + 18
    _bd_worked = list(_bd.get("worked") or [])
    _bd_to_fix = list(_bd.get("to_fix") or [])
    _max_items = max(len(_bd_worked), len(_bd_to_fix), 1)
    for _idx in range(_max_items):
        if _idx < len(_bd_worked):
            _w = _bd_worked[_idx]
            draw_text(page4, left=margin + 4, top=_item_top, text=f"• {_w['label']}", size=8.5, color=black, max_width=_col_w - 8)
            if _w.get("interpretation"):
                draw_text(page4, left=margin + 4, top=_item_top + 11, text=_w["interpretation"], size=7.8, color=muted, max_width=_col_w - 8)
        if _idx < len(_bd_to_fix):
            _f = _bd_to_fix[_idx]
            draw_text(page4, left=margin + _col_w + 16, top=_item_top, text=f"• {_f['label']}", size=8.5, color=black, max_width=_col_w - 8)
            if _f.get("interpretation"):
                draw_text(page4, left=margin + _col_w + 16, top=_item_top + 11, text=_f["interpretation"], size=7.8, color=muted, max_width=_col_w - 8)
        _item_top += 44
    # Recommendation card
    _bd_rec = _bd.get("recommendation") or {}
    _page4_cursor = _item_top
    if _bd_rec.get("better_phrasing"):
        _rec_top = _item_top + 12
        draw_rect(page4, left=margin, top=_rec_top, box_width=width - (margin * 2), box_height=52, fill=light_blue)
        draw_rect(page4, left=margin, top=_rec_top, box_width=4, box_height=52, fill=accent)
        draw_text(page4, left=margin + 12, top=_rec_top + 8, text="Попробуй так:", size=8.5, color=accent, max_width=width - (margin * 2) - 24)
        draw_text(page4, left=margin + 12, top=_rec_top + 24, text=str(_bd_rec["better_phrasing"]), size=9.0, color=black, max_width=width - (margin * 2) - 24)
        _page4_cursor = _rec_top + 52
    # Voice of Customer section
    _voice_situations = list(voice_section.get("situations") or [])
    _voice_top = _page4_cursor + 22
    draw_section_bar(page4, top=_voice_top, title=voice_section["label"], color=(70, 90, 140))
    _voice_card_top = _voice_top + 30
    if voice_section.get("is_placeholder") or not _voice_situations:
        draw_text(page4, left=margin, top=_voice_card_top, text="Ситуации появятся после накопления материала по звонкам.", size=8.5, color=muted, max_width=width - (margin * 2))
    else:
        for _vs in _voice_situations[:3]:
            _vq = str(_vs.get("quote") or "")
            _vc = str(_vs.get("context") or "")
            _vm = f"{_vs.get('client_label', 'Клиент')} · {_vs.get('time_label', '—')}"
            draw_rect(page4, left=margin, top=_voice_card_top, box_width=width - (margin * 2), box_height=38, fill=(248, 248, 255))
            draw_rect(page4, left=margin, top=_voice_card_top, box_width=3, box_height=38, fill=(70, 90, 140))
            draw_text(page4, left=margin + 10, top=_voice_card_top + 4, text=f"«{_vq}»", size=8.5, color=(40, 40, 80), max_width=width - (margin * 2) - 20)
            draw_text(page4, left=margin + 10, top=_voice_card_top + 20, text=_vm + (f" — {_vc}" if _vc else ""), size=7.8, color=muted, max_width=width - (margin * 2) - 20)
            _voice_card_top += 44
    footer(page4, 4)

    # Page 5: Additional coaching situations
    page5 = add_page()
    draw_section_bar(page5, top=58, title=add_sit_section["label"], color=accent)
    _as_top = 96
    _as_sits = list(add_sit_section.get("situations") or [])
    if add_sit_section.get("is_placeholder") or not _as_sits:
        draw_text(page5, left=margin, top=_as_top, text="Дополнительные ситуации появятся после накопления данных по звонкам.", size=8.5, color=muted, max_width=width - (margin * 2))
    else:
        for _as in _as_sits[:3]:
            _as_kind = str(_as.get("kind") or "gap")
            _as_fill = (255, 245, 230) if _as_kind == "gap" else (230, 248, 230)
            _as_bar_color = (200, 100, 40) if _as_kind == "gap" else green
            _as_badge = "Зона роста" if _as_kind == "gap" else "Сильная сторона"
            _as_signal = int(_as.get("signal") or 0)
            _as_title = str(_as.get("title") or "")
            _as_interp = str(_as.get("interpretation") or "")
            draw_rect(page5, left=margin, top=_as_top, box_width=width - (margin * 2), box_height=52, fill=_as_fill)
            draw_rect(page5, left=margin, top=_as_top, box_width=4, box_height=52, fill=_as_bar_color)
            draw_text(page5, left=margin + 12, top=_as_top + 5, text=_as_badge + (f" · {_as_signal} зв." if _as_signal else ""), size=7.5, color=_as_bar_color, max_width=width - (margin * 2) - 24)
            draw_text(page5, left=margin + 12, top=_as_top + 18, text=_as_title, size=9.5, color=black, max_width=width - (margin * 2) - 24)
            draw_text(page5, left=margin + 12, top=_as_top + 34, text=_as_interp, size=8.0, color=muted, max_width=width - (margin * 2) - 24)
            _as_top += 58
    # ПОЗВОНИ ЗАВТРА section on page 5
    _ct_contacts = list(call_tomorrow_section.get("contacts") or [])
    _ct_top = _as_top + 20
    _ct_status_colors = {
        "rescheduled": (200, 100, 40),
        "agreed": accent,
        "open": muted,
    }
    _ct_status_labels = {"rescheduled": "Перезвон", "agreed": "Договорённость", "open": "Открытый"}
    draw_section_bar(page5, top=_ct_top, title=call_tomorrow_section["label"], color=accent)
    _ct_top += 30
    if call_tomorrow_section.get("is_placeholder") or not _ct_contacts:
        draw_text(page5, left=margin, top=_ct_top, text="Нет открытых контактов для перезвона.", size=8.5, color=muted, max_width=width - (margin * 2))
    else:
        for _ct in _ct_contacts:
            _ct_status = str(_ct.get("status") or "open")
            _ct_bar_color = _ct_status_colors.get(_ct_status, muted)
            _ct_client = str(_ct.get("client_label") or "Клиент")
            _ct_time = str(_ct.get("time_label") or "—")
            _ct_badge = _ct_status_labels.get(_ct_status, _ct_status)
            _ct_script = str(_ct.get("opening_script") or "")
            _ct_deadline = _ct.get("deadline")
            draw_rect(page5, left=margin, top=_ct_top, box_width=width - (margin * 2), box_height=46, fill=(250, 250, 255))
            draw_rect(page5, left=margin, top=_ct_top, box_width=4, box_height=46, fill=_ct_bar_color)
            draw_text(page5, left=margin + 12, top=_ct_top + 4, text=f"{_ct_client}  ·  {_ct_time}  [{_ct_badge}]" + (f"  · до {_ct_deadline}" if _ct_deadline else ""), size=8.5, color=black, max_width=width - (margin * 2) - 24)
            draw_text(page5, left=margin + 12, top=_ct_top + 20, text=f"«{_ct_script}»", size=8.0, color=(60, 80, 140), max_width=width - (margin * 2) - 24)
            _ct_top += 52
    footer(page5, 5)

    # Page 6: Morning card
    page6 = add_page()
    draw_section_bar(page6, top=58, title=morning_card_section["label"], color=(47, 97, 170))
    mc_top = 96
    draw_text(page6, left=margin, top=mc_top, text=str(morning_card_section.get("greeting") or ""), size=14.0, color=black, max_width=width - (margin * 2))
    mc_top += 30
    draw_text(page6, left=margin, top=mc_top, text=str(morning_card_section.get("summary_line") or ""), size=11.0, color=accent, max_width=width - (margin * 2))
    mc_top += 32
    _mc_open_calls = list(morning_card_section.get("open_calls") or [])
    if _mc_open_calls:
        draw_text(page6, left=margin, top=mc_top, text="Открытые звонки:", size=9.0, color=muted, max_width=width - (margin * 2))
        mc_top += 18
        for _mc_call in _mc_open_calls:
            draw_rect(page6, left=margin, top=mc_top, box_width=width - (margin * 2), box_height=22, fill=light_orange)
            draw_text(page6, left=margin + 8, top=mc_top + 5, text=f"• {_mc_call.get('time', '—')}  ·  {_mc_call.get('client', '—')}  ·  {_mc_call.get('status', '—')}", size=9.2, color=black, max_width=width - (margin * 2) - 16)
            mc_top += 26
    else:
        draw_text(page6, left=margin, top=mc_top, text="Открытых звонков нет — отличный результат!", size=10.0, color=green, max_width=width - (margin * 2))
        mc_top += 26
    mc_top += 16
    draw_rect(page6, left=margin, top=mc_top, box_width=width - (margin * 2), box_height=54, fill=light_blue)
    draw_rect(page6, left=margin, top=mc_top, box_width=4, box_height=54, fill=accent)
    draw_text(page6, left=margin + 12, top=mc_top + 8, text="Фокус дня:", size=9.0, color=accent, max_width=width - (margin * 2) - 24)
    draw_text(page6, left=margin + 12, top=mc_top + 26, text=str(morning_card_section.get("challenge") or ""), size=10.0, color=black, max_width=width - (margin * 2) - 24)
    footer(page6, 6)

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


def _build_situation_title(score_by_stage: list[dict[str, Any]]) -> str:
    """Build СИТУАЦИЯ ДНЯ heading from the priority stage (first below 4.0 in funnel order)."""
    for item in score_by_stage:
        if item.get("is_priority"):
            name = str(item.get("stage_name") or "")
            score = item.get("score")
            score_str = f" ({score})" if score is not None else ""
            return f"СИТУАЦИЯ ДНЯ · {name}{score_str} — первый этап ниже 4 по воронке"
    return "СИТУАЦИЯ ДНЯ — приоритетный этап не определён"


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
) -> dict[str, str]:
    """Build the fixed-structure v5 block 'ДЕНЬГИ НА СТОЛЕ' with honest fallbacks."""
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
    description = str(key_problem.get("description") or "").strip()
    if description:
        return (
            "Клиент хотел услышать решение под свою конкретную задачу, а не общую презентацию. "
            + description
        )
    return "Клиент ждал конкретики под свой контекст и понятного следующего шага."


def _build_situation_manager_task(
    *,
    score_by_stage: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
) -> str:
    """Return a deterministic 'Наша задача' line for v5 situation block."""
    priority_row = next((row for row in _build_stage_score_rows(score_by_stage) if row.get("is_priority")), None)
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
    priority_row = next((row for row in _build_stage_score_rows(score_by_stage) if row.get("is_priority")), None)
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


def _build_v5_voice_of_customer_section(
    *,
    section: dict[str, Any],
    recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map legacy voice payload to the approved v5 3-column structure."""
    reply_seed = _clean_reader_text(
        str(recommendations[0].get("better_phrasing") or "")
    ) if recommendations else ""
    rows = [
        [
            f"{item.get('client_label') or 'Клиент'} · {item.get('time_label') or '—'}",
            item.get("quote") or "—",
            (
                _build_voice_reply_line(item.get("context"), item.get("quote"))
                + (f" База ответа: {reply_seed}" if reply_seed else "")
            ),
        ]
        for item in section.get("situations") or []
    ]
    return {
        "intro": "3 наиболее показательные ситуации из звонков дня. Критерий выбора: скрытое возражение / незакрытая боль / упущенная связка.",
        "rows": rows[:3],
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
                "client_said": interpretation or "Ситуация повторяется в нескольких звонках.",
                "meant": (
                    "За этим стоит устойчивый рабочий паттерн, который стоит сохранить."
                    if kind == "strength"
                    else "Клиент не получил достаточно конкретики или фиксации следующего шага."
                ),
                "how_to": (
                    "Повторять удачную формулировку и усиливать её короткой привязкой к задаче клиента."
                    if kind == "strength"
                    else "Задать уточняющий вопрос, затем зафиксировать конкретный следующий шаг и дедлайн."
                ),
                "why": (
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
    priority_row = next((row for row in _build_stage_score_rows(score_by_stage) if row.get("is_priority")), None)
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


def _build_v5_call_tomorrow_section(*, section: dict[str, Any]) -> dict[str, Any]:
    """Map legacy call_tomorrow payload to the approved v5 table structure."""
    contacts = list(section.get("contacts") or [])
    rows = [
        [
            f"{_priority_icon_for_contact(str(item.get('status') or 'open'))} {_priority_label_for_contact(str(item.get('status') or 'open'))}",
            _manager_reader_value(item.get("client_label"), "Клиент"),
            _call_context_label(
                str(item.get("status") or ""),
                item.get("deadline"),
                None,
            ),
            _clean_reader_text(str(item.get("opening_script") or "Скрипт открытия будет добавлен после следующего полного запуска.")),
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
    if status == "agreed":
        return f"до {deadline}" if deadline else "—"
    if status == "rescheduled":
        return f"→ {deadline}" if deadline else "перезвон"
    if reason and status in ("open", "refusal"):
        short = reason[:28].rstrip()
        return short + "…" if len(reason) > 28 else short
    return "—"


def _call_status_label(value: Any) -> str:
    """Map internal call status to reader-facing Russian label."""
    mapping = {
        "agreed": "Договорились",
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
