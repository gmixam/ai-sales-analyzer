"""
Verification-only report runner for format testing.

PURPOSE: build a fully-populated manager_daily from synthetic fixture data so that
every visual block can be evaluated without running new AI steps.

ISOLATION guarantees:
- Zero DB reads/writes for fixture data.
- Fixture analyses carry instruction_version="verification_only_v0" and
  scores_detail.provenance="manual_verification_fixture" — they are never
  written to the analyses table and are never usable by the normal reuse path.
- Normal pipeline (reporting.py / orchestrator) is not changed and never
  calls this module.

Usage:
  docker compose exec api python -m app.agents.calls.verification_report_runner
"""

from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timezone

from app.agents.calls.delivery import CallsDelivery
from app.agents.calls.report_templates import render_report_artifact
from app.agents.calls.reporting import (
    ReportArtifact,
    ReportRunFilters,
    build_manager_daily_payload,
)

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

DEPARTMENT_ID = "472cda28-ce71-494c-9068-25d3ffbf7399"
DEPARTMENT_NAME = "[ЭДО] Отдел Продаж"
MANAGER_ID = "09cae83f-7ac1-4ee0-b1d5-3a76c8053c3f"
MANAGER_NAME = "Эльмира Кешубаева"
ANCHOR_DATE = "2026-04-06"
INSTRUCTION_VERSION = "verification_only_v0"
PROVENANCE = "manual_verification_fixture"


# ──────────────────────────────────────────────────────────────
# Analysis contract helpers
# ──────────────────────────────────────────────────────────────
# Key format contract (from _aggregate_finding_items / _aggregate_recommendation_cards):
#   gaps[]:        {"title": ..., "impact": ..., "comment": ..., "evidence": ...}
#   strengths[]:   {"title": ..., "impact": ..., "comment": ..., "evidence": ...}
#   recommendations[]: {"criterion_name": ..., "criterion_code": ..., "better_phrase": ...,
#                        "reason": ..., "problem": ..., "evidence": ...}
#   evidence_fragments[]: {"fragment_type": ..., "client_text": ..., "why": ...}
#   product_signals[]:    {"quote": ..., "topic": ...}

def _gap(title: str, comment: str, impact: str = "") -> dict:
    return {"title": title, "comment": comment, "impact": impact or comment, "evidence": comment}


def _strength(title: str, comment: str) -> dict:
    return {"title": title, "comment": comment, "impact": comment, "evidence": comment}


def _rec(criterion_name: str, criterion_code: str, better_phrase: str,
         reason: str, evidence: str = "") -> dict:
    return {
        "criterion_name": criterion_name,
        "criterion_code": criterion_code,
        "better_phrase": better_phrase,
        "reason": reason,
        "problem": reason,
        "evidence": evidence or reason,
    }


def _efrag(client_text: str, why: str, fragment_type: str = "missed_opportunity") -> dict:
    return {"fragment_type": fragment_type, "client_text": client_text, "why": why}


def _psig(quote: str, topic: str) -> dict:
    return {"quote": quote, "topic": topic}


def _stage(code: str, name: str, stage_score: int, max_score: int,
           criteria: list[dict]) -> dict:
    return {
        "stage_code": code,
        "stage_name": name,
        "stage_score": stage_score,
        "max_stage_score": max_score,
        "criteria_results": criteria,
    }


def _crit(code: str, name: str, score: int, max_score: int, comment: str) -> dict:
    return {
        "criterion_code": code,
        "criterion_name": name,
        "score": score,
        "max_score": max_score,
        "evidence": comment,
        "comment": comment,
    }


# ──────────────────────────────────────────────────────────────
# Shared fixture components
# ──────────────────────────────────────────────────────────────

# The top gap label — used across calls so _aggregate_finding_items sees signal≥3
TOP_GAP = "Не выявляет детальные потребности — переходит в презентацию до понимания задачи клиента"
GAP_2 = "Не проверяет, удобно ли говорить перед началом разговора"
GAP_3 = "Не фиксирует конкретный следующий шаг и срок — перенос остаётся открытым"

STR_1 = "Чётко представляется и называет компанию в начале звонка"
STR_2 = "Сохраняет вежливый и профессиональный тон на протяжении всего разговора"
STR_3 = "Уверенно отрабатывает первичное возражение клиента"

