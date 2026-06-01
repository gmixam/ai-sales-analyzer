"""Calls analyzer wired to the approved MVP-1 checklist and contract."""

from __future__ import annotations

import json
import os
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
from app.agents.calls.llm_simulation import (
    SubagentRuntimeError,
    request_subagent_llm_content,
    request_simulated_llm_content,
    simulated_routing_metadata,
    simulation_enabled,
    subagent_runtime_enabled,
)

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

REPORT_EVIDENCE_CONTRACT_FILE_NAME = "REPORT_EVIDENCE_CONTRACT.md"
REPORT_EVIDENCE_SOURCE_DIR_CANDIDATES = [
    Path(__file__).resolve().parents[4] / "docs",
    Path(__file__).resolve().parents[3] / "docs",
]

APPROVED_SCHEMA_VERSION = "call_analysis.v1"
APPROVED_INSTRUCTION_VERSION = "edo_sales_mvp1_call_analysis_v15_block_ready"
EXPERIMENTAL_CONTEXT_EVIDENCE_INSTRUCTION_VERSION = (
    "edo_sales_mvp1_call_analysis_v16_context_evidence"
)
EXPERIMENTAL_UNIVERSAL_EVIDENCE_INSTRUCTION_VERSION = (
    "edo_sales_mvp1_call_analysis_v17_univ_evidence"
)
LAYERED_LLM2_ORCHESTRATION_VERSION = "llm2_layered_runtime_v1"
LAYERED_LLM2_ANALYSIS_MODES = {"layered", "layered_v1", "layered_llm2", "llm2_layered"}
CONTEXT_EVIDENCE_INSTRUCTION_VERSIONS = {
    EXPERIMENTAL_CONTEXT_EVIDENCE_INSTRUCTION_VERSION,
}
UNIVERSAL_EVIDENCE_INSTRUCTION_VERSIONS = {
    EXPERIMENTAL_UNIVERSAL_EVIDENCE_INSTRUCTION_VERSION,
}
APPROVED_CHECKLIST_VERSION = "edo_sales_mvp1_checklist_v1"
SEMANTIC_EMPTY_ANALYSIS_REASON = "semantically_empty_analysis"
NOT_COACHABLE_ANALYSIS_REASON = "not_coachable_or_reportable"
ANALYSIS_FORENSICS_ATTR = "_analysis_forensics"
SALES_RELEVANT_CALL_TYPES = {"sales_primary", "sales_repeat", "mixed"}
NON_COACHABLE_CALL_TYPES = {"support", "internal", "other"}

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
    analyze_facts_scenes: str = ""
    analyze_scoring_gaps: str = ""
    analyze_claim_proof: str = ""
    analyze_recommendations: str = ""


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

    def _get_analyze_prompt(self, instruction_version: str = APPROVED_INSTRUCTION_VERSION) -> str:
        """Load the default analyzer prompt plus optional experimental overlays."""
        base_prompt = self._get_prompt("analyze")
        if str(instruction_version or "").strip() in CONTEXT_EVIDENCE_INSTRUCTION_VERSIONS:
            overlay = self._get_prompt("analyze_v16_context_evidence")
            return f"{base_prompt.rstrip()}\n\n{overlay.strip()}\n"
        if str(instruction_version or "").strip() in UNIVERSAL_EVIDENCE_INSTRUCTION_VERSIONS:
            overlay = self._get_prompt("analyze_v17_universal_evidence")
            return f"{base_prompt.rstrip()}\n\n{overlay.strip()}\n"
        return base_prompt

    @staticmethod
    def _llm2_layered_analysis_enabled() -> bool:
        """Return whether LLM-2 should run as layered 2A/2B/2C/2D passes."""

        mode = (
            os.getenv("AI_LLM2_ANALYSIS_MODE")
            or getattr(settings, "ai_llm2_analysis_mode", "")
            or "monolithic"
        )
        return str(mode).strip().lower() in LAYERED_LLM2_ANALYSIS_MODES

    def _resolve_source_file(self, key: str) -> Path | None:
        """Resolve one approved MVP-1 source file across known runtime locations."""
        filename = MVP1_SOURCE_FILE_NAMES[key]
        for directory in MVP1_SOURCE_DIR_CANDIDATES:
            candidate = directory / filename
            if candidate.exists():
                return candidate
        return None

    def _resolve_report_evidence_contract_file(self) -> Path | None:
        """Resolve the additive report_evidence contract across known runtime locations."""
        for directory in REPORT_EVIDENCE_SOURCE_DIR_CANDIDATES:
            candidate = directory / REPORT_EVIDENCE_CONTRACT_FILE_NAME
            if candidate.exists():
                return candidate
        return None

    def _load_source_text(self, key: str, fallback_text: str) -> str:
        """Read one source-of-truth MVP-1 document or return a runtime-safe fallback."""
        source_file = self._resolve_source_file(key)
        if source_file is not None:
            return source_file.read_text(encoding="utf-8")
        return fallback_text

    def _load_report_evidence_contract_text(self, fallback_text: str) -> str:
        """Read the additive report_evidence contract or return a runtime-safe fallback."""
        source_file = self._resolve_report_evidence_contract_file()
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

    def get_prompt_assets(
        self,
        instruction_version: str = APPROVED_INSTRUCTION_VERSION,
    ) -> PromptAssetSet:
        """Return loaded analyzer-related prompts."""
        return PromptAssetSet(
            classify=self._get_prompt("classify"),
            analyze=self._get_analyze_prompt(instruction_version),
            agreements=self._get_prompt("agreements"),
            insights=self._get_prompt("insights"),
            analyze_facts_scenes=self._get_prompt("analyze_facts_scenes"),
            analyze_scoring_gaps=self._get_prompt("analyze_scoring_gaps"),
            analyze_claim_proof=self._get_prompt("analyze_claim_proof"),
            analyze_recommendations=self._get_prompt("analyze_recommendations"),
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
        prompt_assets = self.get_prompt_assets(instruction_version=instruction_version)
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
                "report_evidence_contract_markdown": self._load_report_evidence_contract_text(
                    fallback_text=(
                        "Runtime fallback: REPORT_EVIDENCE_CONTRACT.md is unavailable. "
                        "Use prompt_assets.analyze additive report_evidence v1 instructions."
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
                "REPORT_EVIDENCE_CONTRACT.md",
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
        prompt_assets = self.get_prompt_assets(instruction_version=instruction_version)
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
        if self._llm2_layered_analysis_enabled():
            return self._analyze_call_with_layered_llm2(
                interaction=interaction,
                instruction_version=instruction_version,
                llm1_first_pass=llm1_first_pass,
            )

        messages = [
            {"role": "system", "content": self._get_analyze_prompt(instruction_version)},
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
                    "content": self._build_analysis_retry_instruction(exc),
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
                if self._should_mark_not_coachable(
                    error=retry_exc,
                    llm1_first_pass=llm1_first_pass,
                ):
                    normalized = self._mark_not_coachable_result(
                        normalized_result=getattr(retry_exc, "normalized_result", None),
                        llm1_first_pass=llm1_first_pass,
                    )
                    self._store_analysis_forensics(
                        interaction=interaction,
                        raw_llm_response=retry_exc.raw_response or retry_content,
                        normalized_result=normalized,
                        failure_reason=NOT_COACHABLE_ANALYSIS_REASON,
                    )
                    raise SemanticAnalysisError(
                        "Analyzer marked call as not coachable/reportable.",
                        interaction_id=str(interaction.id),
                        raw_response=retry_exc.raw_response or retry_content,
                        normalized_result=normalized,
                        reason_code=NOT_COACHABLE_ANALYSIS_REASON,
                    ) from retry_exc
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

    def _analyze_call_with_layered_llm2(
        self,
        *,
        interaction: Interaction,
        instruction_version: str,
        llm1_first_pass: dict[str, Any],
    ) -> dict[str, Any]:
        """Run opt-in layered LLM-2 passes and return the existing contract shape."""

        prompt_context = self.build_prompt_context(
            interaction=interaction,
            instruction_version=instruction_version,
            llm1_first_pass=llm1_first_pass,
        )
        admission_gate = self._llm2_admission_gate(
            interaction=interaction,
            llm1_first_pass=llm1_first_pass,
        )
        if not admission_gate["admitted"]:
            normalized = self._mark_not_coachable_result(
                normalized_result={
                    "classification": {
                        "analysis_eligibility": "not_eligible",
                        "eligibility_reason": admission_gate["reason_code"],
                    },
                    "diagnostics": {"llm2_admission_gate": admission_gate},
                },
                llm1_first_pass=llm1_first_pass,
            )
            self._store_analysis_forensics(
                interaction=interaction,
                raw_llm_response=json.dumps(
                    {
                        "artifact_type": "llm2_admission_gate_rejection",
                        "call_id": str(interaction.id),
                        "instruction_version": instruction_version,
                        "llm2_admission_gate": admission_gate,
                    },
                    ensure_ascii=False,
                ),
                normalized_result=normalized,
                failure_reason=admission_gate["reason_code"],
            )
            raise SemanticAnalysisError(
                "Analyzer did not admit call into layered LLM-2.",
                interaction_id=str(interaction.id),
                raw_response=json.dumps(admission_gate, ensure_ascii=False),
                normalized_result=normalized,
                reason_code=admission_gate["reason_code"],
            )
        prompt_assets = self.get_prompt_assets(instruction_version=instruction_version)
        artifacts: dict[str, Any] = {}
        pass_metadata: dict[str, Any] = {}
        pass_plan = [
            ("llm2a", "llm2a_facts_scenes", prompt_assets.analyze_facts_scenes, ()),
            ("llm2b", "llm2b_scoring_gaps", prompt_assets.analyze_scoring_gaps, ("llm2a",)),
            ("llm2c", "llm2c_claim_proof", prompt_assets.analyze_claim_proof, ("llm2a", "llm2b")),
            (
                "llm2d",
                "llm2d_recommendations",
                prompt_assets.analyze_recommendations,
                ("llm2a", "llm2b", "llm2c"),
            ),
        ]
        layered_artifact: dict[str, Any] = {
            "artifact_type": "llm2_layered_runtime_artifact",
            "artifact_version": LAYERED_LLM2_ORCHESTRATION_VERSION,
            "call_id": str(interaction.id),
            "source": "CallsAnalyzer.layered_llm2",
            "instruction_version": instruction_version,
            "llm2_admission_gate": deepcopy(admission_gate),
        }
        self.logger.info(
            "analyzer.llm2_layered_start",
            interaction_id=str(interaction.id),
            instruction_version=instruction_version,
        )
        try:
            for artifact_key, request_kind, system_prompt, dependency_keys in pass_plan:
                dependency_payload = {
                    key: artifacts[key]
                    for key in dependency_keys
                    if artifacts.get(key) is not None
                }
                artifacts[artifact_key] = self._request_llm2_layered_pass(
                    interaction=interaction,
                    instruction_version=instruction_version,
                    request_kind=request_kind,
                    system_prompt=system_prompt,
                    prompt_context=prompt_context,
                    previous_artifacts=dependency_payload,
                    admission_gate=admission_gate,
                )
                if artifact_key == "llm2a":
                    self._apply_llm2_admission_gate_to_llm2a(
                        artifacts[artifact_key],
                        admission_gate=admission_gate,
                    )
                if artifact_key == "llm2b":
                    self._validate_llm2b_scoring_after_admission(
                        interaction=interaction,
                        llm2a=artifacts.get("llm2a") or {},
                        llm2b=artifacts[artifact_key],
                        admission_gate=admission_gate,
                    )
                pass_metadata[artifact_key] = self._current_ai_routing_metadata(
                    interaction=interaction,
                    layer="llm2",
                )
            layered_artifact.update(artifacts)

            from app.agents.calls.llm2_layered_analysis import (
                LAYERED_ADAPTER_INSTRUCTION_VERSION,
                normalize_llm2_layered_analysis,
            )

            normalized = normalize_llm2_layered_analysis(
                layered_artifact,
                transcript=interaction.text or "",
                validate_evidence=settings.ai_llm2_report_evidence_validation_enabled,
            )
            normalized.scores_detail["llm2_layered_runtime"] = {
                "enabled": True,
                "orchestration_version": LAYERED_LLM2_ORCHESTRATION_VERSION,
                "adapter_instruction_version": LAYERED_ADAPTER_INSTRUCTION_VERSION,
                "manager_claims_require_proof_cards": True,
                "pass_artifact_keys": list(artifacts),
                "pass_metadata": deepcopy(pass_metadata),
                "validation_valid": normalized.is_valid,
                "report_evidence_validation_enabled": settings.ai_llm2_report_evidence_validation_enabled,
                "semantic_validation_enabled": settings.ai_llm2_semantic_validation_enabled,
            }
            normalized.scores_detail["llm2_layered_artifacts"] = deepcopy(artifacts)
            if not normalized.is_valid:
                validation = normalized.report_evidence_validation
                issue_codes = [
                    getattr(issue, "code", "unknown")
                    for issue in (validation.errors if validation is not None else [])
                ]
                raise LLMResponseError(
                    "Layered LLM-2 report_evidence validation failed: "
                    + ", ".join(issue_codes or ["unknown"]),
                    interaction_id=str(interaction.id),
                    raw_response=json.dumps(layered_artifact, ensure_ascii=False),
                    normalized_result=normalized.scores_detail,
                )
            validated = self._validate_and_normalize_contract(
                raw_contract=normalized.scores_detail,
                interaction=interaction,
                instruction_version=instruction_version,
            )
            validated["llm2_layered_runtime"]["validation_valid"] = True
            self._store_analysis_forensics(
                interaction=interaction,
                raw_llm_response=json.dumps(layered_artifact, ensure_ascii=False),
                normalized_result=validated,
                failure_reason=None,
            )
            self.logger.info(
                "analyzer.llm2_layered_done",
                interaction_id=str(interaction.id),
                instruction_version=instruction_version,
                stages=len(validated.get("score_by_stage") or []),
            )
            return validated
        except (LLMResponseError, SemanticAnalysisError) as exc:
            self._store_analysis_forensics(
                interaction=interaction,
                raw_llm_response=json.dumps(
                    {
                        **layered_artifact,
                        "completed_passes": sorted(artifacts),
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
                normalized_result=getattr(exc, "normalized_result", None),
                failure_reason=getattr(exc, "reason_code", None)
                or "llm2_layered_validation_failed",
            )
            raise
        except Exception as exc:
            failure_payload = {
                "artifact_type": "llm2_layered_runtime_failure",
                "artifact_version": LAYERED_LLM2_ORCHESTRATION_VERSION,
                "call_id": str(interaction.id),
                "instruction_version": instruction_version,
                "completed_passes": sorted(artifacts),
                "error": str(exc),
            }
            self._store_analysis_forensics(
                interaction=interaction,
                raw_llm_response=json.dumps(failure_payload, ensure_ascii=False),
                normalized_result=None,
                failure_reason="llm2_layered_runtime_failed",
            )
            raise AnalysisError(
                f"Layered LLM-2 runtime failed closed: {exc}",
                interaction_id=str(interaction.id),
                original=exc,
            ) from exc

    def _llm2_admission_gate(
        self,
        *,
        interaction: Interaction,
        llm1_first_pass: dict[str, Any],
    ) -> dict[str, Any]:
        """Return the single whole-call admission decision before layered LLM-2."""

        transcript = str(getattr(interaction, "text", "") or "").strip()
        classification = dict(llm1_first_pass.get("classification") or {})
        call_type = str(classification.get("call_type") or "").strip().lower()
        eligibility = str(classification.get("analysis_eligibility") or "").strip().lower()
        reason = str(classification.get("eligibility_reason") or "").strip().lower()
        non_commercial_or_unusable_reason = any(
            token in reason
            for token in (
                "support",
                "technical",
                "non-sales",
                "not_sales",
                "internal",
                "ivr",
                "no_speech",
                "poor_transcript",
                "poor transcript",
                "unusable_transcript",
            )
        )

        if not transcript:
            return {
                "admitted": False,
                "reason_code": "llm2_admission_no_transcript",
                "source": "pre_llm2_admission_gate",
                "duration_sec": getattr(interaction, "duration_sec", None),
                "call_type": call_type or None,
                "llm1_eligibility": eligibility or None,
            }
        if call_type in {"support", "internal"} or (
            eligibility == "not_eligible" and (call_type == "other" or non_commercial_or_unusable_reason)
        ):
            return {
                "admitted": False,
                "reason_code": "llm2_admission_non_commercial_or_unusable",
                "source": "pre_llm2_admission_gate",
                "duration_sec": getattr(interaction, "duration_sec", None),
                "call_type": call_type,
                "llm1_eligibility": eligibility or None,
                "llm1_reason": reason or None,
            }
        return {
            "admitted": True,
            "reason_code": "llm2_admission_accepted",
            "source": "pre_llm2_admission_gate",
            "duration_sec": getattr(interaction, "duration_sec", None),
            "call_type": call_type or None,
            "llm1_eligibility": eligibility or None,
            "llm1_reason": reason or None,
            "duration_is_not_stop_condition": True,
        }

    def _apply_llm2_admission_gate_to_llm2a(
        self,
        artifact: dict[str, Any],
        *,
        admission_gate: dict[str, Any],
    ) -> None:
        """Prevent an admitted commercial call from being stopped inside LLM-2A."""

        artifact["llm2_admission_gate"] = deepcopy(admission_gate)
        if not admission_gate.get("admitted"):
            return
        eligibility = str(artifact.get("analysis_eligibility") or "").strip().lower()
        if eligibility not in {"not_eligible", "insufficient"}:
            return
        if not self._llm2a_indicates_commercial_scoring_scope(artifact):
            return
        original = {
            "analysis_eligibility": artifact.get("analysis_eligibility"),
            "eligibility_reason": artifact.get("eligibility_reason"),
        }
        artifact["analysis_eligibility"] = "eligible"
        artifact["eligibility_reason"] = "llm2_admission_gate_accepted_commercial_scope"
        artifact.setdefault("admission_gate_overrides", []).append(
            {
                "field": "analysis_eligibility",
                "original": original,
                "reason": (
                    "Whole-call admission belongs before LLM-2; duration or short "
                    "commercial context must not stop downstream scoring."
                ),
            }
        )

    def _validate_llm2b_scoring_after_admission(
        self,
        *,
        interaction: Interaction,
        llm2a: dict[str, Any],
        llm2b: dict[str, Any],
        admission_gate: dict[str, Any],
    ) -> None:
        """Fail closed when LLM-2B silently skips scoring an admitted commercial call."""

        if not admission_gate.get("admitted"):
            return
        if not self._llm2a_indicates_commercial_scoring_scope(llm2a):
            return
        if llm2b.get("criteria_results") or llm2b.get("stage_scores"):
            return
        diagnostic = {
            "reason_code": "llm2b_missing_scores_for_admitted_commercial_call",
            "llm2_admission_gate": admission_gate,
            "llm2a": {
                "analysis_eligibility": llm2a.get("analysis_eligibility"),
                "eligibility_reason": llm2a.get("eligibility_reason"),
                "business_outcome_signal": llm2a.get("business_outcome_signal"),
                "scenes_count": len(llm2a.get("scenes") or []),
                "evidence_count": len(llm2a.get("evidence_ledger") or []),
            },
            "llm2b": {
                "criteria_results_count": len(llm2b.get("criteria_results") or []),
                "stage_scores_count": len(llm2b.get("stage_scores") or []),
                "fail_closed": llm2b.get("fail_closed"),
            },
        }
        raise LLMResponseError(
            "LLM-2B returned no scoring for an admitted commercial call.",
            interaction_id=str(interaction.id),
            raw_response=json.dumps(diagnostic, ensure_ascii=False),
            normalized_result=diagnostic,
            reason_code="llm2b_missing_scores_for_admitted_commercial_call",
        )

    @staticmethod
    def _llm2a_indicates_commercial_scoring_scope(artifact: dict[str, Any]) -> bool:
        """Return whether LLM-2A output describes a call that should be scored."""

        business_outcome = dict(artifact.get("business_outcome_signal") or {})
        status = str(business_outcome.get("status") or "").strip().lower()
        if status == "tech_service" or status == "insufficient":
            return False
        if status in {"agreement", "rescheduled", "refusal", "open", "not_suitable"}:
            return True

        reason = str(artifact.get("eligibility_reason") or "").strip().lower()
        if any(token in reason for token in ("support", "technical", "internal", "non-sales", "not_sales")):
            return False
        has_observed_content = bool(artifact.get("scenes")) and bool(artifact.get("evidence_ledger"))
        has_duration_only_rejection = any(
            token in reason
            for token in (
                "duration_below",
                "below threshold",
                "ниже порога",
                "180",
                "корот",
                "short",
            )
        )
        return has_observed_content and has_duration_only_rejection

    def _request_llm2_layered_pass(
        self,
        *,
        interaction: Interaction,
        instruction_version: str,
        request_kind: str,
        system_prompt: str,
        prompt_context: dict[str, Any],
        previous_artifacts: dict[str, Any],
        admission_gate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Request and parse one LLM-2 layered pass artifact."""

        call_id = str(interaction.id)
        if request_kind == "llm2a_facts_scenes":
            metadata = dict(interaction.metadata_ or {})
            user_payload = {
                "call_id": call_id,
                "metadata": metadata,
                "transcript": interaction.text or "",
                "segments": metadata.get("segments")
                or metadata.get("transcript_segments")
                or metadata.get("utterances")
                or [],
                "llm1_first_pass": prompt_context.get("llm1_first_pass") or {},
                "llm2_admission_gate": admission_gate or {},
                "checklist_observation_frame": prompt_context["checklist_definition"],
            }
        elif request_kind == "llm2b_scoring_gaps":
            user_payload = {
                "call_id": call_id,
                "llm2a_artifact": previous_artifacts.get("llm2a") or {},
                "llm2_admission_gate": admission_gate or {},
                "checklist_definition": prompt_context["checklist_definition"],
                "mvp1_contract_shape": prompt_context["analysis_result_contract_template"],
            }
        elif request_kind == "llm2c_claim_proof":
            user_payload = {
                "call_id": call_id,
                "llm2a_artifact": previous_artifacts.get("llm2a") or {},
                "llm2b_artifact": previous_artifacts.get("llm2b") or {},
                "llm2_admission_gate": admission_gate or {},
            }
        elif request_kind == "llm2d_recommendations":
            user_payload = {
                "call_id": call_id,
                "llm2a_artifact": previous_artifacts.get("llm2a") or {},
                "llm2b_artifact": previous_artifacts.get("llm2b") or {},
                "llm2c_artifact": previous_artifacts.get("llm2c") or {},
                "llm2_admission_gate": admission_gate or {},
                "mvp1_contract_shape": prompt_context["analysis_result_contract_template"],
                "report_evidence_contract_v1": prompt_context["approved_sources"].get(
                    "report_evidence_contract_markdown",
                    "",
                ),
            }
        else:
            user_payload = {
                "request_kind": request_kind,
                "interaction": prompt_context["interaction"],
                "checklist_definition": prompt_context["checklist_definition"],
                "analysis_result_contract_template": prompt_context[
                    "analysis_result_contract_template"
                ],
                "llm1_first_pass": prompt_context.get("llm1_first_pass"),
                "previous_artifacts": previous_artifacts,
            }
        content = self._request_llm_content(
            interaction=interaction,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{self._get_prompt('llm2_pass_contracts').rstrip()}\n\n"
                        f"{system_prompt.strip()}"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
                },
            ],
            instruction_version=instruction_version,
            layer="llm2",
            request_kind=request_kind,
            executor_label="LLM-2 OpenAI-compatible executor",
            temperature=0.1,
        )
        try:
            artifact = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                f"{request_kind} returned invalid JSON",
                interaction_id=str(interaction.id),
                raw_response=content,
            ) from exc
        if not isinstance(artifact, dict):
            raise LLMResponseError(
                f"{request_kind} must return a JSON object",
                interaction_id=str(interaction.id),
                raw_response=content,
            )
        artifact.setdefault("call_id", str(interaction.id))
        if str(artifact.get("status") or "").strip().lower() in {"failed", "error"}:
            raise LLMResponseError(
                f"{request_kind} returned failed status",
                interaction_id=str(interaction.id),
                raw_response=content,
            )
        return artifact

    @staticmethod
    def _should_mark_not_coachable(
        *,
        error: LLMResponseError,
        llm1_first_pass: dict[str, Any],
    ) -> bool:
        """Return True when a semantic-empty retry is a bounded non-coachable call."""
        if str(getattr(error, "reason_code", "") or "") != SEMANTIC_EMPTY_ANALYSIS_REASON:
            return False
        candidates: list[dict[str, Any]] = []
        normalized_result = getattr(error, "normalized_result", None)
        if isinstance(normalized_result, dict):
            candidates.append(dict(normalized_result.get("classification") or {}))
        candidates.append(dict(llm1_first_pass.get("classification") or {}))
        for classification in candidates:
            call_type = str(classification.get("call_type") or "").strip()
            eligibility = str(classification.get("analysis_eligibility") or "").strip()
            reason = str(classification.get("eligibility_reason") or "").lower()
            if eligibility == "not_eligible" or call_type in {"support", "internal", "other"}:
                return True
            if any(token in reason for token in ("support", "technical", "non-sales", "not_sales", "internal")):
                return True
        return False

    def _mark_not_coachable_result(
        self,
        *,
        normalized_result: dict[str, Any] | None,
        llm1_first_pass: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a schema-safe normalized snapshot for non-coachable forensics."""
        result = deepcopy(normalized_result or {})
        classification = self._merge_dict(
            dict(llm1_first_pass.get("classification") or {}),
            dict(result.get("classification") or {}),
        )
        classification["analysis_eligibility"] = "not_eligible"
        classification["eligibility_reason"] = (
            classification.get("eligibility_reason")
            or "not_coachable_or_reportable"
        )
        result["classification"] = classification
        result.setdefault("score_by_stage", [])
        result.setdefault("strengths", [])
        result.setdefault("gaps", [])
        result.setdefault("recommendations", [])
        result.setdefault("evidence_fragments", [])
        return result

    @staticmethod
    def _build_analysis_retry_instruction(exc: LLMResponseError) -> str:
        """Build a focused retry instruction for contract or semantic validation failures."""
        reason_code = str(getattr(exc, "reason_code", "") or "").strip()
        base = (
            "The JSON above failed strict approved-contract validation with this error:\n"
            f"{exc}\n\n"
            "Return one corrected JSON object only. Preserve the approved schema, include "
            "all required stage and criterion fields, and do not add explanations. "
            "For `report_evidence.block_candidates`, every `fit=true` item must include "
            "a non-empty canonical `stage_code` from the checklist; use "
            "`cross_stage_transition` only for true cross-stage material and never omit "
            "`stage_code` on usable block candidates."
        )
        if reason_code == SEMANTIC_EMPTY_ANALYSIS_REASON:
            return (
                f"{base}\n\n"
                "If the transcript is sales-relevant and eligible, do not return an empty coaching shell: "
                "include applicable `score_by_stage` with criterion-level evidence plus at least one "
                "`strengths`, one `gaps`, one `recommendations`, and usable `evidence_fragments` when "
                "the transcript supports them. If the call is truly support-only/internal/non-coachable, "
                "set `classification.analysis_eligibility` to `not_eligible` and provide a clear "
                "`eligibility_reason`.\n\n"
                "Preserve the additive `report_evidence_version=\"v1\"` and `report_evidence` package. "
                "When enough transcript or metadata exists, include `report_evidence.call_report_summary` "
                "with `short_topic`, `short_context`, `manager_visible_summary`, semantic `hotness` limited to `hot|warm|low`, "
                "`manager_next_action`, and a manager-voiced `suggested_manager_phrase` that does not copy "
                "client quotes. For business-meaningful calls with enough transcript content, include "
                "`report_evidence.semantic_case` with `case_title`, `case_type`, `core_meaning`, "
                "`customer_signal`, `manager_behavior`, `coaching_diagnosis`, `recommended_next_action`, "
                "optional grounded `best_dialogue_fragment`, and `report_block_fit` for `situation_day`, "
                "`call_breakdown`, `voice_of_customer`, `additional_situations`, and `call_tomorrow`. "
                "Also prepare optional v15 `report_evidence.block_candidates` for `situation_day`, "
                "`call_breakdown`, `voice_of_customer`, `money_on_table`, `tomorrow_follow_up`, "
                "`tomorrow_challenge`, and `call_list_context` when enough transcript content exists. "
                "Each suitable block candidate must be block-ready: include `fit`, `score`, `role`, "
                "`title_mode`, a concrete thesis or signal, what happened, why it matters, proof type, "
                "proof explanation, quote role, counter-evidence, and the next/report action. "
                "Each relevant `fit=true` report block item must include block role, title mode, "
                "evidence target, gap_proven, a `coaching_moment` with `summary`, optional "
                "`missing_action`, optional `why_it_matters`, optional `supporting_quote`, "
                "`evidence_type`, `confidence`, `gap_claim`, `proof_type`, `proof_explanation`, "
                "`quote_role`, and `counter_evidence`, and problem_fit for problem-oriented blocks. "
                "For problem blocks, the quote must prove the manager gap, not merely mention the topic; "
                "if the quote shows the manager did the allegedly missing action, put it in "
                "`counter_evidence` and mark the problem block `fit=false`. "
                "`proof_type=direct_gap` is allowed only when one quote or short fragment directly proves "
                "the manager gap; use `sequence_inference` for event order, `absence_in_context` for a "
                "missing action in the available record, and `context_support` only for context that does "
                "not prove a problem. For missing qualification before product offering, a product-offer "
                "quote is usually `quote_role=supports_context`, not `direct_gap`; the proof should be "
                "`sequence_inference` or `absence_in_context` unless the quote directly proves the gap. "
                "For `fit=false` or not-relevant block items, prefer `coaching_moment=null` instead "
                "of a weak placeholder. `coaching_moment.evidence_type` must be only "
                "`direct_quote`, `absence_in_context`, or `inferred_from_dialogue`; never use "
                "`none` or `insufficient` there. If `evidence_type=direct_quote`, "
                "`supporting_quote` must be a non-empty exact transcript substring. If no exact "
                "quote can be copied, use `supporting_quote=null` with `absence_in_context` or "
                "`inferred_from_dialogue`, or set `coaching_moment=null` for an irrelevant block. "
                "If the semantic case is too weak for report use, "
                "return `case_type=insufficient_evidence`, `evidence_quality=insufficient`, "
                "`best_dialogue_fragment=[]`, and `usable_in_report=false`. "
                "If `report_evidence.business_outcome.status` is `agreement`, `rescheduled`, or `open`, "
                "`manager_coaching_moments` must contain at least one item and at least one of "
                "`situation_candidates` or `manager_coaching_moments` must be non-empty. If the transcript "
                "is too thin for a strong report example, return an explicit `evidence_quality=insufficient`, "
                "`dialogue_fragment=[]`, `usable_in_report=false` item instead of empty arrays. Do not "
                "return `follow_up_candidates` for `refusal`, `tech_service`, or `not_suitable`."
            )
        if "max_score" in str(exc):
            return (
                f"{base}\n\n"
                "Every criterion in `criteria_results` must include `max_score`. For this approved "
                "checklist each criterion has `max_score: 2`."
            )
        return base

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
        if simulation_enabled():
            route_plan = self.ai_router.build_route_plan(
                layer=layer,
                subject_key=str(interaction.id),
            )
            selected = route_plan.current_candidate()
            content = request_simulated_llm_content(
                layer=layer,
                request_kind=request_kind,
                messages=messages,
                subject_key=str(interaction.id),
                instruction_version=instruction_version,
            )
            layer_metadata = simulated_routing_metadata(
                layer=layer,
                request_kind=request_kind,
                subject_key=str(interaction.id),
            )
            layer_metadata.update(
                {
                    "policy": route_plan.policy,
                    "requested_policy": route_plan.requested_policy,
                    "forced_override": route_plan.forced_override,
                    "force_reason": route_plan.force_reason or "ai_llm_simulation_enabled",
                    "configured_pool_size": route_plan.configured_pool_size,
                    "selected_provider": selected.provider,
                    "selected_account_alias": selected.account_alias,
                    "selected_api_key_env": selected.api_key_env,
                    "selected_model": selected.model,
                    "selected_api_base": selected.api_base,
                    "selected_endpoint": selected.endpoint,
                    "selected_timeout_sec": selected.timeout_sec,
                    "selected_max_retries_for_this_provider": (
                        selected.max_retries_for_this_provider
                    ),
                    "selected_execution_mode": "simulation",
                }
            )
            self._store_ai_routing_metadata(
                interaction=interaction,
                layer_metadata=layer_metadata,
            )
            self.logger.info(
                "analyzer.llm_simulated",
                interaction_id=str(interaction.id),
                instruction_version=instruction_version,
                layer=layer,
                request_kind=request_kind,
            )
            return content
        if subagent_runtime_enabled():
            route_plan = self.ai_router.build_route_plan(
                layer=layer,
                subject_key=str(interaction.id),
            )
            selected = route_plan.current_candidate()
            self.logger.info(
                "analyzer.llm_subagent_start",
                interaction_id=str(interaction.id),
                instruction_version=instruction_version,
                layer=layer,
                provider=selected.provider,
                account_alias=selected.account_alias,
                request_kind=request_kind,
            )
            try:
                result = request_subagent_llm_content(
                    layer=layer,
                    request_kind=request_kind,
                    messages=messages,
                    subject_key=str(interaction.id),
                    instruction_version=instruction_version,
                )
            except SubagentRuntimeError as exc:
                route_plan.mark_attempt_failure(str(exc))
                layer_metadata = route_plan.to_metadata(
                    executed=False,
                    request_kind=request_kind,
                    execution_status="subagent_failed",
                    executed_endpoint_path="external_subagent_runner",
                    notes=f"{layer_label} subagent runtime failed closed.",
                )
                layer_metadata.update(getattr(exc, "metadata", {}) or {})
                layer_metadata["selected_execution_mode"] = "subagent_runtime"
                layer_metadata["actual_execution_mode"] = "subagent_runtime"
                layer_metadata["execution_status"] = "subagent_failed"
                self._store_ai_routing_metadata(
                    interaction=interaction,
                    layer_metadata=layer_metadata,
                )
                raise AnalysisError(
                    f"{layer_label} subagent runtime failed: {exc}",
                    interaction_id=str(interaction.id),
                    original=exc,
                ) from exc
            route_plan.mark_attempt_success()
            layer_metadata = route_plan.to_metadata(
                request_kind=request_kind,
                execution_status="subagent_executed",
                executed_endpoint_path="external_subagent_runner",
                provider_request_id=result.metadata.get("provider_request_id"),
                notes=f"{layer_label} subagent runtime request completed.",
            )
            layer_metadata.update(result.metadata)
            layer_metadata["planned_real_llm_route"] = {
                "selected_provider": selected.provider,
                "selected_account_alias": selected.account_alias,
                "selected_api_key_env": selected.api_key_env,
                "selected_model": selected.model,
                "selected_api_base": selected.api_base,
                "selected_endpoint": selected.endpoint,
            }
            layer_metadata["selected_execution_mode"] = "subagent_runtime"
            layer_metadata["actual_execution_mode"] = "subagent_runtime"
            self._store_ai_routing_metadata(
                interaction=interaction,
                layer_metadata=layer_metadata,
            )
            self.logger.info(
                "analyzer.llm_subagent_done",
                interaction_id=str(interaction.id),
                instruction_version=instruction_version,
                layer=layer,
                request_kind=request_kind,
            )
            return result.content
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
        if settings.ai_llm2_report_evidence_validation_enabled:
            self._validate_report_evidence_block_candidate_stage_codes(
                contract=contract,
                allowed_stage_codes=set(allowed_stage_map),
                interaction_id=str(interaction.id),
                raw_response=json.dumps(raw_contract, ensure_ascii=False),
            )
        for stage in contract["score_by_stage"] or []:
            stage_code = stage.get("stage_code")
            if stage_code not in allowed_stage_map:
                raise LLMResponseError(
                    f"Unknown stage_code: {stage_code}",
                    interaction_id=str(interaction.id),
                    raw_response=json.dumps(raw_contract, ensure_ascii=False),
                )
            if isinstance(stage.get("criteria_results"), list):
                self._repair_criterion_scores_from_checklist(stage)
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
        self._enrich_contract_for_reporting(contract)
        self._populate_checklist_score(contract)
        self._apply_analysis_eligibility_guardrails(contract)
        self._enrich_contract_for_reporting(contract)
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
        classification = dict(contract.get("classification") or {})
        analysis_eligibility = str(classification.get("analysis_eligibility") or "").strip()
        call_type = str(classification.get("call_type") or "").strip()
        if analysis_eligibility == "not_eligible" or call_type in {"support", "internal", "other"}:
            if not (contract.get("score_by_stage") or []):
                return [NOT_COACHABLE_ANALYSIS_REASON]
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
        if not settings.ai_llm2_semantic_validation_enabled:
            return
        reason_codes = self._semantic_invalid_reason_codes(contract)
        if reason_codes:
            raise SemanticAnalysisError(
                "Analyzer returned a semantically empty analysis contract.",
                interaction_id=interaction_id,
                raw_response=raw_response,
                normalized_result=deepcopy(contract),
                reason_code=reason_codes[0],
            )

    @staticmethod
    def _validate_report_evidence_block_candidate_stage_codes(
        *,
        contract: dict[str, Any],
        allowed_stage_codes: set[str],
        interaction_id: str,
        raw_response: str,
    ) -> None:
        """Require explicit stage_code on fresh fit=true block-ready material."""
        report_evidence = contract.get("report_evidence")
        if not isinstance(report_evidence, dict):
            return
        block_candidates = report_evidence.get("block_candidates")
        if not isinstance(block_candidates, dict):
            return
        for block_name, raw_candidate in block_candidates.items():
            if not isinstance(raw_candidate, dict):
                continue
            if not CallsAnalyzer._report_block_candidate_fit_is_true(raw_candidate.get("fit")):
                continue
            path = f"report_evidence.block_candidates.{block_name}.stage_code"
            stage_code = str(raw_candidate.get("stage_code") or "").strip()
            if not stage_code:
                raise LLMResponseError(
                    f"{path} is required when fit=true.",
                    interaction_id=interaction_id,
                    raw_response=raw_response,
                )
            if stage_code not in allowed_stage_codes:
                raise LLMResponseError(
                    f"{path} has unknown stage_code: {stage_code}",
                    interaction_id=interaction_id,
                    raw_response=raw_response,
                )

    @staticmethod
    def _report_block_candidate_fit_is_true(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value == 1
        return str(value or "").strip().lower() in {"true", "1", "yes"}

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
    def _current_ai_routing_metadata(
        *,
        interaction: Interaction,
        layer: str,
    ) -> dict[str, Any]:
        """Return the latest stored routing metadata for a layer."""
        metadata = dict(interaction.metadata_ or {})
        ai_routing = dict(metadata.get("ai_routing") or {})
        layer_metadata = ai_routing.get(layer)
        return deepcopy(layer_metadata) if isinstance(layer_metadata, dict) else {}

    @staticmethod
    def _repair_criterion_scores_from_checklist(stage: dict[str, Any]) -> None:
        """Fill criterion max_score from the approved checklist when LLM omits it."""
        known_criteria = {
            criterion["criterion_code"]
            for checklist_stage in CHECKLIST_DEFINITION["stages"]
            if checklist_stage["stage_code"] == stage.get("stage_code")
            for criterion in checklist_stage["criteria"]
        }
        for criterion in stage.get("criteria_results") or []:
            criterion_code = str(criterion.get("criterion_code") or "").strip()
            if criterion_code in known_criteria and criterion.get("max_score") in (None, ""):
                criterion["max_score"] = 2

    @staticmethod
    def _score_int(value: Any) -> int:
        """Return a safe integer score from scalar or common LLM-wrapped score shapes."""
        if isinstance(value, dict):
            for key in ("score", "value", "points", "stage_score", "max_score", "max_stage_score"):
                if key in value:
                    return CallsAnalyzer._score_int(value.get(key))
            return 0
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _populate_stage_scores(stage: dict[str, Any]) -> None:
        """Derive stage-level scores from criterion rows when they are omitted."""
        criteria_results = stage.get("criteria_results") or []
        stage_score = sum(CallsAnalyzer._score_int(item.get("score")) for item in criteria_results)
        max_stage_score = sum(CallsAnalyzer._score_int(item.get("max_score")) for item in criteria_results)
        if not isinstance(stage.get("stage_score"), (int, float, str)):
            stage["stage_score"] = stage_score
        else:
            stage.setdefault("stage_score", stage_score)
        if not isinstance(stage.get("max_stage_score"), (int, float, str)):
            stage["max_stage_score"] = max_stage_score
        else:
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

    def _enrich_contract_for_reporting(self, contract: dict[str, Any]) -> None:
        """Derive bounded coaching fields from existing criterion evidence."""
        layered_runtime = contract.get("llm2_layered_runtime")
        if (
            isinstance(layered_runtime, dict)
            and layered_runtime.get("manager_claims_require_proof_cards") is True
        ):
            return
        if not self._is_sales_relevant_contract(contract):
            return
        weak_criteria, strong_criteria = self._collect_reportable_criteria(contract)
        if weak_criteria and not contract.get("gaps"):
            contract["gaps"] = [self._gap_from_criterion(weak_criteria[0])]
        if strong_criteria and not contract.get("strengths"):
            contract["strengths"] = [self._strength_from_criterion(strong_criteria[0])]
        if weak_criteria and not contract.get("recommendations"):
            contract["recommendations"] = [self._recommendation_from_criterion(weak_criteria[0])]
        if not contract.get("evidence_fragments"):
            fragments = []
            if weak_criteria:
                fragments.append(self._evidence_fragment_from_criterion(weak_criteria[0], "missed_opportunity"))
            if strong_criteria:
                fragments.append(self._evidence_fragment_from_criterion(strong_criteria[0], "good_example"))
            contract["evidence_fragments"] = fragments[:3]

    @staticmethod
    def _is_sales_relevant_contract(contract: dict[str, Any]) -> bool:
        classification = dict(contract.get("classification") or {})
        if classification.get("analysis_eligibility") == "not_eligible":
            return False
        return str(classification.get("call_type") or "") in SALES_RELEVANT_CALL_TYPES

    def _apply_analysis_eligibility_guardrails(self, contract: dict[str, Any]) -> None:
        """Keep post-LLM eligibility consistent with deterministic scoring evidence."""
        classification = contract.setdefault("classification", {})
        call_type = str(classification.get("call_type") or "").strip()
        eligibility = str(classification.get("analysis_eligibility") or "").strip()
        duration_sec = self._contract_duration_sec(contract)

        if call_type in NON_COACHABLE_CALL_TYPES:
            classification["analysis_eligibility"] = "not_eligible"
            classification["eligibility_reason"] = (
                classification.get("eligibility_reason")
                or NOT_COACHABLE_ANALYSIS_REASON
            )
            self._zero_checklist_score_for_not_eligible(contract)
            return

        if call_type not in SALES_RELEVANT_CALL_TYPES:
            return

        has_positive_sales_evidence = self._has_positive_sales_scoring_evidence(contract)
        if eligibility == "not_eligible":
            if has_positive_sales_evidence:
                classification["analysis_eligibility"] = "eligible"
                classification["eligibility_reason"] = self._eligible_reason_for_duration(duration_sec)
            else:
                self._zero_checklist_score_for_not_eligible(contract)
            return

        if eligibility != "eligible":
            return

        reason = str(classification.get("eligibility_reason") or "")
        if "duration_ge_180_sec" in reason and (
            duration_sec is None or duration_sec < settings.calls_min_duration_sec
        ):
            classification["eligibility_reason"] = self._eligible_reason_for_duration(duration_sec)

    @staticmethod
    def _contract_duration_sec(contract: dict[str, Any]) -> int | None:
        duration = dict(contract.get("call") or {}).get("duration_sec")
        try:
            return int(duration)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _has_positive_sales_scoring_evidence(contract: dict[str, Any]) -> bool:
        checklist = dict(dict(contract.get("score") or {}).get("checklist_score") or {})
        try:
            score_percent = float(checklist.get("score_percent") or 0.0)
        except (TypeError, ValueError):
            score_percent = 0.0
        if score_percent <= 0:
            return False
        if contract.get("strengths") or contract.get("gaps") or contract.get("recommendations"):
            return True
        if contract.get("evidence_fragments"):
            return True
        for stage in contract.get("score_by_stage") or []:
            for criterion in stage.get("criteria_results") or []:
                if not isinstance(criterion, dict):
                    continue
                if str(criterion.get("comment") or "").strip():
                    return True
                if str(criterion.get("evidence") or "").strip():
                    return True
        return False

    @staticmethod
    def _eligible_reason_for_duration(duration_sec: int | None) -> str:
        if duration_sec is not None and duration_sec >= settings.calls_min_duration_sec:
            return "duration_ge_180_sec_and_sales_relevant"
        return "positive_sales_score_with_sales_evidence"

    @staticmethod
    def _zero_checklist_score_for_not_eligible(contract: dict[str, Any]) -> None:
        checklist_score = contract.setdefault("score", {}).setdefault("checklist_score", {})
        checklist_score["total_points"] = 0
        checklist_score["max_points"] = 0
        checklist_score["score_percent"] = 0.0
        checklist_score["level"] = "problematic"

    @staticmethod
    def _collect_reportable_criteria(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        weak: list[dict[str, Any]] = []
        strong: list[dict[str, Any]] = []
        for stage in contract.get("score_by_stage") or []:
            for criterion in stage.get("criteria_results") or []:
                if not isinstance(criterion, dict):
                    continue
                score = int(criterion.get("score") or 0)
                max_score = int(criterion.get("max_score") or 0)
                evidence = str(criterion.get("evidence") or "").strip()
                comment = str(criterion.get("comment") or "").strip()
                if not max_score or not (evidence or comment):
                    continue
                enriched = dict(criterion)
                enriched["_stage_name"] = stage.get("stage_name")
                if score < max_score:
                    weak.append(enriched)
                elif score == max_score:
                    strong.append(enriched)
        weak.sort(key=lambda item: int(item.get("score") or 0))
        return weak, strong

    @staticmethod
    def _gap_from_criterion(criterion: dict[str, Any]) -> dict[str, Any]:
        criterion_name = str(criterion.get("criterion_name") or "Зона роста").strip()
        comment = str(criterion.get("comment") or "").strip()
        evidence = str(criterion.get("evidence") or "").strip() or None
        return {
            "title": criterion_name,
            "evidence": evidence,
            "impact": comment or "Этот момент снижает управляемость следующего шага в разговоре.",
            "criterion_code": criterion.get("criterion_code"),
            "criterion_name": criterion_name,
        }

    @staticmethod
    def _strength_from_criterion(criterion: dict[str, Any]) -> dict[str, Any]:
        criterion_name = str(criterion.get("criterion_name") or "Сильная сторона").strip()
        comment = str(criterion.get("comment") or "").strip()
        evidence = str(criterion.get("evidence") or "").strip() or None
        return {
            "title": criterion_name,
            "evidence": evidence,
            "impact": comment or "Этот приём помогает сделать разговор понятнее для клиента.",
            "criterion_code": criterion.get("criterion_code"),
            "criterion_name": criterion_name,
        }

    def _recommendation_from_criterion(self, criterion: dict[str, Any]) -> dict[str, Any]:
        criterion_name = str(criterion.get("criterion_name") or "Зона роста").strip()
        comment = str(criterion.get("comment") or "").strip()
        evidence = str(criterion.get("evidence") or "").strip()
        return {
            "priority": "high" if int(criterion.get("score") or 0) == 0 else "medium",
            "problem": criterion_name,
            "why_it_matters": comment or "Без этого клиенту сложнее понять ценность и следующий шаг.",
            "better_phrase": self._better_phrase_for_criterion(criterion),
            "criterion_code": criterion.get("criterion_code"),
            "criterion_name": criterion_name,
            "evidence": evidence or None,
        }

    @staticmethod
    def _evidence_fragment_from_criterion(criterion: dict[str, Any], fragment_type: str) -> dict[str, Any]:
        comment = str(criterion.get("comment") or "").strip()
        evidence = str(criterion.get("evidence") or "").strip() or None
        return {
            "fragment_type": fragment_type,
            "client_text": None,
            "manager_text": evidence,
            "why": comment or str(criterion.get("criterion_name") or "").strip(),
            "better_variant": None,
        }

    @staticmethod
    def _better_phrase_for_criterion(criterion: dict[str, Any]) -> str:
        criterion_code = str(criterion.get("criterion_code") or "").strip()
        phrases = {
            "cs_permission_and_relevance": "Удобно сейчас коротко обсудить вопрос, или лучше вернуться в другое время?",
            "cs_reason_for_call": "Коротко обозначу, зачем звоню: хочу понять вашу ситуацию и предложить следующий полезный шаг.",
            "qp_current_process": "Подскажите, как сейчас у вас устроен этот процесс и где чаще всего возникают задержки?",
            "qp_role_and_scope": "Подскажите, какую роль вы сами играете в этом процессе и кто ещё влияет на решение?",
            "qp_need_or_trigger": "Что сейчас стало причиной интереса к этому вопросу, и насколько это актуально для вас?",
            "nd_use_cases": "Какие документы или сценарии для вас самые частые и самые трудоёмкие?",
            "nd_pain_and_constraints": "Что в текущем процессе больше всего мешает: скорость, контроль, ошибки или согласование?",
            "nd_priority_and_timing": "Когда вам важно решить этот вопрос и что будет критерием успешного результата?",
            "nd_decision_context": "Кто ещё участвует в решении, и как обычно принимается такое решение?",
            "pr_value_linked_to_context": "Если смотреть именно на ваш процесс, основная польза будет в том, что...",
            "pr_clarity_and_examples": "Покажу на простом примере, как это будет выглядеть для вашей задачи.",
            "oh_clarify_reason": "Правильно понимаю, главное сомнение сейчас в сроках, стоимости или сложности перехода?",
            "oh_reframe_with_value": "Понимаю сомнение. Давайте свяжем это с вашей задачей: для вас это может снять...",
            "oh_check_remaining_concern": "Этот вариант снимает ваш основной вопрос, или осталось ещё что-то важное?",
            "cn_fixed_next_step": "Давайте зафиксируем следующий шаг: я сделаю ..., а мы вернёмся к разговору ...",
            "cn_owner_and_deadline": "Кто со стороны клиента будет смотреть этот вопрос и к какому времени удобно вернуться?",
            "cn_recap_and_confirmation": "Подытожу: договорились о ..., следующий шаг ..., верно?",
        }
        return phrases.get(
            criterion_code,
            "Давайте уточним этот момент и сразу закрепим понятный следующий шаг.",
        )

    def _populate_checklist_score(self, contract: dict[str, Any]) -> None:
        """Recompute checklist score aggregates from normalized stage rows."""
        stages = contract.get("score_by_stage") or []
        total_points = sum(self._score_int(stage.get("stage_score")) for stage in stages)
        max_points = sum(self._score_int(stage.get("max_stage_score")) for stage in stages)
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
