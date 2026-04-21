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
import sys
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
# Fixture helpers
# ──────────────────────────────────────────────────────────────

def _ts(time_str: str) -> datetime:
    return datetime.fromisoformat(f"{ANCHOR_DATE}T{time_str}+06:00").astimezone(timezone.utc)


def _analysis(
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
    strengths: list[dict],
    gaps: list[dict],
    recommendations: list[dict],
) -> dict:
    total_pts = sum(s["stage_score"] for s in score_by_stage)
    max_pts = sum(s["max_stage_score"] for s in score_by_stage)
    score_pct = round(total_pts / max_pts * 100, 1) if max_pts else 0.0
    level = "strong" if score_pct >= 75 else ("basic" if score_pct >= 50 else "problematic")
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
                "total_points": total_pts,
                "max_points": max_pts,
                "score_percent": score_pct,
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
        "product_signals": [],
        "evidence_fragments": [
            {
                "fragment": short_summary[:60] + "...",
                "speaker": "manager",
                "quality_signal": "positive" if score_pct >= 60 else "negative",
            }
        ],
        "analytics_tags": [],
        "data_quality": {
            "transcript_quality": "good",
            "classification_quality": "good",
            "analysis_quality": "good",
            "needs_manual_review": False,
            "manual_review_reason": None,
        },
    }


def _stage(code: str, name: str, stage_score: int, max_score: int, criteria: list[dict]) -> dict:
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
        "evidence": "— (верификационный кейс)",
        "comment": comment,
    }


def _gap(label: str, count: int = 1) -> dict:
    return {"label": label, "count": count, "call_ids": [], "examples": []}


def _strength(label: str, count: int = 1) -> dict:
    return {"label": label, "count": count, "call_ids": [], "examples": []}


def _rec(title: str, action: str) -> dict:
    return {
        "title": title,
        "body": action,
        "priority": "high",
        "stage_code": "needs_discovery",
        "criterion_code": None,
    }


# ──────────────────────────────────────────────────────────────
# Fixture data — 8 calls
# ──────────────────────────────────────────────────────────────