REC_1 = _rec(
    "Выявление детальных потребностей",
    "nd_use_cases",
    "Расскажите, как у вас сейчас организован процесс подписания документов? "
    "Какие типы контрагентов вам важно закрыть в первую очередь?",
    reason="Без понимания конкретного сценария презентация теряет убедительность.",
    evidence="Клиент сам пояснял контекст, менеджер не спрашивал.",
)
REC_2 = _rec(
    "Завершение и фиксация договорённостей",
    "completion_next_step",
    "Итак, договариваемся: я пришлю договор до конца дня, вы ознакомитесь до пятницы — "
    "в пятницу созвонимся и подтвердим. Удобно?",
    reason="Открытый следующий шаг снижает вероятность конверсии.",
    evidence="«Ну хорошо, я подумаю» — без конкретного срока.",
)
REC_3 = _rec(
    "Проверка уместности разговора",
    "cs_permission_and_relevance",
    "Удобно ли вам сейчас пару минут уделить — я расскажу, почему звоню?",
    reason="Клиенты раздражаются, когда разговор начинается без согласия.",
    evidence="Менеджер сразу перешёл к теме, не спросив.",
)

# Stage templates

def _stages_strong() -> list[dict]:
    """Full score on first 3 stages, partial on needs_discovery — score ~75%"""
    return [
        _stage("contact_start", "Первичный контакт", 8, 8, [
            _crit("cs_intro_and_company", "Представился и назвал компанию", 2, 2, "Чётко представился."),
            _crit("cs_permission_and_relevance", "Проверил уместность разговора", 2, 2, "Спросил, удобно ли говорить."),
            _crit("cs_reason_for_call", "Обозначил причину звонка", 2, 2, "Цель звонка озвучена."),
            _crit("cs_tone_and_clarity", "Сохранил вежливый тон", 2, 2, "Тон профессиональный."),
        ]),
        _stage("qualification_primary", "Квалификация и потребность", 7, 8, [
            _crit("qp_current_process", "Выяснил текущий процесс", 2, 2, "Уточнил схему документооборота."),
            _crit("qp_role_and_scope", "Уточнил роль собеседника", 2, 2, "Выяснил, кто принимает решение."),
            _crit("qp_need_or_trigger", "Подтвердил наличие задачи", 2, 2, "Задача подтверждена."),
            _crit("qp_no_early_pitch", "Не ушёл в презентацию рано", 1, 2, "Небольшой ранний pitch."),
        ]),
        _stage("needs_discovery", "Выявление потребностей", 3, 8, [
            _crit("nd_use_cases", "Выявил конкретные сценарии", 1, 2, "Сценарии намечены, не раскрыты."),
            _crit("nd_pain_and_constraints", "Выявил боль и ограничения", 0, 2, "Боль не выявлена."),
            _crit("nd_priority_and_timing", "Понял приоритет и срок", 0, 2, "Сроки не обсуждены."),
            _crit("nd_decision_context", "Понял контекст решения", 2, 2, "Контекст выяснен."),
        ]),
        _stage("presentation", "Формирование предложения", 6, 8, [
            _crit("pr_value_linked_to_context", "Связал ценность с задачей", 2, 2, "Хорошо связал."),
            _crit("pr_adapted_pitch", "Адаптировал подачу", 2, 2, "Адаптировано."),
            _crit("pr_handle_objection", "Отработал возражение", 2, 2, "Отработано."),
            _crit("pr_clear_next_step", "Предложил чёткий шаг", 0, 2, "Шаг нечёткий."),
        ]),
    ]


