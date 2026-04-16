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
        },
        "pdf_bytes": pdf_bytes,
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
    focus_dynamics = payload["focus_criterion_dynamics"]
    call_outcomes = dict(payload.get("call_outcomes_summary") or {})
    outcome_cols = [
        {"label": "ЗВОНКОВ", "value": total_calls, "tone": "neutral"},
        {"label": "ДОГОВОРЕННОСТЬ", "value": _value(call_outcomes.get("agreed_count")), "tone": "positive"},
        {"label": "ПЕРЕНОС", "value": _value(call_outcomes.get("rescheduled_count")), "tone": "focus"},
        {"label": "ОТКАЗ", "value": _value(call_outcomes.get("refusal_count")), "tone": "problem"},
        {"label": "ОТКРЫТ", "value": _value(call_outcomes.get("open_count")), "tone": "warning"},
        {"label": "ТЕХ/СЕРВИС", "value": _value(call_outcomes.get("tech_service_count")), "tone": "neutral"},
    ]
    sections = [
        {
            **_section_meta(template, "day_summary"),
            "outcome_cols": outcome_cols,
        },
        {
            **_section_meta(template, "executive_narrative"),
            "body": narrative["summary"],
            "progress_line": narrative["progress"],
        },
        {
            **_section_meta(template, "signal_of_day"),
            "title": f"Лучший эпизод: {_value(payload['signal_of_day'].get('client_or_phone_mask'), 'Опорный звонок дня')}",
            "body": _value(
                payload["signal_of_day"].get("short_evidence"),
                "В выборке есть сильный эпизод, который стоит использовать как модель поведения.",
            ),
            "time_line": _short_time(payload["signal_of_day"].get("call_time")),
            "items": [
                f"Почему это правильная модель: {_value(payload['signal_of_day'].get('reason_this_matters'), 'Показывает удачный образец разговора за день.')}",
            ],
            "tone": "positive",
        },
        {
            **_section_meta(template, "main_focus_for_tomorrow"),
            "body": payload["main_focus_for_tomorrow"].get("text") or "Фокус не сформирован.",
            "reinforcement": "Это главный ориентир на следующий рабочий день.",
            "tone": "focus",
        },
        {
            **_section_meta(template, "review_block"),
            "left_title": "Что сработало",
            "right_title": "Над чем работать",
            "left_items": [
                f"{item['label']} ({item['signal']}) — {item['interpretation']}"
                for item in payload.get("analysis_worked") or []
            ]
            or [
                "В выборке есть рабочие эпизоды, но для точного выделения сильных паттернов нужно ещё немного устойчивой базы по разбору.",
                "Сейчас ориентируемся на сохранение спокойного темпа разговора и аккуратное ведение клиента к следующему шагу.",
            ],
            "right_items": [
                f"{item['label']} ({item['signal']}) — {item['interpretation']}"
                for item in payload.get("analysis_improve") or []
            ]
            or [
                "Явной доминирующей просадки в этой выборке не выделилось, поэтому держим в фокусе завершение звонка и фиксацию договорённости.",
                "Следующий полный запуск поможет точнее отделить повторяющиеся зоны роста от разовых эпизодов.",
            ],
        },
        {
            **_section_meta(template, "key_problem_of_day"),
            "title": _value(payload["key_problem_of_day"].get("title"), "Критичный провал дня не выделился"),
            "body": _value(
                payload["key_problem_of_day"].get("description"),
                "На этой выборке нет одной доминирующей проблемы. Рабочий фокус остаётся на том, чтобы каждое завершение заканчивалось понятным следующим шагом и зафиксированной договорённостью.",
            ),
            "tone": "problem",
        },
        {
            **_section_meta(template, "recommendations"),
            "editorial_note": _clean_reader_text(
                editorial_recommendations.get("text")
                or "Рекомендации сформированы автоматически и могут быть уточнены оператором перед отправкой."
            ),
            "cards": [
                {
                    "title": item["title"],
                    "priority_tag": item["priority_tag"],
                    "priority_tone": "tomorrow" if item.get("priority_tag") == "Сделай завтра" else "week",
                    "body": _clean_reader_text(item.get("reason") or "Контекст закрепим на ближайшем разборе."),
                    "context": _clean_reader_text(item.get("reason") or "Контекст для примера сформирован по итогам разборов дня."),
                    "how_it_sounded": _clean_reader_text(item.get("how_it_sounded") or "Формулировка пока звучит слишком общей и не закрепляет у клиента конкретный следующий шаг."),
                    "better_phrasing": _clean_reader_text(item.get("better_phrasing") or "Сформулируй следующий шаг конкретно: дата, формат и ответственный."),
                    "why_this_works": _clean_reader_text(item.get("why_this_works") or "Конкретика переводит разговор из намерения в договорённость."),
                    "tone": "orange" if item.get("priority_tag") == "На неделе" else "red",
                }
                for item in payload.get("recommendations") or []
            ],
        },
        {
            **_section_meta(template, "call_outcomes_summary"),
            "metrics": [
                {"label": "Договорились", "value": payload["call_outcomes_summary"].get("agreed_count"), "tone": "positive"},
                {"label": "Перенесли", "value": payload["call_outcomes_summary"].get("rescheduled_count"), "tone": "focus"},
                {"label": "Отказ", "value": payload["call_outcomes_summary"].get("refusal_count"), "tone": "problem"},
                {"label": "Открыт", "value": payload["call_outcomes_summary"].get("open_count"), "tone": "warning"},
            ],
            "note": "Открыт = звонок состоялся, но следующий шаг не зафиксирован.",
        },
        {
            **_section_meta(template, "call_list"),
            "columns": ["Время", "Клиент", "Длит.", "Статус", "Балл", "Следующий шаг"],
            "rows": [
                [
                    _short_time(row.get("time")),
                    _manager_reader_value(row.get("client_or_phone"), "Клиент не определён"),
                    _manager_reader_value(row.get("duration_sec"), "—"),
                    _call_status_label(row.get("status")),
                    _manager_reader_value(row.get("score_percent"), "—"),
                    _manager_reader_value(row.get("next_step"), "—"),
                ]
                for row in payload.get("call_list") or []
            ],
            "note": (
                f"Показаны первые {min(10, len(payload.get('call_list') or []))} из {len(payload.get('call_list') or [])} "
                "звонков дня. Полный список — в CRM."
            ),
        },
        {
            **_section_meta(template, "focus_criterion_dynamics"),
            "pairs": [
                ("Фокусный критерий", _manager_reader_value(focus_dynamics.get("focus_criterion_name"), "Критерий будет определён после накопления базы")),
                ("Текущий период", _manager_reader_value(focus_dynamics.get("current_period_value"), "Нет данных")),
                ("Предыдущий период", _manager_reader_value(focus_dynamics.get("previous_period_value"), "Нет базы сравнения")),
                ("Delta", _manager_reader_value(focus_dynamics.get("delta"), "Нет базы сравнения")),
            ],
            "interpretation": "Сохраняем контроль по одному главному критерию и смотрим, появилась ли динамика между периодами.",
            "bars": [
                {
                    "label": "Предыдущий период",
                    "value": _manager_reader_value(focus_dynamics.get("previous_period_value"), "Нет базы"),
                    "tone": "blue",
                },
                {
                    "label": "Текущий период",
                    "value": _manager_reader_value(focus_dynamics.get("current_period_value"), "Нет данных"),
                    "tone": "orange",
                },
            ],
            "stage_line": (
                f"{_manager_reader_value(focus_dynamics.get('focus_criterion_name'), 'Фокусный критерий')} — "
                f"{_manager_reader_value(focus_dynamics.get('previous_period_value'), 'нет базы')} → "
                f"{_manager_reader_value(focus_dynamics.get('current_period_value'), 'нет данных')}"
            ),
        },
        {
            **_section_meta(template, "memo_legend"),
            "groups": [
                {
                    "title": "Как читать уровни качества",
                    "items": [_call_level_label(item) for item in payload["memo_legend"].get("call_level_legend") or []],
                },
                {
                    "title": "Как читать статусы звонка",
                    "items": [_call_status_label(item) for item in payload["memo_legend"].get("call_status_legend") or []],
                },
                {
                    "title": "Как читать приоритет рекомендаций",
                    "items": payload["memo_legend"].get("recommendation_priority_legend") or [],
                },
                {
                    "title": "Как читать этапы оценки",
                    "items": [
                        "Э1 — контакт и представление",
                        "Э2 — управление временем и переход к сути",
                        "Э3 — выявление потребности",
                        "Э4 — формирование предложения",
                        "Э5 — работа с возражениями",
                        "Э6 — завершение и следующий шаг",
                    ],
                },
            ],
        },
    ]
    return {
        "template": {
            "preset": template.preset,
            "version": template.version,
            "template_id": template.template_id,
        },
        "metadata_line": (
            "Ежедневный отчёт • "
            f"{header['manager_name']} • {header['report_date']} • "
            f"{header['department_name']}"
            + (
                f" • {header['product_or_business_context']}"
                if header.get("product_or_business_context")
                else ""
            )
        ),
        "title": header["report_title"],
        "subtitle": f"{header['manager_name']} • {header['report_date']} • {header['department_name']}",
        "hero_focus": empty_state.get("hero_focus")
        or payload["focus_of_week"].get("text")
        or "На этой неделе держим контроль над конкретным следующим шагом в каждом звонке.",
        "summary_cards": outcome_cols,
        "sections": sections,
        "footer": empty_state.get("footer") or "Конфиденциально · Только для менеджера и РОПа",
        "generation_note": empty_state.get("generation_note") or "",
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
    if template.preset == "manager_daily":
        return _render_manager_daily_html_report(report=report, template=template)
    sections_html = "".join(_render_html_section(section) for section in report["sections"])
    metadata_html = (
        f"<div class=\"metadata-line\"><span>{html.escape(report['metadata_line'])}</span></div>"
    )
    if template.preset == "manager_daily":
        hero_html = (
            "<section class=\"hero\">"
            f"<h1>{html.escape(report['title'])}</h1>"
            f"<p>{html.escape(report['subtitle'])}</p>"
            f"<div class=\"focus-chip\">Фокус недели: {html.escape(report.get('hero_focus') or 'not available')}</div>"
            "</section>"
        )
    else:
        hero_html = (
            "<section class=\"title-page\">"
            f"<h1>{html.escape(report['title'])}</h1>"
            f"<p class=\"subtitle\">{html.escape(report['subtitle'])}</p>"
            "<div class=\"divider\"></div>"
            f"<p>{html.escape(report.get('hero_context') or '')}</p>"
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
    memo = sections["memo_legend"]
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
    review_left = "".join(
        f"<li>{_render_review_item_html(item, positive=True)}</li>"
        for item in review.get("left_items") or ["Нет зафиксированных сильных паттернов."]
    )
    review_right = "".join(
        f"<li>{_render_review_item_html(item, positive=False)}</li>"
        for item in review.get("right_items") or ["Нет зафиксированных зон роста."]
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
                if index == 3
                else f"<td>{html.escape(_manager_reader_value(cell, '—'))}</td>"
            )
            for index, cell in enumerate(row)
        )
        + "</tr>"
        for row in call_list.get("rows") or []
    ) or (
        "<tr><td colspan=\"6\">По выбранным фильтрам нет звонков, готовых к включению в таблицу.</td></tr>"
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
    memo_cards = "".join(
        "<article class=\"memo-card\">"
        f"<h4>{html.escape(str(group.get('title') or 'Памятка'))}</h4>"
        "<ul>"
        + "".join(f"<li>{html.escape(str(item))}</li>" for item in group.get("items") or ["Нет пояснений"])
        + "</ul></article>"
        for group in memo.get("groups") or []
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
        "<section class=\"banner yellow\">"
        f"<span class=\"label\">{html.escape(focus['label'])}:</span> "
        f"<strong>{html.escape(str(focus.get('body') or 'Фокус будет определён после следующего запуска.'))}</strong> "
        f"{html.escape(str(focus.get('reinforcement') or ''))}"
        "</section>"
        f"<div class=\"section-bar navy\">{html.escape(review['label'])}</div>"
        "<section class=\"review-grid\">"
        f"<article class=\"review-col positive\"><h3>✓ {html.escape(str(review.get('left_title') or 'Что сработало'))}</h3><ul>{review_left}</ul></article>"
        f"<article class=\"review-col negative\"><h3>✗ {html.escape(str(review.get('right_title') or 'Над чем работать'))}</h3><ul>{review_right}</ul></article>"
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
    page_four = (
        _manager_daily_page_header(report["metadata_line"]) +
        f"<div class=\"section-bar navy\">{html.escape(memo['label'])}</div>"
        f"<section class=\"memo-grid\">{memo_cards}</section>"
        + _manager_daily_page_footer(report["footer"], 4)
    )
    return (
        "<html><head><meta charset=\"utf-8\">"
        f"<style>{template.css}</style>"
        "</head><body><div class=\"workspace\">"
        f"<section class=\"page\">{page_one}</section>"
        f"<section class=\"page\">{page_two}</section>"
        f"<section class=\"page\">{page_three}</section>"
        f"<section class=\"page\">{page_four}</section>"
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
    if template.preset == "manager_daily":
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
    if template.preset == "manager_daily":
        ensure_space(88)
        y -= 52
        pages[-1].append({"type": "rect", "x": margin, "y": y, "w": width - (margin * 2), "h": 52, "fill": accent})
        pages[-1].append({"type": "text", "x": margin + 14, "y": y + 32, "size": 18, "color": (255, 255, 255), "text": report["title"]})
        pages[-1].append({"type": "text", "x": margin + 14, "y": y + 16, "size": 9.5, "color": (255, 255, 255), "text": report["subtitle"]})
        y -= 12
        add_line(f"Фокус недели: {report.get('hero_focus') or 'not available'}", size=9.5, color=amber, gap=12)
    else:
        add_line(report["title"], size=24, color=accent, gap=2)
        add_line(report["subtitle"], size=11, color=muted, gap=4)
        add_line(report.get("hero_context") or "", size=10, color=black, gap=12)

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
    memo = sections["memo_legend"]

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

    draw_rect(page1, left=margin, top=273, box_width=width - (margin * 2), box_height=78, fill=(243, 245, 247))
    draw_rect(page1, left=margin, top=273, box_width=4, box_height=78, fill=(47, 97, 170))
    draw_text(page1, left=margin + 12, top=286, text=str(executive.get("body") or "Итог дня будет сформирован после следующего запуска."), size=10.4, color=black, max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=327, text=str(executive.get("progress_line") or "Сравнение с базой пока недоступно."), size=9.4, color=muted, max_width=width - (margin * 2) - 24)

    draw_rect(page1, left=margin, top=362, box_width=width - (margin * 2), box_height=54, fill=soft_green)
    draw_rect(page1, left=margin, top=362, box_width=4, box_height=54, fill=green)
    signal_text = (
        f"✓ {signal['label']}: {str(signal.get('body') or 'Опорный пример будет выбран после накопления базы.')} "
        f"Время: {str(signal.get('time_line') or 'не зафиксировано')}. {_manager_signal_reason(signal)}"
    )
    draw_text(page1, left=margin + 12, top=378, text=signal_text, size=10.2, color=black, max_width=width - (margin * 2) - 24)

    draw_rect(page1, left=margin, top=426, box_width=width - (margin * 2), box_height=54, fill=soft_yellow)
    draw_rect(page1, left=margin, top=426, box_width=4, box_height=54, fill=(139, 109, 15))
    focus_text = f"{focus['label']}: {str(focus.get('body') or 'Фокус будет определён после следующего запуска.')} {str(focus.get('reinforcement') or '')}"
    draw_text(page1, left=margin + 12, top=442, text=focus_text, size=10.2, color=black, max_width=width - (margin * 2) - 24)

    draw_section_bar(page1, top=490, title=review["label"], color=accent)
    column_gap = 18
    col_width = (width - (margin * 2) - column_gap) / 2
    draw_rect(page1, left=margin, top=523, box_width=col_width, box_height=128, fill=soft_green)
    draw_rect(page1, left=margin + col_width + column_gap, top=523, box_width=col_width, box_height=128, fill=light_red)
    draw_text(page1, left=margin + 14, top=537, text=f"✓ {review.get('left_title') or 'Что сработало'}", size=11.2, color=green, max_width=col_width - 20)
    draw_text(page1, left=margin + col_width + column_gap + 14, top=537, text=f"✗ {review.get('right_title') or 'Над чем работать'}", size=11.2, color=red, max_width=col_width - 20)
    draw_bullets(page1, left=margin + 14, top=557, items=review.get("left_items") or [], width_limit=col_width - 18, bullet_color=green, size=9.2)
    draw_bullets(page1, left=margin + col_width + column_gap + 14, top=557, items=review.get("right_items") or [], width_limit=col_width - 18, bullet_color=red, size=9.2)

    draw_rect(page1, left=margin, top=664, box_width=width - (margin * 2), box_height=90, fill=light_red)
    draw_rect(page1, left=margin, top=664, box_width=4, box_height=90, fill=red)
    draw_text(page1, left=margin + 12, top=679, text=f"{problem['label']}: {str(problem.get('title') or 'Критичный провал дня не выделился')}", size=11.0, color=red, max_width=width - (margin * 2) - 24)
    draw_text(page1, left=margin + 12, top=701, text=str(problem.get("body") or ""), size=9.8, color=black, max_width=width - (margin * 2) - 24)
    footer(page1, 1)

    page2 = add_page()
    draw_section_bar(page2, top=58, title=recommendations["label"], color=accent)
    rec_top = 92
    for index, card in enumerate(recommendations.get("cards") or []):
        card_fill = soft_week if card.get("tone") == "orange" else soft_problem
        card_edge = amber if card.get("tone") == "orange" else red
        card_height = 152
        draw_rect(page2, left=margin, top=rec_top, box_width=width - (margin * 2), box_height=card_height, fill=card_fill)
        draw_rect(page2, left=margin, top=rec_top, box_width=4, box_height=card_height, fill=card_edge)
        pill_width = 86
        draw_rect(page2, left=width - margin - pill_width, top=rec_top + 12, box_width=pill_width, box_height=20, fill=(194, 103, 17) if card.get("priority_tone") == "week" else (196, 12, 0))
        draw_centered_text(page2, left=width - margin - pill_width, top=rec_top + 18, box_width=pill_width, text=str(card.get("priority_tag") or "Сделай завтра"), size=7.8, color=white)
        draw_text(page2, left=margin + 14, top=rec_top + 18, text=f"{index + 1}. {str(card.get('title') or 'Рекомендация')}", size=11.4, color=accent, max_width=360)
        draw_text(page2, left=margin + 14, top=rec_top + 40, text=str(card.get("context") or card.get("body") or ""), size=9.5, color=black, max_width=width - (margin * 2) - 28)
        example_top = rec_top + 68
        example_width = (width - (margin * 2) - 40) / 2
        draw_rect(page2, left=margin + 14, top=example_top, box_width=example_width, box_height=44, fill=(250, 239, 239))
        draw_rect(page2, left=margin + 14, top=example_top, box_width=2, box_height=44, fill=(227, 167, 164))
        draw_rect(page2, left=margin + 26 + example_width, top=example_top, box_width=example_width, box_height=44, fill=(238, 247, 238))
        draw_rect(page2, left=margin + 26 + example_width, top=example_top, box_width=2, box_height=44, fill=green)
        draw_text(page2, left=margin + 22, top=example_top + 8, text="Как звучало:", size=8.8, color=red, max_width=example_width - 16)
        draw_text(page2, left=margin + 22, top=example_top + 22, text=str(card.get("how_it_sounded") or "Формулировка была слишком общей."), size=8.5, color=muted, max_width=example_width - 16)
        draw_text(page2, left=margin + 34 + example_width, top=example_top + 8, text="Как лучше:", size=8.8, color=green, max_width=example_width - 16)
        draw_text(page2, left=margin + 34 + example_width, top=example_top + 22, text=str(card.get("better_phrasing") or "Сформулируй следующий шаг конкретно."), size=8.5, color=muted, max_width=example_width - 16)
        draw_text(page2, left=margin + 14, top=rec_top + 121, text=f"Почему это работает: {str(card.get('why_this_works') or '')}", size=8.9, color=black, max_width=width - (margin * 2) - 28)
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
    col_widths = [42, 84, 42, 70, 42, width - (margin * 2) - 42 - 84 - 42 - 70 - 42]
    x = margin
    for column, col_width in zip(columns, col_widths, strict=False):
        draw_rect(page3, left=x, top=table_top, box_width=col_width, box_height=22, fill=accent)
        draw_text(page3, left=x + 4, top=table_top + 6, text=str(column), size=8.0, color=white, max_width=col_width - 8)
        x += col_width
    row_top = table_top + 24
    for row in rows[:8]:
        x = margin
        status_value = str(row[3]) if len(row) > 3 else ""
        for index, (cell, col_width) in enumerate(zip(row, col_widths, strict=False)):
            fill = (248, 248, 248)
            if index == 3:
                fill = _manager_status_fill(status_value)
            draw_rect(page3, left=x, top=row_top, box_width=col_width, box_height=24, fill=fill)
            draw_text(page3, left=x + 4, top=row_top + 7, text=str(cell), size=7.7, color=black if index != 3 else _manager_status_text_color(status_value, black, green, amber, red), max_width=col_width - 8)
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
    draw_section_bar(page4, top=58, title=memo["label"], color=accent)
    memo_top = 96
    memo_gap = 16
    memo_width = (width - (margin * 2) - memo_gap) / 2
    memo_height = 130
    for index, group in enumerate(memo.get("groups") or []):
        left = margin + ((memo_width + memo_gap) * (index % 2))
        top = memo_top + ((memo_height + 16) * (index // 2))
        draw_rect(page4, left=left, top=top, box_width=memo_width, box_height=memo_height, fill=(247, 247, 247))
        draw_text(page4, left=left + 14, top=top + 14, text=str(group.get("title") or "Памятка"), size=10.5, color=accent, max_width=memo_width - 28)
        draw_bullets(page4, left=left + 14, top=top + 34, items=[str(item) for item in group.get("items") or ["Нет пояснений"]], width_limit=memo_width - 24, size=8.8)
    footer(page4, 4)
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