def _build_fixtures() -> list[dict]:
    """Return list of 8 analysis dicts for the verification case."""

    # Shared stages to reuse
    stage_cs_ok = _stage("contact_start", "Первичный контакт", 8, 8, [
        _crit("cs_intro_and_company", "Представился и обозначил компанию", 2, 2, "Чётко представился в начале."),
        _crit("cs_permission_and_relevance", "Проверил уместность разговора", 2, 2, "Уточнил, удобно ли говорить."),
        _crit("cs_reason_for_call", "Понятно обозначил причину звонка", 2, 2, "Озвучил цель звонка."),
        _crit("cs_tone_and_clarity", "Сохранил вежливый тон", 2, 2, "Тон вежливый, понятный."),
    ])
    stage_cs_partial = _stage("contact_start", "Первичный контакт", 4, 8, [
        _crit("cs_intro_and_company", "Представился и обозначил компанию", 2, 2, "Представился."),
        _crit("cs_permission_and_relevance", "Проверил уместность разговора", 0, 2, "Не проверил, удобно ли говорить."),
        _crit("cs_reason_for_call", "Понятно обозначил причину звонка", 2, 2, "Причина понятна."),
        _crit("cs_tone_and_clarity", "Сохранил вежливый тон", 0, 2, "Тон несколько напряжённый."),
    ])
    stage_qp_ok = _stage("qualification_primary", "Квалификация и потребность", 6, 8, [
        _crit("qp_current_process", "Выяснил текущий процесс", 2, 2, "Уточнил, как работают с документами."),
        _crit("qp_role_and_scope", "Уточнил роль собеседника", 2, 2, "Выяснил, кто принимает решение."),
        _crit("qp_need_or_trigger", "Проверил наличие реальной задачи", 2, 2, "Подтвердил интерес к системе."),
        _crit("qp_no_early_pitch", "Не ушёл в презентацию рано", 0, 2, "Начал презентацию до завершения квалификации."),
    ])
    stage_qp_weak = _stage("qualification_primary", "Квалификация и потребность", 2, 8, [
        _crit("qp_current_process", "Выяснил текущий процесс", 0, 2, "Текущий процесс не выяснен."),
        _crit("qp_role_and_scope", "Уточнил роль собеседника", 2, 2, "Роль уточнена."),
        _crit("qp_need_or_trigger", "Проверил наличие реальной задачи", 0, 2, "Реальная задача не проверена."),
        _crit("qp_no_early_pitch", "Не ушёл в презентацию рано", 0, 2, "Ушёл в презентацию немедленно."),
    ])
    stage_nd_ok = _stage("needs_discovery", "Выявление детальных потребностей", 6, 8, [
        _crit("nd_use_cases", "Выявил конкретные сценарии", 2, 2, "Уточнил типы документов и сценарии."),
        _crit("nd_pain_and_constraints", "Выявил боль и ограничения", 2, 2, "Выявил неудобство текущего процесса."),
        _crit("nd_priority_and_timing", "Понял приоритет и срок", 0, 2, "Сроки не обсуждались."),
        _crit("nd_decision_context", "Понял контекст принятия решения", 2, 2, "Выяснил, кто влияет на решение."),
    ])
    stage_nd_weak = _stage("needs_discovery", "Выявление детальных потребностей", 0, 8, [
        _crit("nd_use_cases", "Выявил конкретные сценарии", 0, 2, "Сценарии не выявлены."),
        _crit("nd_pain_and_constraints", "Выявил боль и ограничения", 0, 2, "Боль не выявлена."),
        _crit("nd_priority_and_timing", "Понял приоритет и срок", 0, 2, "Сроки не обсуждались."),
        _crit("nd_decision_context", "Понял контекст принятия решения", 0, 2, "Контекст не выяснен."),
    ])
    stage_pr_ok = _stage("presentation", "Формирование предложения", 6, 8, [
        _crit("pr_value_linked_to_context", "Связал ценность с контекстом", 2, 2, "Привязал преимущества к задаче клиента."),
        _crit("pr_adapted_pitch", "Адаптировал подачу под тип клиента", 2, 2, "Подача адаптирована."),
        _crit("pr_handle_objection", "Отработал возражение", 2, 2, "Возражение отработано."),
        _crit("pr_clear_next_step", "Предложил чёткий следующий шаг", 0, 2, "Следующий шаг сформулирован нечётко."),
    ])
    stage_pr_mid = _stage("presentation", "Формирование предложения", 4, 8, [
        _crit("pr_value_linked_to_context", "Связал ценность с контекстом", 2, 2, "Частично связал ценность."),
        _crit("pr_adapted_pitch", "Адаптировал подачу", 0, 2, "Подача шаблонная."),
        _crit("pr_handle_objection", "Отработал возражение", 0, 2, "Возражение не отработано."),
        _crit("pr_clear_next_step", "Предложил чёткий следующий шаг", 2, 2, "Следующий шаг предложен."),
    ])

    common_gaps = [
        _gap("Не проверяет возможность говорить перед началом разговора", 5),
        _gap("Не выявляет детальные потребности — уходит в презентацию рано", 4),
        _gap("Не фиксирует конкретный следующий шаг и сроки", 3),
    ]
    common_strengths = [
        _strength("Чётко представляется и называет компанию", 6),
        _strength("Сохраняет вежливый и профессиональный тон", 5),
    ]
    common_recs = [
        _rec(
            "Ввести стандарт проверки «удобно ли говорить»",
            "Перед переходом к теме всегда уточнять: «Вам удобно говорить сейчас?» "
            "Это снижает раздражение и повышает вовлечённость клиента.",
        ),
        _rec(
            "Задавать вопросы о боли ДО презентации",
            "Выяснить текущую проблему клиента и только после этого предлагать решение. "
            "Шаблон: «Расскажите, как сейчас у вас организован процесс?»",
        ),
    ]

    return [
        # Call 1 — outbound, 75%, agreed, "Алексей Морозов"
        _analysis(
            call_id=str(uuid.UUID(int=1)),
            call_time="09:15:00",
            duration_sec=365,
            direction="outbound",
            contact_name="Алексей Морозов",
            contact_phone="+77019996001",
            call_type="sales_primary",
            scenario_type="warm_webinar_or_lead",
            outcome_code="agreed",
            outcome_text="Договорились о подключении тарифа.",
            next_step_text="Направить договор на email до 17:00.",
            next_step_fixed=True,
            due_date_iso="2026-04-06",
            reason_not_fixed=None,
            short_summary="Клиент заинтересован в ЭДО, договорились о подключении.",
            score_by_stage=[stage_cs_ok, stage_qp_ok, stage_nd_ok, stage_pr_ok],
            strengths=common_strengths[:],
            gaps=[common_gaps[0]],
            recommendations=[common_recs[0]],
        ),
        # Call 2 — outbound, 31%, rescheduled, "Анна Сидорова"
        _analysis(
            call_id=str(uuid.UUID(int=2)),
            call_time="10:30:00",
            duration_sec=290,
            direction="outbound",
            contact_name="Анна Сидорова",
            contact_phone="+77019996002",
            call_type="sales_primary",
            scenario_type="cold_outbound",
            outcome_code="callback_planned",
            outcome_text="Клиент попросил перезвонить на следующей неделе.",
            next_step_text="Перезвонить 07.04 после 14:00.",
            next_step_fixed=True,
            due_date_iso="2026-04-07",
            reason_not_fixed=None,
            short_summary="Клиент занят, попросил перезвонить позже.",
            score_by_stage=[stage_cs_partial, stage_qp_weak, stage_nd_weak, stage_pr_mid],
            strengths=[],
            gaps=common_gaps[:],
            recommendations=common_recs[:],
        ),
        # Call 3 — inbound, 87%, agreed, phone
        _analysis(
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
            due_date_iso="2026-04-06",
            reason_not_fixed=None,
            short_summary="Входящий интерес к системе, договорились о демо.",
            score_by_stage=[
                stage_cs_ok,
                _stage("qualification_primary", "Квалификация и потребность", 8, 8, [
                    _crit("qp_current_process", "Выяснил текущий процесс", 2, 2, "Полностью выяснен."),
                    _crit("qp_role_and_scope", "Уточнил роль собеседника", 2, 2, "Роль и масштаб выяснены."),
                    _crit("qp_need_or_trigger", "Проверил наличие реальной задачи", 2, 2, "Задача подтверждена."),
                    _crit("qp_no_early_pitch", "Не ушёл в презентацию рано", 2, 2, "Квалификация завершена до презентации."),
                ]),
                stage_nd_ok,
                _stage("presentation", "Формирование предложения", 7, 8, [
                    _crit("pr_value_linked_to_context", "Связал ценность с контекстом", 2, 2, "Отлично связал."),
                    _crit("pr_adapted_pitch", "Адаптировал подачу", 2, 2, "Подача адаптирована."),
                    _crit("pr_handle_objection", "Отработал возражение", 2, 2, "Возражение снято."),
                    _crit("pr_clear_next_step", "Предложил чёткий следующий шаг", 1, 2, "Шаг предложен, но без чёткого дедлайна."),
                ]),
            ],
            strengths=[
                _strength("Чётко представляется и называет компанию", 6),
                _strength("Завершает квалификацию до начала презентации", 3),
                _strength("Точно отрабатывает возражения", 2),
            ],
            gaps=[common_gaps[0]],
            recommendations=[common_recs[0]],
        ),
        # Call 4 — outbound, 50%, callback_planned, "Дмитрий Козлов"
        _analysis(
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
            score_by_stage=[stage_cs_ok, stage_qp_ok, stage_nd_weak, stage_pr_mid],
            strengths=[common_strengths[0]],
            gaps=[common_gaps[1], common_gaps[2]],
            recommendations=[common_recs[1]],
        ),
        # Call 5 — outbound, 43%, rescheduled, "Мария Петрова"
        _analysis(
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
            next_step_fixed=True,
            due_date_iso="2026-04-10",
            reason_not_fixed=None,
            short_summary="Клиент занят, перенесли звонок на пятницу.",
            score_by_stage=[stage_cs_partial, stage_qp_ok, stage_nd_weak, stage_pr_mid],
            strengths=[],
            gaps=[common_gaps[1], common_gaps[0]],
            recommendations=[common_recs[1], common_recs[0]],
        ),
        # Call 6 — inbound, 25%, refusal
        _analysis(
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
            reason_not_fixed="Клиент отказался — работает с конкурентом",
            short_summary="Клиент уже использует другую систему ЭДО, отказ.",
            score_by_stage=[stage_cs_partial, stage_qp_weak, stage_nd_weak, stage_pr_mid],
            strengths=[],
            gaps=common_gaps[:],
            recommendations=common_recs[:],
        ),
        # Call 7 — outbound, 62%, open, "Сергей Иванов"
        _analysis(
            call_id=str(uuid.UUID(int=7)),
            call_time="14:20:00",
            duration_sec=335,
            direction="outbound",
            contact_name="Сергей Иванов",
            contact_phone="+77019996007",
            call_type="sales_primary",
            scenario_type="warm_webinar_or_lead",
            outcome_code="open",
            outcome_text="Клиент взял паузу, нужно уточнение у руководства.",
            next_step_text="Ждать ответа от клиента.",
            next_step_fixed=False,
            due_date_iso=None,
            reason_not_fixed=None,
            short_summary="Клиент интересуется, но нужно одобрение руководства.",
            score_by_stage=[stage_cs_ok, stage_qp_ok, stage_nd_ok, stage_pr_mid],
            strengths=[common_strengths[0], common_strengths[1]],
            gaps=[common_gaps[2]],
            recommendations=[common_recs[1]],
        ),
        # Call 8 — inbound, 68%, agreed, "Лариса Новикова"
        _analysis(
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
            score_by_stage=[
                stage_cs_ok,
                stage_qp_ok,
                stage_nd_ok,
                _stage("presentation", "Формирование предложения", 6, 8, [
                    _crit("pr_value_linked_to_context", "Связал ценность с контекстом", 2, 2, "Хорошо связал."),
                    _crit("pr_adapted_pitch", "Адаптировал подачу", 2, 2, "Адаптация есть."),
                    _crit("pr_handle_objection", "Отработал возражение", 0, 2, "Возражение пропущено."),
                    _crit("pr_clear_next_step", "Предложил чёткий следующий шаг", 2, 2, "Чёткий шаг предложен."),
                ]),
            ],
            strengths=common_strengths[:],
            gaps=[common_gaps[0], common_gaps[2]],
            recommendations=[common_recs[0]],
        ),
    ]