def _stages_baseline() -> list[dict]:
    """Partial score — baseline range ~50%"""
    return [
        _stage("contact_start", "Первичный контакт", 6, 8, [
            _crit("cs_intro_and_company", "Представился и назвал компанию", 2, 2, "Представился."),
            _crit("cs_permission_and_relevance", "Проверил уместность разговора", 0, 2, "Не спросил."),
            _crit("cs_reason_for_call", "Обозначил причину звонка", 2, 2, "Причина понятна."),
            _crit("cs_tone_and_clarity", "Сохранил вежливый тон", 2, 2, "Тон вежливый."),
        ]),
        _stage("qualification_primary", "Квалификация и потребность", 4, 8, [
            _crit("qp_current_process", "Выяснил текущий процесс", 2, 2, "Уточнил."),
            _crit("qp_role_and_scope", "Уточнил роль собеседника", 0, 2, "Не уточнил."),
            _crit("qp_need_or_trigger", "Подтвердил наличие задачи", 2, 2, "Подтверждено."),
            _crit("qp_no_early_pitch", "Не ушёл в презентацию рано", 0, 2, "Ранний pitch."),
        ]),
        _stage("needs_discovery", "Выявление потребностей", 0, 8, [
            _crit("nd_use_cases", "Выявил конкретные сценарии", 0, 2, "Не выявлено."),
            _crit("nd_pain_and_constraints", "Выявил боль и ограничения", 0, 2, "Не выявлено."),
            _crit("nd_priority_and_timing", "Понял приоритет и срок", 0, 2, "Не обсуждено."),
            _crit("nd_decision_context", "Понял контекст решения", 0, 2, "Не выяснено."),
        ]),
        _stage("presentation", "Формирование предложения", 4, 8, [
            _crit("pr_value_linked_to_context", "Связал ценность с задачей", 2, 2, "Частично."),
            _crit("pr_adapted_pitch", "Адаптировал подачу", 0, 2, "Шаблонно."),
            _crit("pr_handle_objection", "Отработал возражение", 0, 2, "Не отработано."),
            _crit("pr_clear_next_step", "Предложил чёткий шаг", 2, 2, "Шаг предложен."),
        ]),
    ]


def _stages_problematic() -> list[dict]:
    """Low score — problematic range ~25–30%"""
    return [
        _stage("contact_start", "Первичный контакт", 4, 8, [
            _crit("cs_intro_and_company", "Представился и назвал компанию", 2, 2, "Представился."),
            _crit("cs_permission_and_relevance", "Проверил уместность разговора", 0, 2, "Не спросил."),
            _crit("cs_reason_for_call", "Обозначил причину звонка", 0, 2, "Причина не озвучена."),
            _crit("cs_tone_and_clarity", "Сохранил вежливый тон", 2, 2, "Тон нейтральный."),
        ]),
        _stage("qualification_primary", "Квалификация и потребность", 2, 8, [
            _crit("qp_current_process", "Выяснил текущий процесс", 0, 2, "Не выяснил."),
            _crit("qp_role_and_scope", "Уточнил роль собеседника", 2, 2, "Уточнил."),
            _crit("qp_need_or_trigger", "Подтвердил наличие задачи", 0, 2, "Не подтверждено."),
            _crit("qp_no_early_pitch", "Не ушёл в презентацию рано", 0, 2, "Сразу в презентацию."),
        ]),
        _stage("needs_discovery", "Выявление потребностей", 0, 8, [
            _crit("nd_use_cases", "Выявил конкретные сценарии", 0, 2, "Не выявлено."),
            _crit("nd_pain_and_constraints", "Выявил боль и ограничения", 0, 2, "Не выявлено."),
            _crit("nd_priority_and_timing", "Понял приоритет и срок", 0, 2, "Не обсуждено."),
            _crit("nd_decision_context", "Понял контекст решения", 0, 2, "Не выяснено."),
        ]),
        _stage("presentation", "Формирование предложения", 2, 8, [
            _crit("pr_value_linked_to_context", "Связал ценность с задачей", 0, 2, "Не связал."),
            _crit("pr_adapted_pitch", "Адаптировал подачу", 2, 2, "Частично."),
            _crit("pr_handle_objection", "Отработал возражение", 0, 2, "Не отработано."),
            _crit("pr_clear_next_step", "Предложил чёткий шаг", 0, 2, "Нет шага."),
        ]),
    ]


# ──────────────────────────────────────────────────────────────
# Fixture data builder
# ──────────────────────────────────────────────────────────────

