"""Calls analyzer wired to the approved MVP-1 checklist and contract."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from openai import OpenAI
from sqlalchemy.orm import Session

from app.core_shared.ai_routing import AIProviderRouter
from app.core_shared.config.settings import settings
from app.core_shared.db.models import Interaction
from app.core_shared.exceptions import AnalysisError, LLMResponseError, SemanticAnalysisError

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
MVP1_SOURCE_FILE_NAMES = {
    "handoff": "MVP1_CODEX_HANDOFF.md",
    "checklist": "MVP1_CHECKLIST_DEFINITION_v1.md",
    "contract": "MVP1_CALL_ANALYSIS_CONTRACT_v1.md",
    "example": "MVP1_CALL_ANALYSIS_EXAMPLE_TIMUR_v1.json",
    "manager_card": "MVP1_MANAGER_CARD_FORMAT_v1.md",
}

MVP1_SOURCE_DIR_CANDIDATES = [
    Path(__file__).resolve().parents[4] / "docs" / "mvp1_sources",
    Path(__file__).resolve().parents[3] / "docs" / "mvp1_sources",
    Path(__file__).resolve().parent / "mvp1_sources",
]

APPROVED_SCHEMA_VERSION = "call_analysis.v1"
APPROVED_INSTRUCTION_VERSION = "edo_sales_mvp1_call_analysis_v1"
APPROVED_CHECKLIST_VERSION = "edo_sales_mvp1_checklist_v1"
SEMANTIC_EMPTY_ANALYSIS_REASON = "semantically_empty_analysis"
ANALYSIS_FORENSICS_ATTR = "_analysis_forensics"

CHECKLIST_DEFINITION: dict[str, Any] = {
    "document_code": "edo_sales_mvp1_checklist",
    "version": "v1",
    "checklist_version": APPROVED_CHECKLIST_VERSION,
    "status": "approved_for_implementation",
    "call_type_allowed_values": [
        "sales_primary",
        "sales_repeat",
        "mixed",
        "support",
        "internal",
        "other",
    ],
    "scenario_type_allowed_values": [
        "cold_outbound",
        "hot_incoming_contact",
        "warm_webinar_or_lead",
        "repeat_contact",
        "after_signed_document",
        "post_sale_follow_up",
        "mixed_scenario",
        "other",
    ],
    "outcome_code_allowed_values": [
        "agreed",
        "postponed",
        "declined",
        "demo_scheduled",
        "materials_sent",
        "callback_planned",
        "other",
    ],
    "deep_analysis_eligibility": {
        "minimum_duration_sec": settings.calls_min_duration_sec,
        "must_be_sales_relevant": True,
        "requires_sufficient_transcript_quality": True,
        "requires_manager_client_exchange": True,
        "must_not_analyze_when": [
            "support_only_interaction",
            "internal_call",
            "technical_or_operational_non_sales_call",
            "duration_below_threshold",
            "poor_transcript_quality",
        ],
    },
    "scoring": {
        "criterion_scale": {"0": "not_done_or_harmful", "1": "partial", "2": "good"},
        "stage_score_formula": "sum_of_criterion_scores",
        "max_stage_score_formula": "criteria_count_x_2",
        "overall_score_formula": "(total_points / max_points) * 100",
        "level_mapping": [
            {"min_percent": 0.0, "max_percent": 49.99, "level": "problematic"},
            {"min_percent": 50.0, "max_percent": 69.99, "level": "basic"},
            {"min_percent": 70.0, "max_percent": 84.99, "level": "strong"},
            {"min_percent": 85.0, "max_percent": 100.0, "level": "excellent"},
        ],
        "critical_failure_caps_level_at": "problematic",
    },
    "critical_errors_catalog": [
        {"error_code": "ce_false_information", "title": "False or unverified product/process information as fact"},
        {"error_code": "ce_argumentative_tone", "title": "Argumentative or confrontational phrasing"},
        {"error_code": "ce_disrespect", "title": "Disrespectful or dismissive phrasing"},
        {"error_code": "ce_ignored_direct_question", "title": "Ignored a direct client question in a meaningful moment"},
        {"error_code": "ce_pressure_without_relevance", "title": "Pushed product or sale with no established relevance"},
        {"error_code": "ce_no_next_step_on_relevant_call", "title": "Relevant call ended without any next-step attempt"},
        {"error_code": "ce_contradictory_statements", "title": "Materially contradictory explanation"},
    ],
    "stages": [
        {
            "stage_code": "contact_start",
            "stage_name": "Первичный контакт",
            "applicability_rule": "Applies to almost every external client call.",
            "criteria": [
                {
                    "criterion_code": "cs_intro_and_company",
                    "criterion_name": "Представился и обозначил компанию",
                    "score_rules": {
                        "0": "did not introduce self/company or introduced unclearly",
                        "1": "introduced partially, too quickly, or with weak clarity",
                        "2": "clearly introduced self and company at the start",
                    },
                },
                {
                    "criterion_code": "cs_permission_and_relevance",
                    "criterion_name": "Проверил уместность разговора / возможность говорить",
                    "score_rules": {
                        "0": "jumped into pitch without checking whether it is possible to speak",
                        "1": "checked mechanically but did not adapt to the answer",
                        "2": "checked and adapted the opening to the client situation",
                    },
                },
                {
                    "criterion_code": "cs_reason_for_call",
                    "criterion_name": "Понятно обозначил причину звонка",
                    "score_rules": {
                        "0": "purpose of the call remained vague",
                        "1": "reason was present but weak / generic",
                        "2": "reason was clear and understandable for the client",
                    },
                },
                {
                    "criterion_code": "cs_tone_and_clarity",
                    "criterion_name": "Сохранил нейтральный, вежливый и понятный тон",
                    "score_rules": {
                        "0": "tone created friction, confusion, pressure, or irritation",
                        "1": "tone acceptable but uneven / too rushed",
                        "2": "tone calm, respectful, clear",
                    },
                },
            ],
        },
        {
            "stage_code": "qualification_primary",
            "stage_name": "Квалификация и первичная потребность",
            "applicability_rule": "Applies when the manager attempts to understand relevance, context, process, role, size, or trigger.",
            "criteria": [
                {
                    "criterion_code": "qp_current_process",
                    "criterion_name": "Выяснил, как сейчас устроен процесс / документооборот",
                    "score_rules": {
                        "0": "did not ask about current process",
                        "1": "touched the process superficially",
                        "2": "clearly asked how things work now",
                    },
                },
                {
                    "criterion_code": "qp_role_and_scope",
                    "criterion_name": "Уточнил роль собеседника и/или масштаб задачи",
                    "score_rules": {
                        "0": "role / company context / scale not clarified",
                        "1": "partially clarified",
                        "2": "clearly clarified enough for the conversation stage",
                    },
                },
                {
                    "criterion_code": "qp_need_or_trigger",
                    "criterion_name": "Проверил, есть ли реальная задача / триггер / интерес",
                    "score_rules": {
                        "0": "no real check for need or trigger",
                        "1": "checked weakly or too late",
                        "2": "clearly checked relevance of the topic",
                    },
                },
                {
                    "criterion_code": "qp_no_early_pitch",
                    "criterion_name": "Не ушёл в презентацию слишком рано",
                    "score_rules": {
                        "0": "moved into product explanation before basic qualification",
                        "1": "partly rushed into presentation",
                        "2": "kept qualification before pitching",
                    },
                },
            ],
        },
        {
            "stage_code": "needs_discovery",
            "stage_name": "Выявление детальных потребностей",
            "applicability_rule": "Applies when the conversation goes beyond basic qualification and explores current pain, bottlenecks, scenarios, timing, or decision context.",
            "criteria": [
                {
                    "criterion_code": "nd_use_cases",
                    "criterion_name": "Выявил конкретные сценарии использования / типы документов / процессы",
                    "score_rules": {
                        "0": "no concrete scenarios revealed",
                        "1": "some scenarios touched but shallow",
                        "2": "concrete scenarios or workflows were identified",
                    },
                },
                {
                    "criterion_code": "nd_pain_and_constraints",
                    "criterion_name": "Выявил боль, ограничение, неудобство или риск текущего процесса",
                    "score_rules": {
                        "0": "no pain / friction / limitation identified",
                        "1": "issue mentioned but not unpacked",
                        "2": "pain or limitation identified clearly",
                    },
                },
                {
                    "criterion_code": "nd_priority_and_timing",
                    "criterion_name": "Понял приоритет и срок возможного движения",
                    "score_rules": {
                        "0": "no understanding of timing / urgency",
                        "1": "timing touched but vague",
                        "2": "timing / urgency / later return point identified",
                    },
                },
                {
                    "criterion_code": "nd_decision_context",
                    "criterion_name": "Понял, кто влияет на решение и как оно принимается",
                    "score_rules": {
                        "0": "decision context ignored",
                        "1": "touched partially",
                        "2": "decision logic or decision makers became clearer",
                    },
                },
            ],
        },
        {
            "stage_code": "presentation",
            "stage_name": "Формирование предложения (презентация/КП)",
            "applicability_rule": "Applies when the manager explains the product, sends or discusses КП, or links value to the client’s process.",
            "criteria": [
                {
                    "criterion_code": "pr_value_linked_to_context",
                    "criterion_name": "Связал ценность продукта с контекстом клиента",
                    "score_rules": {
                        "0": "generic pitch not tied to client reality",
                        "1": "some linkage, but broad or weak",
                        "2": "explained value through the client’s actual context",
                    },
                },
                {
                    "criterion_code": "pr_adapted_pitch",
                    "criterion_name": "Адаптировал подачу под тип клиента / сценарий",
                    "score_rules": {
                        "0": "same generic script regardless of context",
                        "1": "some adaptation, but limited",
                        "2": "pitch clearly adapted to scenario",
                    },
                },
                {
                    "criterion_code": "pr_clarity_and_examples",
                    "criterion_name": "Объяснил решение ясно, без путаницы",
                    "score_rules": {
                        "0": "explanation confusing, overloaded, or hard to follow",
                        "1": "understandable but not crisp",
                        "2": "explanation was clear and client-friendly",
                    },
                },
                {
                    "criterion_code": "pr_no_feature_dump",
                    "criterion_name": "Не ушёл в бессвязный список функций",
                    "score_rules": {
                        "0": "dumped features without meaning",
                        "1": "partly overloaded with features",
                        "2": "kept explanation selective and relevant",
                    },
                },
            ],
        },
        {
            "stage_code": "objection_handling",
            "stage_name": "Работа с возражениями",
            "applicability_rule": "Applies when the client raises objections, hesitation, resistance, or doubts.",
            "criteria": [
                {
                    "criterion_code": "oh_clarify_reason",
                    "criterion_name": "Уточнил реальную причину сомнения / отказа",
                    "score_rules": {
                        "0": "argued against the objection without clarifying it",
                        "1": "partial clarification only",
                        "2": "clarified the real reason before responding",
                    },
                },
                {
                    "criterion_code": "oh_reframe_with_value",
                    "criterion_name": "Ответил на возражение через пользу / логику клиента",
                    "score_rules": {
                        "0": "response did not address the concern",
                        "1": "addressed partially",
                        "2": "response was relevant and grounded in client context",
                    },
                },
                {
                    "criterion_code": "oh_safe_tone",
                    "criterion_name": "Отработал возражение экологично, без давления",
                    "score_rules": {
                        "0": "defensive, argumentative, or pressuring tone",
                        "1": "acceptable but tense",
                        "2": "calm and respectful objection handling",
                    },
                },
                {
                    "criterion_code": "oh_check_remaining_concern",
                    "criterion_name": "Проверил, снято ли основное сомнение",
                    "score_rules": {
                        "0": "did not test whether the concern remains",
                        "1": "touched it weakly",
                        "2": "checked whether the concern was addressed",
                    },
                },
            ],
        },
        {
            "stage_code": "completion_next_step",
            "stage_name": "Завершение и договорённости",
            "applicability_rule": "Applies when the conversation approaches a closing, pause, recap, or next-step fixation.",
            "criteria": [
                {
                    "criterion_code": "cn_fixed_next_step",
                    "criterion_name": "Зафиксировал конкретный следующий шаг",
                    "score_rules": {
                        "0": "no concrete next step",
                        "1": "next step exists but vague",
                        "2": "next step clearly defined",
                    },
                },
                {
                    "criterion_code": "cn_owner_and_deadline",
                    "criterion_name": "Определил кто делает и когда",
                    "score_rules": {
                        "0": "no owner and/or timing",
                        "1": "only owner or only approximate time",
                        "2": "owner and timing are clear",
                    },
                },
                {
                    "criterion_code": "cn_recap_and_confirmation",
                    "criterion_name": "Подытожил договорённость и убедился, что обе стороны одинаково поняли",
                    "score_rules": {
                        "0": "no recap",
                        "1": "weak / incomplete recap",
                        "2": "clear recap and confirmation",
                    },
                },
                {
                    "criterion_code": "cn_polite_close",
                    "criterion_name": "Завершил разговор аккуратно и профессионально",
                    "score_rules": {
                        "0": "abrupt, awkward, or friction-heavy close",
                        "1": "acceptable but weak close",
                        "2": "professional close",
                    },
                },
            ],
        },
        {
            "stage_code": "sale_processing",
            "stage_name": "Оформление продажи (если применимо)",
            "applicability_rule": "Applies only when the conversation reaches the operational sale / onboarding / document collection stage.",
            "criteria": [
                {
                    "criterion_code": "sp_process_explained",
                    "criterion_name": "Понятно объяснил следующий операционный шаг продажи",
                    "score_rules": {
                        "0": "process unclear",
                        "1": "partly explained",
                        "2": "process explained clearly",
                    },
                },
                {
                    "criterion_code": "sp_documents_or_inputs",
                    "criterion_name": "Собрал или запросил необходимые данные / документы / условия",
                    "score_rules": {
                        "0": "did not gather needed inputs",
                        "1": "gathered partially",
                        "2": "gathered what was needed for the current step",
                    },
                },
                {
                    "criterion_code": "sp_risks_or_blockers",
                    "criterion_name": "Выявил возможные барьеры на этапе оформления",
                    "score_rules": {
                        "0": "ignored blockers",
                        "1": "touched blockers partially",
                        "2": "identified blockers or risks explicitly",
                    },
                },
            ],
        },
        {
            "stage_code": "sale_final",
            "stage_name": "Продажа (финал) (если применимо)",
            "applicability_rule": "Applies only when there is a real commitment to purchase / payment / launch / final activation.",
            "criteria": [
                {
                    "criterion_code": "sf_commitment_received",
                    "criterion_name": "Получил или подтвердил реальное обязательство клиента",
                    "score_rules": {
                        "0": "no real commitment",
                        "1": "weak or ambiguous commitment",
                        "2": "clear commitment",
                    },
                },
                {
                    "criterion_code": "sf_payment_or_launch_confirmed",
                    "criterion_name": "Подтвердил оплату / запуск / переход к активации",
                    "score_rules": {
                        "0": "final step unclear",
                        "1": "partial clarity",
                        "2": "final step confirmed",
                    },
                },
                {
                    "criterion_code": "sf_final_recap",
                    "criterion_name": "Подвёл итог финальной договорённости",
                    "score_rules": {
                        "0": "no final recap",
                        "1": "weak recap",
                        "2": "clear final recap",
                    },
                },
            ],
        },
        {
            "stage_code": "cross_stage_transition",
            "stage_name": "Сквозной критерий. Переход между этапами",
            "applicability_rule": "Applies whenever the conversation passes through at least two meaningful stages.",
            "criteria": [
                {
                    "criterion_code": "ct_flow_consistency",
                    "criterion_name": "Переходы между этапами логичны",
                    "score_rules": {
                        "0": "jumps, broken logic, chaotic flow",
                        "1": "flow partly logical",
                        "2": "flow coherent and natural",
                    },
                },
                {
                    "criterion_code": "ct_dialog_safety",
                    "criterion_name": "Сохранял конструктивность и управляемость разговора",
                    "score_rules": {
                        "0": "conversation became tense, unsafe, or unmanaged",
                        "1": "some tension / uneven control",
                        "2": "conversation remained controlled and constructive",
                    },
                },
            ],
        },
    ],
}

REQUIRED_STAGE_FIELDS = {
    "stage_code",
    "stage_name",
    "stage_score",
    "max_stage_score",
    "criteria_results",
}

REQUIRED_CRITERION_FIELDS = {
    "criterion_code",
    "criterion_name",
    "score",
    "max_score",
    "comment",
    "evidence",
}


@dataclass(slots=True)
class AnalysisResult:
    """Immutable top-level analysis metadata wrapper."""

    interaction_id: str
    instruction_version: str


@dataclass(slots=True)
class PromptAssetSet:
    """Loaded prompt assets used by the analyzer."""

    classify: str
    analyze: str
    agreements: str
    insights: str


class CallsAnalyzer:
    """Approved MVP-1 calls analyzer with contract-safe LLM output."""

    def __init__(self, department_id: str, db: Session):
        self.department_id = UUID(department_id)
        self.db = db
        self.ai_router = AIProviderRouter()
        self.logger = structlog.get_logger().bind(
            module="calls.analyzer",
            department_id=department_id,
        )

    def _get_prompt(self, prompt_name: str) -> str:
        """Load prompt text from file and keep a minimal safe fallback."""
        prompt_path = PROMPTS_DIR / f"{prompt_name}.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return f"# Missing {prompt_name} prompt\nReturn approved MVP-1 contract JSON only.\n"

    def _resolve_source_file(self, key: str) -> Path | None:
        """Resolve one approved MVP-1 source file across known runtime locations."""
        filename = MVP1_SOURCE_FILE_NAMES[key]
        for directory in MVP1_SOURCE_DIR_CANDIDATES:
            candidate = directory / filename
            if candidate.exists():
                return candidate
        return None

    def _load_source_text(self, key: str, fallback_text: str) -> str:
        """Read one source-of-truth MVP-1 document or return a runtime-safe fallback."""
        source_file = self._resolve_source_file(key)
        if source_file is not None:
            return source_file.read_text(encoding="utf-8")
        return fallback_text

    def _load_example_contract(
        self,
        interaction: Interaction,
        instruction_version: str,
    ) -> dict[str, Any]:
        """Load the approved example contract or fall back to the live contract template."""
        source_file = self._resolve_source_file("example")
        if source_file is not None:
            return json.loads(source_file.read_text(encoding="utf-8"))
        return self.build_contract_template(
            interaction=interaction,
            instruction_version=instruction_version,
        )

    def get_prompt_assets(self) -> PromptAssetSet:
        """Return loaded analyzer-related prompts."""
        return PromptAssetSet(
            classify=self._get_prompt("classify"),
            analyze=self._get_prompt("analyze"),
            agreements=self._get_prompt("agreements"),
            insights=self._get_prompt("insights"),
        )

    def build_checklist_definition(self) -> dict[str, Any]:
        """Return the approved MVP-1 checklist definition."""
        return deepcopy(CHECKLIST_DEFINITION)

    def build_contract_template(
        self,
        interaction: Interaction,
        instruction_version: str = APPROVED_INSTRUCTION_VERSION,
    ) -> dict[str, Any]:
        """Build a schema-safe contract template from interaction metadata."""
        metadata = dict(interaction.metadata_ or {})
        return {
            "schema_version": APPROVED_SCHEMA_VERSION,
            "instruction_version": instruction_version,
            "checklist_version": APPROVED_CHECKLIST_VERSION,
            "analysis_timestamp": datetime.now(UTC).isoformat(),
            "call": {
                "call_id": str(interaction.id),
                "external_call_code": metadata.get("external_call_code") or interaction.external_id,
                "source_system": interaction.source or "onlinepbx",
                "department_id": str(interaction.department_id),
                "manager_id": str(interaction.manager_id) if interaction.manager_id else None,
                "manager_name": metadata.get("manager_name"),
                "call_started_at": self._to_iso_datetime(metadata.get("call_date")),
                "duration_sec": interaction.duration_sec,
                "direction": self._normalize_direction(metadata.get("direction")),
                "contact_name": metadata.get("contact_name"),
                "contact_phone": metadata.get("phone"),
                "contact_company": metadata.get("contact_company"),
                "language": settings.assemblyai_language,
            },
            "classification": {
                "call_type": None,
                "scenario_type": None,
                "channel_context": None,
                "analysis_eligibility": "eligible",
                "eligibility_reason": "duration_ge_180_sec_and_sales_relevant",
                "analysis_confidence": None,
            },
            "summary": {
                "short_summary": None,
                "context": None,
                "call_goal": None,
                "outcome_code": None,
                "outcome_text": None,
                "next_step_text": None,
            },
            "score": {
                "legacy_card_score": None,
                "legacy_card_level": None,
                "checklist_score": {
                    "total_points": 0,
                    "max_points": 0,
                    "score_percent": 0.0,
                    "level": "problematic",
                },
                "critical_failure": False,
                "critical_errors": [],
            },
            "score_by_stage": [],
            "strengths": [],
            "gaps": [],
            "recommendations": [],
            "agreements": [],
            "follow_up": {
                "next_step_fixed": False,
                "next_step_type": None,
                "next_step_text": None,
                "owner": None,
                "due_date_text": None,
                "due_date_iso": None,
                "reason_not_fixed": None,
            },
            "product_signals": [],
            "evidence_fragments": [],
            "analytics_tags": [],
            "data_quality": {
                "transcript_quality": self._infer_transcript_quality(interaction),
                "classification_quality": "pending_llm_analysis",
                "analysis_quality": "pending_llm_analysis",
                "needs_manual_review": False,
                "manual_review_reason": None,
            },
        }

    def build_prompt_context(
        self,
        interaction: Interaction,
        instruction_version: str = APPROVED_INSTRUCTION_VERSION,
        llm1_first_pass: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble the approved input context for the LLM call."""
        prompt_assets = self.get_prompt_assets()
        runtime_fallback_note = (
            "Runtime fallback for Manual Live Validation: the original docs/mvp1_sources files are "
            "not available inside this container, so rely on the embedded approved checklist "
            "definition, contract template, and prompt assets already loaded by the analyzer."
        )
        context = {
            "interaction": {
                "id": str(interaction.id),
                "department_id": str(interaction.department_id),
                "manager_id": str(interaction.manager_id) if interaction.manager_id else None,
                "source": interaction.source,
                "duration_sec": interaction.duration_sec,
                "text": interaction.text or "",
                "metadata": interaction.metadata_ or {},
            },
            "checklist_definition": self.build_checklist_definition(),
            "analysis_result_contract_template": self.build_contract_template(
                interaction=interaction,
                instruction_version=instruction_version,
            ),
            "approved_sources": {
                "handoff": self._load_source_text("handoff", fallback_text=runtime_fallback_note),
                "checklist_definition_markdown": self._load_source_text(
                    "checklist",
                    fallback_text=json.dumps(
                        self.build_checklist_definition(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
                "contract_markdown": self._load_source_text(
                    "contract",
                    fallback_text=json.dumps(
                        self.build_contract_template(
                            interaction=interaction,
                            instruction_version=instruction_version,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
                "manager_card_markdown": self._load_source_text(
                    "manager_card",
                    fallback_text=runtime_fallback_note,
                ),
                "approved_example_contract": self._load_example_contract(
                    interaction=interaction,
                    instruction_version=instruction_version,
                ),
            },
            "prompt_assets": {
                "classify": prompt_assets.classify,
                "analyze": prompt_assets.analyze,
                "agreements": prompt_assets.agreements,
                "insights": prompt_assets.insights,
            },
            "source_of_truth_priority": [
                "MVP1_CODEX_HANDOFF.md",
                "MVP1_CHECKLIST_DEFINITION_v1.md",
                "MVP1_CALL_ANALYSIS_CONTRACT_v1.md",
                "MVP1_CALL_ANALYSIS_EXAMPLE_TIMUR_v1.json",
                "MVP1_MANAGER_CARD_FORMAT_v1.md",
            ],
        }
        if llm1_first_pass is not None:
            context["llm1_first_pass"] = llm1_first_pass
        return context

    def build_llm1_prompt_context(
        self,
        interaction: Interaction,
        instruction_version: str = APPROVED_INSTRUCTION_VERSION,
    ) -> dict[str, Any]:
        """Assemble the separate first-pass context used before the final analysis call."""
        prompt_assets = self.get_prompt_assets()
        checklist_definition = self.build_checklist_definition()
        contract_template = self.build_contract_template(
            interaction=interaction,
            instruction_version=instruction_version,
        )
        runtime_fallback_note = (
            "Runtime fallback for Manual Reporting Pilot: the original docs/mvp1_sources files are "
            "not available inside this container, so rely on the embedded approved checklist "
            "definition, contract template, and prompt assets already loaded by the analyzer."
        )
        return {
            "interaction": {
                "id": str(interaction.id),
                "department_id": str(interaction.department_id),
                "manager_id": str(interaction.manager_id) if interaction.manager_id else None,
                "source": interaction.source,
                "duration_sec": interaction.duration_sec,
                "text": interaction.text or "",
                "metadata": interaction.metadata_ or {},
            },
            "checklist_definition": checklist_definition,
            "expected_output_shape": {
                "classification": contract_template["classification"],
                "summary": contract_template["summary"],
                "follow_up": contract_template["follow_up"],
                "data_quality": contract_template["data_quality"],
                "analysis_focus": [
                    "short focus bullet about what matters most in the call",
                ],
            },
            "approved_sources": {
                "handoff": self._load_source_text("handoff", fallback_text=runtime_fallback_note),
                "checklist_definition_markdown": self._load_source_text(
                    "checklist",
                    fallback_text=json.dumps(
                        checklist_definition,
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
                "contract_markdown": self._load_source_text(
                    "contract",
                    fallback_text=json.dumps(
                        contract_template,
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
            },
            "prompt_assets": {
                "classify": prompt_assets.classify,
            },
            "instructions": {
                "request_kind": "classification_first_pass",
                "required_top_level_keys": [
                    "classification",
                    "summary",
                    "follow_up",
                    "data_quality",
                ],
                "optional_top_level_keys": [
                    "analysis_focus",
                ],
                "rules": [
                    "Return one JSON object only.",
                    "Do not invent transcript facts.",
                    "Keep business-facing summary/follow-up text in Russian.",
                    "Do not return the full final scoring contract here.",
                ],
            },
        }

    def analyze_call(
        self,
        interaction: Interaction,
        instruction_version: str = APPROVED_INSTRUCTION_VERSION,
    ) -> dict[str, Any]:
        """Run the approved MVP-1 LLM analysis and return contract JSON."""
        llm1_first_pass = self._request_llm1_first_pass(
            interaction=interaction,
            instruction_version=instruction_version,
        )

        messages = [
            {"role": "system", "content": self.get_prompt_assets().analyze},
            {
                "role": "user",
                "content": json.dumps(
                    self.build_prompt_context(
                        interaction=interaction,
                        instruction_version=instruction_version,
                        llm1_first_pass=llm1_first_pass,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

        self.logger.info(
            "analyzer.llm_start",
            interaction_id=str(interaction.id),
            instruction_version=instruction_version,
            llm1_focus_count=len(llm1_first_pass.get("analysis_focus") or []),
        )

        content = self._request_analysis_content(
            interaction=interaction,
            messages=messages,
            instruction_version=instruction_version,
        )
        final_content = content
        try:
            validated = self._load_and_validate_contract(
                content=content,
                interaction=interaction,
                instruction_version=instruction_version,
            )
        except LLMResponseError as exc:
            self.logger.warning(
                "analyzer.llm_retry",
                interaction_id=str(interaction.id),
                instruction_version=instruction_version,
                error=str(exc),
            )
            retry_messages = messages + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "The JSON above failed strict approved-contract validation with this error:\n"
                        f"{exc}\n\n"
                        "Return one corrected JSON object only. Preserve the approved schema, include "
                        "all required stage and criterion fields, and do not add explanations."
                    ),
                },
            ]
            retry_content = self._request_analysis_content(
                interaction=interaction,
                messages=retry_messages,
                instruction_version=instruction_version,
            )
            final_content = retry_content
            try:
                validated = self._load_and_validate_contract(
                    content=retry_content,
                    interaction=interaction,
                    instruction_version=instruction_version,
                )
            except LLMResponseError as retry_exc:
                self._store_analysis_forensics(
                    interaction=interaction,
                    raw_llm_response=retry_exc.raw_response or retry_content,
                    normalized_result=getattr(retry_exc, "normalized_result", None),
                    failure_reason=getattr(retry_exc, "reason_code", None),
                )
                raise
        self._store_analysis_forensics(
            interaction=interaction,
            raw_llm_response=final_content,
            normalized_result=validated,
            failure_reason=None,
        )
        self.logger.info(
            "analyzer.llm_done",
            interaction_id=str(interaction.id),
            stages=len(validated["score_by_stage"]),
        )
        return validated

    def _request_llm1_first_pass(
        self,
        *,
        interaction: Interaction,
        instruction_version: str,
    ) -> dict[str, Any]:
        """Run the separate LLM-1 first pass before the final approved analysis pass."""
        messages = [
            {"role": "system", "content": self.get_prompt_assets().classify},
            {
                "role": "user",
                "content": json.dumps(
                    self.build_llm1_prompt_context(
                        interaction=interaction,
                        instruction_version=instruction_version,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]
        self.logger.info(
            "analyzer.llm1_start",
            interaction_id=str(interaction.id),
            instruction_version=instruction_version,
        )
        content = self._request_llm_content(
            interaction=interaction,
            messages=messages,
            instruction_version=instruction_version,
            layer="llm1",
            request_kind="classification_first_pass",
            executor_label="LLM-1 OpenAI-compatible executor",
            temperature=0.0,
        )
        try:
            normalized = self._load_and_normalize_llm1_first_pass(
                content=content,
                interaction=interaction,
                instruction_version=instruction_version,
            )
        except LLMResponseError as exc:
            self.logger.warning(
                "analyzer.llm1_retry",
                interaction_id=str(interaction.id),
                instruction_version=instruction_version,
                error=str(exc),
            )
            retry_messages = messages + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "The JSON above failed first-pass validation with this error:\n"
                        f"{exc}\n\n"
                        "Return one corrected JSON object only with keys "
                        "`classification`, `summary`, `follow_up`, `data_quality`, and optional "
                        "`analysis_focus`."
                    ),
                },
            ]
            retry_content = self._request_llm_content(
                interaction=interaction,
                messages=retry_messages,
                instruction_version=instruction_version,
                layer="llm1",
                request_kind="classification_first_pass_retry",
                executor_label="LLM-1 OpenAI-compatible executor",
                temperature=0.0,
            )
            normalized = self._load_and_normalize_llm1_first_pass(
                content=retry_content,
                interaction=interaction,
                instruction_version=instruction_version,
            )
        self.logger.info(
            "analyzer.llm1_done",
            interaction_id=str(interaction.id),
            instruction_version=instruction_version,
            focus_items=len(normalized.get("analysis_focus") or []),
        )
        return normalized

    def _request_analysis_content(
        self,
        *,
        interaction: Interaction,
        messages: list[dict[str, str]],
        instruction_version: str,
    ) -> str:
        """Request analysis JSON content from the LLM."""
        return self._request_llm_content(
            interaction=interaction,
            messages=messages,
            instruction_version=instruction_version,
            layer="llm2",
            request_kind="approved_contract_generation",
            executor_label="LLM-2 OpenAI-compatible executor",
            temperature=0.2,
        )

    def _request_llm_content(
        self,
        *,
        interaction: Interaction,
        messages: list[dict[str, str]],
        instruction_version: str,
        layer: str,
        request_kind: str,
        executor_label: str,
        temperature: float,
    ) -> str:
        """Request one routed JSON response from an LLM layer."""
        layer_label = {
            "llm1": "LLM-1",
            "llm2": "LLM-2",
        }.get(layer, layer.upper())
        route_plan = self.ai_router.build_route_plan(
            layer=layer,
            subject_key=str(interaction.id),
        )
        selected = route_plan.current_candidate()
        self.logger.info(
            "analyzer.llm_route_selected",
            interaction_id=str(interaction.id),
            instruction_version=instruction_version,
            layer=layer,
            policy=route_plan.policy,
            provider=selected.provider,
            account_alias=selected.account_alias,
            model=selected.model,
            forced_override=route_plan.forced_override,
            request_kind=request_kind,
        )

        while True:
            candidate = route_plan.current_candidate()
            try:
                compatibility_candidate = candidate
                if (candidate.endpoint or "").rstrip("/") == "/chat/completions":
                    # OpenAI SDK already targets chat completions internally, so this
                    # known-safe endpoint hint should not block the compatible executor.
                    compatibility_candidate = replace(candidate, endpoint=None)
                self.ai_router.ensure_execution_compatibility(
                    compatibility_candidate,
                    executor_label=executor_label,
                    required_execution_mode="openai_compatible",
                )
                client = OpenAI(
                    api_key=candidate.resolved_api_key(),
                    base_url=candidate.api_base,
                )
                last_error: Exception | None = None
                attempts_total = max(1, candidate.max_retries_for_this_provider + 1)
                response = None
                for _ in range(attempts_total):
                    try:
                        response = client.chat.completions.create(
                            model=candidate.model,
                            response_format={"type": "json_object"},
                            temperature=temperature,
                            timeout=candidate.timeout_sec or settings.openai_timeout_sec,
                            messages=messages,
                        )
                        break
                    except Exception as exc:
                        last_error = exc
                if response is None:
                    raise last_error or RuntimeError("Unknown LLM request failure")
                route_plan.mark_attempt_success()
                self._store_ai_routing_metadata(
                    interaction=interaction,
                    layer_metadata=route_plan.to_metadata(
                        request_kind=request_kind,
                        usage=self._extract_usage_metadata(response),
                        notes=f"{layer_label} runtime request completed.",
                    ),
                )
                return self._extract_message_content(response)
            except Exception as exc:
                can_fallback = route_plan.mark_attempt_failure(str(exc))
                self._store_ai_routing_metadata(
                    interaction=interaction,
                    layer_metadata=route_plan.to_metadata(
                        executed=False,
                        request_kind=request_kind,
                        notes=f"{layer_label} request failed before success.",
                    ),
                )
                if can_fallback:
                    self.logger.warning(
                        "analyzer.llm_fallback",
                        interaction_id=str(interaction.id),
                        instruction_version=instruction_version,
                        layer=layer,
                        failed_provider=candidate.provider,
                        failed_account_alias=candidate.account_alias,
                        failed_model=candidate.model,
                        policy=route_plan.policy,
                        error=str(exc),
                        request_kind=request_kind,
                    )
                    continue
                raise AnalysisError(
                    f"{layer_label} request failed: {exc}",
                    interaction_id=str(interaction.id),
                    original=exc,
                ) from exc

    def _load_and_normalize_llm1_first_pass(
        self,
        *,
        content: str,
        interaction: Interaction,
        instruction_version: str,
    ) -> dict[str, Any]:
        """Validate the bounded LLM-1 response used as context for LLM-2."""
        try:
            raw_first_pass = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                "LLM-1 returned invalid JSON",
                interaction_id=str(interaction.id),
                raw_response=content,
            ) from exc
        if not isinstance(raw_first_pass, dict):
            raise LLMResponseError(
                "LLM-1 must return a JSON object",
                interaction_id=str(interaction.id),
                raw_response=content,
            )

        template = self.build_contract_template(
            interaction=interaction,
            instruction_version=instruction_version,
        )
        raw_focus = raw_first_pass.get("analysis_focus")
        if raw_focus in (None, ""):
            analysis_focus: list[str] = []
        elif isinstance(raw_focus, list):
            analysis_focus = [str(item).strip() for item in raw_focus if str(item).strip()]
        else:
            analysis_focus = [str(raw_focus).strip()] if str(raw_focus).strip() else []
        return {
            "classification": self._merge_dict(
                template["classification"],
                raw_first_pass.get("classification") or {},
            ),
            "summary": self._merge_dict(
                template["summary"],
                raw_first_pass.get("summary") or {},
            ),
            "follow_up": self._merge_dict(
                template["follow_up"],
                raw_first_pass.get("follow_up") or {},
            ),
            "data_quality": self._merge_dict(
                template["data_quality"],
                raw_first_pass.get("data_quality") or {},
            ),
            "analysis_focus": analysis_focus[:5],
        }

    def _load_and_validate_contract(
        self,
        *,
        content: str,
        interaction: Interaction,
        instruction_version: str,
    ) -> dict[str, Any]:
        """Deserialize and validate one LLM response against the approved contract."""
        try:
            raw_contract = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                "Analyzer returned invalid JSON",
                interaction_id=str(interaction.id),
                raw_response=content,
            ) from exc

        return self._validate_and_normalize_contract(
            raw_contract=raw_contract,
            interaction=interaction,
            instruction_version=instruction_version,
        )

    def prepare_analysis_result(
        self,
        interaction: Interaction,
        instruction_version: str = APPROVED_INSTRUCTION_VERSION,
    ) -> AnalysisResult:
        """Return the immutable top-level wrapper without changing its structure."""
        self.logger.info(
            "analyzer.result_prepared",
            interaction_id=str(interaction.id),
            instruction_version=instruction_version,
        )
        return AnalysisResult(
            interaction_id=str(interaction.id),
            instruction_version=instruction_version,
        )

    def _validate_and_normalize_contract(
        self,
        raw_contract: dict[str, Any],
        interaction: Interaction,
        instruction_version: str,
    ) -> dict[str, Any]:
        """Validate and normalize the LLM contract against approved MVP-1 rules."""
        contract = self.build_contract_template(
            interaction=interaction,
            instruction_version=instruction_version,
        )
        contract = self._merge_dict(contract, raw_contract)
        contract["call"] = self._merge_dict(contract["call"], raw_contract.get("call", {}))
        contract["classification"] = self._merge_dict(
            contract["classification"], raw_contract.get("classification", {})
        )
        contract["summary"] = self._merge_dict(contract["summary"], raw_contract.get("summary", {}))
        contract["score"] = self._merge_dict(contract["score"], raw_contract.get("score", {}))
        contract["score"]["checklist_score"] = self._merge_dict(
            contract["score"]["checklist_score"],
            raw_contract.get("score", {}).get("checklist_score", {}),
        )
        contract["follow_up"] = self._merge_dict(
            contract["follow_up"], raw_contract.get("follow_up", {})
        )
        contract["data_quality"] = self._merge_dict(
            contract["data_quality"], raw_contract.get("data_quality", {})
        )

        required_top_level = [
            "schema_version",
            "instruction_version",
            "checklist_version",
            "analysis_timestamp",
            "call",
            "classification",
            "summary",
            "score",
            "score_by_stage",
            "strengths",
            "gaps",
            "recommendations",
            "agreements",
            "follow_up",
            "product_signals",
            "evidence_fragments",
            "analytics_tags",
            "data_quality",
        ]
        for field in required_top_level:
            if field not in contract:
                raise LLMResponseError(
                    f"Missing required top-level field: {field}",
                    interaction_id=str(interaction.id),
                    raw_response=json.dumps(raw_contract, ensure_ascii=False),
                )

        allowed_stage_map = {
            stage["stage_code"]: {
                "stage_name": stage["stage_name"],
                "criteria": {
                    criterion["criterion_code"]: criterion["criterion_name"]
                    for criterion in stage["criteria"]
                },
            }
            for stage in CHECKLIST_DEFINITION["stages"]
        }
        for stage in contract["score_by_stage"] or []:
            stage_code = stage.get("stage_code")
            if stage_code not in allowed_stage_map:
                raise LLMResponseError(
                    f"Unknown stage_code: {stage_code}",
                    interaction_id=str(interaction.id),
                    raw_response=json.dumps(raw_contract, ensure_ascii=False),
                )
            if isinstance(stage.get("criteria_results"), list):
                self._populate_stage_scores(stage)
            missing_stage_fields = sorted(REQUIRED_STAGE_FIELDS.difference(stage))
            if missing_stage_fields:
                raise LLMResponseError(
                    (
                        f"Stage {stage_code} is missing required fields: "
                        f"{', '.join(missing_stage_fields)}"
                    ),
                    interaction_id=str(interaction.id),
                    raw_response=json.dumps(raw_contract, ensure_ascii=False),
                )
            expected_stage_name = allowed_stage_map[stage_code]["stage_name"]
            if stage.get("stage_name") != expected_stage_name:
                raise LLMResponseError(
                    f"Stage {stage_code} has invalid stage_name: {stage.get('stage_name')}",
                    interaction_id=str(interaction.id),
                    raw_response=json.dumps(raw_contract, ensure_ascii=False),
                )
            if not isinstance(stage.get("criteria_results"), list):
                raise LLMResponseError(
                    f"criteria_results must be a list for stage {stage_code}",
                    interaction_id=str(interaction.id),
                    raw_response=json.dumps(raw_contract, ensure_ascii=False),
                )
            for criterion in stage["criteria_results"]:
                criterion_code = criterion.get("criterion_code")
                if criterion_code not in allowed_stage_map[stage_code]["criteria"]:
                    raise LLMResponseError(
                        f"Unknown criterion_code {criterion_code} for stage {stage_code}",
                        interaction_id=str(interaction.id),
                        raw_response=json.dumps(raw_contract, ensure_ascii=False),
                    )
                missing_criterion_fields = sorted(REQUIRED_CRITERION_FIELDS.difference(criterion))
                if missing_criterion_fields:
                    raise LLMResponseError(
                        (
                            f"Criterion {criterion_code} in stage {stage_code} is missing "
                            f"required fields: {', '.join(missing_criterion_fields)}"
                        ),
                        interaction_id=str(interaction.id),
                        raw_response=json.dumps(raw_contract, ensure_ascii=False),
                    )
                expected_criterion_name = allowed_stage_map[stage_code]["criteria"][criterion_code]
                if criterion.get("criterion_name") != expected_criterion_name:
                    raise LLMResponseError(
                        (
                            f"Criterion {criterion_code} in stage {stage_code} has invalid "
                            f"criterion_name: {criterion.get('criterion_name')}"
                        ),
                        interaction_id=str(interaction.id),
                        raw_response=json.dumps(raw_contract, ensure_ascii=False),
                    )

        criterion_name_map = self._build_criterion_name_map(contract.get("score_by_stage") or [])
        contract["strengths"] = self._normalize_finding_items(
            items=contract.get("strengths") or [],
            criterion_name_map=criterion_name_map,
        )
        contract["gaps"] = self._normalize_finding_items(
            items=contract.get("gaps") or [],
            criterion_name_map=criterion_name_map,
        )
        contract["recommendations"] = self._normalize_recommendation_items(
            items=contract.get("recommendations") or [],
            criterion_name_map=criterion_name_map,
        )
        self._populate_checklist_score(contract)
        self._validate_semantic_completeness(
            contract=contract,
            interaction_id=str(interaction.id),
            raw_response=json.dumps(raw_contract, ensure_ascii=False),
        )
        contract["schema_version"] = APPROVED_SCHEMA_VERSION
        contract["instruction_version"] = instruction_version
        contract["checklist_version"] = APPROVED_CHECKLIST_VERSION
        contract["score_by_stage"] = contract.get("score_by_stage") or []
        contract["strengths"] = contract.get("strengths") or []
        contract["gaps"] = contract.get("gaps") or []
        contract["recommendations"] = contract.get("recommendations") or []
        contract["agreements"] = contract.get("agreements") or []
        contract["product_signals"] = contract.get("product_signals") or []
        contract["evidence_fragments"] = contract.get("evidence_fragments") or []
        contract["analytics_tags"] = contract.get("analytics_tags") or []
        contract["score"]["critical_errors"] = contract["score"].get("critical_errors") or []
        return contract

    @staticmethod
    def _semantic_invalid_reason_codes(contract: dict[str, Any]) -> list[str]:
        """Return bounded semantic-invalid reasons for a normalized contract."""
        if (
            not (contract.get("score_by_stage") or [])
            and not (contract.get("strengths") or [])
            and not (contract.get("gaps") or [])
            and not (contract.get("recommendations") or [])
        ):
            return [SEMANTIC_EMPTY_ANALYSIS_REASON]
        return []

    def _validate_semantic_completeness(
        self,
        *,
        contract: dict[str, Any],
        interaction_id: str,
        raw_response: str,
    ) -> None:
        """Reject shape-valid but semantically empty analysis outputs."""
        reason_codes = self._semantic_invalid_reason_codes(contract)
        if SEMANTIC_EMPTY_ANALYSIS_REASON in reason_codes:
            raise SemanticAnalysisError(
                "Analyzer returned a semantically empty analysis contract.",
                interaction_id=interaction_id,
                raw_response=raw_response,
                normalized_result=deepcopy(contract),
                reason_code=SEMANTIC_EMPTY_ANALYSIS_REASON,
            )

    @staticmethod
    def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Merge dictionaries while preserving schema keys from the base template."""
        result = deepcopy(base)
        result.update(override or {})
        return result

    @staticmethod
    def _extract_message_content(response: Any) -> str:
        """Extract plain text content from an OpenAI chat completion response."""
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content
        return str(content)

    @staticmethod
    def _extract_usage_metadata(response: Any) -> dict[str, Any] | None:
        """Extract token usage from an OpenAI-compatible response when available."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
        else:
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
        if prompt_tokens is None and completion_tokens is None and total_tokens is None:
            return None
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _store_analysis_forensics(
        *,
        interaction: Interaction,
        raw_llm_response: str,
        normalized_result: dict[str, Any] | None,
        failure_reason: str | None,
    ) -> None:
        """Attach transient raw-vs-normalized analyzer forensics to the interaction object."""
        setattr(
            interaction,
            ANALYSIS_FORENSICS_ATTR,
            {
                "raw_llm_response": raw_llm_response,
                "normalized_result": deepcopy(normalized_result) if normalized_result is not None else None,
                "failure_reason": str(failure_reason or "").strip() or None,
            },
        )

    @staticmethod
    def consume_analysis_forensics(interaction: Interaction) -> dict[str, Any]:
        """Pop transient analyzer forensics after persistence consumes them."""
        value = getattr(interaction, ANALYSIS_FORENSICS_ATTR, None)
        if hasattr(interaction, ANALYSIS_FORENSICS_ATTR):
            delattr(interaction, ANALYSIS_FORENSICS_ATTR)
        return dict(value or {})

    @staticmethod
    def _store_ai_routing_metadata(
        *,
        interaction: Interaction,
        layer_metadata: dict[str, Any],
    ) -> None:
        """Persist layer-specific routing metadata without changing analyzer contract."""
        metadata = dict(interaction.metadata_ or {})
        ai_routing = dict(metadata.get("ai_routing") or {})
        layer = str(layer_metadata.get("layer") or "").strip()
        if layer:
            ai_routing[layer] = layer_metadata
            metadata["ai_routing"] = ai_routing
            interaction.metadata_ = metadata

    @staticmethod
    def _populate_stage_scores(stage: dict[str, Any]) -> None:
        """Derive stage-level scores from criterion rows when they are omitted."""
        criteria_results = stage.get("criteria_results") or []
        stage_score = sum(int(item.get("score") or 0) for item in criteria_results)
        max_stage_score = sum(int(item.get("max_score") or 0) for item in criteria_results)
        stage.setdefault("stage_score", stage_score)
        stage.setdefault("max_stage_score", max_stage_score)

    @staticmethod
    def _build_criterion_name_map(score_by_stage: list[dict[str, Any]]) -> dict[str, str]:
        """Build criterion-code to criterion-name lookup from normalized stage rows."""
        mapping: dict[str, str] = {}
        for stage in score_by_stage:
            for criterion in stage.get("criteria_results") or []:
                criterion_code = criterion.get("criterion_code")
                criterion_name = criterion.get("criterion_name")
                if criterion_code and criterion_name:
                    mapping[str(criterion_code)] = str(criterion_name)
        return mapping

    @staticmethod
    def _normalize_finding_items(
        *,
        items: list[dict[str, Any]],
        criterion_name_map: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Support both approved and legacy criterion-based finding shapes."""
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized_item = dict(item)
            criterion_name = criterion_name_map.get(str(normalized_item.get("criterion_code") or ""), "")
            normalized_item.setdefault("title", criterion_name or None)
            normalized_item.setdefault("impact", normalized_item.get("comment"))
            normalized_item.setdefault("evidence", normalized_item.get("evidence"))
            normalized.append(normalized_item)
        return normalized

    @staticmethod
    def _normalize_recommendation_items(
        *,
        items: list[dict[str, Any]],
        criterion_name_map: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Support both approved and legacy recommendation shapes."""
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized_item = dict(item)
            criterion_name = criterion_name_map.get(str(normalized_item.get("criterion_code") or ""), "")
            normalized_item.setdefault("priority", "medium")
            normalized_item.setdefault("problem", criterion_name or None)
            normalized_item.setdefault("why_it_matters", None)
            normalized_item.setdefault("better_phrase", normalized_item.get("recommendation"))
            normalized.append(normalized_item)
        return normalized

    def _populate_checklist_score(self, contract: dict[str, Any]) -> None:
        """Recompute checklist score aggregates from normalized stage rows."""
        stages = contract.get("score_by_stage") or []
        total_points = sum(int(stage.get("stage_score") or 0) for stage in stages)
        max_points = sum(int(stage.get("max_stage_score") or 0) for stage in stages)
        score_percent = round((total_points / max_points) * 100, 2) if max_points else 0.0

        level = "problematic"
        for item in CHECKLIST_DEFINITION["scoring"]["level_mapping"]:
            if item["min_percent"] <= score_percent <= item["max_percent"]:
                level = item["level"]
                break

        checklist_score = contract["score"]["checklist_score"]
        checklist_score["total_points"] = total_points
        checklist_score["max_points"] = max_points
        checklist_score["score_percent"] = score_percent
        checklist_score["level"] = level

    @staticmethod
    def _normalize_direction(value: Any) -> str | None:
        """Normalize telephony direction into the contract wording."""
        if value is None:
            return None
        normalized = str(value).lower()
        mapping = {"in": "inbound", "out": "outbound", "inbound": "inbound", "outbound": "outbound"}
        return mapping.get(normalized, str(value))

    @staticmethod
    def _to_iso_datetime(value: Any) -> str | None:
        """Convert known local datetime formats to ISO-8601 when possible."""
        if value is None:
            return None
        text = str(value)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=UTC).isoformat()
            except ValueError:
                continue
        return text

    @staticmethod
    def _infer_transcript_quality(interaction: Interaction) -> str:
        """Infer a compact transcript-quality label from metadata confidence."""
        metadata = dict(interaction.metadata_ or {})
        confidence = metadata.get("confidence")
        if confidence is None:
            return "unknown"
        if confidence >= 0.85:
            return "high"
        if confidence >= 0.65:
            return "ok"
        return "low"