# ──────────────────────────────────────────────────────────────
# Mock ORM object builder
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
        started_raw = call.get("call_started_at", "")
        try:
            call_started_at = datetime.fromisoformat(started_raw).astimezone(timezone.utc)
        except (ValueError, TypeError):
            call_started_at = None
        artifacts.append(
            ReportArtifact(
                interaction=_make_interaction(call_id, detail),
                analysis=_make_analysis(detail),
                manager=manager,
                call_started_at=call_started_at,
            )
        )
    return artifacts


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

async def run() -> None:
    print("=" * 60)
    print("VERIFICATION-ONLY REPORT RUNNER")
    print("Provenance: manual_verification_fixture")
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
    # Mark provenance clearly in payload meta
    payload["meta"]["verification_only"] = True
    payload["meta"]["provenance"] = PROVENANCE

    print(f"\nPayload built. Manager: {payload['header']['manager_name']}")
    print(f"Calls: {payload['kpi_overview']['calls_count']}")

    rendered = render_report_artifact(payload)
    pdf_bytes: bytes = rendered["pdf_bytes"]
    print(f"PDF rendered: {len(pdf_bytes)} bytes, {rendered.get('page_count')} pages")

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
                f"[ВЕРИФИКАЦИЯ ФОРМАТА] {ANCHOR_DATE}\n"
                f"{MANAGER_NAME} — {len(artifacts)} звонков (синтетические данные)\n"
                f"Провенанс: {PROVENANCE}"
            ),
        )
    telegram_status = (result.get("telegram_test_delivery") or {}).get("status") or "sent (see log)"
    print(f"\nTelegram delivery: {telegram_status}")
    print("\nDone. This report is VERIFICATION-ONLY — not an AI production artifact.")


if __name__ == "__main__":
    asyncio.run(run())