def _build_analysis(
    *,
    call_id: str,
    call_time: str,
    duration_sec: int,
    direction: str,
    contact_name: str | None,
    contact_phone: str,
    call_type: str,
    scenario_type: str,
    outcome_code: str,
    outcome_text: str,
    next_step_text: str,
    next_step_fixed: bool,
    due_date_iso: str | None,
    reason_not_fixed: str | None,
    short_summary: str,
    score_by_stage: list[dict],
    gaps: list[dict],
    strengths: list[dict],
    recommendations: list[dict],
    evidence_fragments: list[dict],
    product_signals: list[dict],
) -> dict:
    total = sum(s["stage_score"] for s in score_by_stage)
    max_pts = sum(s["max_stage_score"] for s in score_by_stage)
    pct = round(total / max_pts * 100, 1) if max_pts else 0.0
    level = "strong" if pct >= 75 else ("basic" if pct >= 50 else "problematic")
    return {
        "schema_version": "call_analysis.v1",
        "instruction_version": INSTRUCTION_VERSION,
        "checklist_version": "edo_sales_mvp1_checklist_v1",
        "provenance": PROVENANCE,
        "call": {
            "call_id": call_id,
            "source_system": "onlinepbx",
            "department_id": DEPARTMENT_ID,
            "manager_id": MANAGER_ID,
            "manager_name": MANAGER_NAME,
            "call_started_at": f"{ANCHOR_DATE}T{call_time}+06:00",
            "duration_sec": duration_sec,
            "direction": direction,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "contact_company": None,
            "language": "ru",
        },
        "classification": {
            "call_type": call_type,
            "scenario_type": scenario_type,
            "channel_context": "onlinepbx",
            "analysis_eligibility": "eligible",
            "eligibility_reason": "duration_ge_180_sec_and_sales_relevant",
        },
        "summary": {
            "short_summary": short_summary,
            "context": short_summary,
            "call_goal": "Обсудить возможности системы Договор-24.",
            "outcome_code": outcome_code,
            "outcome_text": outcome_text,
            "next_step_text": next_step_text,
        },
        "score": {
            "legacy_card_score": None,
            "legacy_card_level": None,
            "checklist_score": {
                "total_points": total,
                "max_points": max_pts,
                "score_percent": pct,
                "level": level,
            },
            "critical_failure": False,
            "critical_errors": [],
        },
        "score_by_stage": score_by_stage,
        "strengths": strengths,
        "gaps": gaps,
        "recommendations": recommendations,
        "agreements": [],
        "follow_up": {
            "next_step_fixed": next_step_fixed,
            "next_step_type": "call_back" if not next_step_fixed else "send_materials",
            "next_step_text": next_step_text,
            "owner": "Менеджер",
            "due_date_text": due_date_iso or "Не согласовано",
            "due_date_iso": due_date_iso,
            "reason_not_fixed": reason_not_fixed,
        },
        "product_signals": product_signals,
        "evidence_fragments": evidence_fragments,
        "analytics_tags": [],
        "data_quality": {
            "transcript_quality": "good",
            "classification_quality": "good",
            "analysis_quality": "good",
            "needs_manual_review": False,
            "manual_review_reason": None,
        },
    }


def _build_fixtures() -> list[dict]:
    """8 verification calls with correct contract format for all second-basket blocks."""

    # Repeated gaps — need the same title string across calls for signal counting
    gap_nd = _gap(TOP_GAP,
                  "Менеджер перешёл к презентации продукта, не задав ни одного вопроса "
                  "о текущем документообороте, объёме контрагентов или болевых точках.",
                  impact="Клиент не чувствует, что решение подобрано под его задачу.")
    gap_cs = _gap(GAP_2,
                  "Менеджер начал звонок с темы, не уточнив, удобно ли говорить.",
                  impact="Высокий риск раздражения и преждевременного завершения разговора.")
    gap_ns = _gap(GAP_3,
                  "Разговор завершился без конкретного дедлайна следующего шага.",
                  impact="Вероятность конверсии снижается без чёткой договорённости.")

    str_intro = _strength(STR_1, "Менеджер чётко называет имя и компанию в первой фразе.")
    str_tone  = _strength(STR_2, "Профессиональный тон сохраняется даже при возражениях.")
    str_obj   = _strength(STR_3, "Менеджер не теряется при первом «нет» и мягко переходит к выгодам.")

    # Evidence fragments for ГОЛОС КЛИЕНТА
    ef1 = _efrag(
        "Я вообще-то не понимаю, чем вы отличаетесь от обычного ЭДО.",
        "Клиент не получил достаточно вопросов о своём процессе — возражение возникло из-за отсутствия квалификации.",
        "missed_opportunity",
    )
    ef2 = _efrag(
        "Ну раз уж позвонили, расскажите подробнее — у нас пока нет времени разбираться самим.",
        "Клиент проявил интерес, но менеджер ушёл в стандартный скрипт вместо уточняющих вопросов.",
        "missed_opportunity",
    )
    ef3 = _efrag(
        "Мне нравится, что вы объясняете просто, но хотелось бы конкретику по нашему объёму.",
        "Клиент сигнализирует о потребности в персонализации, которая не была выявлена.",
        "product_signal",
    )

    # Product signals
    ps1 = _psig("Мы подписываем около 300 договоров в месяц — если система ускорит хотя бы треть, это уже интересно.",
                "объём подписания / ROI")
    ps2 = _psig("Сейчас у нас два контрагента, которые вообще не работают с цифровыми документами.",
                "барьеры контрагентов")

    return [
        # ── Call 1: STRONG, agreed, Алексей Морозов ──────────────────────────────
        _build_analysis(
            call_id=str(uuid.UUID(int=1)),
            call_time="09:15:00",
            duration_sec=365,
            direction="outbound",
            contact_name="Алексей Морозов",
            contact_phone="+77019996001",
            call_type="sales_primary",
            scenario_type="warm_webinar_or_lead",
            outcome_code="agreed",
            outcome_text="Договорились на подключение тарифа Бизнес.",
            next_step_text="Направить договор на email до 17:00.",
            next_step_fixed=True,
            due_date_iso="2026-04-06",
            reason_not_fixed=None,
            short_summary="Клиент заинтересован в ЭДО, договорились о подключении.",
            score_by_stage=_stages_strong(),
            strengths=[str_intro, str_tone],
            gaps=[gap_nd],
            recommendations=[REC_1, REC_3],
            evidence_fragments=[ef1],
            product_signals=[ps1],
        ),
        # ── Call 2: PROBLEMATIC, rescheduled, Анна Сидорова ─────────────────────
        # next_step_fixed=False + reason_not_fixed with "перезвон" → status=rescheduled
        _build_analysis(
            call_id=str(uuid.UUID(int=2)),
            call_time="10:30:00",
            duration_sec=290,
            direction="outbound",
            contact_name="Анна Сидорова",
            contact_phone="+77019996002",
            call_type="sales_primary",
            scenario_type="cold_outbound",
            outcome_code="callback_planned",
            outcome_text="Клиент попросил перезвонить позже.",
            next_step_text="Перезвонить 07.04 после 14:00.",
            next_step_fixed=False,
            due_date_iso="2026-04-07",
            reason_not_fixed="Попросила перезвонить — занята до следующей недели",
            short_summary="Клиент занят, попросила перезвонить позже.",
            score_by_stage=_stages_problematic(),
            strengths=[str_intro],
            gaps=[gap_nd, gap_cs, gap_ns],
            recommendations=[REC_1, REC_2, REC_3],
            evidence_fragments=[ef2],
            product_signals=[],
        ),
        # ── Call 3: STRONG, agreed, inbound ──────────────────────────────────────
        _build_analysis(
            call_id=str(uuid.UUID(int=3)),
            call_time="11:00:00",
            duration_sec=412,
            direction="inbound",
            contact_name=None,
            contact_phone="+77019876543",
            call_type="sales_primary",
            scenario_type="hot_incoming_contact",
            outcome_code="agreed",
            outcome_text="Клиент согласился на демо-доступ.",
            next_step_text="Отправить ссылку на демо на email.",
            next_step_fixed=True,
            due_date_iso="2026-04-07",
            reason_not_fixed=None,
            short_summary="Входящий интерес к системе, договорились о демо.",
            score_by_stage=[
                _stage("contact_start", "Первичный контакт", 8, 8, [
                    _crit("cs_intro_and_company", "Представился и назвал компанию", 2, 2, "Отлично."),
                    _crit("cs_permission_and_relevance", "Проверил уместность разговора", 2, 2, "Спросил."),
                    _crit("cs_reason_for_call", "Обозначил причину звонка", 2, 2, "Обозначил."),
                    _crit("cs_tone_and_clarity", "Сохранил вежливый тон", 2, 2, "Отличный тон."),
                ]),
                _stage("qualification_primary", "Квалификация и потребность", 8, 8, [
                    _crit("qp_current_process", "Выяснил текущий процесс", 2, 2, "Полностью."),
                    _crit("qp_role_and_scope", "Уточнил роль собеседника", 2, 2, "Выяснил."),
                    _crit("qp_need_or_trigger", "Подтвердил наличие задачи", 2, 2, "Подтверждено."),
                    _crit("qp_no_early_pitch", "Не ушёл в презентацию рано", 2, 2, "Отлично."),
                ]),
                _stage("needs_discovery", "Выявление потребностей", 6, 8, [
                    _crit("nd_use_cases", "Выявил конкретные сценарии", 2, 2, "Выявил."),
                    _crit("nd_pain_and_constraints", "Выявил боль и ограничения", 2, 2, "Выявил."),
                    _crit("nd_priority_and_timing", "Понял приоритет и срок", 0, 2, "Не обсуждено."),
                    _crit("nd_decision_context", "Понял контекст решения", 2, 2, "Выяснил."),
                ]),
                _stage("presentation", "Формирование предложения", 7, 8, [
                    _crit("pr_value_linked_to_context", "Связал ценность с задачей", 2, 2, "Отлично."),
                    _crit("pr_adapted_pitch", "Адаптировал подачу", 2, 2, "Адаптировано."),
                    _crit("pr_handle_objection", "Отработал возражение", 2, 2, "Снял возражение."),
                    _crit("pr_clear_next_step", "Предложил чёткий шаг", 1, 2, "Шаг без дедлайна."),
                ]),
            ],
            strengths=[str_intro, str_tone, str_obj],
            gaps=[gap_nd],
            recommendations=[REC_1],
            evidence_fragments=[ef3],
            product_signals=[ps2],
        ),
        # ── Call 4: BASELINE, agreed (callback_planned outcome, fixed step) ──────
        _build_analysis(
            call_id=str(uuid.UUID(int=4)),
            call_time="11:45:00",
            duration_sec=245,
            direction="outbound",
            contact_name="Дмитрий Козлов",
            contact_phone="+77019996004",
            call_type="sales_primary",
            scenario_type="warm_webinar_or_lead",
            outcome_code="callback_planned",
            outcome_text="Клиент запросил КП для изучения.",
            next_step_text="Прислать КП на email. Перезвонить через 2 дня.",
            next_step_fixed=True,
            due_date_iso="2026-04-08",
            reason_not_fixed=None,
            short_summary="Клиент запросил коммерческое предложение.",
            score_by_stage=_stages_baseline(),
            strengths=[str_intro],
            gaps=[gap_nd, gap_ns],
            recommendations=[REC_1, REC_2],
            evidence_fragments=[],
            product_signals=[],
        ),
        # ── Call 5: PROBLEMATIC, rescheduled (перезвон → status=rescheduled) ─────
        _build_analysis(
            call_id=str(uuid.UUID(int=5)),
            call_time="12:10:00",
            duration_sec=195,
            direction="outbound",
            contact_name="Мария Петрова",
            contact_phone="+77019996005",
            call_type="sales_primary",
            scenario_type="cold_outbound",
            outcome_code="callback_planned",
            outcome_text="Договорились перезвонить в пятницу.",
            next_step_text="Перезвонить в пятницу до 12:00.",
            next_step_fixed=False,
            due_date_iso="2026-04-10",
            reason_not_fixed="Перенос на пятницу, попросила перезвонить позже",
            short_summary="Клиент занята, перенесли звонок на пятницу.",
            score_by_stage=_stages_problematic(),
            strengths=[],
            gaps=[gap_nd, gap_cs],
            recommendations=[REC_1, REC_3],
            evidence_fragments=[],
            product_signals=[],
        ),
        # ── Call 6: PROBLEMATIC, refusal ─────────────────────────────────────────
        # next_step_fixed=False + reason_not_fixed with "отказ" → status=refusal
        _build_analysis(
            call_id=str(uuid.UUID(int=6)),
            call_time="13:00:00",
            duration_sec=180,
            direction="inbound",
            contact_name=None,
            contact_phone="+77071234567",
            call_type="sales_primary",
            scenario_type="hot_incoming_contact",
            outcome_code="refusal",
            outcome_text="Клиент отказался, уже работает с другим оператором.",
            next_step_text="Предложить вернуться через 3 месяца.",
            next_step_fixed=False,
            due_date_iso=None,
            reason_not_fixed="Отказ — работает с конкурентом, не интересно",
            short_summary="Клиент уже использует другую систему ЭДО.",
            score_by_stage=_stages_problematic(),
            strengths=[],
            gaps=[gap_nd, gap_cs, gap_ns],
            recommendations=[REC_1, REC_2, REC_3],
            evidence_fragments=[],
            product_signals=[],
        ),
        # ── Call 7: BASELINE, open (no fixed step, no keyword → open) ────────────
        _build_analysis(
            call_id=str(uuid.UUID(int=7)),
            call_time="14:20:00",
            duration_sec=335,
            direction="outbound",
            contact_name="Сергей Иванов",
            contact_phone="+77019996007",
            call_type="sales_primary",
            scenario_type="warm_webinar_or_lead",
            outcome_code="open",
            outcome_text="Клиент взял паузу, нужно одобрение руководства.",
            next_step_text="Ждать ответа от клиента.",
            next_step_fixed=False,
            due_date_iso=None,
            reason_not_fixed="Ждёт одобрения руководства",
            short_summary="Клиент интересуется, но нужно согласование.",
            score_by_stage=_stages_baseline(),
            strengths=[str_intro, str_tone],
            gaps=[gap_ns],
            recommendations=[REC_2],
            evidence_fragments=[],
            product_signals=[],
        ),
        # ── Call 8: STRONG, agreed, Лариса Новикова ──────────────────────────────
        _build_analysis(
            call_id=str(uuid.UUID(int=8)),
            call_time="15:30:00",
            duration_sec=478,
            direction="inbound",
            contact_name="Лариса Новикова",
            contact_phone="+77019996008",
            call_type="sales_primary",
            scenario_type="hot_incoming_contact",
            outcome_code="agreed",
            outcome_text="Договорились о пробном периоде на 14 дней.",
            next_step_text="Активировать пробный доступ и отправить инструкцию.",
            next_step_fixed=True,
            due_date_iso="2026-04-07",
            reason_not_fixed=None,
            short_summary="Клиент запросил пробный доступ, договорились.",
            score_by_stage=_stages_strong(),
            strengths=[str_intro, str_tone, str_obj],
            gaps=[gap_nd, gap_ns],
            recommendations=[REC_1, REC_2],
            evidence_fragments=[],
            product_signals=[ps1],
        ),
    ]


# ──────────────────────────────────────────────────────────────
# Mock ORM object builders
# ──────────────────────────────────────────────────────────────

def _make_interaction(call_id: str, scores_detail: dict) -> object:
    call = scores_detail.get("call", {})
    ns = types.SimpleNamespace()
    ns.id = uuid.UUID(call_id)
    ns.department_id = uuid.UUID(DEPARTMENT_ID)
    ns.manager_id = uuid.UUID(MANAGER_ID)
    ns.duration_sec = call.get("duration_sec", 0)
    ns.metadata_ = {
        "call_date": call.get("call_started_at", ""),
        "contact_phone": call.get("contact_phone", ""),
        "manager_name": MANAGER_NAME,
    }
    ns.text = "Верификационный транскрипт — не AI-generated."
    return ns


def _make_analysis(scores_detail: dict) -> object:
    score = scores_detail.get("score", {}).get("checklist_score", {})
    ns = types.SimpleNamespace()
    ns.id = uuid.uuid4()
    ns.instruction_version = INSTRUCTION_VERSION
    ns.score_total = score.get("score_percent", 0.0)
    ns.scores_detail = scores_detail
    ns.is_failed = False
    ns.fail_reason = None
    return ns


def _make_manager() -> object:
    ns = types.SimpleNamespace()
    ns.id = uuid.UUID(MANAGER_ID)
    ns.name = MANAGER_NAME
    return ns


def _build_artifacts(fixture_list: list[dict]) -> list[ReportArtifact]:
    manager = _make_manager()
    artifacts = []
    for detail in fixture_list:
        call = detail.get("call", {})
        call_id = str(call.get("call_id", uuid.uuid4()))
        try:
            call_started_at = datetime.fromisoformat(
                call.get("call_started_at", "")).astimezone(timezone.utc)
        except (ValueError, TypeError):
            call_started_at = None
        artifacts.append(ReportArtifact(
            interaction=_make_interaction(call_id, detail),
            analysis=_make_analysis(detail),
            manager=manager,
            call_started_at=call_started_at,
        ))
    return artifacts


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

async def run() -> None:
    print("=" * 60)
    print("VERIFICATION-ONLY REPORT RUNNER")
    print(f"Provenance: {PROVENANCE}")
    print("No DB reads/writes. No AI steps.")
    print("=" * 60)

    fixture_list = _build_fixtures()
    artifacts = _build_artifacts(fixture_list)
    filters = ReportRunFilters(
        manager_ids={MANAGER_ID},
        date_from=ANCHOR_DATE,
        date_to=ANCHOR_DATE,
    )

    payload = build_manager_daily_payload(
        department_id=DEPARTMENT_ID,
        department_name=DEPARTMENT_NAME,
        artifacts=artifacts,
        period={"date_from": ANCHOR_DATE, "date_to": ANCHOR_DATE},
        filters=filters,
        mode="report_from_ready_data_only",
        model_override=None,
    )
    payload["meta"]["verification_only"] = True
    payload["meta"]["provenance"] = PROVENANCE

    # Quick content check
    kp = payload.get("key_problem_of_day", {})
    voc = payload.get("voice_of_customer", {})
    ads = payload.get("additional_situations", {})
    ct = payload.get("call_tomorrow", {})
    sr = payload.get("score_by_stage", [])
    cb = payload.get("call_breakdown", {})

    print(f"\nManager: {payload['header']['manager_name']} | Calls: {payload['kpi_overview']['calls_count']}")
    print(f"СИТУАЦИЯ ДНЯ: title={kp.get('title', '')[:50]!r}, example={bool(kp.get('call_example'))}, scripts={len(kp.get('scripts') or [])}")
    print(f"РАЗБОР ЗВОНКА: placeholder={cb.get('is_placeholder')}, stages={len(cb.get('stage_steps') or [])}")
    print(f"ГОЛОС КЛИЕНТА: placeholder={voc.get('is_placeholder')}, quotes={len(voc.get('situations') or [])}")
    print(f"ДОП СИТУАЦИИ:  placeholder={ads.get('is_placeholder')}, situations={len(ads.get('situations') or [])}")
    print(f"ПОЗВОНИ ЗАВТРА: contacts={len(ct.get('contacts') or [])}")
    for c in (ct.get("contacts") or []):
        print(f"  {c.get('client_label')} | {c.get('status')} | {c.get('deadline')}")
    print(f"БАЛЛЫ ПО ЭТАПАМ: rows={len(sr)}")
    for row in sr:
        print(f"  {row.get('stage_name')} avg={row.get('score')} prio={row.get('is_priority')} crit={len(row.get('criteria_detail') or [])}")

    rendered = render_report_artifact(payload)
    pdf_bytes: bytes = rendered["pdf_bytes"]
    print(f"\nPDF rendered: {len(pdf_bytes):,} bytes, {rendered.get('page_count')} pages")

    from app.core_shared.db.session import SessionLocal
    with SessionLocal() as db:
        delivery = CallsDelivery(department_id=DEPARTMENT_ID, db=db)
        result = delivery.deliver_operator_report(
            primary_email=None,
            cc_emails=[],
            subject=f"[VERIFICATION ONLY] {MANAGER_NAME} — {ANCHOR_DATE}",
            text=rendered.get("text", ""),
            html=rendered.get("html"),
            pdf_bytes=pdf_bytes,
            pdf_filename=f"verification_{MANAGER_NAME.replace(' ', '_')}_{ANCHOR_DATE}.pdf",
            template_meta=payload["meta"].get("report_template"),
            send_business_email=False,
            morning_card_text=(
                f"[ВЕРИФИКАЦИЯ ФОРМАТА — ВТОРАЯ КОРЗИНА]\n"
                f"{ANCHOR_DATE} · {MANAGER_NAME}\n"
                f"{len(artifacts)} синтетических звонков · {PROVENANCE}"
            ),
        )
    tg_status = (result.get("telegram_test_delivery") or {}).get("status") or "sent (see log)"
    print(f"\nTelegram: {tg_status}")
    print("\nDone. VERIFICATION-ONLY — not a production AI artifact.")


if __name__ == "__main__":
    asyncio.run(run())
