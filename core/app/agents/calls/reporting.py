"""Manual reporting pilot orchestration for bounded report runs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.agents.calls.analysis_purpose import is_controlled_analysis
from app.agents.calls.analyzer import (
    APPROVED_CHECKLIST_VERSION,
    CallsAnalyzer,
    SEMANTIC_EMPTY_ANALYSIS_REASON,
)
from app.agents.calls.call_breakdown_composer import compose_call_breakdown_from_situation
from app.agents.calls.bitrix_readonly import Bitrix24ReadOnlyClient, BitrixReadOnlyError
from app.agents.calls.config import calls_config
from app.agents.calls.delivery import CallsDelivery
from app.agents.calls.extractor import CallsExtractor
from app.agents.calls.intake import OnlinePBXIntake
from app.agents.calls.orchestrator import (
    CallsManualPilotOrchestrator,
    analysis_contract_failure_reason,
)
from app.agents.calls.report_block_router import route_evidence_items
from app.agents.calls.report_evidence_registry import (
    build_report_evidence_registry,
    report_evidence_registry_as_dicts,
)
from app.agents.calls.report_evidence import validate_report_evidence
from app.agents.calls.report_templates import get_active_template_version, render_report_artifact
from app.agents.calls.situation_day_composer import (
    SITUATION_DAY_COMPOSER_VERSION,
    compose_situation_day,
)
from app.agents.calls.situation_day_daily_composer import (
    SITUATION_DAY_DAILY_COMPOSER_VERSION,
    SITUATION_DAY_DAILY_SOURCE,
    compose_daily_situation_day,
)
from app.agents.calls.situation_day_daily_input import build_situation_day_daily_input
from app.agents.calls.situation_day_writer import compose_situation_day_view
from app.agents.calls.voice_of_customer_composer import compose_voice_of_customer
from app.core_shared.db.models import Analysis, Department, Interaction, Manager
from app.core_shared.exceptions import ASAError, DeliveryError, LLMResponseError, SemanticAnalysisError

REPORTING_SCHEMA_VERSION = "manual_reporting_pilot_v1"
REPORTING_LOGIC_VERSION = "manual_reporting_logic_v1"
REPORTING_REUSE_POLICY_VERSION = "manual_reporting_reuse_v3"
REPORTING_MONITORING_EMAIL = "sales@dogovor24.kz"
REPORTING_ALLOWED_MODES = {
    "build_missing_and_report",
    "report_from_ready_data_only",
}
REPORT_DELIVERY_MODES = {
    "preview_only",
    "telegram_test_only",
    "business_email_only",
    "telegram_and_email",
}
SOURCE_AUDIO_UNAVAILABLE_REASON = "source_audio_unavailable"
MANAGER_DAILY_MAX_WINDOW_WORKDAYS = 3
MEANINGFUL_ABSOLUTE_MIN_DURATION_SEC = 15
MEANINGFUL_NO_TRANSCRIPT_MIN_DURATION_SEC = 90
MANAGER_DAILY_FULL_REPORT_MIN_RELEVANT_CALLS = 6
MANAGER_DAILY_FULL_REPORT_MIN_READY_ANALYSES = 5
MANAGER_DAILY_FULL_REPORT_MIN_ANALYSIS_COVERAGE = 75.0
MANAGER_DAILY_SIGNAL_REPORT_MIN_READY_ANALYSES = 2
MANAGER_DAILY_FALLBACK_RECOMMENDATION_TITLE = "Пока недостаточно рекомендаций"
MANAGER_DAILY_FALLBACK_KEY_PROBLEM_TITLE = "Требует уточнения"
MANAGER_DAILY_FALLBACK_KEY_PROBLEM_DESCRIPTION = "Недостаточно данных для выделения одной главной проблемы."
MANAGER_DAILY_DATA_SCOPE_REPORT_DAY = "report_day"
MANAGER_DAILY_DATA_SCOPE_EXPANDED_COACHING_BASE = "expanded_coaching_base"
MANAGER_DAILY_DATA_SCOPE_ROLLING_WINDOW = "rolling_window"
REPORTING_REQUIRED_ANALYSIS_KEYS = (
    "classification",
    "score",
    "score_by_stage",
    "strengths",
    "gaps",
    "recommendations",
    "follow_up",
)
UNCLASSIFIED_REASON_LABELS = {
    "no_transcript": "Нет транскрипта",
    "no_analysis": "Нет готового анализа",
    "analysis_failed": "Анализ завершился ошибкой",
    "analysis_failed_contract": "Ошибка контракта анализа",
    "analysis_failed_provider": "Ошибка провайдера анализа",
    "analysis_failed_unknown": "Анализ завершился ошибкой",
    "analysis_not_reusable": "Анализ не проходит reuse-проверку",
    "not_eligible": "Звонок не подходит для разбора",
    "not_coachable_or_reportable": "Не coaching/reporting-звонок",
    "semantic_empty": "Звонок не подходит для разбора",
    "no_follow_up_outcome": "Нет результата follow-up",
    "cdr_only_probable_live": "CDR-only: вероятный живой разговор",
    "missing_classification": "Нет классификации в анализе",
    "support_or_internal": "Тех/сервис или внутренний звонок",
    "unknown": "Причина не определена",
}
UNCLASSIFIED_MANAGER_STATUS_LABELS = {
    "no_transcript": "Без транскрипта",
    "cdr_only_probable_live": "Без транскрипта",
    "no_analysis": "Без анализа",
    "analysis_failed": "Ошибка анализа",
    "analysis_failed_contract": "Ошибка анализа",
    "analysis_failed_provider": "Ошибка провайдера",
    "analysis_failed_unknown": "Ошибка анализа",
    "analysis_not_reusable": "Не подходит для разбора",
    "not_coachable_or_reportable": "Не подходит для разбора",
    "not_eligible": "Не подходит для разбора",
    "semantic_empty": "Не подходит для разбора",
    "no_follow_up_outcome": "Нет итога",
    "missing_classification": "Нет классификации",
    "support_or_internal": "Тех/сервис",
    "unknown": "Без разбора",
}
UNCLASSIFIED_MANAGER_CONTEXT_LABELS = {
    "no_transcript": "Транскрипт не построен",
    "cdr_only_probable_live": "Транскрипт не построен",
    "no_analysis": "Нет готового анализа",
    "analysis_failed": "Ошибка при анализе",
    "analysis_failed_contract": "Ошибка контракта анализа",
    "analysis_failed_provider": "Ошибка провайдера",
    "analysis_failed_unknown": "Ошибка при анализе",
    "analysis_not_reusable": "Анализ не дал usable результата",
    "not_coachable_or_reportable": "Не подходит для разбора",
    "not_eligible": "Не подходит для разбора",
    "semantic_empty": "Не подходит для разбора",
    "no_follow_up_outcome": "Нет результата follow-up",
    "missing_classification": "Нет классификации",
    "support_or_internal": "Тех/сервис",
    "unknown": "Нет готового разбора",
}
MANAGER_FACING_COMPLETENESS_BLOCKING_BUCKETS = {
    "Без транскрипта",
    "Без анализа",
    "Ошибка анализа",
    "Ошибка провайдера",
}
MANAGER_FACING_COMPLETENESS_REQUIRED_ACTIONS = {
    "Без транскрипта": "Достроить транскрипт перед отправкой менеджеру.",
    "Без анализа": "Достроить анализ перед отправкой менеджеру.",
    "Ошибка анализа": "Проверить техническую ошибку анализа и перезапустить точечно.",
    "Ошибка провайдера": "Проверить provider/quota и перезапустить точечно после устранения.",
}


@dataclass(slots=True)
class ReportRunFilters:
    """Normalized manual filters for one report run."""

    manager_ids: set[str] = field(default_factory=set)
    manager_extensions: set[str] = field(default_factory=set)
    date_from: str = ""
    date_to: str = ""
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None
    force_retry_quota_blocked: bool = False
    include_controlled_samples: bool = False
    analysis_instruction_version: str | None = None


@dataclass(slots=True)
class ProviderErrorInfo:
    """Audit-safe provider error classification for build_missing guardrails."""

    error_class: str
    raw_message: str


@dataclass(slots=True)
class ReportPreset:
    """One supported reporting preset."""

    code: str
    title: str
    recipient_kind: str
    requires_single_day: bool = False


@dataclass(slots=True, frozen=True)
class ReportDeliveryOptions:
    """Explicit report delivery channel selection."""

    mode: str
    send_telegram_test_delivery: bool = False
    send_business_email: bool = False


@dataclass(slots=True)
class ReportArtifact:
    """Persisted artifacts needed for one report call row."""

    interaction: Interaction
    analysis: Analysis | None
    manager: Manager | None
    call_started_at: datetime | None
    original_analysis: Analysis | None = None
    analysis_reuse_reason: str | None = None


@dataclass(slots=True, frozen=True)
class BusinessOutcome:
    """Final manager_daily business outcome for one report-day call row."""

    final_status: str | None
    reason_code: str | None
    evidence: str | None = None
    confidence: str = "medium"
    deadline: str | None = None


class BusinessOutcomeResolver:
    """Resolve manager-facing call outcome from persisted report-day artifacts.

    The resolver is intentionally deterministic and reporting-local. It reads the
    persisted analysis/transcript surface and never changes analyzer eligibility,
    scoring, prompts, selection, or readiness.
    """

    SERVICE_TERMS = (
        "эцп",
        "эцк",
        "qr",
        "нцалейер",
        "ncalayer",
        "nc layer",
        "подписание",
        "подписанный документ",
        "подписать договор",
        "документ не открывается",
        "не можем подписать",
        "модуль договор 24",
        "личный кабинет",
        "личном кабинете",
        "регистрац",
        "активац",
        "парол",
        "техподдерж",
        "техническая поддержка",
        "передам техническую",
        "передать ваш номер в техническую",
        "помогут найти подписанный документ",
        "дальнейшие действия",
        "ошибка",
        "статус код",
    )
    OFFTOPIC_NO_OUTCOME_TERMS = (
        "chat gpt",
        "чат gpt",
        "чад gpt",
        "искусственного интеллекта",
        "другая компания",
        "белимкласс",
        "блимкласс",
    )
    REFUSAL_TERMS = (
        "не рассматриваем",
        "не рассматривает",
        "не актуально",
        "неактуально",
        "нет необходимости",
        "нет потребности",
        "не интересно",
        "не заинтересован",
        "больше ничего не интересует",
        "уже другой нашли",
        "уже нашли",
        "передумали",
        "нет финансовой возможности",
        "платно пока не рассматриваем",
        "пока нет потребности",
        "пока нет необходимости",
        "пока не планируете",
    )
    AGREEMENT_TERMS = (
        "zoom",
        "зум",
        "встреч",
        "демо",
        "презентац",
        "выставить счет",
        "выставляйте счет",
        "счет на whatsapp",
        "счёт на whatsapp",
        "счет выстав",
        "счёт выстав",
        "подключен",
        "до встречи",
    )
    WEAK_CONTINUATION_TERMS = (
        "скиньте",
        "отправьте",
        "на whatsapp",
        "на ватсап",
        "посмотрю",
        "подумаем",
        "совет",
        "перезвоню",
        "может быть",
        "возможно",
        "обратной связи",
        "напоминайте",
        "напишите",
    )
    RESCHEDULE_TERMS = (
        "после праздников",
        "в конце года",
        "в следующем году",
        "позже",
        "сейчас нет времени",
        "сейчас занят",
        "сейчас занято",
        "после согласования",
        "после просмотра",
    )

    def resolve(self, artifact: ReportArtifact) -> BusinessOutcome:
        """Return the final business outcome for a manager_daily call row."""
        transcript = self._normalize(getattr(artifact.interaction, "text", "") or "")
        source_analysis = artifact.analysis or artifact.original_analysis
        detail = dict((getattr(source_analysis, "scores_detail", None) or {}) if source_analysis is not None else {})
        follow_up = dict(detail.get("follow_up") or {})
        classification = dict(detail.get("classification") or {})
        call_type = str(classification.get("call_type") or "").strip().lower()
        eligibility = str(classification.get("analysis_eligibility") or "").strip().lower()
        failure_reason = (
            _classify_failed_analysis_reason(artifact.original_analysis, artifact.analysis_reuse_reason)
            if artifact.original_analysis is not None and bool(getattr(artifact.original_analysis, "is_failed", False))
            else None
        )

        blocker = self._technical_blocker(
            artifact=artifact,
            transcript=transcript,
            source_analysis=source_analysis,
            failure_reason=failure_reason,
        )
        if blocker is not None:
            return blocker

        text = self._combined_text(
            transcript=transcript,
            classification=classification,
            follow_up=follow_up,
            detail=detail,
        )
        grounded_text = self._grounded_outcome_text(
            transcript=transcript,
            classification=classification,
            follow_up=follow_up,
        )
        deadline = _format_iso_deadline(
            str(follow_up.get("due_date_text") or follow_up.get("due_date_iso") or "").strip() or None
        )

        tech = self._resolve_tech_service(text=text, call_type=call_type)
        if tech is not None:
            return tech

        refusal = self._resolve_refusal(text=grounded_text, follow_up=follow_up)
        if refusal is not None:
            return refusal

        agreed = self._resolve_agreement(text=text, follow_up=follow_up, deadline=deadline)
        if agreed is not None:
            return agreed

        rescheduled = self._resolve_rescheduled(text=text, follow_up=follow_up, deadline=deadline)
        if rescheduled is not None:
            return rescheduled

        off_topic = self._resolve_offtopic_no_outcome(text=text)
        if off_topic is not None:
            return off_topic

        open_outcome = self._resolve_open(text=text, follow_up=follow_up, call_type=call_type, deadline=deadline)
        if open_outcome is not None:
            return open_outcome

        if failure_reason in {"semantic_empty", "not_coachable_or_reportable"}:
            return BusinessOutcome(
                final_status=None,
                reason_code=failure_reason,
                evidence=self._evidence(text, ()),
                confidence="high" if failure_reason == "semantic_empty" else "medium",
            )
        if eligibility in {"not_eligible", "not_coachable", "not_reportable", "not_coachable_or_reportable"}:
            return BusinessOutcome(
                final_status=None,
                reason_code="not_coachable_or_reportable",
                evidence=self._evidence(text, ()),
                confidence="medium",
            )
        if not classification or not call_type:
            return BusinessOutcome(final_status=None, reason_code="missing_classification", confidence="medium")
        if not follow_up:
            return BusinessOutcome(final_status=None, reason_code="no_follow_up_outcome", confidence="medium")
        return BusinessOutcome(final_status="open", reason_code="open_fallback", confidence="low", deadline=deadline)

    def _technical_blocker(
        self,
        *,
        artifact: ReportArtifact,
        transcript: str,
        source_analysis: Any,
        failure_reason: str | None,
    ) -> BusinessOutcome | None:
        if not transcript:
            reason_code = "no_transcript" if getattr(artifact.interaction, "raw_ref", None) else "cdr_only_probable_live"
            if not _is_cdr_only_probable_live(artifact):
                reason_code = "no_transcript"
            return BusinessOutcome(final_status=None, reason_code=reason_code, confidence="high")
        if source_analysis is None:
            return BusinessOutcome(final_status=None, reason_code="no_analysis", confidence="high")
        if failure_reason in {"analysis_failed_contract", "analysis_failed_provider", "analysis_failed_unknown"}:
            return BusinessOutcome(final_status=None, reason_code=failure_reason, confidence="high")
        return None

    def _resolve_tech_service(self, *, text: str, call_type: str) -> BusinessOutcome | None:
        service_hit = self._find_first(text, self.SERVICE_TERMS)
        if not service_hit:
            return None
        actual_service_hit = self._find_first(
            text,
            (
                "qr",
                "нцалейер",
                "ncalayer",
                "nc layer",
                "не можем подписать",
                "документ не открывается",
                "модуль договор 24",
                "личный кабинет",
                "парол",
                "регистрац",
                "активац",
                "передам техническую",
                "передать ваш номер в техническую",
                "помогут найти подписанный документ",
                "дальнейшие действия",
                "ошибка",
                "статус код",
            ),
        )
        if (
            call_type in {"support", "internal"}
            or actual_service_hit is not None
        ):
            if self._contains_any(text, self.OFFTOPIC_NO_OUTCOME_TERMS) and not self._contains_any(
                text,
                ("подписание", "подписанный документ", "договор 24", "личный кабинет", "парол", "активац"),
            ):
                return None
            return BusinessOutcome(
                final_status="tech_service",
                reason_code="business_outcome_tech_service",
                evidence=self._evidence(text, (service_hit,)),
                confidence="high",
            )
        return None

    def _resolve_refusal(self, *, text: str, follow_up: dict[str, Any]) -> BusinessOutcome | None:
        refusal_hit = self._find_first(text, self.REFUSAL_TERMS)
        if refusal_hit:
            return BusinessOutcome(
                final_status="refusal",
                reason_code="business_outcome_refusal",
                evidence=self._evidence(text, (refusal_hit,)),
                confidence="high",
            )
        reason = self._normalize(str(follow_up.get("reason_not_fixed") or ""))
        if self._contains_any(reason, ("отказ", "не проявил интерес", "не заинтересован", "клиент не заинтересован")):
            return BusinessOutcome(
                final_status="refusal",
                reason_code="business_outcome_refusal_follow_up",
                evidence=str(follow_up.get("reason_not_fixed") or "").strip() or None,
                confidence="medium",
            )
        if "все устраивает" in text and self._contains_any(text, ("не рассматриваем", "не рассматриваете")):
            return BusinessOutcome(
                final_status="refusal",
                reason_code="business_outcome_refusal_satisfied_no_alternative",
                evidence=self._evidence(text, ("все устраивает", "не рассматриваем")),
                confidence="high",
            )
        return None

    def _resolve_agreement(
        self,
        *,
        text: str,
        follow_up: dict[str, Any],
        deadline: str | None,
    ) -> BusinessOutcome | None:
        next_text = self._normalize(str(follow_up.get("next_step_text") or ""))
        next_type = self._normalize(str(follow_up.get("next_step_type") or ""))
        combined = " ".join(part for part in (text, next_text, next_type) if part)
        agreement_hit = self._find_first(combined, self.AGREEMENT_TERMS)
        if agreement_hit:
            return BusinessOutcome(
                final_status="agreed",
                reason_code="business_outcome_agreed_commercial_step",
                evidence=self._evidence(combined, (agreement_hit,)),
                confidence="high",
                deadline=deadline,
            )
        if follow_up.get("next_step_fixed") and self._contains_any(
            combined,
            ("покуп", "подключ", "подписк", "коммерческое предложение", "кп", "созвон", "обсудить"),
        ) and not self._contains_any(combined, self.WEAK_CONTINUATION_TERMS):
            return BusinessOutcome(
                final_status="agreed",
                reason_code="business_outcome_agreed_structured_follow_up",
                evidence=str(follow_up.get("next_step_text") or "").strip() or None,
                confidence="medium",
                deadline=deadline,
            )
        return None

    def _resolve_offtopic_no_outcome(self, *, text: str) -> BusinessOutcome | None:
        if self._contains_any(text, self.OFFTOPIC_NO_OUTCOME_TERMS) and not self._contains_any(
            text,
            (
                "подписанный документ",
                "подписание",
                "личный кабинет",
                "парол",
                "активац",
                "техподдерж",
                "техническая поддержка",
                "коммерческое предложение",
                "счет",
                "счёт",
                "встреч",
                "zoom",
                "зум",
            ),
        ):
            return BusinessOutcome(
                final_status=None,
                reason_code="not_coachable_or_reportable",
                evidence=self._evidence(text, self.OFFTOPIC_NO_OUTCOME_TERMS),
                confidence="high",
            )
        return None

    def _resolve_rescheduled(
        self,
        *,
        text: str,
        follow_up: dict[str, Any],
        deadline: str | None,
    ) -> BusinessOutcome | None:
        combined = " ".join(
            part
            for part in (
                text,
                self._normalize(str(follow_up.get("next_step_text") or "")),
                self._normalize(str(follow_up.get("reason_not_fixed") or "")),
            )
            if part
        )
        reschedule_hit = self._find_first(combined, self.RESCHEDULE_TERMS)
        if reschedule_hit:
            return BusinessOutcome(
                final_status="rescheduled",
                reason_code="business_outcome_rescheduled",
                evidence=self._evidence(combined, (reschedule_hit,)),
                confidence="high",
                deadline=deadline,
            )
        return None

    def _resolve_open(
        self,
        *,
        text: str,
        follow_up: dict[str, Any],
        call_type: str,
        deadline: str | None,
    ) -> BusinessOutcome | None:
        combined = " ".join(
            part
            for part in (
                text,
                self._normalize(str(follow_up.get("next_step_text") or "")),
                self._normalize(str(follow_up.get("reason_not_fixed") or "")),
            )
            if part
        )
        open_hit = self._find_first(combined, self.WEAK_CONTINUATION_TERMS)
        if open_hit:
            return BusinessOutcome(
                final_status="open",
                reason_code="business_outcome_open_follow_up",
                evidence=self._evidence(combined, (open_hit,)),
                confidence="high",
                deadline=deadline,
            )
        if call_type in {"sales", "sales_primary", "follow_up", "follow-up"}:
            return BusinessOutcome(
                final_status="open",
                reason_code="business_outcome_open_sales_contact",
                evidence=str(follow_up.get("reason_not_fixed") or follow_up.get("next_step_text") or "").strip()
                or self._evidence(combined, ()),
                confidence="medium",
                deadline=deadline,
            )
        return None

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.replace("ё", "е").strip().lower())

    @classmethod
    def _contains_any(cls, text: str, tokens: tuple[str, ...]) -> bool:
        return any(cls._normalize(token) in text for token in tokens)

    @classmethod
    def _find_first(cls, text: str, tokens: tuple[str, ...]) -> str | None:
        for token in tokens:
            normalized = cls._normalize(token)
            if normalized in text:
                return normalized
        return None

    @classmethod
    def _combined_text(
        cls,
        *,
        transcript: str,
        classification: dict[str, Any],
        follow_up: dict[str, Any],
        detail: dict[str, Any],
    ) -> str:
        parts: list[str] = [transcript]
        parts.extend(str(value or "") for value in classification.values())
        parts.extend(str(value or "") for value in follow_up.values())
        for key in ("strengths", "gaps", "recommendations", "product_signals", "evidence_fragments"):
            value = detail.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        parts.extend(str(child or "") for child in item.values())
                    else:
                        parts.append(str(item or ""))
        return cls._normalize(" ".join(parts))

    @classmethod
    def _grounded_outcome_text(
        cls,
        *,
        transcript: str,
        classification: dict[str, Any],
        follow_up: dict[str, Any],
    ) -> str:
        parts: list[str] = [transcript]
        parts.extend(str(value or "") for value in classification.values())
        parts.extend(str(value or "") for value in follow_up.values())
        return cls._normalize(" ".join(parts))

    @classmethod
    def _evidence(cls, text: str, tokens: tuple[str, ...]) -> str | None:
        normalized_tokens = [cls._normalize(token) for token in tokens if token]
        indexes = [text.find(token) for token in normalized_tokens if token and text.find(token) >= 0]
        if not indexes:
            return text[:240].strip() or None
        start = max(0, min(indexes) - 90)
        end = min(len(text), min(indexes) + 180)
        return text[start:end].strip() or None


def classify_provider_error(error: BaseException | str) -> ProviderErrorInfo:
    """Classify provider-facing errors without exposing secrets."""
    raw = str(error or "").strip()
    text = raw.lower()
    if "insufficient_quota" in text or ("429" in text and "quota" in text):
        return ProviderErrorInfo(error_class="quota_insufficient", raw_message=raw)
    if "rate_limit" in text or "rate limited" in text or ("429" in text and "quota" not in text):
        return ProviderErrorInfo(error_class="rate_limited", raw_message=raw)
    if any(token in text for token in ("401", "403", "unauthorized", "forbidden", "invalid_api_key", "incorrect api key")):
        return ProviderErrorInfo(error_class="auth_error", raw_message=raw)
    if any(token in text for token in ("timeout", "timed out", "readtimeout", "connecttimeout")):
        return ProviderErrorInfo(error_class="provider_timeout", raw_message=raw)
    if re.search(r"\b5\d\d\b", text) or any(token in text for token in ("server error", "bad gateway", "service unavailable")):
        return ProviderErrorInfo(error_class="provider_5xx", raw_message=raw)
    return ProviderErrorInfo(error_class="unknown_provider_error", raw_message=raw)


def _previous_quota_blocker(interaction: Interaction) -> dict[str, Any] | None:
    """Return previous quota failure marker for an interaction, if any."""
    metadata = dict(getattr(interaction, "metadata_", None) or {})
    failure = metadata.get("last_provider_failure")
    if not isinstance(failure, dict):
        return None
    if failure.get("type") == "quota_blocked" or failure.get("error_class") == "quota_insufficient":
        return dict(failure)
    return None


def _onlinepbx_canonical_call_id(interaction: Interaction) -> str | None:
    """Return a persisted OnlinePBX call uuid that can refresh recording URLs."""
    source = str(getattr(interaction, "source", "") or "").strip().lower()
    metadata = dict(getattr(interaction, "metadata_", None) or {})
    external_id = str(getattr(interaction, "external_id", "") or "").strip()
    external_call_code = str(metadata.get("external_call_code") or "").strip()
    has_onlinepbx_metadata = bool(external_call_code) or source == "onlinepbx"
    if source and source != "onlinepbx" and not has_onlinepbx_metadata:
        return None
    return external_id or external_call_code or None


def _should_refresh_onlinepbx_audio_url(interaction: Interaction) -> bool:
    """Return whether build_missing should refresh a bounded OnlinePBX audio URL."""
    if not _onlinepbx_canonical_call_id(interaction):
        return False
    raw_ref = str(getattr(interaction, "raw_ref", "") or "")
    if not raw_ref:
        return True
    raw_lower = raw_ref.lower()
    metadata = dict(getattr(interaction, "metadata_", None) or {})
    diagnostic_text = " ".join(
        str(value or "")
        for value in (
            getattr(interaction, "error_message", None),
            metadata.get(SOURCE_AUDIO_UNAVAILABLE_REASON),
            metadata.get("last_audio_source_failure"),
        )
    ).lower()
    if "key_is_expired" in diagnostic_text:
        return True
    if "api2.onlinepbx" in raw_lower and "/calls-records/download/" in raw_lower:
        return True
    return False


def _extract_quota_blocker(*, build_summary: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
    """Return the structured quota blocker from a run summary/errors."""
    blocker = build_summary.get("quota_blocker")
    if isinstance(blocker, dict) and blocker:
        return dict(blocker)
    if any(item.startswith("quota_blocked_previous_run:") for item in errors):
        return {
            "type": "quota_blocked",
            "stage": "provider",
            "error_class": "quota_insufficient",
            "message": "Previous provider insufficient_quota marker blocked automatic retry.",
        }
    if any("insufficient_quota" in item for item in errors):
        return {
            "type": "quota_blocked",
            "stage": "provider",
            "error_class": "quota_insufficient",
            "message": "Provider returned insufficient_quota. Further billable calls were stopped.",
        }
    return None


@dataclass(slots=True, frozen=True)
class ManagerDailyWindow:
    """One candidate rolling window for manager_daily readiness."""

    workdays_used: int
    period: dict[str, str]
    included_days: tuple[str, ...]


def resolve_report_preset(code: str) -> ReportPreset:
    """Return the bounded preset config for the requested code."""
    normalized = code.strip().lower()
    presets = {
        "manager_daily": ReportPreset(
            code="manager_daily",
            title="Ежедневный разбор звонков",
            recipient_kind="manager",
            requires_single_day=True,
        ),
        "rop_weekly": ReportPreset(
            code="rop_weekly",
            title="Еженедельный отчёт",
            recipient_kind="rop",
        ),
    }
    preset = presets.get(normalized)
    if preset is None:
        supported = ", ".join(sorted(presets))
        raise ASAError(f"Unsupported report preset '{code}'. Supported presets: {supported}.")
    return preset


def resolve_report_delivery_options(
    *,
    delivery_mode: str | None = None,
    send_email: bool = False,
    send_telegram_test: bool = False,
) -> ReportDeliveryOptions:
    """Resolve explicit delivery flags into one safe channel matrix."""
    normalized = str(delivery_mode or "").strip().lower().replace("-", "_")
    if normalized in {"", "none"}:
        if send_telegram_test and send_email:
            normalized = "telegram_and_email"
        elif send_telegram_test:
            normalized = "telegram_test_only"
        elif send_email:
            normalized = "business_email_only"
        else:
            normalized = "preview_only"
    elif normalized in {"no_delivery", "no_delivery_preview", "preview", "preview_only"}:
        normalized = "preview_only"
    if normalized not in REPORT_DELIVERY_MODES:
        allowed = ", ".join(sorted(REPORT_DELIVERY_MODES))
        raise ASAError(f"Unsupported delivery_mode '{delivery_mode}'. Supported modes: {allowed}.")
    return ReportDeliveryOptions(
        mode=normalized,
        send_telegram_test_delivery=normalized in {"telegram_test_only", "telegram_and_email"},
        send_business_email=normalized in {"business_email_only", "telegram_and_email"},
    )


class CallsManualReportingOrchestrator:
    """Build bounded manual reports from persisted call artifacts."""

    def __init__(self, department_id: str, db: Session):
        self.department_id = UUID(department_id)
        self.db = db
        self.intake = OnlinePBXIntake(department_id=department_id, db=db)
        self.extractor = CallsExtractor(department_id=department_id, db=db)
        self.analyzer = CallsAnalyzer(department_id=department_id, db=db)
        self.delivery = CallsDelivery(department_id=department_id, db=db)
        self.call_orchestrator = CallsManualPilotOrchestrator(
            department_id=department_id,
            db=db,
        )

    async def run_report(
        self,
        *,
        preset_code: str,
        mode: str,
        filters: ReportRunFilters,
        model_override: str | None = None,
        send_email: bool = False,
        delivery_mode: str | None = None,
        send_telegram_test: bool = False,
    ) -> dict[str, Any]:
        """Execute one bounded manual reporting run."""
        preset = resolve_report_preset(preset_code)
        delivery_options = resolve_report_delivery_options(
            delivery_mode=delivery_mode,
            send_email=send_email,
            send_telegram_test=send_telegram_test,
        )
        normalized_mode = mode.strip().lower()
        if normalized_mode not in REPORTING_ALLOWED_MODES:
            allowed = ", ".join(sorted(REPORTING_ALLOWED_MODES))
            raise ASAError(f"Unsupported report mode '{mode}'. Supported modes: {allowed}.")
        filters.analysis_instruction_version = _normalize_analysis_instruction_version(
            filters.analysis_instruction_version
        )

        period = self._build_period(filters=filters, preset=preset)
        source_period = period
        manager_daily_windows: list[ManagerDailyWindow] = []
        if preset.code == "manager_daily":
            manager_daily_windows = self._build_manager_daily_windows(anchor_day=period["date_from"])
            source_period = manager_daily_windows[-1].period
        diagnostics_context = self._collect_run_diagnostics_context(
            preset=preset,
            mode=normalized_mode,
            filters=filters,
            period=source_period,
        )
        execution_model = self._resolve_execution_model(preset=preset)
        source_summary = self._empty_source_summary(period=source_period, execution_model=execution_model)
        source_discovery_errors: list[str] = []
        if self._allows_source_discovery(preset=preset):
            try:
                source_summary = self._discover_and_persist_source_calls(
                    filters=filters,
                    period=source_period,
                    mode=normalized_mode,
                )
                source_summary["execution_model"] = execution_model
            except ASAError as exc:
                error_token = f"source_discovery_failed:{exc}"
                if normalized_mode == "report_from_ready_data_only":
                    # Non-fatal in ready-only mode: report from whatever is already persisted.
                    source_discovery_errors.append(error_token)
                else:
                    return self._build_terminal_run_result(
                        preset=preset,
                        mode=normalized_mode,
                        period=period,
                        source_period=source_period,
                        diagnostics_context=diagnostics_context,
                        filters=filters,
                        source_summary=self._empty_source_summary(period=source_period, execution_model=execution_model),
                        build_summary=self._empty_build_summary(),
                        reports=[],
                        selected_interactions_count=0,
                        final_selected_interactions_count=0,
                        overall_status="blocked",
                        errors=[error_token],
                        artifacts=[],
                        delivery_options=delivery_options,
                    )
        interactions = self._select_interactions(filters=filters, period=source_period)
        if not interactions:
            if preset.code == "manager_daily":
                shell_report = self._build_manager_daily_empty_state_result(
                    status="no_data",
                    artifacts=[],
                    period=period,
                    filters=filters,
                    mode=normalized_mode,
                    model_override=model_override,
                    delivery_options=delivery_options,
                    reason_codes=["no_interactions_for_selected_filters"],
                    relevant_calls=0,
                    ready_analyses=0,
                    analysis_coverage=0.0,
                    missing=["no_interactions_for_selected_filters"],
                    readiness=None,
                )
                return self._build_terminal_run_result(
                    preset=preset,
                    mode=normalized_mode,
                    period=period,
                    source_period=source_period,
                    diagnostics_context=diagnostics_context,
                    filters=filters,
                    source_summary=source_summary,
                    build_summary=self._empty_build_summary(),
                    reports=[shell_report],
                    selected_interactions_count=0,
                    final_selected_interactions_count=0,
                    overall_status="no_data",
                    errors=["no_interactions_for_selected_filters"],
                    artifacts=[],
                    delivery_options=delivery_options,
                )
            return self._build_terminal_run_result(
                preset=preset,
                mode=normalized_mode,
                period=period,
                source_period=source_period,
                diagnostics_context=diagnostics_context,
                filters=filters,
                source_summary=source_summary,
                build_summary=self._empty_build_summary(),
                reports=[],
                selected_interactions_count=0,
                final_selected_interactions_count=0,
                overall_status="no_data",
                errors=["no_interactions_for_selected_filters"],
                artifacts=[],
                delivery_options=delivery_options,
            )

        artifacts, build_summary, build_errors = await self._prepare_artifacts(
            interactions=interactions,
            preset=preset,
            mode=normalized_mode,
            force_retry_quota_blocked=filters.force_retry_quota_blocked,
            include_controlled_samples=filters.include_controlled_samples,
            analysis_instruction_version=filters.analysis_instruction_version,
        )

        reports = self._group_and_build_reports(
            preset=preset,
            artifacts=artifacts,
            period=period,
            source_period=source_period,
            filters=filters,
            mode=normalized_mode,
            model_override=model_override,
            delivery_options=delivery_options,
            manager_daily_windows=manager_daily_windows,
        )
        all_errors = [*source_discovery_errors, *build_errors]
        overall_status = self._derive_run_overall_status(reports=reports, build_errors=all_errors)
        return self._build_terminal_run_result(
            preset=preset,
            mode=normalized_mode,
            period=period,
            source_period=source_period,
            diagnostics_context=diagnostics_context,
            filters=filters,
            source_summary=source_summary,
            build_summary=build_summary,
            reports=reports,
            selected_interactions_count=len(interactions),
            final_selected_interactions_count=sum(
                item.get("payload", {}).get("meta", {}).get("source_artifacts", {}).get("interaction_count", 0)
                for item in reports
                if item.get("payload")
            ),
            overall_status=overall_status,
            errors=all_errors,
            send_email=delivery_options.send_business_email,
            artifacts=artifacts,
            delivery_options=delivery_options,
        )

    def _build_terminal_run_result(
        self,
        *,
        preset: ReportPreset,
        mode: str,
        period: dict[str, str],
        source_period: dict[str, str],
        diagnostics_context: dict[str, Any],
        filters: ReportRunFilters,
        source_summary: dict[str, Any],
        build_summary: dict[str, Any],
        reports: list[dict[str, Any]],
        selected_interactions_count: int,
        final_selected_interactions_count: int,
        overall_status: str,
        errors: list[str] | None = None,
        send_email: bool = False,
        artifacts: list[ReportArtifact] | None = None,
        delivery_options: ReportDeliveryOptions | None = None,
    ) -> dict[str, Any]:
        """Build the final structured run response for success and blocked outcomes."""
        quota_blocker = _extract_quota_blocker(build_summary=build_summary, errors=errors or [])
        resolved_delivery_options = delivery_options or resolve_report_delivery_options(send_email=send_email)
        return {
            "status": overall_status,
            "preset": preset.code,
            "mode": mode,
            "period": period,
            "selected_interactions": selected_interactions_count,
            "prepared_artifacts": build_summary,
            "blocker": quota_blocker,
            "processed": {
                "transcripts_built": build_summary.get("transcripts_built", 0),
                "analyses_built": build_summary.get("analyses_built", 0),
                "skipped_due_to_quota": build_summary.get("skipped_due_to_quota", 0),
                "quota_blocked_previous_run": build_summary.get("quota_blocked_previous_run", 0),
            },
            "reports": reports,
            "errors": list(errors or []),
            "observability": self._build_run_observability(
                preset=preset,
                source_summary=source_summary,
                period=period,
                source_period=source_period,
                mode=mode,
                delivery_options=resolved_delivery_options,
                selected_interactions_count=selected_interactions_count,
                build_summary=build_summary,
                reports=reports,
                overall_status=overall_status,
                errors=errors,
                artifacts=artifacts or [],
            ),
            "diagnostics": self._build_run_diagnostics(
                preset=preset,
                mode=mode,
                period=period,
                source_period=source_period,
                filters=filters,
                diagnostics_context=diagnostics_context,
                build_summary=build_summary,
                reports=reports,
                selected_interactions_count=selected_interactions_count,
                final_selected_interactions_count=final_selected_interactions_count,
                overall_status=overall_status,
                source_summary=source_summary,
                errors=errors or [],
            ),
            "delivery_options": {
                "mode": resolved_delivery_options.mode,
                "send_telegram_test_delivery": resolved_delivery_options.send_telegram_test_delivery,
                "send_business_email": resolved_delivery_options.send_business_email,
            },
        }

    @staticmethod
    def _derive_run_overall_status(
        *,
        reports: list[dict[str, Any]],
        build_errors: list[str],
    ) -> str:
        """Collapse report-level results into one run-level status."""
        statuses = {item.get("status") for item in reports}
        if not reports:
            return "blocked" if build_errors else "completed"
        had_success = any(status in {"ready", "delivered", "partial"} for status in statuses)
        had_skip = "skip_accumulate" in statuses
        had_blocking = any(status in {"missing_artifacts", "blocked", "review_required"} for status in statuses) or bool(build_errors)
        if had_success and had_blocking:
            return "partial"
        if had_success:
            return "completed"
        if had_skip and had_blocking:
            return "partial"
        if had_skip:
            return "completed"
        return "blocked"

    @staticmethod
    def _empty_source_summary(*, period: dict[str, str], execution_model: str) -> dict[str, Any]:
        """Return a zeroed source summary for blocked early exits."""
        days_scanned = (date.fromisoformat(period["date_to"]) - date.fromisoformat(period["date_from"])).days + 1
        return {
            "execution_model": execution_model,
            "days_scanned": max(days_scanned, 0),
            "source_records_total": 0,
            "source_raw_calls_total": 0,
            "source_calls_after_ui_filters_total": 0,
            "eligible_source_records_total": 0,
            "targeted_source_records_total": 0,
            "already_persisted_source_records_total": 0,
            "missing_source_records_total": 0,
            "ingest_created_total": 0,
            "ingest_skipped_total": 0,
        }

    @staticmethod
    def _resolve_execution_model(*, preset: ReportPreset) -> str:
        """Return the standing execution model for the selected preset."""
        if preset.code == "manager_daily":
            return "source_aware_full_manual"
        return "persisted_only"

    @classmethod
    def _allows_source_discovery(cls, *, preset: ReportPreset) -> bool:
        """Return True when the preset may perform source discovery and ingest."""
        return cls._resolve_execution_model(preset=preset) == "source_aware_full_manual"

    @classmethod
    def _allows_build_missing(cls, *, preset: ReportPreset, mode: str) -> bool:
        """Return True when the preset may build missing transcript/analysis artifacts."""
        return (
            cls._resolve_execution_model(preset=preset) == "source_aware_full_manual"
            and mode == "build_missing_and_report"
        )

    @staticmethod
    def _empty_build_summary() -> dict[str, int]:
        """Return a zeroed artifact summary for blocked early exits."""
        return {
            "transcripts_built": 0,
            "transcripts_reused": 0,
            "analyses_built": 0,
            "analyses_reused": 0,
            "analyses_rejected_for_reuse": 0,
            "analyses_rejected_for_instruction_version": 0,
            "missing_transcripts_before_build": 0,
            "missing_analyses_before_build": 0,
            "transcript_build_failed": 0,
            "analysis_build_failed": 0,
            "include_controlled_samples": False,
            "analysis_selection_policy": "latest_reusable_stable_excluding_controlled_samples",
            "analysis_instruction_version": None,
            "skipped_due_to_quota": 0,
            "quota_blocked_previous_run": 0,
            "quota_blocker": None,
        }

    def _discover_and_persist_source_calls(
        self,
        *,
        filters: ReportRunFilters,
        period: dict[str, str],
        mode: str,
    ) -> dict[str, int]:
        """Discover source calls for the selected period and persist any missing interactions."""
        source_extensions = self._resolve_source_extensions(filters=filters)
        days_scanned = 0
        records_total = 0
        source_raw_total = 0
        source_after_ui_filters_total = 0
        eligible_total = 0
        targeted_total = 0
        already_persisted_total = 0
        missing_before_ingest_total = 0
        ingest_created_total = 0
        ingest_skipped_total = 0

        for day in self._iter_period_days(period=period):
            days_scanned += 1
            records = self.intake.get_cdr_list(day)
            records_total += len(records)
            source_scoped = [
                record
                for record in records
                if self._record_matches_source_scope(
                    record=record,
                    source_extensions=source_extensions,
                )
            ]
            source_raw_total += len(source_scoped)
            targeted = [
                record
                for record in source_scoped
                if self._record_matches_source_filters(
                    record=record,
                    filters=filters,
                )
            ]
            source_after_ui_filters_total += len(targeted)
            source_build_eligible = [
                record for record in targeted if self._record_is_source_build_eligible(record)
            ]
            eligible_total += len(source_build_eligible)
            targeted_total += len(targeted)
            if not targeted:
                continue

            existing_external_ids = {
                row.external_id
                for row in self.db.query(Interaction.external_id)
                .filter(
                    Interaction.department_id == self.department_id,
                    Interaction.external_id.in_([record.call_id for record in targeted]),
                )
                .all()
            }
            already_persisted_total += len(existing_external_ids)
            missing_before_ingest_total += len(
                [record for record in targeted if record.call_id not in existing_external_ids]
            )

            if mode == "build_missing_and_report":
                for record in targeted:
                    if self._record_is_source_build_eligible(record) and not record.record_url:
                        record.record_url = self.intake.get_recording_url(record.call_id)

            created, skipped = self.intake.save_interactions(targeted)
            ingest_created_total += created
            ingest_skipped_total += skipped

        return {
            "days_scanned": days_scanned,
            "source_records_total": records_total,
            "source_raw_calls_total": source_raw_total,
            "source_calls_after_ui_filters_total": source_after_ui_filters_total,
            "eligible_source_records_total": eligible_total,
            "targeted_source_records_total": targeted_total,
            "already_persisted_source_records_total": already_persisted_total,
            "missing_source_records_total": missing_before_ingest_total,
            "ingest_created_total": ingest_created_total,
            "ingest_skipped_total": ingest_skipped_total,
        }

    @staticmethod
    def _iter_period_days(*, period: dict[str, str]) -> list[str]:
        """Return workday YYYY-MM-DD days inside the selected period (weekends skipped)."""
        current = date.fromisoformat(period["date_from"])
        end = date.fromisoformat(period["date_to"])
        days: list[str] = []
        while current <= end:
            if current.weekday() < 5:
                days.append(current.isoformat())
            current += timedelta(days=1)
        return days

    def _resolve_source_extensions(self, *, filters: ReportRunFilters) -> set[str]:
        """Resolve effective source-side extension filters from manager ids/extensions."""
        extensions = {item.strip() for item in filters.manager_extensions if item.strip()}
        if not filters.manager_ids:
            return extensions
        try:
            manager_ids = {UUID(item) for item in filters.manager_ids}
        except ValueError as exc:
            raise ASAError("manager_ids must contain valid UUID values.") from exc
        rows = (
            self.db.query(Manager)
            .filter(
                Manager.department_id == self.department_id,
                Manager.id.in_(manager_ids),
            )
            .all()
        )
        for row in rows:
            if row.extension:
                extensions.add(str(row.extension).strip())
        return {item for item in extensions if item}

    @staticmethod
    def _record_matches_source_scope(
        *,
        record: Any,
        source_extensions: set[str],
    ) -> bool:
        """Return True when a CDR belongs to the selected source day/manager scope."""
        if source_extensions and str(record.extension or "").strip() not in source_extensions:
            return False
        return True

    @staticmethod
    def _record_matches_source_filters(
        *,
        record: Any,
        filters: ReportRunFilters,
    ) -> bool:
        """Return True when the source record matches explicit UI filters."""
        if filters.min_duration_sec is not None and (record.talk_duration or 0) < filters.min_duration_sec:
            return False
        if filters.max_duration_sec is not None and record.talk_duration is not None:
            if record.talk_duration > filters.max_duration_sec:
                return False
        return True

    def _record_is_source_build_eligible(self, record: Any) -> bool:
        """Return True for source calls that can reasonably enter audio/STT build."""
        return (
            record.status in self.intake.config.allowed_statuses
            and record.direction in self.intake.config.allowed_directions
        )

    def _build_period(self, *, filters: ReportRunFilters, preset: ReportPreset) -> dict[str, str]:
        """Validate and normalize date bounds."""
        if not filters.date_from:
            raise ASAError("Provide date_from for manual report run.")
        date_to = filters.date_to or filters.date_from
        start_date = date.fromisoformat(filters.date_from)
        end_date = date.fromisoformat(date_to)
        if end_date < start_date:
            raise ASAError("date_to must be greater than or equal to date_from.")
        if preset.requires_single_day and start_date != end_date:
            raise ASAError(f"Preset '{preset.code}' currently supports one selected day only.")
        return {
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
        }

    @staticmethod
    def _build_manager_daily_windows(*, anchor_day: str) -> list[ManagerDailyWindow]:
        """Return rolling 1/2/3-workday windows anchored at the requested day."""
        anchor = date.fromisoformat(anchor_day)
        windows: list[ManagerDailyWindow] = []
        for workdays_used in range(1, MANAGER_DAILY_MAX_WINDOW_WORKDAYS + 1):
            included_days = tuple(_last_workdays(anchor=anchor, count=workdays_used))
            windows.append(
                ManagerDailyWindow(
                    workdays_used=workdays_used,
                    period={
                        "date_from": included_days[0],
                        "date_to": included_days[-1],
                    },
                    included_days=included_days,
                )
            )
        return windows

    def _select_interactions(
        self,
        *,
        filters: ReportRunFilters,
        period: dict[str, str],
    ) -> list[Interaction]:
        """Select persisted interactions for the requested period and filters."""
        interactions = (
            self.db.query(Interaction)
            .filter(Interaction.department_id == self.department_id)
            .all()
        )
        start_date = date.fromisoformat(period["date_from"])
        end_date = date.fromisoformat(period["date_to"])
        try:
            manager_ids = {UUID(item) for item in filters.manager_ids}
        except ValueError as exc:
            raise ASAError("manager_ids must contain valid UUID values.") from exc

        selected: list[Interaction] = []
        for interaction in interactions:
            metadata = dict(interaction.metadata_ or {})
            call_started_at = parse_call_started_at(metadata)
            if call_started_at is None:
                continue
            call_day = call_started_at.date()
            if call_day < start_date or call_day > end_date:
                continue
            if filters.min_duration_sec is not None and (
                interaction.duration_sec or 0
            ) < filters.min_duration_sec:
                continue
            if filters.max_duration_sec is not None and interaction.duration_sec is not None:
                if interaction.duration_sec > filters.max_duration_sec:
                    continue
            extension = str(metadata.get("extension") or "").strip()
            if manager_ids and interaction.manager_id not in manager_ids:
                continue
            if filters.manager_extensions and extension not in filters.manager_extensions:
                continue
            selected.append(interaction)
        return sorted(
            selected,
            key=lambda item: parse_call_started_at(dict(item.metadata_ or {}))
            or datetime.min.replace(tzinfo=UTC),
        )

    async def _prepare_artifacts(
        self,
        *,
        interactions: list[Interaction],
        preset: ReportPreset,
        mode: str,
        force_retry_quota_blocked: bool = False,
        include_controlled_samples: bool = False,
        analysis_instruction_version: str | None = None,
    ) -> tuple[list[ReportArtifact], dict[str, Any], list[str]]:
        """Reuse persisted artifacts and optionally build only missing ones."""
        required_analysis_instruction_version = _normalize_analysis_instruction_version(
            analysis_instruction_version
        )
        analyses_by_interaction = self._load_latest_analyses_by_interaction(
            interactions=interactions,
            include_controlled_samples=include_controlled_samples,
            analysis_instruction_version=required_analysis_instruction_version,
        )
        managers_by_id = self._load_managers_by_id(interactions=interactions)

        built_transcripts = 0
        reused_transcripts = 0
        built_analyses = 0
        reused_analyses = 0
        analyses_rejected_for_reuse = 0
        analyses_rejected_for_instruction_version = 0
        missing_transcripts_before_build = 0
        missing_analyses_before_build = 0
        failed_transcripts = 0
        failed_analyses = 0
        skipped_due_to_quota = 0
        quota_blocked_previous_run = 0
        quota_blocker: dict[str, Any] | None = None
        build_errors: list[str] = []
        artifacts: list[ReportArtifact] = []
        for interaction in interactions:
            analysis = analyses_by_interaction.get(interaction.id)
            original_analysis = analysis
            analysis_reuse_reason: str | None = None
            if interaction.text:
                reused_transcripts += 1
            else:
                missing_transcripts_before_build += 1
            reusable_analysis, analysis_reuse_reason = _is_analysis_reusable_for_reporting(
                analysis,
                required_instruction_version=required_analysis_instruction_version,
            )
            if reusable_analysis:
                reused_analyses += 1
            else:
                missing_analyses_before_build += 1
                if analysis is not None:
                    analyses_rejected_for_reuse += 1
                    if _is_instruction_version_mismatch_reason(analysis_reuse_reason):
                        analyses_rejected_for_instruction_version += 1
                    if not (
                        self._allows_build_missing(preset=preset, mode=mode)
                        and interaction.text
                    ):
                        build_errors.append(
                            f"analysis_reuse_rejected:{interaction.id}:{analysis_reuse_reason}"
                        )
                    analysis = None
            if self._allows_build_missing(preset=preset, mode=mode):
                if not interaction.text:
                    if _is_interaction_source_build_eligible(interaction):
                        previous_blocker = _previous_quota_blocker(interaction)
                        if previous_blocker and not force_retry_quota_blocked:
                            quota_blocked_previous_run += 1
                            skipped_due_to_quota += 1
                            build_errors.append(
                                f"quota_blocked_previous_run:{interaction.id}:{previous_blocker.get('stage') or 'provider'}"
                            )
                        elif quota_blocker is not None:
                            skipped_due_to_quota += 1
                            self._record_provider_failure(
                                interaction=interaction,
                                blocker=quota_blocker,
                                error_message="skipped_due_to_quota_current_run",
                            )
                            build_errors.append(
                                f"quota_blocked_current_run:{interaction.id}:{quota_blocker.get('stage') or 'provider'}"
                            )
                        else:
                            refresh_error = self._refresh_source_audio_url_before_transcript_build(
                                interaction=interaction
                            )
                            if refresh_error is not None:
                                failed_transcripts += 1
                                build_errors.append(refresh_error)
                            else:
                                provider_context = self._provider_context_for_layer(
                                    layer="stt",
                                    interaction_id=str(interaction.id),
                                )
                                try:
                                    await self.extractor.process(interaction)
                                    built_transcripts += 1
                                except ASAError as exc:
                                    failed_transcripts += 1
                                    provider_error = classify_provider_error(exc)
                                    if provider_error.error_class == "quota_insufficient":
                                        quota_blocker = self._build_quota_blocker(
                                            stage="stt",
                                            provider_context=provider_context,
                                            error_info=provider_error,
                                        )
                                        self._record_provider_failure(
                                            interaction=interaction,
                                            blocker=quota_blocker,
                                            error_message=str(exc),
                                        )
                                    build_errors.append(f"transcript_build_failed:{interaction.id}:{exc}")
                if (
                    analysis is None or not isinstance(analysis.scores_detail, dict) or not analysis.scores_detail
                ) and interaction.text:
                    previous_blocker = _previous_quota_blocker(interaction)
                    if previous_blocker and not force_retry_quota_blocked:
                        quota_blocked_previous_run += 1
                        skipped_due_to_quota += 1
                        build_errors.append(
                            f"quota_blocked_previous_run:{interaction.id}:{previous_blocker.get('stage') or 'provider'}"
                        )
                    elif quota_blocker is not None:
                        skipped_due_to_quota += 1
                        self._record_provider_failure(
                            interaction=interaction,
                            blocker=quota_blocker,
                            error_message="skipped_due_to_quota_current_run",
                        )
                        build_errors.append(
                            f"quota_blocked_current_run:{interaction.id}:{quota_blocker.get('stage') or 'provider'}"
                        )
                    else:
                        provider_context = self._provider_context_for_layer(
                            layer="llm1",
                            interaction_id=str(interaction.id),
                        )
                        try:
                            result = self.analyzer.analyze_call(interaction)
                            analysis = self.call_orchestrator.persist_analysis(
                                interaction=interaction,
                                result=result,
                            )
                            built_analyses += 1
                            reusable_analysis, analysis_reuse_reason = (
                                _is_analysis_reusable_for_reporting(
                                    analysis,
                                    required_instruction_version=(
                                        required_analysis_instruction_version
                                    ),
                                )
                            )
                            if not reusable_analysis:
                                original_analysis = analysis
                                analyses_rejected_for_reuse += 1
                                if _is_instruction_version_mismatch_reason(analysis_reuse_reason):
                                    analyses_rejected_for_instruction_version += 1
                                analysis = None
                                build_errors.append(
                                    "analysis_reuse_rejected:"
                                    f"{interaction.id}:{analysis_reuse_reason}"
                                )
                        except SemanticAnalysisError as exc:
                            failed_analyses += 1
                            original_analysis = self.call_orchestrator.persist_failed_analysis(
                                interaction=interaction,
                                error=exc,
                            )
                            analysis_reuse_reason = str(original_analysis.fail_reason or exc)
                            build_errors.append(f"analysis_build_failed:{interaction.id}:{exc}")
                        except LLMResponseError as exc:
                            failed_analyses += 1
                            fail_reason = analysis_contract_failure_reason(exc)
                            original_analysis = self.call_orchestrator.persist_failed_analysis(
                                interaction=interaction,
                                error=exc,
                                fail_reason=fail_reason,
                            )
                            analysis_reuse_reason = str(original_analysis.fail_reason or fail_reason)
                            build_errors.append(
                                f"analysis_build_failed:{interaction.id}:{fail_reason}"
                            )
                        except ASAError as exc:
                            failed_analyses += 1
                            provider_error = classify_provider_error(exc)
                            if provider_error.error_class == "quota_insufficient":
                                stage = "llm2" if "llm-2" in str(exc).lower() else "llm1"
                                if stage != "llm1":
                                    provider_context = self._provider_context_for_layer(
                                        layer=stage,
                                        interaction_id=str(interaction.id),
                                    )
                                quota_blocker = self._build_quota_blocker(
                                    stage=stage,
                                    provider_context=provider_context,
                                    error_info=provider_error,
                                )
                                self._record_provider_failure(
                                    interaction=interaction,
                                    blocker=quota_blocker,
                                    error_message=str(exc),
                                )
                            build_errors.append(f"analysis_build_failed:{interaction.id}:{exc}")
            artifacts.append(
                ReportArtifact(
                    interaction=interaction,
                    analysis=analysis,
                    manager=managers_by_id.get(interaction.manager_id) if interaction.manager_id else None,
                    call_started_at=parse_call_started_at(dict(interaction.metadata_ or {})),
                    original_analysis=original_analysis,
                    analysis_reuse_reason=analysis_reuse_reason,
                )
            )
        return (
            artifacts,
            {
                "transcripts_built": built_transcripts,
                "transcripts_reused": reused_transcripts,
                "analyses_built": built_analyses,
                "analyses_reused": reused_analyses,
                "analyses_rejected_for_reuse": analyses_rejected_for_reuse,
                "analyses_rejected_for_instruction_version": (
                    analyses_rejected_for_instruction_version
                ),
                "missing_transcripts_before_build": missing_transcripts_before_build,
                "missing_analyses_before_build": missing_analyses_before_build,
                "transcript_build_failed": failed_transcripts,
                "analysis_build_failed": failed_analyses,
                "include_controlled_samples": include_controlled_samples,
                "analysis_selection_policy": (
                    "latest_reusable_including_controlled_samples"
                    if include_controlled_samples
                    else "latest_reusable_stable_excluding_controlled_samples"
                )
                + (
                    f"_instruction_version={required_analysis_instruction_version}"
                    if required_analysis_instruction_version
                    else ""
                ),
                "analysis_instruction_version": required_analysis_instruction_version,
                "skipped_due_to_quota": skipped_due_to_quota,
                "quota_blocked_previous_run": quota_blocked_previous_run,
                "quota_blocker": quota_blocker,
            },
            build_errors,
        )

    def _provider_context_for_layer(self, *, layer: str, interaction_id: str) -> dict[str, Any]:
        """Return audit-safe configured provider context for one AI layer."""
        router = getattr(getattr(self, "extractor", None), "ai_router", None)
        if layer in {"llm1", "llm2"}:
            router = getattr(getattr(self, "analyzer", None), "ai_router", router)
        try:
            route_plan = router.build_route_plan(layer=layer, subject_key=interaction_id)
            candidate = route_plan.current_candidate()
        except Exception:
            return {"stage": layer}
        return {
            "stage": layer,
            "provider": candidate.provider,
            "account_alias": candidate.account_alias,
            "model": candidate.model,
            "api_key_env": candidate.api_key_env,
            "max_retries_for_this_provider": candidate.max_retries_for_this_provider,
        }

    @staticmethod
    def _build_quota_blocker(
        *,
        stage: str,
        provider_context: dict[str, Any],
        error_info: ProviderErrorInfo,
    ) -> dict[str, Any]:
        """Build a structured quota blocker without secret values."""
        return {
            "type": "quota_blocked",
            "stage": stage,
            "provider": provider_context.get("provider"),
            "account_alias": provider_context.get("account_alias"),
            "model": provider_context.get("model"),
            "api_key_env": provider_context.get("api_key_env"),
            "error_class": error_info.error_class,
            "message": "Provider returned insufficient_quota. Further billable calls were stopped.",
        }

    def _refresh_source_audio_url_before_transcript_build(
        self,
        *,
        interaction: Interaction,
    ) -> str | None:
        """Refresh one selected OnlinePBX recording URL before billable STT."""
        if not _should_refresh_onlinepbx_audio_url(interaction):
            return None
        call_id = _onlinepbx_canonical_call_id(interaction)
        if not call_id:
            return self._record_source_audio_unavailable(
                interaction=interaction,
                reason="missing_canonical_onlinepbx_call_id",
            )
        try:
            fresh_url = self.intake.get_recording_url(call_id)
        except ASAError as exc:
            return self._record_source_audio_unavailable(
                interaction=interaction,
                reason="recording_url_refresh_failed",
                error_message=str(exc),
            )
        if not fresh_url:
            return self._record_source_audio_unavailable(
                interaction=interaction,
                reason="recording_url_refresh_empty",
            )

        metadata = dict(interaction.metadata_ or {})
        metadata["source_audio_url_refresh"] = {
            "provider": "onlinepbx",
            "canonical_call_id": call_id,
            "status": "refreshed",
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
        metadata.pop(SOURCE_AUDIO_UNAVAILABLE_REASON, None)
        metadata.pop("last_audio_source_failure", None)
        interaction.metadata_ = metadata
        interaction.raw_ref = fresh_url
        current_error = str(getattr(interaction, "error_message", "") or "")
        if current_error.startswith(SOURCE_AUDIO_UNAVAILABLE_REASON) or (
            "Failed to download audio artifact:" in current_error
            and (
                "onlinepbx" in current_error.lower()
                or "key_is_expired" in current_error.lower()
            )
        ):
            interaction.error_message = None
        db = getattr(self, "db", None)
        if db is not None:
            db.commit()
        return None

    def _record_source_audio_unavailable(
        self,
        *,
        interaction: Interaction,
        reason: str,
        error_message: str | None = None,
    ) -> str:
        """Persist an operator-facing source-audio diagnostic without secrets."""
        metadata = dict(interaction.metadata_ or {})
        diagnostic = {
            "provider": "onlinepbx",
            "canonical_call_id": _onlinepbx_canonical_call_id(interaction),
            "reason": reason,
            "failed_at": datetime.now(UTC).isoformat(),
        }
        if error_message:
            diagnostic["message"] = error_message[:500]
        metadata[SOURCE_AUDIO_UNAVAILABLE_REASON] = diagnostic
        metadata["last_audio_source_failure"] = diagnostic
        interaction.metadata_ = metadata
        interaction.error_message = f"{SOURCE_AUDIO_UNAVAILABLE_REASON}:{reason}"
        db = getattr(self, "db", None)
        if db is not None:
            db.commit()
        return f"{SOURCE_AUDIO_UNAVAILABLE_REASON}:{interaction.id}:{reason}"

    def _record_provider_failure(
        self,
        *,
        interaction: Interaction,
        blocker: dict[str, Any],
        error_message: str,
    ) -> None:
        """Persist the last quota failure marker on an interaction for retry guard."""
        metadata = dict(interaction.metadata_ or {})
        failure = {
            "type": blocker.get("type"),
            "stage": blocker.get("stage"),
            "provider": blocker.get("provider"),
            "account_alias": blocker.get("account_alias"),
            "model": blocker.get("model"),
            "api_key_env": blocker.get("api_key_env"),
            "error_class": blocker.get("error_class"),
            "failed_at": datetime.now(UTC).isoformat(),
            "message": blocker.get("message"),
        }
        metadata["last_provider_failure"] = failure
        history = list(metadata.get("provider_failure_history") or [])
        history.append(failure)
        metadata["provider_failure_history"] = history[-5:]
        interaction.metadata_ = metadata
        if not getattr(interaction, "error_message", None):
            interaction.error_message = error_message
        db = getattr(self, "db", None)
        if db is not None:
            db.commit()

    def _build_run_observability(
        self,
        *,
        preset: ReportPreset,
        source_summary: dict[str, int],
        period: dict[str, str],
        source_period: dict[str, str],
        mode: str,
        delivery_options: ReportDeliveryOptions,
        selected_interactions_count: int,
        build_summary: dict[str, int],
        reports: list[dict[str, Any]],
        overall_status: str,
        errors: list[str] | None = None,
        artifacts: list[ReportArtifact] | None = None,
    ) -> dict[str, Any]:
        """Build a UI-facing observability snapshot without changing execution flow."""
        stage_errors: list[str] = list(errors or [])
        report_errors = [
            error
            for report in reports
            for error in report.get("errors", [])
            if error
        ]
        all_errors = [*stage_errors, *report_errors]
        delivery_summary = self._build_delivery_summary(
            reports=reports,
            delivery_options=delivery_options,
        )
        ai_costs = self._build_ai_costs(build_summary=build_summary, reports=reports)
        quota_blocker = _extract_quota_blocker(build_summary=build_summary, errors=all_errors)
        return {
            "run_state": self._map_run_state(overall_status),
            "stages": [
                self._build_source_discovery_stage(
                    preset=preset,
                    source_summary=source_summary,
                    period=source_period,
                    errors=errors or [],
                ),
                self._build_persistence_check_stage(
                    preset=preset,
                    source_summary=source_summary,
                    errors=all_errors,
                ),
                self._build_ingest_missing_stage(
                    preset=preset,
                    source_summary=source_summary,
                    errors=all_errors,
                ),
                self._build_audio_fetch_stage(
                    preset=preset,
                    build_summary=build_summary,
                    mode=mode,
                    errors=all_errors,
                ),
                self._build_stt_stage(
                    preset=preset,
                    build_summary=build_summary,
                    mode=mode,
                    errors=all_errors,
                ),
                self._build_analysis_stage(
                    preset=preset,
                    build_summary=build_summary,
                    mode=mode,
                    errors=all_errors,
                ),
                self._build_report_render_stage(
                    reports=reports,
                    errors=all_errors,
                ),
                self._build_delivery_stage(
                    reports=reports,
                    delivery_summary=delivery_summary,
                    errors=all_errors,
                ),
            ],
            "summary": {
                "execution_model": self._resolve_execution_model(preset=preset),
                "selected_interactions_count": selected_interactions_count,
                "reused_analyses_count": build_summary.get("analyses_reused", 0),
                "rebuilt_analyses_count": build_summary.get("analyses_built", 0),
                "final_report_status": overall_status,
                "blocker": quota_blocker,
                "skipped_due_to_quota": build_summary.get("skipped_due_to_quota", 0),
                "quota_blocked_previous_run": build_summary.get("quota_blocked_previous_run", 0),
                "template_version": next(
                    (
                        ((report.get("artifact") or {}).get("template_version"))
                        for report in reports
                        if (report.get("artifact") or {}).get("template_version")
                    ),
                    get_active_template_version(preset.code),
                ),
                "template_id": next(
                    (
                        ((report.get("artifact") or {}).get("template_id"))
                        for report in reports
                        if (report.get("artifact") or {}).get("template_id")
                    ),
                    get_active_template_version(preset.code),
                ),
                "render_variant": next(
                    (
                        ((report.get("artifact") or {}).get("render_variant"))
                        for report in reports
                        if (report.get("artifact") or {}).get("render_variant")
                    ),
                    f"template_pdf_{get_active_template_version(preset.code)}",
                ),
                "generator_path": next(
                    (
                        ((report.get("artifact") or {}).get("generator_path"))
                        for report in reports
                        if (report.get("artifact") or {}).get("generator_path")
                    ),
                    "app.agents.calls.report_templates.render_report_artifact",
                ),
                "artifact_type": next(
                    (
                        ((report.get("artifact") or {}).get("media_type"))
                        for report in reports
                        if (report.get("artifact") or {}).get("media_type")
                    ),
                    "application/pdf",
                ),
                "conversion_path": next(
                    (
                        ((report.get("artifact") or {}).get("conversion_path"))
                        for report in reports
                        if (report.get("artifact") or {}).get("conversion_path")
                    ),
                    None,
                ),
                "conversion_status": next(
                    (
                        ((report.get("artifact") or {}).get("conversion_status"))
                        for report in reports
                        if (report.get("artifact") or {}).get("conversion_status")
                    ),
                    None,
                ),
                "delivery": delivery_summary,
                "source": source_summary,
            },
            "ai_layers": self._build_ai_layer_summary(
                preset=preset,
                mode=mode,
                build_summary=build_summary,
                artifacts=artifacts or [],
            ),
            "ai_costs": ai_costs,
        }

    def _collect_run_diagnostics_context(
        self,
        *,
        preset: ReportPreset,
        mode: str,
        filters: ReportRunFilters,
        period: dict[str, str],
    ) -> dict[str, Any]:
        """Collect lightweight selection transparency context before the run is executed."""
        department = (
            self.db.query(Department)
            .filter(Department.id == self.department_id)
            .first()
        )
        directory_managers = (
            self.db.query(Manager)
            .filter(Manager.department_id == self.department_id)
            .all()
        )
        directory_manager_ids = {str(item.id) for item in directory_managers}
        selected_manager_ids = sorted(filters.manager_ids)
        selected_manager_extensions = sorted(filters.manager_extensions)

        period_only_interactions = self._select_interactions(
            filters=ReportRunFilters(
                date_from=filters.date_from,
                date_to=filters.date_to,
                min_duration_sec=filters.min_duration_sec,
                max_duration_sec=filters.max_duration_sec,
            ),
            period=period,
        )
        manager_only_interactions = (
            self._select_interactions(
                filters=ReportRunFilters(
                    manager_ids=set(filters.manager_ids),
                    date_from=filters.date_from,
                    date_to=filters.date_to,
                    min_duration_sec=filters.min_duration_sec,
                    max_duration_sec=filters.max_duration_sec,
                ),
                period=period,
            )
            if filters.manager_ids
            else []
        )
        extension_only_interactions = (
            self._select_interactions(
                filters=ReportRunFilters(
                    manager_extensions=set(filters.manager_extensions),
                    date_from=filters.date_from,
                    date_to=filters.date_to,
                    min_duration_sec=filters.min_duration_sec,
                    max_duration_sec=filters.max_duration_sec,
                ),
                period=period,
            )
            if filters.manager_extensions
            else []
        )

        return {
            "department_id": str(self.department_id),
            "department_name": department.name if department is not None else str(self.department_id),
            "preset": preset.code,
            "execution_model": self._resolve_execution_model(preset=preset),
            "mode": mode,
            "period": period,
            "analysis_instruction_version": filters.analysis_instruction_version,
            "selected_manager_ids": selected_manager_ids,
            "selected_manager_extensions": selected_manager_extensions,
            "manager_filter_logic": (
                "intersection"
                if selected_manager_ids and selected_manager_extensions
                else "manager_ids_only"
                if selected_manager_ids
                else "manager_extensions_only"
                if selected_manager_extensions
                else "department_scope"
            ),
            "missing_local_manager_ids": [
                item for item in selected_manager_ids if item not in directory_manager_ids
            ],
            "period_only_interactions_count": len(period_only_interactions),
            "manager_only_interactions_count": len(manager_only_interactions),
            "extension_only_interactions_count": len(extension_only_interactions),
        }

    def _build_run_diagnostics(
        self,
        *,
        preset: ReportPreset,
        mode: str,
        period: dict[str, str],
        source_period: dict[str, str],
        filters: ReportRunFilters,
        diagnostics_context: dict[str, Any],
        build_summary: dict[str, int],
        reports: list[dict[str, Any]],
        selected_interactions_count: int,
        final_selected_interactions_count: int,
        overall_status: str,
        source_summary: dict[str, int],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return a structured diagnostics block for operator-side transparency."""
        reason_codes = self._build_diagnostics_reason_codes(
            mode=mode,
            diagnostics_context=diagnostics_context,
            build_summary=build_summary,
            reports=reports,
            selected_interactions_count=selected_interactions_count,
            final_selected_interactions_count=final_selected_interactions_count,
            errors=errors,
        )
        notes = [
            (
                "report_from_ready_data_only on manager_daily performs source discovery and may ingest missing interactions, "
                "but it still does not fetch audio or run new STT / LLM-1 / LLM-2 builds."
            )
            if preset.code == "manager_daily" and mode == "report_from_ready_data_only"
            else (
                "build_missing_and_report on manager_daily performs source discovery, persists missing interactions, "
                "and then runs audio fetch / STT / LLM-1 / LLM-2 only for missing artifacts with reuse-first behavior."
            )
            if preset.code == "manager_daily"
            else (
                "rop_weekly uses persisted-only execution: no source discovery, no ingest of missing calls, "
                "and no new audio/STT/analysis run inside weekly reporting."
            )
        ]
        if diagnostics_context["manager_filter_logic"] == "intersection":
            notes.append(
                "manager_ids and manager_extensions are both selected, so the current bounded logic uses their intersection."
            )
        if filters.analysis_instruction_version:
            notes.append(
                "Analysis reuse is restricted to "
                f"instruction_version={filters.analysis_instruction_version}; "
                "older analyses cannot satisfy readiness."
            )

        return {
            "effective_preset": preset.code,
            "effective_mode": mode,
            "execution_model": diagnostics_context["execution_model"],
            "effective_department": {
                "id": diagnostics_context["department_id"],
                "name": diagnostics_context["department_name"],
            },
            "effective_period": period,
            "source_period": source_period,
            "selected_manager_ids": sorted(filters.manager_ids),
            "selected_manager_extensions": sorted(filters.manager_extensions),
            "analysis_instruction_version": filters.analysis_instruction_version,
            "analysis_selection_policy": build_summary.get("analysis_selection_policy"),
            "manager_filter_logic": diagnostics_context["manager_filter_logic"],
            "uses_filters_intersection": diagnostics_context["manager_filter_logic"] == "intersection",
            "interactions_found_before_reuse_build": selected_interactions_count,
            "ready_transcripts_count": build_summary.get("transcripts_reused", 0),
            "ready_analyses_count": build_summary.get("analyses_reused", 0),
            "final_selected_interactions_count": final_selected_interactions_count,
            "source_funnel": {
                "source_records_total": source_summary.get("source_records_total", 0),
                "source_raw_calls_total": source_summary.get("source_raw_calls_total", 0),
                "source_calls_after_ui_filters_total": source_summary.get(
                    "source_calls_after_ui_filters_total", 0
                ),
                "source_build_eligible_calls_total": source_summary.get(
                    "eligible_source_records_total", 0
                ),
                "selected_interactions_count": selected_interactions_count,
                "meaningful_calls_total": sum(
                    int(((report.get("payload") or {}).get("selection_model") or {}).get("meaningful_calls_total") or 0)
                    for report in reports
                ),
                "coaching_core_total": final_selected_interactions_count,
            },
            "reason_codes": reason_codes,
            "machine_readable_status": overall_status,
            "notes": notes,
            "report_origin": {
                "template_version": next(
                    (
                        ((report.get("artifact") or {}).get("template_version"))
                        for report in reports
                        if (report.get("artifact") or {}).get("template_version")
                    ),
                    get_active_template_version(preset.code),
                ),
                "template_id": next(
                    (
                        ((report.get("artifact") or {}).get("template_id"))
                        for report in reports
                        if (report.get("artifact") or {}).get("template_id")
                    ),
                    None,
                ),
                "render_variant": next(
                    (
                        ((report.get("artifact") or {}).get("render_variant"))
                        for report in reports
                        if (report.get("artifact") or {}).get("render_variant")
                    ),
                    f"template_pdf_{get_active_template_version(preset.code)}",
                ),
                "generator_path": next(
                    (
                        ((report.get("artifact") or {}).get("generator_path"))
                        for report in reports
                        if (report.get("artifact") or {}).get("generator_path")
                    ),
                    "app.agents.calls.report_templates.render_report_artifact",
                ),
                "artifact_type": next(
                    (
                        ((report.get("artifact") or {}).get("media_type"))
                        for report in reports
                        if (report.get("artifact") or {}).get("media_type")
                    ),
                    "application/pdf",
                ),
                "conversion_path": next(
                    (
                        ((report.get("artifact") or {}).get("conversion_path"))
                        for report in reports
                        if (report.get("artifact") or {}).get("conversion_path")
                    ),
                    None,
                ),
                "conversion_status": next(
                    (
                        ((report.get("artifact") or {}).get("conversion_status"))
                        for report in reports
                        if (report.get("artifact") or {}).get("conversion_status")
                    ),
                    None,
                ),
            },
            "source": source_summary,
            "readiness": self._build_readiness_summary(reports=reports),
            "local_directory": {
                "missing_manager_ids": diagnostics_context["missing_local_manager_ids"],
            },
        }

    @staticmethod
    def _build_readiness_summary(*, reports: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate manager_daily readiness decisions for structured diagnostics."""
        groups: list[dict[str, Any]] = []
        counts = {
            "full_report": 0,
            "signal_report": 0,
            "skip_accumulate": 0,
        }
        for report in reports:
            readiness = dict(report.get("readiness") or {})
            outcome = str(readiness.get("readiness_outcome") or "").strip()
            if not outcome:
                continue
            if outcome in counts:
                counts[outcome] += 1
            groups.append(
                {
                    "group_key": report.get("group_key"),
                    "readiness_outcome": outcome,
                    "readiness_reason_codes": list(readiness.get("readiness_reason_codes") or []),
                    "window_days_used": readiness.get("window_days_used"),
                    "relevant_calls": readiness.get("relevant_calls"),
                    "ready_analyses": readiness.get("ready_analyses"),
                    "analysis_coverage": readiness.get("analysis_coverage"),
                    "content_blocks": dict(readiness.get("content_blocks") or {}),
                }
            )
        return {
            "counts": counts,
            "groups": groups,
        }

    @staticmethod
    def _build_diagnostics_reason_codes(
        *,
        mode: str,
        diagnostics_context: dict[str, Any],
        build_summary: dict[str, int],
        reports: list[dict[str, Any]],
        selected_interactions_count: int,
        final_selected_interactions_count: int,
        errors: list[str],
    ) -> list[str]:
        """Return stable reason codes for empty or limited report-run results."""
        reason_codes: list[str] = []
        if diagnostics_context.get("missing_local_manager_ids"):
            reason_codes.append("manager_not_in_local_directory")
        if any(item.startswith("source_discovery_failed:") for item in errors):
            reason_codes.append("source_discovery_failed")
        if any(item.startswith("transcript_build_failed:") for item in errors):
            reason_codes.append("transcript_build_failed")
        if any(item.startswith("analysis_build_failed:") for item in errors):
            reason_codes.append("analysis_build_failed")
        if any(item.startswith("analysis_reuse_rejected:") for item in errors):
            reason_codes.append("analysis_reuse_rejected")
        if build_summary.get("analyses_rejected_for_instruction_version", 0) or any(
            "instruction_version_mismatch" in item for item in errors
        ):
            reason_codes.append("analysis_instruction_version_mismatch")
        if build_summary.get("quota_blocker") or any(item.startswith("quota_blocked_") for item in errors):
            reason_codes.append("quota_blocked")
        if build_summary.get("quota_blocked_previous_run", 0):
            reason_codes.append("quota_blocked_previous_run")
        if diagnostics_context.get("period_only_interactions_count", 0) == 0:
            reason_codes.append("date_range_has_no_persisted_calls")
        if (
            selected_interactions_count == 0
            and diagnostics_context.get("manager_filter_logic") == "intersection"
            and diagnostics_context.get("manager_only_interactions_count", 0) > 0
            and diagnostics_context.get("extension_only_interactions_count", 0) > 0
        ):
            reason_codes.append("filters_intersection_empty")
        if selected_interactions_count == 0:
            reason_codes.append("no_persisted_interactions_for_filters")
        if (
            mode == "report_from_ready_data_only"
            and selected_interactions_count > 0
            and final_selected_interactions_count == 0
            and (
                build_summary.get("transcripts_reused", 0) == 0
                or build_summary.get("analyses_reused", 0) == 0
            )
        ):
            reason_codes.append("no_ready_artifacts_for_ready_only_mode")
        if (
            mode == "report_from_ready_data_only"
            and selected_interactions_count > 0
            and final_selected_interactions_count == 0
            and reports
            and all(item.get("status") == "missing_artifacts" for item in reports)
            and "no_ready_artifacts_for_ready_only_mode" not in reason_codes
        ):
            reason_codes.append("no_ready_artifacts_for_ready_only_mode")
        for report in reports:
            readiness = dict(report.get("readiness") or {})
            for code in readiness.get("readiness_reason_codes") or []:
                reason_codes.append(str(code))
        deduped: list[str] = []
        for code in reason_codes:
            if code not in deduped:
                deduped.append(code)
        return deduped

    @staticmethod
    def _map_run_state(status: str) -> str:
        """Map internal reporting statuses to the UI run-state indicator."""
        if status in {"completed", "delivered", "ready"}:
            return "completed"
        if status in {"blocked", "partial", "no_data", "recipient_blocked", "missing_artifacts", "review_required"}:
            return "blocked"
        return "failed"

    @staticmethod
    def _build_source_discovery_stage(
        *,
        preset: ReportPreset,
        source_summary: dict[str, int],
        period: dict[str, str],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the source-discovery stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "source-discovery",
                "label": "source-discovery",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so source discovery is not executed.",
                "error": None,
            }
        source_failure = next((item for item in errors if item.startswith("source_discovery_failed:")), None)
        if source_failure:
            return {
                "code": "source-discovery",
                "label": "source-discovery",
                "status": "blocked",
                "summary": (
                    f"Source discovery failed while scanning {period['date_from']}..{period['date_to']}."
                ),
                "error": source_failure,
            }
        if source_summary.get("targeted_source_records_total", 0) <= 0:
            return {
                "code": "source-discovery",
                "label": "source-discovery",
                "status": "warn",
                "summary": (
                    f"Scanned {source_summary.get('days_scanned', 0)} days for {period['date_from']}..{period['date_to']}. "
                    "No source calls matched the current manager/UI filters."
                ),
                "error": errors[0] if errors else None,
            }
        return {
            "code": "source-discovery",
            "label": "source-discovery",
            "status": "completed",
            "summary": (
                f"Scanned {source_summary.get('days_scanned', 0)} days, fetched "
                f"{source_summary.get('source_records_total', 0)} source calls, "
                f"{source_summary.get('source_raw_calls_total', 0)} in manager source scope, "
                f"{source_summary.get('source_calls_after_ui_filters_total', 0)} after UI filters, "
                f"{source_summary.get('eligible_source_records_total', 0)} build-eligible."
            ),
            "error": None,
        }

    @staticmethod
    def _build_persistence_check_stage(
        *,
        preset: ReportPreset,
        source_summary: dict[str, int],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the persistence-check stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "persistence-check",
                "label": "persistence-check",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so no source/persistence reconciliation runs.",
                "error": None,
            }
        if source_summary.get("targeted_source_records_total", 0) <= 0:
            return {
                "code": "persistence-check",
                "label": "persistence-check",
                "status": "idle",
                "summary": "Source discovery produced no matched calls, so persistence-check stayed idle.",
                "error": None,
            }
        status = "completed" if source_summary.get("missing_source_records_total", 0) == 0 else "warn"
        return {
            "code": "persistence-check",
            "label": "persistence-check",
            "status": status,
            "summary": (
                f"Already persisted {source_summary.get('already_persisted_source_records_total', 0)} "
                f"matched source calls; missing before ingest {source_summary.get('missing_source_records_total', 0)}."
            ),
            "error": errors[0] if status == "warn" and errors else None,
        }

    @staticmethod
    def _build_ingest_missing_stage(
        *,
        preset: ReportPreset,
        source_summary: dict[str, int],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the ingest-missing stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "ingest-missing",
                "label": "ingest-missing",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so no missing source calls are ingested.",
                "error": None,
            }
        if source_summary.get("targeted_source_records_total", 0) <= 0:
            return {
                "code": "ingest-missing",
                "label": "ingest-missing",
                "status": "skipped",
                "summary": "No matched source calls required ingestion.",
                "error": None,
            }
        if source_summary.get("missing_source_records_total", 0) <= 0:
            return {
                "code": "ingest-missing",
                "label": "ingest-missing",
                "status": "completed",
                "summary": "All matched source calls were already persisted; no new interactions were created.",
                "error": None,
            }
        return {
            "code": "ingest-missing",
            "label": "ingest-missing",
            "status": "completed",
            "summary": (
                f"Created {source_summary.get('ingest_created_total', 0)} interactions and "
                f"updated/skipped {source_summary.get('ingest_skipped_total', 0)} existing rows."
            ),
            "error": errors[0] if errors and source_summary.get("ingest_created_total", 0) == 0 else None,
        }

    @staticmethod
    def _build_audio_fetch_stage(
        *,
        preset: ReportPreset,
        build_summary: dict[str, int],
        mode: str,
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the audio-fetch stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "audio-fetch",
                "label": "audio-fetch",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so weekly reporting never fetches new audio.",
                "error": None,
            }
        if mode != "build_missing_and_report":
            return {
                "code": "audio-fetch",
                "label": "audio-fetch",
                "status": "skipped",
                "summary": "Ready-only mode does not fetch audio for missing calls.",
                "error": None,
            }
        audio_error = next(
            (
                item
                for item in errors
                if item.startswith("transcript_build_failed:")
                and "audio" in item.lower()
            ),
            None,
        )
        if audio_error:
            return {
                "code": "audio-fetch",
                "label": "audio-fetch",
                "status": "blocked",
                "summary": "Audio fetch/download failed for at least one missing interaction.",
                "error": audio_error,
            }
        return {
            "code": "audio-fetch",
            "label": "audio-fetch",
            "status": "completed",
            "summary": (
                f"Fetched audio for {build_summary.get('transcripts_built', 0)} interactions that required transcript build."
            ),
            "error": None,
        }

    @staticmethod
    def _build_stt_stage(
        *,
        preset: ReportPreset,
        build_summary: dict[str, int],
        mode: str,
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the STT stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "stt",
                "label": "STT",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so weekly reporting never runs new STT.",
                "error": None,
            }
        if mode != "build_missing_and_report":
            return {
                "code": "stt",
                "label": "STT",
                "status": "skipped",
                "summary": "Ready-only mode does not run STT for missing calls.",
                "error": None,
            }
        quota_error = next((item for item in errors if item.startswith("quota_blocked_") or "insufficient_quota" in item), None)
        if quota_error:
            return {
                "code": "stt",
                "label": "STT",
                "status": "blocked",
                "summary": (
                    "STT/provider quota blocked this run; remaining billable calls were stopped "
                    f"or skipped ({build_summary.get('skipped_due_to_quota', 0)} skipped)."
                ),
                "error": quota_error,
            }
        stt_error = next(
            (
                item
                for item in errors
                if item.startswith("transcript_build_failed:")
                and any(token in item.lower() for token in ("stt", "whisper", "transcrib", "speech"))
            ),
            None,
        )
        if stt_error:
            return {
                "code": "stt",
                "label": "STT",
                "status": "blocked",
                "summary": "STT failed for at least one missing interaction.",
                "error": stt_error,
            }
        return {
            "code": "stt",
            "label": "STT",
            "status": "completed",
            "summary": (
                f"Built {build_summary.get('transcripts_built', 0)} transcripts and reused "
                f"{build_summary.get('transcripts_reused', 0)} ready transcripts."
            ),
            "error": None,
        }

    @staticmethod
    def _build_analysis_stage(
        *,
        preset: ReportPreset,
        build_summary: dict[str, int],
        mode: str,
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the analysis stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "analysis",
                "label": "analysis",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so weekly reporting reuses existing analyses only.",
                "error": None,
            }
        if mode != "build_missing_and_report":
            return {
                "code": "analysis",
                "label": "analysis",
                "status": "skipped",
                "summary": "Ready-only mode does not run new analysis for missing calls.",
                "error": None,
            }
        quota_error = next((item for item in errors if item.startswith("quota_blocked_") or "insufficient_quota" in item), None)
        if quota_error:
            return {
                "code": "analysis",
                "label": "analysis",
                "status": "blocked",
                "summary": (
                    "Provider quota blocked analysis/build continuation; remaining billable calls were stopped "
                    f"or skipped ({build_summary.get('skipped_due_to_quota', 0)} skipped)."
                ),
                "error": quota_error,
            }
        analysis_error = next((item for item in errors if item.startswith("analysis_build_failed:")), None)
        if analysis_error:
            return {
                "code": "analysis",
                "label": "analysis",
                "status": "blocked",
                "summary": "Analysis build failed for at least one interaction.",
                "error": analysis_error,
            }
        return {
            "code": "analysis",
            "label": "analysis",
            "status": "completed",
            "summary": (
                f"Built {build_summary.get('analyses_built', 0)} analyses and reused "
                f"{build_summary.get('analyses_reused', 0)} persisted analyses."
            ),
            "error": None,
        }

    @staticmethod
    def _build_report_render_stage(
        *,
        reports: list[dict[str, Any]],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the report-build/render stage snapshot."""
        if not reports:
            return {
                "code": "report-build",
                "label": "report-build / render",
                "status": "idle",
                "summary": "No report groups were built.",
                "error": errors[0] if errors else None,
            }
        rendered_total = sum(1 for item in reports if item.get("payload") or item.get("preview"))
        blocked_total = sum(1 for item in reports if item.get("status") == "missing_artifacts")
        skipped_total = sum(1 for item in reports if item.get("status") == "skip_accumulate")
        if rendered_total == 0 and skipped_total == len(reports):
            return {
                "code": "report-build",
                "label": "report-build / render",
                "status": "completed",
                "summary": f"Readiness decision skipped render for {skipped_total} manager_daily groups.",
                "error": None,
            }
        status = "completed" if rendered_total > 0 else "blocked"
        if blocked_total and rendered_total:
            status = "warn"
        return {
            "code": "report-build",
            "label": "report-build / render",
            "status": status,
            "summary": f"Built {len(reports)} report groups and rendered {rendered_total} previews.",
            "error": errors[0] if status in {"blocked", "warn"} and errors else None,
        }

    @staticmethod
    def _build_delivery_stage(
        *,
        reports: list[dict[str, Any]],
        delivery_summary: dict[str, Any],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the delivery stage snapshot."""
        if not reports:
            return {
                "code": "delivery",
                "label": "delivery",
                "status": "idle",
                "summary": "No report groups reached delivery.",
                "error": None,
            }
        if all(item.get("status") == "skip_accumulate" for item in reports):
            if any((item.get("delivery") or {}).get("transport") for item in reports):
                telegram_status = (delivery_summary.get("telegram_test_delivery") or {}).get("status", "unknown")
                email_status = (delivery_summary.get("email_delivery") or {}).get("status", "unknown")
                telegram_targets = ", ".join((delivery_summary.get("telegram_test_delivery") or {}).get("targets", [])) or "no telegram target"
                email_targets = ", ".join((delivery_summary.get("email_delivery") or {}).get("targets", [])) or "no email targets"
                status = "completed" if delivery_summary.get("result") in {"sent", "skipped"} else "warn"
                return {
                    "code": "delivery",
                    "label": "delivery",
                    "status": status,
                    "summary": (
                        "Preview shell delivery for non-deliverable manager_daily: "
                        f"Telegram {telegram_status} to {telegram_targets}; "
                        f"email {email_status} to {email_targets}."
                    ),
                    "error": errors[0] if status in {"blocked", "warn"} and errors else None,
                }
            return {
                "code": "delivery",
                "label": "delivery",
                "status": "completed",
                "summary": "Readiness decision selected skip_accumulate, so delivery was intentionally skipped.",
                "error": None,
            }
        telegram_status = (delivery_summary.get("telegram_test_delivery") or {}).get("status", "unknown")
        email_status = (delivery_summary.get("email_delivery") or {}).get("status", "unknown")
        if delivery_summary.get("result") in {"sent", "skipped"}:
            status = "completed"
        elif delivery_summary.get("result") == "partial":
            status = "warn"
        elif delivery_summary.get("result") == "blocked":
            status = "blocked"
        else:
            status = "warn"
        telegram_targets = ", ".join((delivery_summary.get("telegram_test_delivery") or {}).get("targets", [])) or "no telegram target"
        email_targets = ", ".join((delivery_summary.get("email_delivery") or {}).get("targets", [])) or "no email targets"
        return {
            "code": "delivery",
            "label": "delivery",
            "status": status,
            "summary": (
                f"Telegram test delivery {telegram_status} to {telegram_targets}; "
                f"email delivery {email_status} to {email_targets}; "
                f"overall result {delivery_summary.get('result', 'unknown')}."
            ),
            "error": errors[0] if status in {"blocked", "warn"} and errors else None,
        }

    def _build_delivery_summary(
        self,
        *,
        reports: list[dict[str, Any]],
        delivery_options: ReportDeliveryOptions,
    ) -> dict[str, Any]:
        """Return a compact delivery summary for the operator UI."""
        if not reports:
            return {
                "mode": delivery_options.mode,
                "targets": [],
                "result": "not_started",
                "telegram_test_delivery": {
                    "enabled": delivery_options.send_telegram_test_delivery,
                    "status": "not_started",
                    "targets": [],
                },
                "email_delivery": {
                    "enabled": delivery_options.send_business_email,
                    "status": "not_started",
                    "targets": [],
                },
            }
        targets: list[str] = []
        mode = "unknown"
        telegram_targets: list[str] = []
        email_targets: list[str] = []
        telegram_status = "not_started"
        email_status = "not_started"
        telegram_enabled = delivery_options.send_telegram_test_delivery
        email_enabled = delivery_options.send_business_email
        for report in reports:
            delivery = report.get("delivery") or {}
            transport = delivery.get("transport") or {}
            if transport.get("mode"):
                mode = str(transport["mode"])

            telegram = transport.get("telegram_test_delivery") or {}
            email = transport.get("email_delivery") or {}
            telegram_enabled = telegram_enabled or bool(telegram.get("enabled"))
            email_enabled = email_enabled or bool(email.get("enabled"))

            telegram_target = str(telegram.get("target") or "").strip()
            if telegram_target:
                value = f"telegram:{telegram_target}"
                if value not in telegram_targets:
                    telegram_targets.append(value)
                if value not in targets:
                    targets.append(value)
            resolved_email = transport.get("resolved_email") or {}
            primary_email = str(resolved_email.get("primary_email") or email.get("primary_email") or "").strip()
            if primary_email:
                value = f"resolved-email:{primary_email}"
                if value not in email_targets:
                    email_targets.append(value)
                if value not in targets:
                    targets.append(value)
            for cc_email in resolved_email.get("cc_emails") or email.get("cc_emails") or []:
                if cc_email:
                    value = f"resolved-cc:{cc_email}"
                    if value not in email_targets:
                        email_targets.append(value)
                    if value not in targets:
                        targets.append(value)

            telegram_status = self._merge_channel_status(telegram_status, str(telegram.get("status") or "not_started"))
            email_status = self._merge_channel_status(email_status, str(email.get("status") or "not_started"))

        result = self._derive_overall_delivery_result(
            telegram_status=telegram_status,
            email_status=email_status,
            telegram_enabled=telegram_enabled,
            email_enabled=email_enabled,
        )
        return {
            "mode": mode,
            "targets": targets,
            "result": result,
            "telegram_test_delivery": {
                "enabled": telegram_enabled,
                "status": telegram_status,
                "targets": telegram_targets,
            },
            "email_delivery": {
                "enabled": email_enabled,
                "status": email_status,
                "targets": email_targets,
            },
        }

    @staticmethod
    def _merge_channel_status(current: str, candidate: str) -> str:
        """Merge multiple report-level channel statuses into one summary status."""
        priority = {
            "failed": 5,
            "blocked": 4,
            "delivered": 3,
            "sent": 3,
            "planned": 2,
            "skipped": 1,
            "not_started": 0,
            "unknown": 0,
        }
        return candidate if priority.get(candidate, 0) >= priority.get(current, 0) else current

    @staticmethod
    def _derive_overall_delivery_result(
        *,
        telegram_status: str,
        email_status: str,
        telegram_enabled: bool,
        email_enabled: bool,
    ) -> str:
        """Derive one operator-facing delivery result from split channel states."""
        enabled_statuses = []
        if telegram_enabled:
            enabled_statuses.append(telegram_status)
        if email_enabled:
            enabled_statuses.append(email_status)
        if not enabled_statuses:
            return "skipped"
        if any(status in {"failed", "blocked"} for status in enabled_statuses):
            return "partial" if any(status in {"delivered", "sent"} for status in enabled_statuses) else "blocked"
        if all(status in {"delivered", "sent", "skipped"} for status in enabled_statuses):
            return "sent"
        return "unknown"

    @staticmethod
    def _flatten_delivery_targets(delivery: dict[str, Any]) -> list[str]:
        """Flatten preview/delivery target metadata into readable strings."""
        targets: list[str] = []
        primary = str(delivery.get("primary_email") or "").strip()
        if primary:
            targets.append(f"email:{primary}")
        for email in delivery.get("cc_emails") or []:
            if email:
                targets.append(f"cc:{email}")
        if delivery.get("telegram_chat_id"):
            targets.append(f"telegram:{delivery['telegram_chat_id']}")
        transport = delivery.get("resolved_email") or {}
        primary = str(transport.get("primary_email") or "").strip()
        if primary:
            targets.append(f"resolved-email:{primary}")
        for email in transport.get("cc_emails") or []:
            if email:
                targets.append(f"resolved-cc:{email}")
        deduped: list[str] = []
        for item in targets:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def _build_ai_costs(
        self,
        *,
        build_summary: dict[str, int],
        reports: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return AI node cost blocks with exact metadata when available."""
        ai_costs: list[dict[str, Any]] = []
        if build_summary.get("transcripts_built", 0) > 0:
            ai_costs.append(
                self._make_ai_cost_entry(
                    node="stt",
                    used_count=build_summary.get("transcripts_built", 0),
                    metadata_candidates=[],
                    summary="Speech-to-text ran for missing transcripts in this run.",
                )
            )
        if build_summary.get("analyses_built", 0) > 0:
            metadata_candidates = [
                report.get("payload", {})
                for report in reports
                if report.get("payload")
            ]
            ai_costs.append(
                self._make_ai_cost_entry(
                    node="llm1",
                    used_count=build_summary.get("analyses_built", 0),
                    metadata_candidates=metadata_candidates,
                    summary="LLM-1 first-pass analysis ran for rebuilt analyses in this run.",
                )
            )
            ai_costs.append(
                self._make_ai_cost_entry(
                    node="llm2",
                    used_count=build_summary.get("analyses_built", 0),
                    metadata_candidates=metadata_candidates,
                    summary="LLM-2 approved-contract generation ran for rebuilt analyses in this run.",
                )
            )
        return ai_costs

    def _build_ai_layer_summary(
        self,
        *,
        preset: ReportPreset,
        mode: str,
        build_summary: dict[str, int],
        artifacts: list[ReportArtifact],
    ) -> list[dict[str, Any]]:
        """Return per-layer execution/reuse/skip observability for the current run."""
        return [
            self._build_ai_layer_entry(
                layer="stt",
                label="STT",
                preset=preset,
                mode=mode,
                executed_count=build_summary.get("transcripts_built", 0),
                reused_count=build_summary.get("transcripts_reused", 0),
                not_activated_count=build_summary.get("missing_transcripts_before_build", 0),
                artifacts=artifacts,
            ),
            self._build_ai_layer_entry(
                layer="llm1",
                label="LLM-1",
                preset=preset,
                mode=mode,
                executed_count=build_summary.get("analyses_built", 0),
                reused_count=build_summary.get("analyses_reused", 0),
                not_activated_count=build_summary.get("missing_analyses_before_build", 0),
                artifacts=artifacts,
            ),
            self._build_ai_layer_entry(
                layer="llm2",
                label="LLM-2",
                preset=preset,
                mode=mode,
                executed_count=build_summary.get("analyses_built", 0),
                reused_count=build_summary.get("analyses_reused", 0),
                not_activated_count=build_summary.get("missing_analyses_before_build", 0),
                artifacts=artifacts,
            ),
        ]

    def _build_ai_layer_entry(
        self,
        *,
        layer: str,
        label: str,
        preset: ReportPreset,
        mode: str,
        executed_count: int,
        reused_count: int,
        not_activated_count: int,
        artifacts: list[ReportArtifact],
    ) -> dict[str, Any]:
        """Build one layer-level audit block for operator observability."""
        selected_routes = self._collect_ai_layer_routes(artifacts=artifacts, layer=layer)
        current_run_status = "idle"
        skip_reason = None
        if preset.code == "rop_weekly":
            current_run_status = "skipped"
            skip_reason = "preset_persisted_only"
        elif mode != "build_missing_and_report":
            current_run_status = "skipped"
            skip_reason = "mode_ready_only_no_new_builds"
        elif executed_count > 0:
            current_run_status = "executed"
        elif reused_count > 0:
            current_run_status = "reused_only"
        return {
            "layer": layer,
            "label": label,
            "current_run_status": current_run_status,
            "skip_reason": skip_reason,
            "executed_count": executed_count,
            "reused_count": reused_count,
            "not_activated_count": not_activated_count if current_run_status == "skipped" else 0,
            "provider_audit_available": bool(selected_routes),
            "selected_routes": selected_routes,
        }

    @staticmethod
    def _collect_ai_layer_routes(
        *,
        artifacts: list[ReportArtifact],
        layer: str,
    ) -> list[dict[str, Any]]:
        """Collect unique route metadata already persisted on source interactions."""
        routes: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for artifact in artifacts:
            metadata = dict(artifact.interaction.metadata_ or {})
            ai_routing = dict(metadata.get("ai_routing") or {})
            layer_metadata = ai_routing.get(layer)
            if not isinstance(layer_metadata, dict):
                continue
            route = {
                "selected_provider": layer_metadata.get("selected_provider"),
                "selected_account_alias": layer_metadata.get("selected_account_alias"),
                "selected_api_key_env": layer_metadata.get("selected_api_key_env"),
                "selected_model": layer_metadata.get("selected_model"),
                "selected_api_base": layer_metadata.get("selected_api_base"),
                "selected_endpoint": layer_metadata.get("selected_endpoint"),
                "executed_endpoint_path": layer_metadata.get("executed_endpoint_path"),
                "selected_execution_mode": layer_metadata.get("selected_execution_mode"),
                "request_kind": layer_metadata.get("request_kind"),
                "execution_status": layer_metadata.get("execution_status"),
                "executed": layer_metadata.get("executed"),
                "provider_failure": layer_metadata.get("provider_failure"),
                "skip_reason": layer_metadata.get("skip_reason"),
                "provider_request_id": layer_metadata.get("provider_request_id"),
                "usage": layer_metadata.get("usage"),
            }
            key = (
                route["selected_provider"],
                route["selected_account_alias"],
                route["selected_model"],
                route["selected_api_base"],
                route["selected_endpoint"],
                route["request_kind"],
                route["execution_status"],
            )
            if key in seen:
                continue
            seen.add(key)
            routes.append(route)
        return routes

    def _make_ai_cost_entry(
        self,
        *,
        node: str,
        used_count: int,
        metadata_candidates: list[dict[str, Any]],
        summary: str,
    ) -> dict[str, Any]:
        """Normalize one AI cost entry with safe fallbacks."""
        exact_cost = self._extract_known_cost_metadata(metadata_candidates)
        if exact_cost is None:
            return {
                "node": node,
                "used": True,
                "used_count": used_count,
                "cost_status": "not_available",
                "cost_usd": None,
                "tokens": None,
                "summary": f"{summary} Exact cost metadata is not available in current runtime payloads.",
            }
        return {
            "node": node,
            "used": True,
            "used_count": used_count,
            "cost_status": "available",
            "cost_usd": exact_cost.get("cost_usd"),
            "tokens": exact_cost.get("tokens"),
            "summary": summary,
        }

    @classmethod
    def _extract_known_cost_metadata(cls, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Scan nested payloads for known cost/token metadata without inventing values."""
        for candidate in candidates:
            found = cls._search_cost_metadata(candidate)
            if found is not None:
                return found
        return None

    @classmethod
    def _search_cost_metadata(cls, value: Any) -> dict[str, Any] | None:
        """Recursively search one nested payload for cost-like metadata."""
        if isinstance(value, dict):
            cost_usd = None
            for key in ("cost_usd", "usd_cost", "price_usd", "estimated_cost_usd"):
                if value.get(key) is not None:
                    cost_usd = value.get(key)
                    break
            tokens = None
            for key in ("total_tokens", "prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"):
                if value.get(key) is not None:
                    tokens = {
                        token_key: value.get(token_key)
                        for token_key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
                        if value.get(token_key) is not None
                    } or None
                    break
            if cost_usd is not None or tokens is not None:
                return {
                    "cost_usd": cost_usd,
                    "tokens": tokens,
                }
            for child in value.values():
                found = cls._search_cost_metadata(child)
                if found is not None:
                    return found
        if isinstance(value, list):
            for item in value:
                found = cls._search_cost_metadata(item)
                if found is not None:
                    return found
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                return None
            return cls._search_cost_metadata(parsed)
        return None

    def _load_latest_analyses_by_interaction(
        self,
        *,
        interactions: list[Interaction],
        include_controlled_samples: bool = False,
        analysis_instruction_version: str | None = None,
    ) -> dict[UUID, Analysis]:
        """Return the best stable analysis row for each selected interaction.

        Normal manager_daily runs ignore controlled sample / verification rows
        and fall back past invalid latest rows to an older reusable stable row.
        When a target instruction version is set, only rows with that exact
        version can satisfy reuse; older rows may only explain rejection.
        """
        interaction_ids = [item.id for item in interactions]
        if not interaction_ids:
            return {}
        rows = (
            self.db.query(Analysis)
            .filter(
                Analysis.department_id == self.department_id,
                Analysis.interaction_id.in_(interaction_ids),
            )
            .order_by(Analysis.interaction_id, Analysis.created_at.desc())
            .all()
        )
        grouped: dict[UUID, list[Analysis]] = {}
        for row in rows:
            grouped.setdefault(row.interaction_id, []).append(row)
        selected: dict[UUID, Analysis] = {}
        for interaction_id, candidates in grouped.items():
            analysis = _select_stable_analysis_for_reporting(
                candidates,
                include_controlled_samples=include_controlled_samples,
                analysis_instruction_version=analysis_instruction_version,
            )
            if analysis is not None:
                selected[interaction_id] = analysis
        return selected

    def _load_managers_by_id(self, *, interactions: list[Interaction]) -> dict[UUID, Manager]:
        """Load manager rows referenced by the selected interactions."""
        manager_ids = sorted({item.manager_id for item in interactions if item.manager_id})
        if not manager_ids:
            return {}
        rows = (
            self.db.query(Manager)
            .filter(
                Manager.department_id == self.department_id,
                Manager.id.in_(manager_ids),
            )
            .all()
        )
        return {row.id: row for row in rows}

    def _group_and_build_reports(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        source_period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        delivery_options: ReportDeliveryOptions,
        manager_daily_windows: list[ManagerDailyWindow],
    ) -> list[dict[str, Any]]:
        """Build bounded reports for the selected preset."""
        if preset.code == "manager_daily":
            return self._build_manager_daily_reports_with_readiness(
                preset=preset,
                artifacts=artifacts,
                source_period=source_period,
                filters=filters,
                mode=mode,
                model_override=model_override,
                delivery_options=delivery_options,
                windows=manager_daily_windows,
            )
        grouped_artifacts = self._group_artifacts_by_preset(
            preset=preset,
            artifacts=artifacts,
            period=period,
        )
        return [
            self._build_single_report_result(
                preset=preset,
                artifacts=group,
                period=period,
                filters=filters,
                mode=mode,
                model_override=model_override,
                delivery_options=delivery_options,
            )
            for group in grouped_artifacts
        ]

    def _build_manager_daily_reports_with_readiness(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        source_period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        delivery_options: ReportDeliveryOptions,
        windows: list[ManagerDailyWindow],
    ) -> list[dict[str, Any]]:
        """Build manager_daily groups through the bounded readiness decision layer."""
        grouped: dict[str, list[ReportArtifact]] = {}
        for artifact in artifacts:
            manager_key = str(artifact.interaction.manager_id or "unmapped")
            grouped.setdefault(manager_key, []).append(artifact)
        return [
            self._build_manager_daily_group_result(
                preset=preset,
                artifacts=group,
                source_period=source_period,
                filters=filters,
                mode=mode,
                model_override=model_override,
                delivery_options=delivery_options,
                windows=windows,
            )
            for _, group in sorted(grouped.items())
        ]

    def _build_manager_daily_group_result(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        source_period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        delivery_options: ReportDeliveryOptions,
        windows: list[ManagerDailyWindow],
    ) -> dict[str, Any]:
        """Choose full_report, signal_report, or skip_accumulate for one manager group."""
        last_readiness = _build_manager_daily_readiness_result(
            outcome="skip_accumulate",
            reason_codes=["skip_accumulate_no_relevant_calls"],
            window=windows[-1] if windows else ManagerDailyWindow(1, source_period, (source_period["date_from"],)),
            relevant_calls=0,
            ready_analyses=0,
            analysis_coverage=0.0,
            content_blocks={},
            content_signals={},
        )
        for window in windows:
            window_artifacts = [
                item
                for item in artifacts
                if item.call_started_at is not None and item.call_started_at.date().isoformat() in window.included_days
            ]
            payload = None
            missing, usable = self._split_usable_artifacts(
                window_artifacts,
                require_coaching_core_eligible=True,
            )
            if usable:
                payload = self._build_payload(
                    preset=preset,
                    artifacts=usable,
                    period=window.period,
                    filters=filters,
                    mode=mode,
                    model_override=model_override,
                    window_artifacts=window_artifacts,
                )
            readiness = _evaluate_manager_daily_readiness(
                artifacts=window_artifacts,
                usable_artifacts=usable,
                payload=payload,
                window=window,
            )
            last_readiness = readiness
            if readiness["readiness_outcome"] in {"full_report", "signal_report"} and payload is not None:
                readiness["total_group_calls"] = len(artifacts)
                return self._render_and_deliver_report_result(
                    preset=preset,
                    usable=usable,
                    payload=payload,
                    delivery_options=delivery_options,
                    missing=missing,
                    readiness=readiness,
                )
        return self._build_manager_daily_empty_state_result(
            status="skip_accumulate",
            artifacts=artifacts,
            period=last_readiness["effective_period"],
            filters=filters,
            mode=mode,
            model_override=model_override,
            delivery_options=delivery_options,
            reason_codes=list(last_readiness["readiness_reason_codes"]),
            relevant_calls=last_readiness["relevant_calls"],
            ready_analyses=last_readiness["ready_analyses"],
            analysis_coverage=last_readiness["analysis_coverage"],
            missing=[],
            readiness=last_readiness,
        )

    def _group_artifacts_by_preset(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
    ) -> list[list[ReportArtifact]]:
        """Group selected artifacts into report-sized buckets for one preset."""
        if preset.code == "manager_daily":
            grouped: dict[tuple[str, str], list[ReportArtifact]] = {}
            for artifact in artifacts:
                manager_key = str(artifact.interaction.manager_id or "unmapped")
                day_key = (
                    artifact.call_started_at.date().isoformat()
                    if artifact.call_started_at is not None
                    else period["date_from"]
                )
                grouped.setdefault((manager_key, day_key), []).append(artifact)
            return [group for _, group in sorted(grouped.items())]
        return [artifacts]

    def _build_single_report_result(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        delivery_options: ReportDeliveryOptions,
    ) -> dict[str, Any]:
        """Build one normalized payload, render it, and optionally deliver it."""
        missing, usable = self._split_usable_artifacts(
            artifacts,
            require_coaching_core_eligible=preset.code == "manager_daily",
        )

        if not usable:
            if preset.code == "manager_daily":
                return self._build_manager_daily_empty_state_result(
                    status="missing_artifacts",
                    artifacts=artifacts,
                    period=period,
                    filters=filters,
                    mode=mode,
                    model_override=model_override,
                    delivery_options=delivery_options,
                    reason_codes=["missing_artifacts", "insufficient_ready_artifacts"],
                    relevant_calls=len(artifacts),
                    ready_analyses=0,
                    analysis_coverage=0.0,
                    missing=missing or ["no_usable_artifacts"],
                    readiness=None,
                )
            return {
                "status": "missing_artifacts",
                "preset": preset.code,
                "group_key": self._build_group_key(preset=preset, artifacts=artifacts, period=period),
                "errors": missing or ["no_usable_artifacts"],
                "delivery": None,
            }

        payload = self._build_payload(
            preset=preset,
            artifacts=usable,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
            window_artifacts=artifacts,
        )
        return self._render_and_deliver_report_result(
            preset=preset,
            usable=usable,
            payload=payload,
            delivery_options=delivery_options,
            missing=missing,
            readiness=None,
        )

    @staticmethod
    def _split_usable_artifacts(
        artifacts: list[ReportArtifact],
        *,
        require_coaching_core_eligible: bool = False,
    ) -> tuple[list[str], list[ReportArtifact]]:
        """Separate ready report artifacts from rows missing transcript or analysis.

        For manager_daily, "usable" is the coaching_core subset, so not_eligible
        support/internal calls must stay out of coaching blocks while remaining
        available in window_artifacts for meaningful call list and counters.
        """
        missing: list[str] = []
        usable: list[ReportArtifact] = []
        for artifact in artifacts:
            if artifact.analysis is None:
                missing.append(f"analysis_missing:{artifact.interaction.id}")
                continue
            if not artifact.interaction.text:
                missing.append(f"transcript_missing:{artifact.interaction.id}")
                continue
            if require_coaching_core_eligible and not _is_coaching_core_eligible(artifact):
                missing.append(f"coaching_core_not_eligible:{artifact.interaction.id}")
                continue
            usable.append(artifact)
        return missing, usable

    def _render_and_deliver_report_result(
        self,
        *,
        preset: ReportPreset,
        usable: list[ReportArtifact],
        payload: dict[str, Any],
        delivery_options: ReportDeliveryOptions,
        missing: list[str],
        readiness: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Render one ready payload and run split delivery."""
        if readiness is not None:
            payload.setdefault("meta", {})["readiness"] = readiness
        manager_gate = None
        gate_failed = False
        effective_send_email = delivery_options.send_business_email
        effective_send_telegram = delivery_options.send_telegram_test_delivery
        if preset.code == "manager_daily":
            manager_gate = _build_manager_facing_completeness_gate(
                call_list=list(payload.get("call_list") or [])
            )
            payload["manager_facing_completeness"] = manager_gate
            payload.setdefault("meta", {})["manager_facing_completeness"] = {
                "status": manager_gate["status"],
                "reason": manager_gate.get("reason"),
                "manager_report_allowed": manager_gate["manager_report_allowed"],
                "blocking_counts": dict(manager_gate["blocking_counts"]),
            }
            gate_failed = not bool(manager_gate["manager_report_allowed"])
            if gate_failed:
                effective_send_email = False
                header = payload.setdefault("header", {})
                title = str(header.get("report_title") or "Ежедневный разбор звонков")
                if "OPERATOR PREVIEW" not in title:
                    header["report_title"] = f"{title} — OPERATOR PREVIEW / INCOMPLETE"
        rendered = render_report_email(payload, prefer_docx_first=True)

        try:
            delivery_targets = self._resolve_delivery_targets(
                preset=preset,
                artifacts=usable,
            )
            primary_email = delivery_targets["primary_email"]
            cc_emails = delivery_targets["cc_emails"]
            email_resolution_error = None
        except DeliveryError as exc:
            primary_email = None
            cc_emails = []
            email_resolution_error = str(exc)

        preview = {key: value for key, value in rendered.items() if key != "pdf_bytes"}
        result = {
            "status": "review_required" if gate_failed else "ready",
            "preset": preset.code,
            "group_key": payload["meta"]["group_key"],
            "errors": [*missing, "manager_facing_gate_failed:incomplete_day_call_processing"] if gate_failed else missing,
            "payload": payload,
            "preview": preview,
            "artifact": rendered.get("artifact"),
            "delivery": self.delivery.preview_report_delivery(
                primary_email=primary_email,
                cc_emails=cc_emails,
                send_telegram_test_delivery=effective_send_telegram,
                send_business_email=effective_send_email,
                email_resolution_error=email_resolution_error,
            ),
        }
        if manager_gate is not None:
            result["manager_facing_completeness"] = manager_gate
        if readiness is not None:
            result.update(
                {
                    "readiness_outcome": readiness["readiness_outcome"],
                    "readiness_reason_codes": list(readiness["readiness_reason_codes"]),
                    "window_days_used": readiness["window_days_used"],
                    "window_start": readiness.get("window_start"),
                    "window_end": readiness.get("window_end"),
                    "relevant_calls": readiness["relevant_calls"],
                    "ready_analyses": readiness["ready_analyses"],
                    "analysis_coverage": readiness["analysis_coverage"],
                    "content_blocks": dict(readiness["content_blocks"]),
                    "readiness": readiness,
                }
            )
        delivery = self.delivery.deliver_operator_report(
            primary_email=primary_email,
            cc_emails=cc_emails,
            subject=rendered["subject"],
            text=rendered["text"],
            html=rendered["html"],
            pdf_bytes=rendered["pdf_bytes"],
            pdf_filename=rendered["artifact"]["filename"],
            template_meta=rendered.get("template"),
            artifact_meta=rendered.get("artifact"),
            send_business_email=effective_send_email,
            send_telegram_test_delivery=effective_send_telegram,
            email_resolution_error=email_resolution_error,
            morning_card_text=rendered.get("morning_card_text"),
        )
        result["delivery"] = delivery

        transport = delivery.get("transport") or {}
        telegram_status = ((transport.get("telegram_test_delivery") or {}).get("status") or "").strip()
        email_status = ((transport.get("email_delivery") or {}).get("status") or "").strip()
        telegram_enabled = bool((transport.get("telegram_test_delivery") or {}).get("enabled"))
        email_enabled = bool((transport.get("email_delivery") or {}).get("enabled"))
        delivery_result = self._derive_overall_delivery_result(
            telegram_status=telegram_status,
            email_status=email_status,
            telegram_enabled=telegram_enabled,
            email_enabled=email_enabled,
        )

        if gate_failed:
            result["status"] = "review_required"
        elif delivery_result == "sent":
            result["status"] = "delivered"
        elif delivery_result == "skipped":
            result["status"] = "ready"
        elif delivery_result == "partial":
            result["status"] = "partial"
        else:
            result["status"] = "blocked"

        delivery_errors = [
            error
            for error in [
                (transport.get("telegram_test_delivery") or {}).get("error"),
                (transport.get("email_delivery") or {}).get("error"),
            ]
            if error
        ]
        if delivery_errors:
            base_errors = [*missing, "manager_facing_gate_failed:incomplete_day_call_processing"] if gate_failed else list(missing)
            result["errors"] = [*base_errors, *delivery_errors]
        return result

    def _build_manager_daily_empty_state_result(
        self,
        *,
        status: str,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        delivery_options: ReportDeliveryOptions,
        reason_codes: list[str],
        relevant_calls: int,
        ready_analyses: int,
        analysis_coverage: float,
        missing: list[str],
        readiness: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Render an operator-only empty-state shell for non-deliverable manager_daily."""
        payload = self._build_manager_daily_empty_state_payload(
            artifacts=artifacts,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
            status=status,
            reason_codes=reason_codes,
            relevant_calls=relevant_calls,
            ready_analyses=ready_analyses,
            analysis_coverage=analysis_coverage,
            readiness=readiness,
            missing=missing,
        )
        rendered = render_report_email(payload, prefer_docx_first=True)
        preview = {key: value for key, value in rendered.items() if key != "pdf_bytes"}
        delivery = self.delivery.deliver_operator_report(
            primary_email=None,
            cc_emails=[],
            subject=rendered["subject"],
            text=rendered["text"],
            html=rendered["html"],
            pdf_bytes=rendered["pdf_bytes"],
            pdf_filename=rendered["artifact"]["filename"],
            template_meta=rendered.get("template"),
            artifact_meta=rendered.get("artifact"),
            send_business_email=False,
            send_telegram_test_delivery=delivery_options.send_telegram_test_delivery,
            email_resolution_error=None,
            morning_card_text=rendered.get("morning_card_text"),
        )
        result = {
            "status": status,
            "preset": "manager_daily",
            "group_key": payload["meta"]["group_key"],
            "errors": list(missing),
            "payload": payload,
            "preview": preview,
            "artifact": rendered.get("artifact"),
            "delivery": delivery,
            "preview_only": True,
            "not_deliverable_manager_report": True,
            "readiness_outcome": status if status in {"skip_accumulate", "no_data", "missing_artifacts"} else "skip_accumulate",
            "readiness_reason_codes": list(reason_codes),
            "window_days_used": (readiness or {}).get("window_days_used"),
            "window_start": (readiness or {}).get("window_start"),
            "window_end": (readiness or {}).get("window_end"),
            "relevant_calls": relevant_calls,
            "ready_analyses": ready_analyses,
            "analysis_coverage": analysis_coverage,
            "content_blocks": dict((readiness or {}).get("content_blocks") or {}),
            "readiness": readiness,
        }
        return result

    def _build_manager_daily_empty_state_payload(
        self,
        *,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        status: str,
        reason_codes: list[str],
        relevant_calls: int,
        ready_analyses: int,
        analysis_coverage: float,
        readiness: dict[str, Any] | None,
        missing: list[str],
    ) -> dict[str, Any]:
        """Build a preview-only shell payload for non-deliverable manager_daily."""
        manager_name = self._resolve_manager_daily_empty_state_manager_name(
            artifacts=artifacts,
            filters=filters,
        )
        department_name = self._resolve_department_name()
        status_label = {
            "skip_accumulate": "Недостаточно данных для deliverable отчёта",
            "missing_artifacts": "Недостаточно ready-артефактов",
            "no_data": "Нет звонков по выбранным фильтрам",
        }.get(status, "Недостаточно данных")
        formatted_coverage = round(float(analysis_coverage or 0.0), 1)
        reason_lines = [code.replace("_", " ") for code in reason_codes[:6]]
        if not reason_lines:
            reason_lines = ["Нужно больше готовых данных для полного daily report."]
        explanation = (
            f"Это preview shell для оператора. Полноценный manager_daily не собран: "
            f"найдено {relevant_calls} звонков, ready analyses {ready_analyses}, coverage {formatted_coverage}%."
        )
        if status == "no_data":
            explanation = (
                "Это preview shell для оператора. По выбранным фильтрам не найдено persisted звонков, "
                "которые можно включить в daily report без нового build."
            )
        elif status == "missing_artifacts":
            explanation = (
                "Это preview shell для оператора. Persisted звонки найдены, но ready transcript/analysis "
                "недостаточны для сборки обычного daily report."
            )

        payload = {
            "meta": _build_base_meta(
                preset="manager_daily",
                department_id=str(getattr(self, "department_id", "unknown-department")),
                period=period,
                filters=filters,
                mode=mode,
                model_override=model_override,
                artifacts=artifacts,
                group_key=f"manager_daily_preview:{manager_name}:{period['date_from']}",
            ),
            "empty_state": {
                "enabled": True,
                "status": status,
                "reason_codes": list(reason_codes),
                "summary_cards": [
                    {"label": "Найдено звонков", "value": relevant_calls, "tone": "blue"},
                    {"label": "Ready analyses", "value": ready_analyses, "tone": "yellow"},
                    {"label": "Coverage", "value": f"{formatted_coverage}%", "tone": "problem"},
                    {"label": "Окно", "value": f"{(readiness or {}).get('window_days_used', 1)} раб. дн.", "tone": "focus"},
                    {"label": "Статус", "value": status, "tone": "problem"},
                ],
                "hero_focus": "PREVIEW • insufficient data • not a deliverable manager report",
                "footer": "Preview shell · Недостаточно данных · Не отправлять менеджеру как обычный daily report",
                "generation_note": (
                    "Operator-facing preview shell only. "
                    "Этот artifact показывает layout и diagnostics, но не считается deliverable manager report."
                ),
            },
            "header": {
                "report_title": "PREVIEW — Ежедневный разбор звонков",
                "manager_id": str(artifacts[0].interaction.manager_id) if artifacts and artifacts[0].interaction.manager_id else None,
                "manager_name": manager_name,
                "report_date": _format_period_label(period),
                "department_name": department_name,
                "department_id": str(getattr(self, "department_id", "unknown-department")),
                "product_or_business_context": None,
            },
            "focus_of_week": {
                "text": "Preview shell: структура daily report показана, но данных для deliverable результата недостаточно.",
                "is_placeholder": True,
            },
            "kpi_overview": {
                "calls_count": relevant_calls,
                "average_score": None,
                "strong_calls_pct": None,
                "baseline_calls_pct": None,
                "problematic_calls_pct": None,
                "score_vs_period_avg": None,
                "delta_vs_period_avg": None,
                "interpretation_label": status_label,
            },
            "narrative_day_conclusion": {
                "text": explanation,
                "source": "preview_shell",
                "model_dependent": False,
            },
            "signal_of_day": {
                "call_time": None,
                "client_or_phone_mask": "Preview shell",
                "short_evidence": "Сильный/критичный сигнал не выделен: итоговый deliverable report не собран.",
                "reason_this_matters": "Показываем форму отчёта и диагностику, не маскируя слабую базу под рабочий daily report.",
                "is_placeholder": True,
            },
            "main_focus_for_tomorrow": {
                "text": "Следующий шаг — либо накопить больше ready persisted analyses, либо запускать build_missing_and_report отдельной задачей.",
                "source": "preview_shell",
                "model_dependent": False,
            },
            "analysis_worked": [
                {
                    "label": "Placeholder секции",
                    "signal": 0,
                    "interpretation": "Здесь будут сильные зоны, когда ready dataset станет достаточным для deliverable daily report.",
                }
            ],
            "analysis_improve": [
                {
                    "label": "Почему отчёт не собран",
                    "signal": len(reason_codes),
                    "interpretation": "; ".join(reason_lines),
                }
            ],
            "key_problem_of_day": {
                "title": "Недостаточно данных для итогового разбора",
                "description": "Отчёт за этот день не собран: звонки найдены, но анализов недостаточно для полноценного daily report.",
            },
            "recommendations": [
                {
                    "priority_tag": "На неделе",
                    "title": "Почему это preview, а не deliverable report",
                    "reason": explanation,
                    "how_it_sounded": "Reason codes: " + (", ".join(reason_codes[:5]) if reason_codes else "нет"),
                    "better_phrasing": "Не отправлять менеджеру как обычный daily report. Использовать только для operator preview и диагностики.",
                    "why_this_works": "Позволяет увидеть layout отчёта и причины недосбора без запуска новых AI шагов.",
                }
            ],
            "call_outcomes_summary": {
                "agreed_count": 0,
                "rescheduled_count": 0,
                "refusal_count": 0,
                "open_count": 0,
                "tech_service_count": 0,
            },
            "score_by_stage": [],
            "call_list": [
                {
                    "time": period["date_from"],
                    "client_or_phone": "Preview shell",
                    "duration_sec": "—",
                    "status": status,
                    "score_percent": f"{formatted_coverage}%",
                    "next_step": "Открыть diagnostics и reason codes вместо отправки обычного daily report.",
                }
            ],
            "focus_criterion_dynamics": {
                "focus_criterion_name": "Readiness / coverage",
                "current_period_value": f"{formatted_coverage}%",
                "previous_period_value": f"{ready_analyses} ready analyses",
                "delta": f"{relevant_calls} найдено",
            },
            "memo_legend": {
                "call_level_legend": [
                    "Preview shell",
                    "Insufficient data",
                    "Not a deliverable manager report",
                ],
                "call_status_legend": [
                    "preset=manager_daily",
                    f"mode={mode}",
                    f"period={period['date_from']}..{period['date_to']}",
                ],
                "recommendation_priority_legend": [
                    f"readiness_outcome={status}",
                    f"reason_codes={', '.join(reason_codes[:4]) if reason_codes else 'n/a'}",
                    "business email intentionally disabled for this shell",
                ],
            },
            "delivery_meta": {
                "email_subject": f"[PREVIEW][INSUFFICIENT DATA] manager_daily — {manager_name} — {_format_period_label(period)}",
                "render_variant": f"template_pdf_{get_active_template_version('manager_daily')}",
            },
        }
        payload["meta"]["empty_state"] = {
            "status": status,
            "reason_codes": list(reason_codes),
            "not_deliverable_manager_report": True,
        }
        return payload

    def _resolve_department_name(self) -> str:
        """Return department name for shell/report payloads."""
        db = getattr(self, "db", None)
        if db is not None:
            department = db.query(Department).filter(Department.id == self.department_id).first()
            if department is not None and str(department.name or "").strip():
                return str(department.name)
        return "Отдел продаж"

    def _resolve_manager_daily_empty_state_manager_name(
        self,
        *,
        artifacts: list[ReportArtifact],
        filters: ReportRunFilters,
    ) -> str:
        """Resolve the display manager name for a preview-only daily shell."""
        if artifacts:
            manager = artifacts[0].manager
            if manager is not None and str(manager.name or "").strip():
                return str(manager.name)
            interaction_metadata = dict(artifacts[0].interaction.metadata_ or {})
            if str(interaction_metadata.get("manager_name") or "").strip():
                return str(interaction_metadata["manager_name"]).strip()
        if len(filters.manager_ids) == 1:
            db = getattr(self, "db", None)
            if db is not None:
                try:
                    manager_id = UUID(filters.manager_ids[0])
                except ValueError:
                    manager_id = None
                if manager_id is not None:
                    manager = db.query(Manager).filter(Manager.id == manager_id).first()
                    if manager is not None and str(manager.name or "").strip():
                        return str(manager.name)
        if len(filters.manager_extensions) == 1:
            return f"Менеджер {filters.manager_extensions[0]}"
        return "Менеджер не выбран"

    def _resolve_delivery_targets(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
    ) -> dict[str, Any]:
        """Resolve primary recipient and monitoring copy for the report."""
        department = (
            self.db.query(Department)
            .filter(Department.id == self.department_id)
            .first()
        )
        reporting_settings = dict((department.settings or {}).get("reporting") or {}) if department else {}
        monitoring_email = (
            reporting_settings.get("monitoring_email")
            or REPORTING_MONITORING_EMAIL
        )

        if preset.recipient_kind == "manager":
            manager = artifacts[0].manager
            if manager is None or not manager.email:
                raise DeliveryError(
                    "manager_daily recipient is not resolvable. Expected manager email in Bitrix-synced manager card."
                )
            return {
                "primary_email": manager.email,
                "cc_emails": [email for email in [monitoring_email] if email and email != manager.email],
            }

        primary_email = (
            reporting_settings.get("rop_weekly_email")
            or (reporting_settings.get("recipient_resolution") or {}).get("rop_weekly_email")
            or self._resolve_rop_weekly_email_from_bitrix_head(department=department)
        )
        if not primary_email:
            raise DeliveryError(
                "rop_weekly recipient is not configured. Set department.settings.reporting.rop_weekly_email "
                "or ensure Bitrix department UF_HEAD resolves to an active user with email."
            )
        return {
            "primary_email": primary_email,
            "cc_emails": [email for email in [monitoring_email] if email and email != primary_email],
        }

    def _resolve_rop_weekly_email_from_bitrix_head(
        self,
        *,
        department: Department | None,
    ) -> str | None:
        """Resolve the weekly recipient from Bitrix department head when local config is absent."""
        if department is None:
            return None
        department_settings = dict(department.settings or {})
        bitrix_department_id = str(department_settings.get("bitrix_department_id") or "").strip()
        if not bitrix_department_id:
            return None

        client = Bitrix24ReadOnlyClient()
        try:
            departments = client.list_departments()
        except BitrixReadOnlyError:
            return None

        head_user_id = next(
            (
                item.head_user_id
                for item in departments
                if item.bitrix_department_id == bitrix_department_id and item.head_user_id
            ),
            None,
        )
        if not head_user_id:
            return None

        try:
            head_user = client.get_user_by_id(head_user_id)
        except BitrixReadOnlyError:
            return None
        if head_user is None or not head_user.active or not head_user.email:
            return None
        return head_user.email

    def _build_payload(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        window_artifacts: list[ReportArtifact] | None = None,
    ) -> dict[str, Any]:
        """Build a normalized preset payload before rendering."""
        department_id = str(getattr(self, "department_id", "unknown-department"))
        department_name = "Отдел продаж"
        db = getattr(self, "db", None)
        if db is not None:
            department = (
                db.query(Department)
                .filter(Department.id == self.department_id)
                .first()
            )
            if department is not None and str(department.name or "").strip():
                department_name = department.name
        if preset.code == "manager_daily":
            return build_manager_daily_payload(
                department_id=department_id,
                department_name=department_name,
                artifacts=artifacts,
                period=period,
                filters=filters,
                mode=mode,
                model_override=model_override,
                window_artifacts=window_artifacts,
            )
        return build_rop_weekly_payload(
            department_id=department_id,
            department_name=department_name,
            artifacts=artifacts,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
        )

    @staticmethod
    def _build_group_key(
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
    ) -> str:
        """Build a deterministic key for one report group."""
        if preset.code == "manager_daily":
            manager_id = str(artifacts[0].interaction.manager_id or "unmapped")
            return f"{preset.code}:{manager_id}:{period['date_from']}"
        return f"{preset.code}:{period['date_from']}:{period['date_to']}"


def parse_call_started_at(metadata: dict[str, Any]) -> datetime | None:
    """Parse persisted call date metadata into UTC-aware datetime."""
    raw = str(metadata.get("call_date") or metadata.get("call_started_at") or "").strip()
    if not raw:
        return None
    candidates = (
        raw,
        raw.replace(" ", "T"),
        raw.replace("Z", "+00:00"),
    )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _last_workdays(*, anchor: date, count: int) -> list[str]:
    """Return the last N working days inclusive of anchor, skipping weekends."""
    days: list[str] = []
    current = anchor
    while len(days) < max(count, 0):
        if current.weekday() < 5:
            days.append(current.isoformat())
        current -= timedelta(days=1)
    return list(reversed(days))


def _build_manager_daily_readiness_result(
    *,
    outcome: str,
    reason_codes: list[str],
    window: ManagerDailyWindow,
    relevant_calls: int,
    ready_analyses: int,
    analysis_coverage: float,
    content_blocks: dict[str, bool],
    content_signals: dict[str, Any],
) -> dict[str, Any]:
    """Return one normalized readiness payload for decision transparency."""
    window_start = window.period.get("date_from")
    window_end = window.period.get("date_to")
    return {
        "readiness_outcome": outcome,
        "readiness_reason_codes": reason_codes,
        "window_days_used": window.workdays_used,
        "window_start": window_start,
        "window_end": window_end,
        "effective_period": dict(window.period),
        "relevant_calls": relevant_calls,
        "ready_analyses": ready_analyses,
        "analysis_coverage": analysis_coverage,
        "content_blocks": content_blocks,
        "content_signals": content_signals,
    }


def _classify_meaningful_call(artifact: ReportArtifact) -> tuple[bool, str | None]:
    """Return (is_meaningful, exclusion_reason) for one call.

    Implements bounded SM-2 rule set. Rules are evaluated in order; first match wins.
    Exclusion reason codes match the selection_model.exclusion_reasons contract.

    Rule summary (canonical: docs/MANAGER_DAILY_SELECTION_MODEL.md Section B):
    - R1: no duration data → too_short_or_no_speech
    - R2: duration < floor AND no transcript → too_short_or_no_speech
    - R3: has transcript → meaningful (real conversation, regardless of call_type)
    - R4: call_type=other + analysis_eligibility=not_eligible + no transcript → ivr_or_autoanswer
    - R5: no transcript + weak source signal → too_short_or_no_speech
    - Default: probable live conversation with enough CDR talk time → meaningful
    """
    duration = artifact.interaction.duration_sec or 0
    has_transcript = bool(artifact.interaction.text)

    # R1: missing or zero duration with no transcript
    if duration <= 0 and not has_transcript:
        return False, "too_short_or_no_speech"

    # R2: below absolute floor and no real speech detected
    if duration < MEANINGFUL_ABSOLUTE_MIN_DURATION_SEC and not has_transcript:
        return False, "too_short_or_no_speech"

    # R3: transcript present → real conversation occurred
    if has_transcript:
        return True, None

    # R4: analyzer flagged as not_eligible with call_type=other → IVR/autoanswer/beep
    if artifact.analysis is not None:
        detail = dict(artifact.analysis.scores_detail or {})
        classification = detail.get("classification") or {}
        call_type = str(classification.get("call_type") or "").lower()
        eligibility = str(classification.get("analysis_eligibility") or "").lower()
        if call_type == "other" and eligibility == "not_eligible":
            return False, "ivr_or_autoanswer"

    metadata = dict(getattr(artifact.interaction, "metadata_", None) or {})
    source_status = str(metadata.get("source_status") or "").lower()
    direction = str(metadata.get("direction") or "").lower()
    if source_status and source_status != "answered":
        return False, "too_short_or_no_speech"
    if direction and direction not in {"in", "out"}:
        return False, "too_short_or_no_speech"
    if duration < MEANINGFUL_NO_TRANSCRIPT_MIN_DURATION_SEC:
        return False, "too_short_or_no_speech"

    # Default: enough talk time in answered CDR to keep as probable live conversation.
    return True, None


def _build_selection_model_counters(
    *,
    window_artifacts: list[ReportArtifact],
    usable_artifacts: list[ReportArtifact],
) -> dict[str, Any]:
    """Compute selection model counters for manager_daily payload.

    window_artifacts = all calls loaded for this report window (before usable split).
    usable_artifacts = calls with ready analysis + transcript (coaching_core candidates).
    """
    raw_calls_total = len(window_artifacts)

    too_short_count = 0
    ivr_count = 0
    meaningful_calls: list[ReportArtifact] = []
    service_calls_total = 0

    for artifact in window_artifacts:
        is_meaningful, reason = _classify_meaningful_call(artifact)
        if not is_meaningful:
            if reason == "too_short_or_no_speech":
                too_short_count += 1
            elif reason == "ivr_or_autoanswer":
                ivr_count += 1
            continue
        meaningful_calls.append(artifact)
        if artifact.analysis is not None:
            detail = dict(artifact.analysis.scores_detail or {})
            call_type = str((detail.get("classification") or {}).get("call_type") or "").lower()
            if call_type in {"support", "internal"}:
                service_calls_total += 1

    meaningful_calls_total = len(meaningful_calls)

    coaching_candidate_calls_total = 0
    for artifact in usable_artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis else {})
        call_type = str((detail.get("classification") or {}).get("call_type") or "").lower()
        if call_type not in {"support", "internal"}:
            coaching_candidate_calls_total += 1

    without_analysis = sum(1 for a in window_artifacts if a.analysis is None)
    failed_analysis = sum(
        1 for a in window_artifacts
        if a.analysis is not None and bool(getattr(a.analysis, "is_failed", False))
    )

    return {
        "raw_calls_total": raw_calls_total,
        "meaningful_calls_total": meaningful_calls_total,
        "service_calls_total": service_calls_total,
        "coaching_candidate_calls_total": coaching_candidate_calls_total,
        "analyzed_calls_total": len(usable_artifacts),
        "included_in_report_total": len(usable_artifacts),
        "exclusion_reasons": {
            "too_short_or_no_speech": too_short_count,
            "ivr_or_autoanswer": ivr_count,
            "support_internal": service_calls_total,
            "not_enough_analysis": without_analysis + failed_analysis,
            "not_selected_for_core_review": 0,
        },
    }


def _evaluate_manager_daily_readiness(
    *,
    artifacts: list[ReportArtifact],
    usable_artifacts: list[ReportArtifact],
    payload: dict[str, Any] | None,
    window: ManagerDailyWindow,
) -> dict[str, Any]:
    """Choose full_report, signal_report, or skip_accumulate for one manager_daily window."""
    relevant_calls = len(artifacts)
    ready_analyses = len(usable_artifacts)
    analysis_coverage = _pct(ready_analyses, relevant_calls) if relevant_calls else 0.0

    worked_items = list((payload or {}).get("analysis_worked") or [])
    improve_items = list((payload or {}).get("analysis_improve") or [])
    recommendations = list((payload or {}).get("recommendations") or [])
    narrative = str(((payload or {}).get("narrative_day_conclusion") or {}).get("text") or "").strip()
    key_problem = dict((payload or {}).get("key_problem_of_day") or {})
    signal_of_day = dict((payload or {}).get("signal_of_day") or {})

    strong_zones_count = len([item for item in worked_items if _is_meaningful_finding(item)])
    growth_zones_count = len([item for item in improve_items if _is_meaningful_finding(item)])
    main_problems_count = 1 if _is_meaningful_key_problem(key_problem) else 0
    normal_recommendations_count = len(
        [item for item in recommendations if _is_meaningful_recommendation(item)]
    )

    content_blocks = {
        "day_summary_ready": bool(narrative),
        "review_ready": strong_zones_count > 0 and growth_zones_count > 0,
        "key_problem_ready": main_problems_count > 0,
        "recommendations_ready": normal_recommendations_count > 0,
    }
    has_positive_signal = bool(str(signal_of_day.get("short_evidence") or "").strip()) and any(
        _score_bucket(item.analysis) == "strong" for item in usable_artifacts
    )
    has_critical_signal = main_problems_count > 0 and any(
        _score_bucket(item.analysis) == "problematic" for item in usable_artifacts
    )
    has_coaching_pattern = any(int(item.get("signal") or 0) >= 2 for item in improve_items if _is_meaningful_finding(item))
    has_manager_action = normal_recommendations_count > 0

    content_signals = {
        "strong_zones_count": strong_zones_count,
        "growth_zones_count": growth_zones_count,
        "main_problems_count": main_problems_count,
        "normal_recommendations_count": normal_recommendations_count,
        "positive_signal_available": has_positive_signal,
        "critical_signal_available": has_critical_signal,
        "coaching_pattern_available": has_coaching_pattern,
        "manager_action_available": has_manager_action,
    }

    full_reasons: list[str] = []
    if relevant_calls < MANAGER_DAILY_FULL_REPORT_MIN_RELEVANT_CALLS:
        full_reasons.append("relevant_calls_below_full_threshold")
    if ready_analyses < MANAGER_DAILY_FULL_REPORT_MIN_READY_ANALYSES:
        full_reasons.append("ready_analyses_below_full_threshold")
    if analysis_coverage < MANAGER_DAILY_FULL_REPORT_MIN_ANALYSIS_COVERAGE:
        full_reasons.append("analysis_coverage_below_full_threshold")
    if not content_blocks["day_summary_ready"]:
        full_reasons.append("content_block_day_summary_missing")
    if not content_blocks["review_ready"]:
        full_reasons.append("content_block_review_missing")
    if not content_blocks["key_problem_ready"]:
        full_reasons.append("content_block_key_problem_missing")
    if not content_blocks["recommendations_ready"]:
        full_reasons.append("content_block_recommendations_missing")
    if strong_zones_count <= 0:
        full_reasons.append("strong_zone_missing")
    if growth_zones_count <= 0:
        full_reasons.append("growth_zone_missing")
    if main_problems_count <= 0:
        full_reasons.append("main_problem_missing")
    if normal_recommendations_count <= 0:
        full_reasons.append("normal_recommendation_missing")
    if not full_reasons:
        return _build_manager_daily_readiness_result(
            outcome="full_report",
            reason_codes=["full_report_ready"],
            window=window,
            relevant_calls=relevant_calls,
            ready_analyses=ready_analyses,
            analysis_coverage=analysis_coverage,
            content_blocks=content_blocks,
            content_signals=content_signals,
        )

    signal_reasons: list[str] = list(full_reasons)
    if ready_analyses < MANAGER_DAILY_SIGNAL_REPORT_MIN_READY_ANALYSES:
        signal_reasons.append("ready_analyses_below_signal_threshold")
    if not (has_positive_signal or has_critical_signal or has_coaching_pattern):
        signal_reasons.append("signal_case_not_found")
    if not has_manager_action:
        signal_reasons.append("manager_action_missing")
    if ready_analyses >= MANAGER_DAILY_SIGNAL_REPORT_MIN_READY_ANALYSES and (
        has_positive_signal or has_critical_signal or has_coaching_pattern
    ) and has_manager_action:
        outcome_reasons = ["signal_report_ready"]
        if has_positive_signal:
            outcome_reasons.append("signal_positive_case_available")
        if has_critical_signal:
            outcome_reasons.append("signal_critical_case_available")
        if has_coaching_pattern:
            outcome_reasons.append("signal_coaching_pattern_available")
        return _build_manager_daily_readiness_result(
            outcome="signal_report",
            reason_codes=outcome_reasons,
            window=window,
            relevant_calls=relevant_calls,
            ready_analyses=ready_analyses,
            analysis_coverage=analysis_coverage,
            content_blocks=content_blocks,
            content_signals=content_signals,
        )

    deduped_reasons: list[str] = []
    for code in ["skip_accumulate_readiness_not_met", *signal_reasons]:
        if code not in deduped_reasons:
            deduped_reasons.append(code)
    return _build_manager_daily_readiness_result(
        outcome="skip_accumulate",
        reason_codes=deduped_reasons,
        window=window,
        relevant_calls=relevant_calls,
        ready_analyses=ready_analyses,
        analysis_coverage=analysis_coverage,
        content_blocks=content_blocks,
        content_signals=content_signals,
    )


def _is_meaningful_finding(item: dict[str, Any]) -> bool:
    """Return True when the finding item is populated enough for readiness."""
    return bool(str(item.get("label") or "").strip() and str(item.get("interpretation") or "").strip())


def _is_meaningful_key_problem(value: dict[str, Any]) -> bool:
    """Return True when key_problem_of_day is not a deterministic fallback."""
    title = str(value.get("title") or "").strip()
    description = str(value.get("description") or "").strip()
    if not title or not description:
        return False
    return not (
        title == MANAGER_DAILY_FALLBACK_KEY_PROBLEM_TITLE
        and description == MANAGER_DAILY_FALLBACK_KEY_PROBLEM_DESCRIPTION
    )


def _is_meaningful_recommendation(item: dict[str, Any]) -> bool:
    """Return True when the recommendation card is not the bounded fallback placeholder."""
    title = str(item.get("title") or "").strip()
    better_phrasing = str(item.get("better_phrasing") or "").strip()
    if not title or not better_phrasing:
        return False
    return title != MANAGER_DAILY_FALLBACK_RECOMMENDATION_TITLE


def _stage_funnel_label_for_code(stage_code: str) -> str | None:
    code = str(stage_code or "").strip()
    for known_code, funnel_label, _stage_name in _STAGE_FUNNEL_ORDER:
        if known_code == code:
            return funnel_label
    return None


def _priority_stage_from_scores(
    *,
    score_by_stage: list[dict[str, Any]],
    key_problem: dict[str, Any],
) -> dict[str, Any] | None:
    priority_stage = next((item for item in score_by_stage if item.get("is_priority")), None)
    if priority_stage is not None:
        return dict(priority_stage)
    if _is_meaningful_key_problem(key_problem):
        scored_stages = [item for item in score_by_stage if item.get("score") is not None]
        if scored_stages:
            return dict(min(scored_stages, key=lambda item: float(item.get("score") or 999.0)))
    return None


def _daily_focus_stage_code(daily_focus: dict[str, Any] | None) -> str:
    return str((daily_focus or {}).get("stage_code") or "").strip()


def _focus_problem_signal(value: str, *, fallback: str) -> str:
    normalized = _summary_norm(value)
    tokens = re.findall(r"[a-zа-яё0-9]+", normalized)
    if not tokens:
        return fallback
    return "_".join(tokens[:8])[:80] or fallback


def _build_daily_coaching_focus(
    *,
    score_by_stage: list[dict[str, Any]],
    key_problem: dict[str, Any],
    data_scope: dict[str, Any],
) -> dict[str, Any]:
    """Build the single focus object that all main coaching blocks must align to."""
    priority_stage = _priority_stage_from_scores(score_by_stage=score_by_stage, key_problem=key_problem)
    if priority_stage is None:
        scope = dict(data_scope)
        return {
            "stage_id": None,
            "stage_code": None,
            "stage_name": None,
            "problem_signal": None,
            "problem_statement": MANAGER_DAILY_FALLBACK_KEY_PROBLEM_DESCRIPTION,
            "data_scope": scope.get("code") or MANAGER_DAILY_DATA_SCOPE_REPORT_DAY,
            "data_scope_details": scope,
            "evidence_call_id": None,
            "breakdown_call_id": None,
            "challenge_metric_source": "insufficient_stage_data",
            "confidence": "low",
            "validation": {"status": "warning", "issues": ["focus_stage_missing"]},
        }

    stage_code = str(priority_stage.get("stage_code") or "").strip()
    stage_name = str(priority_stage.get("stage_name") or "").strip() or _stage_name_for_code(stage_code, score_by_stage)
    problem_statement = _first_sentence(str(priority_stage.get("problem_summary") or ""), limit=220)
    if not problem_statement and _is_meaningful_key_problem(key_problem):
        key_problem_stage = _stage_code_from_criterion_code(str(key_problem.get("criterion_code") or ""))
        if not key_problem_stage or key_problem_stage == stage_code:
            problem_statement = _first_sentence(str(key_problem.get("title") or ""), limit=220)
    if not problem_statement:
        problem_statement = _focus_stage_generic_text(stage_name, kind="wrong")
    normalized_focus_problem = _normalize_problem_statement(
        problem_statement,
        stage_code=stage_code,
        fallback=_stage_problem_fallback(stage_code),
    )
    problem_statement = str(normalized_focus_problem.get("text") or problem_statement).strip()

    confidence = "high" if priority_stage.get("is_priority") and priority_stage.get("problem_summary") else "medium"
    scope = dict(data_scope)
    validation_issues = list(normalized_focus_problem.get("warnings") or [])
    return {
        "stage_id": _stage_funnel_label_for_code(stage_code),
        "stage_code": stage_code,
        "stage_name": stage_name,
        "problem_signal": _focus_problem_signal(problem_statement, fallback=stage_code or "focus_stage"),
        "problem_statement": problem_statement,
        "data_scope": scope.get("code") or MANAGER_DAILY_DATA_SCOPE_REPORT_DAY,
        "data_scope_details": scope,
        "evidence_call_id": None,
        "breakdown_call_id": None,
        "challenge_metric_source": "score_by_stage.priority",
        "confidence": confidence,
        "problem_normalized_from": normalized_focus_problem.get("source_text"),
        "validation": {"status": "pending", "issues": validation_issues},
    }


def _block_stage_code(block: dict[str, Any] | None) -> str:
    return str((block or {}).get("stage_code") or "").strip()


def _finalize_daily_coaching_focus(
    *,
    daily_focus: dict[str, Any],
    situation_evidence_quote: dict[str, Any] | None,
    situation_day_coaching_view: dict[str, Any] | None,
    call_breakdown: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach selected evidence IDs and alignment diagnostics to the daily focus."""
    result = dict(daily_focus)
    focus_stage = _daily_focus_stage_code(result)
    issues: list[str] = list((result.get("validation") or {}).get("issues") or [])

    situation_stage = _block_stage_code(situation_day_coaching_view) or str(
        (situation_evidence_quote or {}).get("stage_code") or ""
    ).strip()
    situation_selection_mode = str(
        dict((situation_day_coaching_view or {}).get("selection_diagnostics") or {}).get(
            "selection_mode"
        )
        or ""
    ).strip()
    if (
        focus_stage
        and situation_stage
        and situation_stage != focus_stage
        and situation_selection_mode in SITUATION_FOCUS_OVERRIDE_SELECTION_MODES
    ):
        original_focus = {
            "stage_code": result.get("stage_code"),
            "stage_name": result.get("stage_name"),
            "stage_id": result.get("stage_id"),
            "problem_signal": result.get("problem_signal"),
            "problem_statement": result.get("problem_statement"),
            "challenge_metric_source": result.get("challenge_metric_source"),
        }
        result["original_score_focus"] = original_focus
        result["stage_code"] = situation_stage
        result["stage_id"] = _stage_funnel_label_for_code(situation_stage)
        result["stage_name"] = (
            str((situation_day_coaching_view or {}).get("stage_label") or "").strip()
            or situation_stage
        )
        problem_statement = _first_sentence(
            str(
                (situation_day_coaching_view or {}).get("pattern_title")
                or (situation_day_coaching_view or {}).get("what_was_missing")
                or (situation_day_coaching_view or {}).get("what_happened")
                or original_focus.get("problem_statement")
                or ""
            ),
            limit=220,
        )
        result["problem_signal"] = _focus_problem_signal(
            problem_statement,
            fallback=f"{situation_selection_mode}_selected",
        )
        result["problem_statement"] = problem_statement
        result["challenge_metric_source"] = situation_selection_mode
        result["focus_override_reason"] = situation_selection_mode
        focus_stage = situation_stage

    if focus_stage and situation_stage and situation_stage != focus_stage:
        issues.append(f"situation_stage_mismatch:{situation_stage}")

    breakdown_stage = _block_stage_code(call_breakdown)
    if focus_stage and breakdown_stage and breakdown_stage != focus_stage:
        issues.append(f"call_breakdown_stage_mismatch:{breakdown_stage}")

    evidence_call_id = str((situation_evidence_quote or {}).get("call_id") or "").strip() or None
    breakdown_call_id = str((call_breakdown or {}).get("call_id") or "").strip() or None
    result["evidence_call_id"] = evidence_call_id
    result["breakdown_call_id"] = breakdown_call_id
    result["situation_stage_code"] = situation_stage or None
    result["breakdown_stage_code"] = breakdown_stage or None
    result["validation"] = {
        "status": "warning" if issues else "passed",
        "issues": issues,
    }
    return result


SITUATION_FOCUS_OVERRIDE_SELECTION_MODES = {
    "best_semantic_case_after_focus_mismatch",
    "best_block_candidate_after_focus_mismatch",
    "evidence_registry_single_manager_gap",
    "evidence_registry_repeated_weak_manager_gap",
    "daily_situation_composer_v1",
    "best_manager_gap_scene_by_score",
    "llm3_daily_situation_selection",
}


def _maybe_override_daily_focus_from_situation(
    *,
    daily_focus: dict[str, Any],
    situation_evidence_quote: dict[str, Any] | None,
    situation_day_coaching_view: dict[str, Any] | None,
) -> dict[str, Any]:
    """Align dependent report blocks to the coherent Situation Day case early.

    When there is no same-stage candidate, the report layer may deliberately pick
    the strongest proven Situation Day case from another stage. In that mode the
    selected case becomes the coaching focus for downstream blocks too.
    """
    focus_stage = _daily_focus_stage_code(daily_focus)
    situation_stage = _block_stage_code(situation_day_coaching_view) or str(
        (situation_evidence_quote or {}).get("stage_code") or ""
    ).strip()
    selection_diagnostics = dict((situation_day_coaching_view or {}).get("selection_diagnostics") or {})
    selection_mode = str(selection_diagnostics.get("selection_mode") or "").strip()
    candidate_source = str(selection_diagnostics.get("candidate_source") or "").strip()
    situation_source = str((situation_day_coaching_view or {}).get("source") or "").strip()
    selected_problem_statement = _first_sentence(
        str(
            (situation_day_coaching_view or {}).get("what_was_missing")
            or (situation_day_coaching_view or {}).get("pattern_title")
            or (situation_day_coaching_view or {}).get("what_happened")
            or ""
        ),
        limit=220,
    )
    trusted_situation_case = (
        candidate_source == "report_evidence.block_candidates"
        or situation_source.startswith("report_evidence.block_candidates")
        or situation_source == "report_evidence.semantic_case"
        or situation_source.startswith("report_evidence.evidence_registry")
        or situation_source.startswith(SITUATION_DAY_DAILY_SOURCE)
    )
    if not focus_stage or not situation_stage:
        return daily_focus

    if situation_stage == focus_stage:
        if not trusted_situation_case or not selected_problem_statement:
            return daily_focus
        current_problem = str(daily_focus.get("problem_statement") or "").strip()
        if _summary_norm(current_problem) == _summary_norm(selected_problem_statement):
            return daily_focus
        result = dict(daily_focus)
        result.setdefault(
            "original_score_focus",
            {
                "stage_code": result.get("stage_code"),
                "stage_name": result.get("stage_name"),
                "stage_id": result.get("stage_id"),
                "problem_signal": result.get("problem_signal"),
                "problem_statement": result.get("problem_statement"),
                "challenge_metric_source": result.get("challenge_metric_source"),
            },
        )
        result["problem_signal"] = _focus_problem_signal(
            selected_problem_statement,
            fallback="situation_day_selected_case",
        )
        result["problem_statement"] = selected_problem_statement
        result["problem_statement_source"] = "situation_day_selected_case"
        result["challenge_metric_source"] = "situation_day_selected_case"
        return result

    if selection_mode not in SITUATION_FOCUS_OVERRIDE_SELECTION_MODES:
        return daily_focus

    result = dict(daily_focus)
    original_focus = {
        "stage_code": result.get("stage_code"),
        "stage_name": result.get("stage_name"),
        "stage_id": result.get("stage_id"),
        "problem_signal": result.get("problem_signal"),
        "problem_statement": result.get("problem_statement"),
        "challenge_metric_source": result.get("challenge_metric_source"),
    }
    problem_statement = _first_sentence(
        str(
            (situation_day_coaching_view or {}).get("pattern_title")
            or (situation_day_coaching_view or {}).get("what_was_missing")
            or (situation_day_coaching_view or {}).get("what_happened")
            or original_focus.get("problem_statement")
            or ""
        ),
        limit=220,
    )
    result.update(
        {
            "original_score_focus": original_focus,
            "stage_id": _stage_funnel_label_for_code(situation_stage),
            "stage_code": situation_stage,
            "stage_name": str((situation_day_coaching_view or {}).get("stage_label") or "").strip()
            or situation_stage,
            "problem_signal": _focus_problem_signal(
                problem_statement,
                fallback=f"{selection_mode}_selected",
            ),
            "problem_statement": problem_statement,
            "challenge_metric_source": selection_mode,
            "focus_override_reason": selection_mode,
        }
    )
    return result


def _build_problem_wording_diagnostics(
    *,
    score_by_stage: list[dict[str, Any]],
    daily_focus: dict[str, Any],
    additional_situations: dict[str, Any] | None,
    situation_day_coaching_view: dict[str, Any] | None,
    call_breakdown: dict[str, Any] | None,
) -> dict[str, Any]:
    """Expose warnings when problem wording needed normalization or still looks unsafe."""
    warnings: list[dict[str, Any]] = []
    normalized_count = 0

    def add_warning(source: str, value: Any, reason: str) -> None:
        text = _first_sentence(str(value or ""), limit=220)
        if text:
            warnings.append({"source": source, "reason": reason, "text": text})

    for stage in score_by_stage:
        for reason in stage.get("problem_wording_warnings") or []:
            add_warning(f"score_by_stage.{stage.get('stage_code')}", stage.get("problem_normalized_from") or stage.get("problem_summary"), str(reason))
            normalized_count += 1
        if _problem_statement_is_positive_or_neutral(str(stage.get("problem_summary") or "")):
            add_warning(f"score_by_stage.{stage.get('stage_code')}", stage.get("problem_summary"), "positive_or_neutral_problem_wording")

    if daily_focus.get("problem_normalized_from"):
        add_warning("daily_coaching_focus.problem_statement", daily_focus.get("problem_normalized_from"), "positive_or_neutral_problem_wording_normalized")
        normalized_count += 1
    if _problem_statement_is_positive_or_neutral(str(daily_focus.get("problem_statement") or "")):
        add_warning("daily_coaching_focus.problem_statement", daily_focus.get("problem_statement"), "positive_or_neutral_problem_wording")

    for item in (additional_situations or {}).get("situations") or []:
        if str(item.get("kind") or "") != "gap":
            continue
        item_warnings = [str(reason) for reason in item.get("problem_wording_warnings") or []]
        if item.get("title_normalized_from"):
            add_warning(
                "additional_situations.title",
                item.get("title_normalized_from"),
                "positive_or_neutral_problem_wording_normalized",
            )
            normalized_count += 1
        if item.get("body_normalized_from"):
            add_warning(
                "additional_situations.body",
                item.get("body_normalized_from"),
                "positive_or_neutral_problem_wording_normalized",
            )
            normalized_count += 1
        if item_warnings and not item.get("title_normalized_from") and not item.get("body_normalized_from"):
            for reason in item_warnings:
                add_warning("additional_situations.title", item.get("title"), reason)
                normalized_count += 1
        title = str(item.get("title") or "")
        body = " ".join(str(item.get(key) or "") for key in ("client_said", "interpretation", "meant"))
        if _problem_statement_is_positive_or_neutral(title):
            add_warning("additional_situations.title", title, "positive_gap_title")
        if _problem_statement_is_positive_or_neutral(body):
            add_warning("additional_situations.body", body, "positive_gap_body")

    for source, block, key in (
        ("situation_day.what_happened", situation_day_coaching_view or {}, "what_happened"),
        ("call_breakdown.rows", call_breakdown or {}, "rows"),
    ):
        if key == "rows":
            for row in block.get("rows") or []:
                text = str(row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else "")
                if _problem_statement_is_positive_or_neutral(text):
                    add_warning(source, text, "positive_or_neutral_problem_wording")
        elif _problem_statement_is_positive_or_neutral(str(block.get(key) or "")):
            add_warning(source, block.get(key), "positive_or_neutral_problem_wording")

    return {
        "status": "warning" if warnings else "passed",
        "normalized_count": normalized_count,
        "warnings": warnings,
    }


ADDITIONAL_SITUATION_GENERIC_TEXT_MARKERS = (
    "клиент не получил достаточно конкретики или фиксации следующего шага",
    "задать уточняющий вопрос, затем зафиксировать конкретный следующий шаг и дедлайн",
    "конкретика снижает зависание звонка",
    "ситуация повторяется в нескольких звонках",
    "подтверждено в нескольких звонках",
    "выявлено в нескольких звонках",
    "хорошо отработано в нескольких звонках",
)


def _additional_stage_profile(stage_code: str | None) -> dict[str, str]:
    code = str(stage_code or "").strip()
    if code == "contact_start":
        return {
            "why_it_matters": "Проблема в первичном контакте снижает доверие: клиенту неясно, кто звонит, зачем и почему разговор уместен сейчас.",
            "next_action": "Коротко подтвердить компанию, повод контакта и удобство разговора, затем связать вопрос с задачей клиента.",
            "why_this_works": "Так менеджер снимает барьер доверия и получает разрешение продолжить диалог.",
        }
    if code == "qualification_primary":
        return {
            "why_it_matters": "Без роли, текущего процесса и потребности предложение звучит преждевременно и хуже попадает в задачу клиента.",
            "next_action": "Уточнить роль собеседника, текущий процесс и критерий решения до предложения продукта.",
            "why_this_works": "Квалификация помогает привязать следующий шаг к реальной задаче клиента, а не к общей презентации.",
        }
    if code == "needs_discovery":
        return {
            "why_it_matters": "Если конкретные сценарии использования не раскрыты, менеджер не понимает, какой результат клиент хочет получить.",
            "next_action": "Задать 2-3 вопроса о сценариях, участниках процесса и критериях успеха перед рекомендацией решения.",
            "why_this_works": "Так предложение становится ответом на конкретный сценарий клиента и меньше звучит как шаблонная презентация.",
        }
    if code == "presentation":
        return {
            "why_it_matters": "Презентация без связи с задачей клиента перегружает разговор и не помогает принять решение.",
            "next_action": "Показывать только те возможности продукта, которые прямо закрывают выявленную задачу клиента.",
            "why_this_works": "Короткая привязка функции к боли клиента делает предложение понятнее и повышает шанс на следующий шаг.",
        }
    if code == "objection_handling":
        return {
            "why_it_matters": "Неразобранное сомнение остаётся барьером для следующего шага, даже если клиент продолжает слушать.",
            "next_action": "Уточнить причину сомнения, подтвердить её и ответить на конкретный риск клиента.",
            "why_this_works": "Разбор причины возражения показывает, что менеджер слышит клиента и работает с реальным барьером.",
        }
    if code == "completion_next_step":
        return {
            "why_it_matters": "Без даты, канала или ответственного договорённость остаётся открытой и легко теряется после звонка.",
            "next_action": "Зафиксировать конкретный следующий шаг: канал, срок возврата и кто что делает до следующего контакта.",
            "why_this_works": "Конкретная фиксация переводит интерес в управляемый follow-up и снижает риск зависания.",
        }
    return {
        "why_it_matters": "Ситуация влияет на качество диалога и требует отдельного разбора с менеджером.",
        "next_action": "Разобрать evidence, уточнить недостающий шаг и закрепить один конкретный способ улучшения.",
        "why_this_works": "Так дополнительный паттерн становится понятным действием, а не общей заметкой.",
    }


def _additional_text_is_generic(value: Any) -> bool:
    normalized = _summary_norm(value)
    if not normalized:
        return True
    if len(normalized) < 18:
        return True
    return any(marker in normalized for marker in ADDITIONAL_SITUATION_GENERIC_TEXT_MARKERS)


def _additional_concrete_context(value: Any) -> str:
    text = _first_sentence(str(value or ""), limit=220).strip()
    if not text or _additional_text_is_generic(text):
        return ""
    return text


def _additional_confidence(*, evidence_quality: str, evidence_quote: str, context: str) -> str:
    quality = str(evidence_quality or "").strip().lower()
    if quality == "direct" and evidence_quote:
        return "high"
    if quality in {"direct", "indirect"} and (evidence_quote or context):
        return "medium"
    if quality == "weak" and (evidence_quote or context):
        return "medium"
    return "low"


def _additional_quality_reason_counts(filtered: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in filtered:
        for reason in item.get("reasons") or []:
            key = str(reason)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _apply_additional_situations_quality_gate(
    *,
    additional_situations: dict[str, Any],
    data_scope: dict[str, Any],
    daily_focus: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Filter additional situations that are generic, duplicated, or not evidence/context-backed."""
    candidates = [dict(item or {}) for item in (additional_situations or {}).get("situations") or []]
    rendered: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    scope = dict(data_scope or {})
    scope_code = str(scope.get("code") or MANAGER_DAILY_DATA_SCOPE_REPORT_DAY)

    for index, candidate in enumerate(candidates, start=1):
        item = dict(candidate)
        reasons: list[str] = []
        kind = str(item.get("kind") or "gap").strip() or "gap"
        stage_code = str(item.get("stage_code") or _daily_focus_stage_code(daily_focus) or "").strip()
        profile = _additional_stage_profile(stage_code)
        title = _first_sentence(str(item.get("title") or ""), limit=140).rstrip(".")
        evidence_quote = _additional_concrete_context(item.get("evidence_quote"))
        what_happened = _additional_concrete_context(
            item.get("what_happened")
            or item.get("client_said")
            or evidence_quote
            or item.get("interpretation")
        )
        why_it_matters = _first_sentence(str(item.get("why_it_matters") or item.get("meant") or item.get("interpretation") or ""), limit=220)
        next_action = _first_sentence(str(item.get("next_action") or item.get("how_to") or ""), limit=220)
        why_this_works = _first_sentence(str(item.get("why_this_works") or item.get("why") or ""), limit=220)

        if kind == "gap":
            if _additional_text_is_generic(why_it_matters):
                why_it_matters = profile["why_it_matters"]
            if _additional_text_is_generic(next_action):
                next_action = profile["next_action"]
            if _additional_text_is_generic(why_this_works):
                why_this_works = profile["why_this_works"]

        has_specific_context = bool(
            what_happened
            and (
                item.get("evidence_call_id")
                or item.get("client_call_reference")
                or str(item.get("source") or "").startswith("report_evidence")
            )
        )
        if not evidence_quote and not has_specific_context:
            reasons.append("missing_evidence")
        if kind == "gap" and (
            _problem_statement_is_positive_or_neutral(title)
            or _problem_statement_is_positive_or_neutral(what_happened)
        ):
            reasons.append("title_body_mismatch")
        if _additional_text_is_generic(why_it_matters) or _additional_text_is_generic(next_action):
            reasons.append("generic_wording")

        problem_signal = str(item.get("problem_signal") or "").strip() or _focus_problem_signal(
            " ".join(part for part in (stage_code, title) if part),
            fallback=stage_code or f"additional_{index}",
        )
        if problem_signal in seen_signals:
            reasons.append("duplicate_signal")

        confidence = str(item.get("confidence") or "").strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = _additional_confidence(
                evidence_quality=str(item.get("evidence_quality") or ""),
                evidence_quote=evidence_quote,
                context=what_happened,
            )
        if confidence == "low":
            reasons.append("low_confidence")

        if reasons:
            filtered.append(
                {
                    "title": title or str(item.get("title") or ""),
                    "problem_signal": problem_signal,
                    "source": item.get("source"),
                    "reasons": sorted(set(reasons)),
                }
            )
            continue

        seen_signals.add(problem_signal)
        item.update(
            {
                "kind": kind,
                "title": title,
                "stage_id": _stage_funnel_label_for_code(stage_code),
                "stage_code": stage_code,
                "problem_signal": problem_signal,
                "data_scope": scope_code,
                "data_scope_details": scope,
                "evidence_call_id": str(item.get("evidence_call_id") or "").strip() or None,
                "evidence_quote": evidence_quote or None,
                "what_happened": what_happened,
                "why_it_matters": why_it_matters,
                "next_action": next_action,
                "why_this_works": why_this_works,
                "confidence": confidence,
                # Render-model compatibility aliases.
                "client_said": what_happened,
                "meant": why_it_matters,
                "how_to": next_action,
                "why": why_this_works,
            }
        )
        rendered.append(item)

    result = dict(additional_situations or {})
    result["situations"] = rendered[:3]
    result["is_placeholder"] = False
    if not rendered:
        result["hidden_reason"] = "quality_gate_no_valid_situations"

    diagnostics = {
        "status": "passed" if not filtered else ("hidden" if not rendered and candidates else "warning"),
        "input_count": len(candidates),
        "rendered_count": len(rendered[:3]),
        "filtered_count": len(filtered),
        "filtered_reasons": _additional_quality_reason_counts(filtered),
        "filtered": filtered,
        "rendered_situations": [
            {
                "title": item.get("title"),
                "stage_id": item.get("stage_id"),
                "problem_signal": item.get("problem_signal"),
                "confidence": item.get("confidence"),
                "source": item.get("source"),
            }
            for item in rendered[:3]
        ],
    }
    return result, diagnostics


def build_manager_daily_payload(
    *,
    department_id: str,
    department_name: str,
    artifacts: list[ReportArtifact],
    period: dict[str, str],
    filters: ReportRunFilters,
    mode: str,
    model_override: str | None,
    window_artifacts: list[ReportArtifact] | None = None,
) -> dict[str, Any]:
    """Build the normalized manager_daily payload."""
    manager = artifacts[0].manager
    manager_name = manager.name if manager is not None else _fallback_manager_name(artifacts[0])
    calls_count = len(artifacts)
    score_values = [_extract_score_percent(item.analysis) for item in artifacts]
    average_score = round(sum(score_values) / len(score_values), 1) if score_values else None
    recent_score = _latest_call_score(artifacts)
    level_counts = {"strong": 0, "baseline": 0, "problematic": 0}
    all_window_artifacts = window_artifacts if window_artifacts is not None else artifacts
    operational_day_artifacts = _filter_artifacts_by_period(
        artifacts=all_window_artifacts,
        period={
            "date_from": filters.date_from or period["date_from"],
            "date_to": filters.date_to or filters.date_from or period["date_to"],
        },
    )
    # Outcomes summary uses report-day meaningful calls (same source as call_list), not coaching_core.
    # This aligns ИТОГ ДНЯ and ДЕНЬГИ НА СТОЛЕ with the call list totals.
    operational_meaningful_artifacts = [
        a for a in operational_day_artifacts if _classify_meaningful_call(a)[0]
    ]
    report_evidence_index = _build_report_evidence_index(artifacts=operational_meaningful_artifacts)
    call_outcomes_summary = _build_call_outcomes_summary(artifacts=operational_meaningful_artifacts)
    unclassified_breakdown = _build_unclassified_breakdown(artifacts=operational_meaningful_artifacts)
    call_list = _build_meaningful_call_list(
        window_artifacts=operational_day_artifacts,
        report_evidence_index=report_evidence_index,
    )
    call_list_context_quality = _build_call_list_context_quality_diagnostics(call_list)
    call_list_by_interaction_id = _call_list_rows_by_interaction_id(call_list)
    coaching_content_artifacts = _filter_coaching_artifacts_by_final_outcome(
        artifacts=artifacts,
        call_list_by_interaction_id=call_list_by_interaction_id,
    )
    report_evidence_registry_items = build_report_evidence_registry(coaching_content_artifacts)
    report_bounds = _report_day_bounds(period=period, filters=filters)
    artifact_by_id = _artifact_by_interaction_id(coaching_content_artifacts)
    coaching_data_scope = _coaching_base_data_scope(
        artifacts=coaching_content_artifacts,
        period=period,
        filters=filters,
    )
    manager_facing_completeness = _build_manager_facing_completeness_gate(call_list=call_list)
    worked_items = _aggregate_finding_items(artifacts=coaching_content_artifacts, key="strengths")
    improve_items = _aggregate_finding_items(artifacts=coaching_content_artifacts, key="gaps")
    recommendation_cards = _aggregate_recommendation_cards(artifacts=coaching_content_artifacts)
    product_signal = _select_most_important_product_signal(coaching_content_artifacts)
    evidence_fragment = _select_evidence_fragment(coaching_content_artifacts)
    key_problem = _build_manager_daily_key_problem(
        improve_items=improve_items,
        artifacts=coaching_content_artifacts,
        calls_count=calls_count,
    )
    focus_dynamics = _build_focus_criterion_dynamics(
        artifacts=coaching_content_artifacts,
        improve_items=improve_items,
    )
    score_by_stage = _aggregate_stage_scores(artifacts=coaching_content_artifacts)
    daily_coaching_focus = _build_daily_coaching_focus(
        score_by_stage=score_by_stage,
        key_problem=key_problem,
        data_scope=coaching_data_scope,
    )
    (
        report_evidence_situation,
        situation_day_daily_composer_result,
        situation_day_daily_input,
    ) = _build_verified_situation_day_from_daily_composer(
        artifacts=coaching_content_artifacts,
        report_evidence_index=report_evidence_index,
        evidence_registry_items=report_evidence_registry_items,
    )
    situation_day_composer_result = None
    situation_evidence_quote = (report_evidence_situation or {}).get("evidence_quote")
    situation_day_coaching_view = (report_evidence_situation or {}).get("coaching_view")
    no_verified_situation_day = bool((report_evidence_situation or {}).get("no_verified_situation_day"))
    daily_coaching_focus = _maybe_override_daily_focus_from_situation(
        daily_focus=daily_coaching_focus,
        situation_evidence_quote=situation_evidence_quote,
        situation_day_coaching_view=situation_day_coaching_view,
    )
    situation_selected_call_id = str((situation_evidence_quote or {}).get("call_id") or "").strip() or None
    report_block_routes = route_evidence_items(
        report_evidence_registry_items,
        selected_situation_call_id=situation_selected_call_id,
    )
    situation_rejected_call_ids = _situation_day_rejected_call_ids(report_evidence_situation)
    call_breakdown = _build_call_breakdown_from_evidence_registry_route(
        artifacts=coaching_content_artifacts,
        routed_items=report_block_routes.get("call_breakdown") or [],
        score_by_stage=score_by_stage,
    )
    if call_breakdown is None:
        call_breakdown = _build_call_breakdown_from_report_evidence(
            artifacts=coaching_content_artifacts,
            report_evidence_index=report_evidence_index,
            call_list_by_interaction_id=call_list_by_interaction_id,
            score_by_stage=score_by_stage,
            daily_focus=daily_coaching_focus,
            excluded_call_ids=situation_rejected_call_ids,
            preferred_call_id=situation_selected_call_id,
        )
    if call_breakdown is None:
        call_breakdown = _build_call_breakdown(
            improve_items=improve_items,
            artifacts=coaching_content_artifacts,
            daily_focus=daily_coaching_focus,
        )
    legacy_voice_of_customer = _build_voice_of_customer_from_report_evidence(
        artifacts=coaching_content_artifacts,
        report_evidence_index=report_evidence_index,
        call_list_by_interaction_id=call_list_by_interaction_id,
    )
    if legacy_voice_of_customer is None:
        legacy_voice_of_customer = _build_voice_of_customer(artifacts=coaching_content_artifacts)
    voice_of_customer = legacy_voice_of_customer
    composed_voice_of_customer = compose_voice_of_customer(
        coaching_content_artifacts,
        legacy_voice_of_customer=legacy_voice_of_customer,
        report_evidence_index=report_evidence_index,
    )
    if composed_voice_of_customer.get("status") == "verified":
        voice_of_customer = composed_voice_of_customer
    elif (
        composed_voice_of_customer.get("status") == "insufficient"
        and int(
            dict(composed_voice_of_customer.get("voice_of_customer_quality") or {}).get("input_count")
            or 0
        )
        > 0
    ):
        voice_of_customer = composed_voice_of_customer
    additional_situations = _build_additional_situations_from_report_evidence(
        artifacts=coaching_content_artifacts,
        report_evidence_index=report_evidence_index,
        call_list_by_interaction_id=call_list_by_interaction_id,
        top_situation_title=str((report_evidence_situation or {}).get("situation_title") or "").strip() or None,
    )
    if additional_situations is None:
        additional_situations = _build_additional_situations(
            improve_items=improve_items,
            worked_items=worked_items,
            top_gap_title=(improve_items[0]["label"] if improve_items else None),
        )
    call_tomorrow = _build_call_tomorrow(
        call_list=call_list,
        report_evidence_index=report_evidence_index,
    )
    call_report_summary_diagnostics = _build_call_report_summary_diagnostics(
        call_list=call_list,
        call_tomorrow=call_tomorrow,
        voice_of_customer=voice_of_customer,
    )
    if situation_evidence_quote is None and not no_verified_situation_day:
        situation_evidence_quote = _build_situation_evidence_quote(
            artifacts=coaching_content_artifacts,
            score_by_stage=score_by_stage,
            improve_items=improve_items,
        )
    if situation_evidence_quote is None and not no_verified_situation_day:
        situation_evidence_quote = _build_situation_evidence_quote_from_call_breakdown(
            artifacts=coaching_content_artifacts,
            call_breakdown=call_breakdown,
            score_by_stage=score_by_stage,
        )
    situation_dialogue_excerpt = (report_evidence_situation or {}).get("dialogue_excerpt")
    if situation_dialogue_excerpt is None and not no_verified_situation_day:
        situation_dialogue_excerpt = _build_situation_dialogue_excerpt(
            artifacts=coaching_content_artifacts,
            situation_evidence_quote=situation_evidence_quote,
        )
    focus_stage_deep_dive = _build_focus_stage_deep_dive(
        score_by_stage=score_by_stage,
        key_problem=key_problem,
        recommendations=recommendation_cards,
        daily_focus=daily_coaching_focus,
    )
    focus_stage_recommendation = _build_focus_stage_recommendation(
        focus_stage_deep_dive=focus_stage_deep_dive,
        recommendations=recommendation_cards,
    )
    if situation_dialogue_excerpt is None and not no_verified_situation_day:
        situation_dialogue_excerpt = _build_situation_dialogue_excerpt_from_call_breakdown(
            artifacts=coaching_content_artifacts,
            call_breakdown=call_breakdown,
        )
    if situation_day_coaching_view is None:
        situation_day_coaching_view = _build_situation_day_coaching_view(
            score_by_stage=score_by_stage,
            situation_evidence_quote=situation_evidence_quote,
            situation_dialogue_excerpt=situation_dialogue_excerpt,
            focus_stage_deep_dive=focus_stage_deep_dive,
            focus_stage_recommendation=focus_stage_recommendation,
        )
    situation_day_evidence_packet = _build_situation_day_evidence_packet(
        artifacts=coaching_content_artifacts,
        situation_evidence_quote=situation_evidence_quote,
        situation_day_coaching_view=situation_day_coaching_view,
    )
    if situation_day_evidence_packet is not None and situation_day_evidence_packet.get("status") == "verified":
        situation_dialogue_excerpt = dict(situation_day_evidence_packet.get("dialogue_excerpt") or {})
        if situation_day_coaching_view is not None:
            situation_day_coaching_view = {
                **situation_day_coaching_view,
                "evidence_packet": situation_day_evidence_packet,
                "proof_strength": situation_day_evidence_packet.get("proof_strength"),
                "situation_day_evidence_status": "verified",
                "customer_context": situation_day_evidence_packet.get("customer_context"),
                "customer_reaction": situation_day_evidence_packet.get("customer_reaction"),
                "causal_link": situation_day_evidence_packet.get("causal_link"),
            }
    elif situation_day_coaching_view is not None and (
        str(situation_day_coaching_view.get("source") or "").startswith("report_evidence")
        or str((situation_evidence_quote or {}).get("source") or "").startswith("report_evidence")
    ):
        insufficiency_reason = str(
            (situation_day_evidence_packet or {}).get("insufficiency_reason")
            or "situation_day_verified_packet_missing"
        )
        situation_day_coaching_view = _build_situation_day_insufficient_view(
            reason=insufficiency_reason,
            previous_view=situation_day_coaching_view,
        )
        situation_dialogue_excerpt = None
    situation_day_coaching_view = _apply_situation_day_writer(
        report_evidence_situation=report_evidence_situation,
        situation_evidence_quote=situation_evidence_quote,
        situation_dialogue_excerpt=situation_dialogue_excerpt,
        situation_day_evidence_packet=situation_day_evidence_packet,
        situation_day_coaching_view=situation_day_coaching_view,
    )
    if (
        situation_day_evidence_packet is not None
        and situation_day_evidence_packet.get("status") == "verified"
        and situation_day_coaching_view is not None
    ):
        situation_day_evidence_packet = {
            **situation_day_evidence_packet,
            "observed_manager_behavior": situation_day_coaching_view.get("what_happened")
            or situation_day_evidence_packet.get("observed_manager_behavior"),
            "missing_action": situation_day_coaching_view.get("manager_error")
            or situation_day_coaching_view.get("what_was_missing")
            or situation_day_evidence_packet.get("missing_action"),
            "causal_link": situation_day_coaching_view.get("evidence_explanation")
            or situation_day_coaching_view.get("meaning")
            or situation_day_evidence_packet.get("causal_link"),
            "manager_lesson": situation_day_coaching_view.get("next_time_action")
            or situation_day_evidence_packet.get("manager_lesson"),
        }
    situation_call_id_for_breakdown = str(
        ((situation_day_evidence_packet or {}).get("dialogue_excerpt") or {}).get("call_id")
        or (situation_evidence_quote or {}).get("call_id")
        or ""
    ).strip()
    call_breakdown_call_id = str((call_breakdown or {}).get("call_id") or "").strip()
    if (
        situation_day_evidence_packet is not None
        and situation_day_evidence_packet.get("status") == "verified"
        and situation_call_id_for_breakdown
    ):
        composer_breakdown = compose_call_breakdown_from_situation(
            artifacts=coaching_content_artifacts,
            situation_day_evidence_packet=situation_day_evidence_packet,
            situation_day_coaching_view=situation_day_coaching_view,
            score_by_stage=score_by_stage,
        )
        if (
            composer_breakdown is not None
            and str(composer_breakdown.get("call_id") or "").strip() == situation_call_id_for_breakdown
            and composer_breakdown.get("rows")
        ):
            call_breakdown = composer_breakdown
        elif (
            not call_breakdown
            or call_breakdown_call_id != situation_call_id_for_breakdown
            or call_breakdown_call_id in situation_rejected_call_ids
        ):
            situation_packet_breakdown = _build_call_breakdown_from_situation_day_packet(
                situation_day_evidence_packet=situation_day_evidence_packet,
                situation_day_coaching_view=situation_day_coaching_view,
            )
            if situation_packet_breakdown is not None:
                call_breakdown = situation_packet_breakdown
    situation_data_scope = _reference_call_scope(
        refs=[
            situation_evidence_quote,
            situation_dialogue_excerpt,
            dict(key_problem.get("call_example") or {}),
        ],
        artifact_by_id=artifact_by_id,
        report_bounds=report_bounds,
        fallback=coaching_data_scope,
    )
    call_breakdown_data_scope = _block_call_scope(
        block=call_breakdown,
        artifact_by_id=artifact_by_id,
        report_bounds=report_bounds,
        fallback=coaching_data_scope,
    )
    key_problem = _with_data_scope(key_problem, coaching_data_scope)
    call_breakdown = _with_data_scope(call_breakdown, call_breakdown_data_scope)
    call_breakdown, call_breakdown_quality = _apply_call_breakdown_quality_gate(
        call_breakdown=call_breakdown,
        daily_focus=daily_coaching_focus,
    )
    additional_situations = _with_data_scope(additional_situations, coaching_data_scope)
    additional_situations, additional_situations_quality = _apply_additional_situations_quality_gate(
        additional_situations=additional_situations,
        data_scope=coaching_data_scope,
        daily_focus=daily_coaching_focus,
    )
    if situation_day_coaching_view is not None:
        situation_day_coaching_view = _with_data_scope(situation_day_coaching_view, situation_data_scope)
    call_breakdown = _reduce_situation_call_breakdown_repetition(
        situation_day_coaching_view=situation_day_coaching_view,
        situation_evidence_quote=situation_evidence_quote,
        call_breakdown=call_breakdown,
    )
    daily_coaching_focus = _finalize_daily_coaching_focus(
        daily_focus=daily_coaching_focus,
        situation_evidence_quote=situation_evidence_quote,
        situation_day_coaching_view=situation_day_coaching_view,
        call_breakdown=call_breakdown,
    )
    semantic_case_block_sources = _build_semantic_case_block_sources(
        index=report_evidence_index,
        situation_evidence_quote=situation_evidence_quote,
        situation_day_coaching_view=situation_day_coaching_view,
        call_breakdown=call_breakdown,
        call_breakdown_quality=call_breakdown_quality,
        voice_of_customer=voice_of_customer,
        additional_situations=additional_situations,
        call_tomorrow=call_tomorrow,
    )
    report_evidence_diagnostics = _build_report_evidence_diagnostics(
        index=report_evidence_index,
        semantic_case_used_call_ids=_semantic_case_used_call_ids_from_block_sources(semantic_case_block_sources),
        semantic_case_block_sources=semantic_case_block_sources,
    )
    report_evidence_registry_diagnostics = _build_report_evidence_registry_diagnostics(
        evidence_items=report_evidence_registry_items,
        report_block_routes=report_block_routes,
    )
    problem_wording_diagnostics = _build_problem_wording_diagnostics(
        score_by_stage=score_by_stage,
        daily_focus=daily_coaching_focus,
        additional_situations=additional_situations,
        situation_day_coaching_view=situation_day_coaching_view,
        call_breakdown=call_breakdown,
    )
    for artifact in artifacts:
        bucket = _score_bucket(artifact.analysis)
        level_counts[bucket] += 1

    payload = {
        "meta": _build_base_meta(
            preset="manager_daily",
            department_id=department_id,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
            artifacts=artifacts,
            group_key=f"manager_daily:{artifacts[0].interaction.manager_id}:{period['date_from']}",
        ),
        "header": {
            "report_title": "Ежедневный разбор звонков",
            "manager_id": str(artifacts[0].interaction.manager_id) if artifacts[0].interaction.manager_id else None,
            "manager_name": manager_name,
            "report_date": _format_period_label(period),
            "department_name": department_name,
            "department_id": department_id,
            "product_or_business_context": None,
        },
        "focus_of_week": {
            "text": _build_focus_of_week(improve_items=improve_items, worked_items=worked_items),
            "is_placeholder": False if improve_items or worked_items else True,
        },
        "kpi_overview": {
            "calls_count": calls_count,
            "average_score": average_score,
            "strong_calls_pct": _pct(level_counts["strong"], calls_count),
            "baseline_calls_pct": _pct(level_counts["baseline"], calls_count),
            "problematic_calls_pct": _pct(level_counts["problematic"], calls_count),
            "score_vs_period_avg": recent_score,
            "delta_vs_period_avg": round(recent_score - average_score, 1)
            if recent_score is not None and average_score is not None
            else None,
            "interpretation_label": _performance_label(average_score),
        },
        "narrative_day_conclusion": {
            "text": _build_manager_daily_narrative(
                manager_name=manager_name,
                average_score=average_score,
                calls_count=calls_count,
                worked_items=worked_items,
                improve_items=improve_items,
            ),
            "source": "deterministic_fallback",
            "model_dependent": True,
        },
        "signal_of_day": {
            "call_time": _best_call_time(artifacts),
            "client_or_phone_mask": _best_contact(artifacts),
            "short_evidence": _best_signal_text(artifacts, evidence_fragment=evidence_fragment),
            "reason_this_matters": _build_signal_reason(
                product_signal=product_signal,
                worked_items=worked_items,
            ),
            "is_placeholder": False if artifacts else True,
        },
        "main_focus_for_tomorrow": {
            "text": _build_main_focus(
                improve_items=improve_items,
                recommendation_cards=recommendation_cards,
            ),
            "source": "deterministic_fallback",
            "model_dependent": True,
        },
        "analysis_worked": worked_items,
        "analysis_improve": improve_items,
        "key_problem_of_day": key_problem,
        "call_breakdown": call_breakdown,
        "voice_of_customer": voice_of_customer,
        "additional_situations": additional_situations,
        "call_tomorrow": call_tomorrow,
        "recommendations": recommendation_cards,
        "call_outcomes_summary": call_outcomes_summary,
        "unclassified_breakdown": unclassified_breakdown,
        "call_list_context_quality": call_list_context_quality,
        "manager_facing_completeness": manager_facing_completeness,
        "score_by_stage": score_by_stage,
        "situation_evidence_quote": situation_evidence_quote,
        "situation_dialogue_excerpt": situation_dialogue_excerpt,
        "situation_day_evidence_packet": situation_day_evidence_packet,
        "focus_stage_deep_dive": focus_stage_deep_dive,
        "focus_stage_recommendation": focus_stage_recommendation,
        "situation_day_coaching_view": situation_day_coaching_view,
        "situation_day_composer_result": situation_day_composer_result,
        "situation_day_daily_composer_result": situation_day_daily_composer_result,
        "situation_day_daily_input_diagnostics": dict(
            (situation_day_daily_input or {}).get("diagnostics") or {}
        ),
        "daily_coaching_focus": daily_coaching_focus,
        "daily_coaching_focus_validation": dict(daily_coaching_focus.get("validation") or {}),
        "problem_wording_diagnostics": problem_wording_diagnostics,
        "additional_situations_quality": additional_situations_quality,
        "call_breakdown_quality": call_breakdown_quality,
        "coaching_data_scope": coaching_data_scope,
        "data_scopes": {
            "coaching_base": coaching_data_scope,
            "situation_day": situation_data_scope,
            "call_breakdown": call_breakdown_data_scope,
            "additional_situations": coaching_data_scope,
            "challenge": coaching_data_scope,
        },
        "report_evidence_diagnostics": report_evidence_diagnostics,
        "report_evidence_registry_diagnostics": report_evidence_registry_diagnostics,
        "report_block_router_diagnostics": report_block_routes.get("diagnostics"),
        "call_report_summary_diagnostics": call_report_summary_diagnostics,
        "call_list": call_list,
        "focus_criterion_dynamics": focus_dynamics,
        "memo_legend": {
            "call_level_legend": ["strong", "baseline", "problematic"],
            "call_status_legend": ["agreed", "rescheduled", "refusal", "open"],
            "recommendation_priority_legend": ["Сделай завтра", "На неделе"],
        },
        "delivery_meta": {
            "email_subject": f"Ежедневный разбор звонков — {manager_name} — {_format_period_label(period)}",
            "render_variant": f"template_pdf_{get_active_template_version('manager_daily')}",
        },
        "editorial_recommendations": {
            "text": _build_manager_daily_editorial_recommendations(
                recommendation_cards=recommendation_cards,
            ),
        },
        "selection_model": _build_selection_model_counters(
            window_artifacts=operational_day_artifacts,
            usable_artifacts=artifacts,
        ),
    }
    payload["meta"]["report_evidence"] = report_evidence_diagnostics["summary"]
    return payload


def _filter_artifacts_by_period(*, artifacts: list[ReportArtifact], period: dict[str, str]) -> list[ReportArtifact]:
    """Return artifacts whose call date belongs to the requested operational report period."""
    try:
        date_from = date.fromisoformat(period["date_from"])
        date_to = date.fromisoformat(period["date_to"])
    except (KeyError, TypeError, ValueError):
        return artifacts

    selected: list[ReportArtifact] = []
    for artifact in artifacts:
        if artifact.call_started_at is None:
            selected.append(artifact)
            continue
        call_day = artifact.call_started_at.date()
        if date_from <= call_day <= date_to:
            selected.append(artifact)
    return selected


def _date_bounds_from_period(period: dict[str, str] | None) -> tuple[date, date] | None:
    """Return date bounds from a normalized period dict, if parseable."""
    if not period:
        return None
    try:
        date_from = date.fromisoformat(str(period.get("date_from") or ""))
        raw_to = str(period.get("date_to") or period.get("date_from") or "")
        date_to = date.fromisoformat(raw_to)
    except (TypeError, ValueError):
        return None
    return date_from, date_to


def _report_day_bounds(*, period: dict[str, str], filters: ReportRunFilters) -> tuple[date, date] | None:
    """Return the operational report-day bounds, preferring explicit user filters."""
    filtered_period = {
        "date_from": filters.date_from or period.get("date_from") or "",
        "date_to": filters.date_to or filters.date_from or period.get("date_to") or period.get("date_from") or "",
    }
    return _date_bounds_from_period(filtered_period)


def _artifact_call_day(artifact: ReportArtifact) -> date | None:
    if artifact.call_started_at is not None:
        return artifact.call_started_at.date()
    metadata = dict(getattr(artifact.interaction, "metadata_", None) or {})
    parsed = parse_call_started_at(metadata)
    return parsed.date() if parsed is not None else None


def _date_in_bounds(value: date | None, bounds: tuple[date, date] | None) -> bool:
    if value is None or bounds is None:
        return True
    return bounds[0] <= value <= bounds[1]


def _coaching_base_data_scope(
    *,
    artifacts: list[ReportArtifact],
    period: dict[str, str],
    filters: ReportRunFilters,
) -> dict[str, Any]:
    """Describe whether coaching blocks use report-day or expanded data."""
    report_bounds = _report_day_bounds(period=period, filters=filters)
    effective_bounds = _date_bounds_from_period(period)
    call_days = sorted({day for artifact in artifacts if (day := _artifact_call_day(artifact)) is not None})
    base_from = call_days[0].isoformat() if call_days else None
    base_to = call_days[-1].isoformat() if call_days else None
    report_from = report_bounds[0].isoformat() if report_bounds else None
    report_to = report_bounds[1].isoformat() if report_bounds else None
    has_non_report_day = any(not _date_in_bounds(day, report_bounds) for day in call_days)

    code = MANAGER_DAILY_DATA_SCOPE_REPORT_DAY
    if has_non_report_day:
        if effective_bounds and report_bounds and effective_bounds != report_bounds:
            code = MANAGER_DAILY_DATA_SCOPE_ROLLING_WINDOW
        else:
            code = MANAGER_DAILY_DATA_SCOPE_EXPANDED_COACHING_BASE

    return {
        "code": code,
        "report_date_from": report_from,
        "report_date_to": report_to,
        "base_date_from": base_from or report_from,
        "base_date_to": base_to or report_to,
        "base_days_count": len(call_days) or (1 if report_from else 0),
        "base_calls_count": len(artifacts),
    }


def _call_data_scope(
    *,
    artifact: ReportArtifact | None,
    report_bounds: tuple[date, date] | None,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Return data scope for a block tied to one selected call."""
    if artifact is None:
        return dict(fallback)
    day = _artifact_call_day(artifact)
    code = (
        MANAGER_DAILY_DATA_SCOPE_REPORT_DAY
        if _date_in_bounds(day, report_bounds)
        else MANAGER_DAILY_DATA_SCOPE_EXPANDED_COACHING_BASE
    )
    result = dict(fallback)
    result.update(
        {
            "code": code,
            "selected_call_date": day.isoformat() if day else None,
            "selected_call_id": str(artifact.interaction.id),
        }
    )
    return result


def _artifact_by_interaction_id(artifacts: list[ReportArtifact]) -> dict[str, ReportArtifact]:
    return {str(artifact.interaction.id): artifact for artifact in artifacts}


def _block_call_scope(
    *,
    block: dict[str, Any] | None,
    artifact_by_id: dict[str, ReportArtifact],
    report_bounds: tuple[date, date] | None,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Return data scope for a payload block that may carry a selected call_id."""
    if not block:
        return dict(fallback)
    call_id = str(block.get("call_id") or "").strip()
    artifact = artifact_by_id.get(call_id) if call_id else None
    return _call_data_scope(artifact=artifact, report_bounds=report_bounds, fallback=fallback)


def _reference_call_scope(
    *,
    refs: list[dict[str, Any] | None],
    artifact_by_id: dict[str, ReportArtifact],
    report_bounds: tuple[date, date] | None,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Return data scope from the first reference with a known call_id."""
    for ref in refs:
        if not ref:
            continue
        call_id = str(ref.get("call_id") or "").strip()
        artifact = artifact_by_id.get(call_id) if call_id else None
        if artifact is not None:
            return _call_data_scope(artifact=artifact, report_bounds=report_bounds, fallback=fallback)
    return dict(fallback)


def _with_data_scope(block: dict[str, Any] | None, scope: dict[str, Any]) -> dict[str, Any]:
    """Attach manager_daily block data scope without mutating caller-owned dicts."""
    result = dict(block or {})
    result["data_scope"] = str(scope.get("code") or MANAGER_DAILY_DATA_SCOPE_REPORT_DAY)
    result["data_scope_details"] = dict(scope)
    return result


def build_rop_weekly_payload(
    *,
    department_id: str,
    department_name: str,
    artifacts: list[ReportArtifact],
    period: dict[str, str],
    filters: ReportRunFilters,
    mode: str,
    model_override: str | None,
) -> dict[str, Any]:
    """Build the normalized rop_weekly payload."""
    by_manager: dict[str, list[ReportArtifact]] = {}
    for artifact in artifacts:
        key = str(artifact.interaction.manager_id or "unmapped")
        by_manager.setdefault(key, []).append(artifact)

    dashboard_rows = [_build_weekly_dashboard_row(group) for _, group in sorted(by_manager.items())]
    risk_zone_cards = [
        _build_risk_zone_card(group)
        for group in by_manager.values()
        if _build_weekly_dashboard_row(group)["status_signal"] in {"Наблюдение", "Зона риска"}
    ]
    systemic_team_problems = _build_systemic_problems(artifacts)
    top_block, anti_top_block = _build_top_blocks(dashboard_rows)
    current_period_score = round(
        sum(row["average_score"] for row in dashboard_rows if row["average_score"] is not None)
        / max(1, len([row for row in dashboard_rows if row["average_score"] is not None])),
        1,
    ) if dashboard_rows else None
    payload = {
        "meta": _build_base_meta(
            preset="rop_weekly",
            department_id=department_id,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
            artifacts=artifacts,
            group_key=f"rop_weekly:{period['date_from']}:{period['date_to']}",
        ),
        "header": {
            "report_title": "Еженедельный отчёт",
            "subtitle": "Недельный управленческий обзор по качеству звонков команды продаж",
            "department_id": department_id,
            "department_name": department_name,
            "week_label": f"{period['date_from']}..{period['date_to']}",
            "date_range": period,
            "confidentiality_note": "Только для РОП и руководства",
        },
        "what_is_inside": [
            "dashboard",
            "week_over_week_dynamics",
            "risk_zones",
            "systemic_problems",
            "top_and_anti_top",
            "rop_tasks",
            "business_results_placeholder",
        ],
        "dashboard_rows": dashboard_rows,
        "week_over_week_dynamics": {
            "previous_period_score": None,
            "current_period_score": current_period_score,
            "delta": None,
            "trend": "n/a",
            "stage_level_deltas": [],
            "best_dynamics_commentary": _build_weekly_best_commentary(
                dashboard_rows=dashboard_rows,
                top_block=top_block,
            ),
            "alarming_dynamics_commentary": _build_weekly_alarm_commentary(
                anti_top_block=anti_top_block,
                systemic_team_problems=systemic_team_problems,
            ),
        },
        "risk_zone_cards": risk_zone_cards,
        "systemic_team_problems": systemic_team_problems,
        "top_block": top_block,
        "anti_top_block": anti_top_block,
        "rop_tasks_next_week": _build_rop_tasks(risk_zone_cards=risk_zone_cards, systemic_team_problems=systemic_team_problems),
        "business_results_placeholder": {
            "status": "placeholder",
            "reason": "crm_dependent_block_not_connected_in_manual_reporting_pilot_v1",
        },
        "leader_memo": {
            "status_signal_explanation": ["Эталон", "Растёт", "Стабильно", "Наблюдение", "Зона риска"],
            "trend_explanation": "Детальная динамика будет усилена после подключения устойчивой historical comparison базы.",
            "score_scale": "0-100",
            "action_priority_explanation": ["Критично", "Высокий", "Средний", "Поддержка"],
        },
        "delivery_meta": {
            "email_subject": f"Еженедельный отчёт РОП — {period['date_from']}..{period['date_to']}",
            "render_variant": f"template_pdf_{get_active_template_version('rop_weekly')}",
        },
    }
    payload["editorial_summary"] = {
        "executive_summary": _build_rop_weekly_executive_summary(
            department_name=department_name,
            dashboard_rows=dashboard_rows,
            current_period_score=current_period_score,
        ),
        "team_risks_wording": _build_rop_weekly_team_risks(
            systemic_team_problems=systemic_team_problems,
            anti_top_block=anti_top_block,
        ),
        "rop_tasks_wording": _build_rop_weekly_tasks_commentary(
            tasks=payload["rop_tasks_next_week"],
        ),
        "final_managerial_commentary": _build_rop_weekly_final_commentary(
            top_block=top_block,
            anti_top_block=anti_top_block,
        ),
    }
    return payload


def render_report_email(payload: dict[str, Any], *, prefer_docx_first: bool = False) -> dict[str, Any]:
    """Render the final operator artifact from versioned template assets."""
    return render_report_artifact(payload, prefer_docx_first=prefer_docx_first)


def _build_base_meta(
    *,
    preset: str,
    department_id: str,
    period: dict[str, str],
    filters: ReportRunFilters,
    mode: str,
    model_override: str | None,
    artifacts: list[ReportArtifact],
    group_key: str,
) -> dict[str, Any]:
    """Build stable report metadata for audit and reuse."""
    instruction_versions = sorted(
        {
            item.analysis.instruction_version
            for item in artifacts
            if item.analysis is not None and item.analysis.instruction_version
        }
    )
    return {
        "preset": preset,
        "schema_version": REPORTING_SCHEMA_VERSION,
        "report_logic_version": REPORTING_LOGIC_VERSION,
        "reuse_policy_version": REPORTING_REUSE_POLICY_VERSION,
        "checklist_version": APPROVED_CHECKLIST_VERSION,
        "template_version": get_active_template_version(preset),
        "template_id": get_active_template_version(preset),
        "render_variant": f"template_pdf_{get_active_template_version(preset)}",
        "generator_path": "app.agents.calls.report_templates.render_report_artifact",
        "generated_at": datetime.now(UTC).isoformat(),
        "department_id": department_id,
        "period": period,
        "mode": mode,
        "group_key": group_key,
        "filters": {
            "manager_ids": sorted(filters.manager_ids),
            "manager_extensions": sorted(filters.manager_extensions),
            "min_duration_sec": filters.min_duration_sec,
            "max_duration_sec": filters.max_duration_sec,
            "analysis_instruction_version": filters.analysis_instruction_version,
        },
        "report_composer": {
            "enabled": False,
            "selected_model": model_override,
            "status": "not_enabled_in_v1",
        },
        "effective_versions": {
            "schema_version": REPORTING_SCHEMA_VERSION,
            "report_logic_version": REPORTING_LOGIC_VERSION,
            "reuse_policy_version": REPORTING_REUSE_POLICY_VERSION,
            "checklist_version": APPROVED_CHECKLIST_VERSION,
            "template_version": get_active_template_version(preset),
            "template_id": get_active_template_version(preset),
            "render_variant": f"template_pdf_{get_active_template_version(preset)}",
            "generator_path": "app.agents.calls.report_templates.render_report_artifact",
            "analysis_instruction_versions": instruction_versions,
        },
        "reuse": {
            "report_payload_reused": False,
            "render_reused": False,
            "enough_for_reuse": {
                "transcript": all(bool(item.interaction.text) for item in artifacts),
                "analysis": all(_is_analysis_reusable_for_reporting(item.analysis)[0] for item in artifacts),
            },
            "rebuild_on_version_mismatch": [
                "report_payload",
                "readiness_decision",
                "rendered_artifact",
            ],
        },
        "source_artifacts": {
            "interaction_count": len(artifacts),
            "analysis_count": len([item for item in artifacts if item.analysis is not None]),
            "instruction_versions": instruction_versions,
        },
    }


_STAGE_FUNNEL_ORDER: list[tuple[str, str, str]] = [
    ("contact_start", "Э1", "Первичный контакт"),
    ("qualification_primary", "Э2", "Квалификация и первичная потребность"),
    ("needs_discovery", "Э3", "Выявление детальных потребностей"),
    ("presentation", "Э4", "Формирование предложения"),
    ("objection_handling", "Э5", "Работа с возражениями"),
    ("completion_next_step", "Э6", "Завершение и договорённости"),
    ("cross_stage_transition", "Сквозной", "Сквозной критерий"),
]

_CRITERION_STAGE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("cs_", "contact_start"),
    ("qp_", "qualification_primary"),
    ("nd_", "needs_discovery"),
    ("pr_", "presentation"),
    ("oh_", "objection_handling"),
    ("ns_", "completion_next_step"),
    ("cn_", "completion_next_step"),
    ("completion_", "completion_next_step"),
    ("cross_", "cross_stage_transition"),
)

POSITIVE_PROBLEM_WORDING_MARKERS = (
    "не ушел в презентац слишком рано",
    "не ушёл в презентац слишком рано",
    "не переходил к презентац слишком рано",
    "сохранил нейтральн",
    "сохранил вежлив",
    "представился",
    "обозначил компанию",
    "понятно обозначил причину",
)


def _stage_problem_fallback(stage_code: str | None, criterion_code: str | None = None) -> str:
    code = str(stage_code or "").strip()
    criterion = str(criterion_code or "").strip()
    if code == "contact_start":
        if criterion.startswith("cs_"):
            return "Повод звонка был объяснён недостаточно ясно."
        return "Первичный контакт не был связан с задачей клиента."
    if code == "qualification_primary":
        return "Квалификация не была завершена до предложения."
    if code == "needs_discovery":
        return "Потребность клиента не была раскрыта до предложения."
    if code == "presentation":
        return "Предложение не было связано с выявленной задачей клиента."
    if code == "objection_handling":
        return "Причина сомнения клиента не была разобрана."
    if code == "completion_next_step":
        return "Следующий шаг не был закреплён достаточно конкретно."
    return "Проблема требует уточнения по evidence."


def _specific_problem_rewrite(
    *,
    text: str,
    stage_code: str | None = None,
    criterion_code: str | None = None,
    criterion_name: str | None = None,
) -> str | None:
    normalized = _summary_norm(text)
    criterion_text = _summary_norm(f"{criterion_code or ''} {criterion_name or ''}")
    if "не уш" in normalized and "презентац" in normalized and "слишком рано" in normalized:
        if str(stage_code or "").strip() == "needs_discovery":
            return "Потребность клиента не была раскрыта до предложения."
        return "Квалификация не была завершена до предложения."
    if "сохранил" in normalized and any(marker in normalized for marker in ("нейтральн", "вежлив", "понятн")):
        return "Тон был вежливым, но не помог продвинуть разговор."
    if "представ" in normalized and ("компан" in normalized or "себ" in normalized):
        return "Повод звонка был объяснён недостаточно ясно."
    if "понятно обозначил" in normalized and "причин" in normalized:
        return "Причина звонка не была связана с задачей клиента."
    if "презентац" in criterion_text and "рано" in criterion_text:
        return _stage_problem_fallback(stage_code, criterion_code)
    return None


def _problem_statement_is_positive_or_neutral(text: str) -> bool:
    normalized = _summary_norm(text)
    if not normalized:
        return False
    if any(marker in normalized for marker in POSITIVE_PROBLEM_WORDING_MARKERS):
        return True
    positive_starts = (
        "менеджер сохранил",
        "менеджер представ",
        "менеджер обозначил",
        "менеджер понятно",
        "сохранил",
        "представ",
        "понятно обозначил",
    )
    if normalized.startswith(positive_starts):
        return True
    if normalized.startswith("не ") and any(marker in normalized for marker in ("слишком рано", "излишне", "давил")):
        return True
    return False


def _normalize_problem_statement(
    value: Any,
    *,
    stage_code: str | None = None,
    criterion_code: str | None = None,
    criterion_name: str | None = None,
    fallback: str | None = None,
) -> dict[str, Any]:
    """Return actionable manager-facing problem wording from persisted issue text."""
    original = re.sub(r"`[^`]+`", "", str(value or ""))
    original = re.sub(r"\b[a-z]{2,}_[a-z0-9_]+\b", "", original, flags=re.IGNORECASE)
    original = re.sub(r"\s+", " ", original).strip(" -–—:;")
    sentence_end = re.search(r"[.!?]\s+", original)
    if sentence_end:
        original = original[: sentence_end.start()].strip()
    if len(original) > 220:
        original = original[:220].rsplit(" ", 1)[0].strip()
    replacement = _specific_problem_rewrite(
        text=original,
        stage_code=stage_code,
        criterion_code=criterion_code,
        criterion_name=criterion_name,
    )
    warnings: list[str] = []
    if replacement:
        warnings.append("positive_or_neutral_problem_wording_normalized")
    elif _problem_statement_is_positive_or_neutral(original):
        replacement = fallback or _stage_problem_fallback(stage_code, criterion_code)
        warnings.append("positive_or_neutral_problem_wording_normalized")
    elif not original:
        replacement = fallback or _stage_problem_fallback(stage_code, criterion_code)
        warnings.append("missing_problem_wording_fallback")

    text = replacement or original
    return {
        "text": text,
        "source_text": original if text != original else None,
        "warnings": warnings,
    }


def _stage_code_from_criterion_code(criterion_code: str) -> str | None:
    """Resolve analyzer criterion_code prefix to report stage_code."""
    code = str(criterion_code or "").strip().lower()
    if not code:
        return None
    for prefix, stage_code in _CRITERION_STAGE_PREFIXES:
        if code.startswith(prefix):
            return stage_code
    return None


def _first_sentence(value: str, *, limit: int = 180) -> str:
    """Return one short manager-facing sentence without exposing raw codes."""
    text = re.sub(r"`[^`]+`", "", str(value or ""))
    text = re.sub(r"\b[a-z]{2,}_[a-z0-9_]+\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -–—:;")
    if not text:
        return ""
    sentence_end = re.search(r"(?<=[.!?])\s+", text)
    if sentence_end:
        text = text[: sentence_end.start()].strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _stage_problem_text_from_issue(
    issue: dict[str, Any],
    *,
    stage_code: str | None = None,
    criterion_code: str | None = None,
    criterion_name: str | None = None,
) -> dict[str, Any]:
    """Build one bounded stage problem sentence from already persisted analysis data."""
    for key in ("comment", "interpretation", "impact", "evidence", "title", "criterion_name"):
        text = _first_sentence(str(issue.get(key) or ""))
        if text:
            return _normalize_problem_statement(
                text,
                stage_code=stage_code,
                criterion_code=criterion_code,
                criterion_name=criterion_name,
            )
    return {"text": "", "source_text": None, "warnings": []}


def _aggregate_stage_scores(*, artifacts: list[ReportArtifact]) -> list[dict[str, Any]]:
    """Average per-call stage scores across all artifacts, ordered by funnel.

    Score scale: 0–10 (stage_score / max_stage_score * 10).
    Priority rule: first stage below 4.0 in funnel order is marked as priority.
    For the priority stage, criteria_detail is populated (avg per criterion, sorted asc).
    """
    stage_buckets: dict[str, list[float]] = {}
    crit_stage: dict[str, dict[str, list[float]]] = {}
    crit_names: dict[str, str] = {}
    stage_problem_candidates: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for stage in detail.get("score_by_stage") or []:
            code = str(stage.get("stage_code") or "")
            stage_score = int(stage.get("stage_score") or 0)
            max_score = int(stage.get("max_stage_score") or 0)
            if max_score > 0:
                stage_buckets.setdefault(code, []).append(round(stage_score / max_score * 10, 1))
            for crit in stage.get("criteria_results") or []:
                ccode = str(crit.get("criterion_code") or "").strip()
                cname = str(crit.get("criterion_name") or ccode).strip()
                cscore = int(crit.get("score") or 0)
                cmax = int(crit.get("max_score") or 0)
                if ccode and cmax > 0:
                    normalized = round(cscore / cmax * 10, 1)
                    crit_stage.setdefault(code, {}).setdefault(ccode, []).append(normalized)
                    crit_names.setdefault(ccode, cname)
                    normalized_problem = _stage_problem_text_from_issue(
                        dict(crit),
                        stage_code=code,
                        criterion_code=ccode,
                        criterion_name=cname,
                    )
                    candidate_text = str(normalized_problem.get("text") or "").strip()
                    if candidate_text:
                        stage_problem_candidates.setdefault(code, []).append(
                            {
                                "source": "criteria_comment",
                                "score": normalized,
                                "text": candidate_text,
                                "source_text": normalized_problem.get("source_text"),
                                "wording_warnings": list(normalized_problem.get("warnings") or []),
                                "criterion_code": ccode,
                                "criterion_name": cname,
                            }
                        )
        for item in detail.get("gaps") or []:
            item_code = str(item.get("criterion_code") or "").strip()
            stage_code = _stage_code_from_criterion_code(item_code)
            normalized_problem = _stage_problem_text_from_issue(
                dict(item),
                stage_code=stage_code,
                criterion_code=item_code,
                criterion_name=str(item.get("criterion_name") or item.get("title") or ""),
            )
            candidate_text = str(normalized_problem.get("text") or "").strip()
            if stage_code and candidate_text:
                stage_problem_candidates.setdefault(stage_code, []).append(
                    {
                        "source": "gap",
                        "score": 0.0,
                        "text": candidate_text,
                        "source_text": normalized_problem.get("source_text"),
                        "wording_warnings": list(normalized_problem.get("warnings") or []),
                        "criterion_code": item_code,
                        "criterion_name": str(item.get("criterion_name") or item.get("title") or "").strip(),
                    }
                )
        for item in detail.get("evidence_fragments") or []:
            item_code = str(item.get("criterion_code") or "").strip()
            stage_code = _stage_code_from_criterion_code(item_code)
            normalized_problem = _stage_problem_text_from_issue(
                dict(item),
                stage_code=stage_code,
                criterion_code=item_code,
            )
            candidate_text = str(normalized_problem.get("text") or "").strip()
            if stage_code and candidate_text:
                stage_problem_candidates.setdefault(stage_code, []).append(
                    {
                        "source": "evidence",
                        "score": 5.0,
                        "text": candidate_text,
                        "source_text": normalized_problem.get("source_text"),
                        "wording_warnings": list(normalized_problem.get("warnings") or []),
                        "criterion_code": item_code,
                        "criterion_name": "",
                    }
                )
    rows: list[dict[str, Any]] = []
    priority_found = False
    source_rank = {"criteria_comment": 0, "gap": 1, "evidence": 2, "fallback": 3}
    for stage_code, funnel_label, stage_name in _STAGE_FUNNEL_ORDER:
        scores = stage_buckets.get(stage_code)
        if not scores:
            continue
        avg = round(sum(scores) / len(scores), 1)
        is_priority = not priority_found and avg < 4.0
        if is_priority:
            priority_found = True
        criteria_detail: list[dict[str, Any]] | None = None
        if is_priority and crit_stage.get(stage_code):
            crits = []
            for ccode, cscores in crit_stage[stage_code].items():
                cavg = round(sum(cscores) / len(cscores), 1)
                crits.append({
                    "name": crit_names.get(ccode, ccode),
                    "score": cavg,
                    "is_weak": cavg < 5.0,
                })
            crits.sort(key=lambda x: x["score"])
            criteria_detail = crits[:5]
        problem_candidates = [
            item
            for item in stage_problem_candidates.get(stage_code, [])
            if str(item.get("text") or "").strip()
        ]
        problem_summary = None
        problem_source = None
        problem_normalized_from = None
        problem_wording_warnings: list[str] = []
        if problem_candidates:
            problem_candidates.sort(
                key=lambda item: (
                    float(item.get("score") if item.get("score") is not None else 10.0),
                    source_rank.get(str(item.get("source") or ""), 9),
                )
            )
            best_problem = problem_candidates[0]
            problem_summary = str(best_problem.get("text") or "").strip() or None
            problem_source = str(best_problem.get("source") or "").strip() or None
            problem_normalized_from = str(best_problem.get("source_text") or "").strip() or None
            problem_wording_warnings = list(best_problem.get("wording_warnings") or [])
        rows.append({
            "stage_code": stage_code,
            "funnel_label": funnel_label,
            "stage_name": stage_name,
            "score": avg,
            "is_priority": is_priority,
            "criteria_detail": criteria_detail,
            "problem_summary": problem_summary,
            "problem_source": problem_source,
            "problem_normalized_from": problem_normalized_from,
            "problem_wording_warnings": problem_wording_warnings,
        })
    return rows


def _build_situation_evidence_quote(
    *,
    artifacts: list[ReportArtifact],
    score_by_stage: list[dict[str, Any]],
    improve_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select one real dialogue fragment linked to the situation day's priority stage."""
    priority_stage = next((item for item in score_by_stage if item.get("is_priority")), None)
    priority_stage_code = str((priority_stage or {}).get("stage_code") or "").strip()
    if not priority_stage_code:
        return None

    key_problem_code = str((improve_items[0] if improve_items else {}).get("criterion_code") or "").strip()
    weak_criterion_codes: set[str] = set()
    candidates: list[tuple[int, float, datetime, dict[str, Any]]] = []

    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for stage in detail.get("score_by_stage") or []:
            if str(stage.get("stage_code") or "").strip() != priority_stage_code:
                continue
            for crit in stage.get("criteria_results") or []:
                ccode = str(crit.get("criterion_code") or "").strip()
                cscore = int(crit.get("score") or 0)
                cmax = int(crit.get("max_score") or 0)
                if ccode and cmax > 0 and round(cscore / cmax * 10, 1) < 5.0:
                    weak_criterion_codes.add(ccode)

        for frag in detail.get("evidence_fragments") or []:
            criterion_code = str(frag.get("criterion_code") or "").strip()
            stage_code = _stage_code_from_criterion_code(criterion_code)
            client_text = str(frag.get("client_text") or "").strip()
            if stage_code != priority_stage_code or len(client_text) < 5:
                continue

            manager_text = str(
                frag.get("manager_text")
                or frag.get("manager_phrase")
                or frag.get("manager")
                or ""
            ).strip() or None
            ref = _artifact_call_reference(artifact)
            rank = 2
            if key_problem_code and criterion_code == key_problem_code:
                rank = 0
            elif criterion_code in weak_criterion_codes:
                rank = 1
            score = _extract_score_percent(artifact.analysis)
            candidates.append(
                (
                    rank,
                    score,
                    artifact.call_started_at or datetime.max.replace(tzinfo=UTC),
                    {
                        "client_text": client_text,
                        "manager_text": manager_text,
                        "criterion_code": criterion_code,
                        "stage_code": stage_code,
                        "source": "evidence_fragments",
                        **ref,
                    },
                )
            )

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def _dialogue_norm(value: str) -> str:
    """Normalize text for safe quote matching without semantic guessing."""
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _dialogue_turn_text(value: str, *, limit: int = 320) -> str:
    """Keep a bounded dialogue line."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].strip() + "…"


_GREETING_ONLY_WORDS = {
    "а",
    "ага",
    "алло",
    "вас",
    "вечер",
    "говорить",
    "да",
    "день",
    "добрый",
    "здравствуйте",
    "меня",
    "минуту",
    "можно",
    "слышно",
    "слушаю",
    "секунду",
    "утро",
    "угу",
    "это",
    "я",
}

_CALL_START_BOILERPLATE_PHRASES = (
    "вас приветствует",
    "наберите внутренний номер",
    "дождитесь ответа",
    "все менеджеры заняты",
    "оставайтесь на линии",
    "главный эксперт по путешествиям",
    "турагентства",
    "забронировать тур",
    "оплачивая картой",
    "виза или мастер",
    "visa или master",
)

_BUSINESS_FRAGMENT_TERMS = (
    "акт",
    "бухгалтер",
    "ватсап",
    "whatsapp",
    "договор",
    "документ",
    "документооборот",
    "кп",
    "коммерчес",
    "контрагент",
    "лиценз",
    "оплат",
    "подключ",
    "подпис",
    "подписка",
    "потребност",
    "прайс",
    "рассматрива",
    "соглас",
    "стоимост",
    "счёт",
    "счет",
    "тариф",
    "цен",
    "эдо",
    "электрон",
)


def _dialogue_compact(value: str) -> str:
    return re.sub(r"[^\wа-яё]+", "", _dialogue_norm(value), flags=re.IGNORECASE)


def _business_fragment_signal_count(text: str) -> int:
    normalized = _dialogue_norm(text)
    return sum(1 for term in _BUSINESS_FRAGMENT_TERMS if term in normalized)


def is_greeting_only_fragment(value: str) -> bool:
    """Return True for call-start boilerplate that is unsafe as report evidence."""
    text = _dialogue_norm(value)
    if not text:
        return True

    compact = _dialogue_compact(text)
    if compact in {"алло", "да", "угу", "ага", "добрыйдень", "здравствуйте", "телефонныйзвонок"}:
        return True
    if any(phrase in text for phrase in _CALL_START_BOILERPLATE_PHRASES):
        return True

    words = re.findall(r"[a-zа-яё0-9]+", text, flags=re.IGNORECASE)
    if words and len(words) <= 7 and all(word in _GREETING_ONLY_WORDS for word in words):
        return True
    return False


def fragment_information_score(value: str) -> int:
    """Score how useful one persisted fragment is as manager-facing evidence."""
    text = _dialogue_norm(value)
    if not text:
        return 0
    if is_greeting_only_fragment(text):
        return 0

    words = re.findall(r"[a-zа-яё0-9]+", text, flags=re.IGNORECASE)
    useful_words = [word for word in words if len(word) >= 4 and word not in _GREETING_ONLY_WORDS]
    business_signals = _business_fragment_signal_count(text)
    score = min(len(useful_words), 8) + business_signals * 4
    if "?" in text:
        score += 1
    return score


def is_low_information_fragment(value: str) -> bool:
    """Guard legacy fallback from treating greetings/IVR as proof fragments."""
    return fragment_information_score(value) < 4


def _build_situation_dialogue_excerpt(
    *,
    artifacts: list[ReportArtifact],
    situation_evidence_quote: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a bounded dialogue excerpt around the situation quote when persisted data supports it."""
    if not situation_evidence_quote:
        return None

    call_id = str(situation_evidence_quote.get("call_id") or "").strip()
    client_text = str(situation_evidence_quote.get("client_text") or "").strip()
    if not call_id or not client_text:
        return None

    base = {
        "call_id": call_id,
        "client_name": (
            str(situation_evidence_quote.get("client_label") or "").strip()
            if not re.sub(r"\D", "", str(situation_evidence_quote.get("client_label") or "")).strip()
            else None
        ),
        "client_phone": situation_evidence_quote.get("client_phone"),
        "date_label": situation_evidence_quote.get("date_label"),
        "time_label": situation_evidence_quote.get("time_label"),
    }

    artifact = next((item for item in artifacts if str(item.interaction.id) == call_id), None)
    segments = list(((artifact.interaction.metadata_ or {}).get("segments") or []) if artifact is not None else [])
    quote_norm = _dialogue_norm(client_text)
    matched_index = None
    for index, segment in enumerate(segments):
        segment_text = str((segment or {}).get("text") or "")
        if quote_norm and quote_norm in _dialogue_norm(segment_text):
            matched_index = index
            break

    if matched_index is not None:
        turns: list[dict[str, str]] = []
        for idx in range(max(0, matched_index - 1), min(len(segments), matched_index + 2)):
            segment_text = _dialogue_turn_text(str((segments[idx] or {}).get("text") or ""))
            if not segment_text:
                continue
            speaker = "client" if idx == matched_index else "unknown"
            turns.append({"speaker": speaker, "text": client_text if idx == matched_index else segment_text})
        if turns:
            return {
                **base,
                "source": "transcript_turns",
                "is_partial": True,
                "partial_reason": "speaker_roles_unavailable",
                "turns": turns[:3],
            }

    manager_text = str(situation_evidence_quote.get("manager_text") or "").strip()
    turns = []
    if manager_text:
        turns.append({"speaker": "manager", "text": _dialogue_turn_text(manager_text)})
    turns.append({"speaker": "client", "text": _dialogue_turn_text(client_text)})
    return {
        **base,
        "source": "evidence_fragments",
        "is_partial": True,
        "partial_reason": "surrounding_transcript_turns_unavailable",
        "turns": turns,
    }


def _voice_customer_contextual_quote(
    *,
    artifact: ReportArtifact,
    quote: str,
    limit: int = 420,
) -> str | None:
    """Return a short transcript excerpt around a customer quote for manager context."""
    quote_text = _dialogue_turn_text(str(quote or ""), limit=180)
    transcript = str(getattr(artifact.interaction, "text", None) or "").strip()
    if not quote_text or not transcript:
        return None

    quote_norm = _dialogue_norm(quote_text)
    chunks = [
        _dialogue_turn_text(chunk, limit=260)
        for chunk in re.split(r"(?<=[.!?])\s+", transcript)
        if _dialogue_turn_text(chunk, limit=260)
    ]
    matched_index = None
    for index, chunk in enumerate(chunks):
        chunk_norm = _dialogue_norm(chunk)
        if quote_norm and (quote_norm in chunk_norm or chunk_norm in quote_norm):
            matched_index = index
            break
    if matched_index is None:
        return None

    excerpt_chunks = chunks[max(0, matched_index - 4) : min(len(chunks), matched_index + 2)]
    excerpt = _dialogue_turn_text(" ".join(excerpt_chunks), limit=limit)
    if not excerpt or _dialogue_norm(excerpt) == quote_norm:
        return None
    if quote_norm not in _dialogue_norm(excerpt):
        return None
    return excerpt


def _transcript_context_turns_around_quote(
    *,
    transcript: str | None,
    quote: str | None,
    before: int = 3,
    after: int = 4,
    chunk_limit: int = 280,
) -> list[dict[str, str]]:
    """Return grounded transcript chunks around a selected evidence quote."""
    quote_text = _dialogue_turn_text(str(quote or ""), limit=240)
    transcript_text = str(transcript or "").strip()
    if not quote_text or not transcript_text:
        return []

    quote_norm = _dialogue_norm(quote_text)
    chunks = [
        _dialogue_turn_text(chunk, limit=chunk_limit)
        for chunk in re.split(r"(?<=[.!?])\s+", transcript_text)
        if _dialogue_turn_text(chunk, limit=chunk_limit)
    ]
    matched_index = None
    for index, chunk in enumerate(chunks):
        chunk_norm = _dialogue_norm(chunk)
        if quote_norm and (quote_norm in chunk_norm or chunk_norm in quote_norm):
            matched_index = index
            break
    if matched_index is None:
        return []

    excerpt_chunks = chunks[max(0, matched_index - before) : min(len(chunks), matched_index + after + 1)]
    turns: list[dict[str, str]] = []
    for index, chunk in enumerate(excerpt_chunks, start=max(0, matched_index - before)):
        speaker = "evidence" if index == matched_index else "context"
        turns.append({"speaker": speaker, "text": chunk})
    return turns


def _build_situation_day_insufficient_view(
    *,
    reason: str,
    previous_view: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return an explicit fail-closed view for weak Situation Day evidence."""
    stage_code = str((previous_view or {}).get("stage_code") or "").strip()
    stage_label = str((previous_view or {}).get("stage_label") or "").strip()
    stage_score_label = str((previous_view or {}).get("stage_score_label") or "").strip()
    return {
        "pattern_title": "Нет надежно подтвержденной ситуации дня",
        "stage_code": stage_code,
        "stage_label": stage_label,
        "stage_score_label": stage_score_label,
        "what_happened": (
            "Механизм не нашел достаточно сильную мини-сцену из транскрипта, "
            "которая доказывает одну проблему дня."
        ),
        "moment_summary": None,
        "supporting_quote": None,
        "meaning": "Лучше не показывать менеджеру сомнительный вывод без контекста.",
        "what_was_missing": None,
        "next_time_action": None,
        "scripts": [],
        "source": "situation_day_evidence_packet",
        "proof_strength": "insufficient",
        "situation_day_evidence_status": "insufficient",
        "insufficiency_reason": reason,
    }


def _situation_claim_says_need_not_identified(value: str) -> bool:
    """Return True when a Situation Day claim is about missing need qualification."""
    text = _dialogue_norm(value)
    if not text:
        return False
    has_need_or_qualification = any(
        token in text
        for token in (
            "квалификац",
            "потребност",
            "задач",
            "текущий процесс",
            "процесс клиента",
        )
    )
    has_missing_signal = any(
        token in text
        for token in (
            "без предвар",
            "не выясн",
            "не уточн",
            "не понял",
            "не выяв",
            "не было выясн",
        )
    )
    return has_need_or_qualification and has_missing_signal


def _transcript_has_explicit_vehicle_registration_need(value: str) -> bool:
    """Detect a concrete vehicle-sale/registration need already stated by the customer."""
    text = _dialogue_norm(value)
    if not text:
        return False
    contract_signal = "договор" in text and any(
        token in text
        for token in (
            "купли",
            "продаж",
            "транспорт",
            "движим",
            "прицеп",
            "тс",
        )
    )
    registration_signal = any(
        token in text
        for token in (
            "соно",
            "автоцон",
            "авто цон",
            "отображал",
            "регистрац",
            "оформля",
        )
    )
    return contract_signal and registration_signal


def _situation_claim_contradicts_transcript(
    *,
    transcript: str,
    situation_day_coaching_view: dict[str, Any],
) -> str | None:
    """Return a rejection reason when the LLM claim is contradicted by transcript facts."""
    claim_text = " ".join(
        str(situation_day_coaching_view.get(key) or "")
        for key in (
            "pattern_title",
            "what_happened",
            "moment_summary",
            "what_was_missing",
            "missing_action",
            "proof_explanation",
        )
    )
    if (
        _situation_claim_says_need_not_identified(claim_text)
        and _transcript_has_explicit_vehicle_registration_need(transcript)
    ):
        return "qualification_gap_claim_conflicts_with_explicit_vehicle_registration_need"
    return None


def _build_situation_day_evidence_packet(
    *,
    artifacts: list[ReportArtifact],
    situation_evidence_quote: dict[str, Any] | None,
    situation_day_coaching_view: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a verified evidence packet for Situation Day from transcript context."""
    if not situation_evidence_quote or not situation_day_coaching_view:
        return None

    call_id = str(situation_evidence_quote.get("call_id") or "").strip()
    artifact = next((item for item in artifacts if str(item.interaction.id) == call_id), None)
    transcript = str(getattr(getattr(artifact, "interaction", None), "text", None) or "").strip()
    quote = (
        str(situation_day_coaching_view.get("supporting_quote") or "").strip()
        or str(situation_evidence_quote.get("client_text") or "").strip()
        or str(situation_evidence_quote.get("manager_text") or "").strip()
    )
    if artifact is None or not transcript:
        return {
            "status": "insufficient",
            "proof_strength": "insufficient",
            "insufficiency_reason": "missing_transcript_for_verified_situation_day",
        }
    if not quote or _summary_norm(quote) not in _summary_norm(transcript):
        return {
            "status": "insufficient",
            "proof_strength": "insufficient",
            "insufficiency_reason": "situation_day_quote_not_grounded_in_transcript",
        }

    turns = _verified_role_dialogue_turns(
        raw_turns=situation_day_coaching_view.get("dialogue_turns"),
        quote=quote,
    ) or _transcript_context_turns_around_quote(
        transcript=transcript,
        quote=quote,
        before=3,
        after=6,
    )
    if len(turns) < 2:
        return {
            "status": "insufficient",
            "proof_strength": "insufficient",
            "insufficiency_reason": "situation_day_context_window_missing",
        }

    what_happened = str(situation_day_coaching_view.get("what_happened") or "").strip()
    what_was_missing = str(situation_day_coaching_view.get("what_was_missing") or "").strip()
    next_time_action = str(situation_day_coaching_view.get("next_time_action") or "").strip()
    proof_type = str(situation_day_coaching_view.get("proof_type") or "").strip()
    quote_role = str(situation_day_coaching_view.get("quote_role") or "").strip()
    if not what_happened or not (what_was_missing or next_time_action):
        return {
            "status": "insufficient",
            "proof_strength": "insufficient",
            "insufficiency_reason": "situation_day_missing_problem_chain",
        }
    contradiction_reason = _situation_claim_contradicts_transcript(
        transcript=transcript,
        situation_day_coaching_view=situation_day_coaching_view,
    )
    if contradiction_reason:
        return {
            "status": "insufficient",
            "proof_strength": "insufficient",
            "insufficiency_reason": contradiction_reason,
        }

    strong_proof = proof_type in {"direct_gap", "sequence_inference", "absence_in_context"} and (
        not quote_role or quote_role in {"proves_gap", "supports_context"}
    )
    proof_strength = "strong" if strong_proof and len(turns) >= 3 else "medium"
    ref = _artifact_call_reference(artifact)
    return {
        "status": "verified",
        "proof_strength": proof_strength,
        "problem_claim": str(situation_day_coaching_view.get("pattern_title") or "").strip(),
        "observed_manager_behavior": what_happened,
        "missing_action": what_was_missing,
        "customer_context": _dialogue_turn_text(" ".join(turn["text"] for turn in turns), limit=700),
        "customer_reaction": _dialogue_turn_text(str(turns[-1].get("text") or ""), limit=260),
        "causal_link": str(
            situation_day_coaching_view.get("proof_explanation")
            or situation_day_coaching_view.get("meaning")
            or ""
        ).strip(),
        "manager_lesson": next_time_action,
        "proof_type": proof_type or None,
        "quote_role": quote_role or None,
        "dialogue_excerpt": {
            **ref,
            "source": "transcript_verified_situation_day_packet",
            "is_partial": True,
            "partial_reason": "bounded_transcript_window",
            "turns": turns,
        },
    }


def _verified_role_dialogue_turns(
    *,
    raw_turns: Any,
    quote: str,
) -> list[dict[str, str]]:
    """Use prepared role-aware turns when they contain the verified quote."""
    turns: list[dict[str, str]] = []
    for raw_turn in raw_turns or []:
        if not isinstance(raw_turn, dict):
            continue
        speaker = str(raw_turn.get("speaker") or raw_turn.get("role") or "unknown").strip().lower()
        if speaker not in {"client", "manager"}:
            continue
        text = _dialogue_turn_text(str(raw_turn.get("text") or raw_turn.get("quote") or ""), limit=360)
        if text:
            turns.append({"speaker": speaker, "text": text})
        if len(turns) >= 6:
            break
    if len(turns) < 2:
        return []
    speakers = {turn["speaker"] for turn in turns}
    if not {"client", "manager"}.issubset(speakers):
        return []
    joined = _summary_norm(" ".join(turn["text"] for turn in turns))
    quote_norm = _summary_norm(quote)
    if quote_norm and quote_norm not in joined:
        return []
    return turns


def _attach_situation_day_evidence_packet(
    *,
    result: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    """Attach a verified Situation Day evidence packet to a selected candidate."""
    updated = dict(result)
    updated["dialogue_excerpt"] = dict(packet.get("dialogue_excerpt") or {})
    updated["evidence_packet"] = packet
    coaching_view = dict(updated.get("coaching_view") or {})
    coaching_view.update(
        {
            "evidence_packet": packet,
            "proof_strength": packet.get("proof_strength"),
            "situation_day_evidence_status": "verified",
            "customer_context": packet.get("customer_context"),
            "customer_reaction": packet.get("customer_reaction"),
            "causal_link": packet.get("causal_link"),
        }
    )
    updated["coaching_view"] = coaching_view
    return updated


def _verified_situation_day_result(
    *,
    artifacts: list[ReportArtifact],
    result: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Return a verified Situation Day result or a stable rejection reason."""
    packet = _build_situation_day_evidence_packet(
        artifacts=artifacts,
        situation_evidence_quote=dict(result.get("evidence_quote") or {}),
        situation_day_coaching_view=dict(result.get("coaching_view") or {}),
    )
    if packet is not None and packet.get("status") == "verified":
        return _attach_situation_day_evidence_packet(result=result, packet=packet), None
    return None, str(
        (packet or {}).get("insufficiency_reason")
        or "situation_day_verified_packet_missing"
    )


def _merge_missing_call_reference_fields(
    *,
    block: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing call reference fields without overwriting richer block data."""
    updated = dict(block)
    for key, value in reference.items():
        if updated.get(key) in (None, "", "—"):
            updated[key] = value
    return updated


def _prepare_composer_situation_day_result(
    *,
    artifacts: list[ReportArtifact],
    result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize SituationDayComposer output before Report Layer verification."""
    if not isinstance(result, dict):
        return None

    updated = dict(result)
    selected_call_id = str(
        updated.get("selected_call_id")
        or (dict(updated.get("evidence_quote") or {}).get("call_id"))
        or ""
    ).strip()
    artifact = next(
        (item for item in artifacts if str(item.interaction.id) == selected_call_id),
        None,
    )
    if artifact is not None:
        ref = _artifact_call_reference(artifact)
        for key in ("evidence_quote", "dialogue_excerpt"):
            block = updated.get(key)
            if isinstance(block, dict):
                updated[key] = _merge_missing_call_reference_fields(
                    block=block,
                    reference=ref,
                )

    coaching_view = dict(updated.get("coaching_view") or {})
    coaching_view["source"] = "report_evidence.situation_day_composer.v1"
    coaching_view["composer_version"] = SITUATION_DAY_COMPOSER_VERSION
    if updated.get("proof_type") and not coaching_view.get("proof_type"):
        coaching_view["proof_type"] = updated.get("proof_type")
    if updated.get("proof_strength") and not coaching_view.get("proof_strength"):
        coaching_view["proof_strength"] = updated.get("proof_strength")
    selection_diagnostics = dict(updated.get("selection_diagnostics") or {})
    rejected = selection_diagnostics.get("rejected_candidates")
    if rejected is None and isinstance(selection_diagnostics.get("rejected"), list):
        selection_diagnostics["rejected_candidates"] = selection_diagnostics["rejected"]
    selection_diagnostics["composer_version"] = SITUATION_DAY_COMPOSER_VERSION
    selection_diagnostics.setdefault("selection_mode", "situation_day_composer_v1")
    selection_diagnostics.setdefault("block", "situation_day")
    updated["selection_diagnostics"] = selection_diagnostics
    coaching_view["selection_diagnostics"] = selection_diagnostics
    updated["coaching_view"] = coaching_view

    evidence_quote = updated.get("evidence_quote")
    if isinstance(evidence_quote, dict):
        quote = dict(evidence_quote)
        quote["source"] = "report_evidence.situation_day_composer.v1"
        updated["evidence_quote"] = quote
    dialogue_excerpt = updated.get("dialogue_excerpt")
    if isinstance(dialogue_excerpt, dict):
        excerpt = dict(dialogue_excerpt)
        excerpt["source"] = "report_evidence.situation_day_composer.v1"
        updated["dialogue_excerpt"] = excerpt

    return updated


def _build_verified_situation_day_from_composer(
    *,
    artifacts: list[ReportArtifact],
    report_evidence_index: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Run the pilot composer and return only transcript-verified Situation Day output."""
    raw_result = compose_situation_day(
        artifacts,
        report_evidence_index=report_evidence_index,
    )
    prepared = _prepare_composer_situation_day_result(
        artifacts=artifacts,
        result=raw_result,
    )
    if not prepared or prepared.get("status") != "verified":
        return None, prepared

    verified, rejection_reason = _verified_situation_day_result(
        artifacts=artifacts,
        result=prepared,
    )
    if verified is None:
        prepared = dict(prepared)
        quality = dict(prepared.get("quality_diagnostics") or {})
        quality["report_layer_verification_status"] = "failed"
        quality["report_layer_rejection_reason"] = rejection_reason
        prepared["quality_diagnostics"] = quality
        return None, prepared

    selection_diagnostics = dict(verified.get("selection_diagnostics") or {})
    selection_diagnostics["composer_version"] = SITUATION_DAY_COMPOSER_VERSION
    selection_diagnostics["report_layer_verification_status"] = "passed"
    verified["selection_diagnostics"] = selection_diagnostics
    verified.setdefault("coaching_view", {})["selection_diagnostics"] = selection_diagnostics
    return verified, prepared


def _build_verified_situation_day_from_daily_composer(
    *,
    artifacts: list[ReportArtifact],
    report_evidence_index: dict[str, dict[str, Any]],
    evidence_registry_items: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    """Build Situation Day through the day-level LLM3 composer and fail closed."""
    daily_input = build_situation_day_daily_input(
        artifacts,
        report_evidence_index=report_evidence_index,
        evidence_registry_items=evidence_registry_items,
    )
    raw_result = compose_daily_situation_day(daily_input)
    prepared = _prepare_daily_situation_day_result(
        artifacts=artifacts,
        result=raw_result,
    )
    rejected = list((raw_result or {}).get("rejected_candidates") or []) if isinstance(raw_result, dict) else []
    selection_mode = str((raw_result or {}).get("selection_reason") or "daily_situation_composer_v1").strip()
    if not prepared or prepared.get("status") != "verified":
        return (
            _no_verified_situation_day_result(
                reason=selection_mode or "daily_situation_composer_insufficient",
                rejected=rejected,
                selection_mode="daily_situation_composer_v1",
            ),
            prepared,
            daily_input,
        )

    verified, rejection_reason = _verified_situation_day_result(
        artifacts=artifacts,
        result=prepared,
    )
    if verified is None:
        prepared = dict(prepared)
        quality = dict(prepared.get("quality_diagnostics") or {})
        quality["report_layer_verification_status"] = "failed"
        quality["report_layer_rejection_reason"] = rejection_reason
        prepared["quality_diagnostics"] = quality
        return (
            _no_verified_situation_day_result(
                reason=rejection_reason or "daily_situation_composer_not_verified",
                rejected=rejected,
                selection_mode="daily_situation_composer_v1",
            ),
            prepared,
            daily_input,
        )

    selection_diagnostics = dict(verified.get("selection_diagnostics") or {})
    selection_diagnostics["composer_version"] = SITUATION_DAY_DAILY_COMPOSER_VERSION
    selection_diagnostics["report_layer_verification_status"] = "passed"
    selection_diagnostics.setdefault("selection_mode", selection_mode or "daily_situation_composer_v1")
    selection_diagnostics.setdefault("block", "situation_day")
    verified["selection_diagnostics"] = selection_diagnostics
    verified.setdefault("coaching_view", {})["selection_diagnostics"] = selection_diagnostics
    return verified, prepared, daily_input


def _prepare_daily_situation_day_result(
    *,
    artifacts: list[ReportArtifact],
    result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize Daily Situation Composer output before transcript verification."""
    if not isinstance(result, dict):
        return None
    if str(result.get("status") or "").strip() != "verified":
        return dict(result)

    selected_call_id = str(result.get("selected_call_id") or "").strip()
    artifact = next((item for item in artifacts if str(item.interaction.id) == selected_call_id), None)
    if artifact is None:
        updated = dict(result)
        updated["status"] = "insufficient"
        updated["selection_reason"] = "selected_call_id_not_in_report_artifacts"
        return updated

    ref = _artifact_call_reference(artifact)
    quote = _dialogue_turn_text(str(result.get("supporting_quote") or ""), limit=260)
    dialogue_turns = _daily_situation_dialogue_turns(result.get("dialogue_turns"))
    stage_code = str(result.get("stage_code") or "").strip()
    proof_type = str(result.get("proof_type") or "").strip() or "sequence_inference"
    selection_diagnostics = _semantic_case_selection_diagnostics(
        block_name="situation_day",
        selected={
            "call_id": selected_call_id,
            "source": SITUATION_DAY_DAILY_SOURCE,
            "stage_code": stage_code or None,
            "selection_reason": result.get("selection_reason"),
            "source_fact_ids": list(result.get("source_fact_ids") or []),
        },
        rejected=list(result.get("rejected_candidates") or []),
        selection_mode=str(result.get("selection_reason") or "daily_situation_composer_v1").strip()
        or "daily_situation_composer_v1",
    )
    diagnostics = dict(result.get("diagnostics") or {})
    if diagnostics:
        selection_diagnostics["composer_diagnostics"] = diagnostics
    coaching_view = {
        "source": SITUATION_DAY_DAILY_SOURCE,
        "composer_version": SITUATION_DAY_DAILY_COMPOSER_VERSION,
        "pattern_title": str(result.get("situation_title") or "Ситуация дня").strip(),
        "moment_summary": str(result.get("moment_summary") or "").strip() or None,
        "what_happened": str(result.get("what_happened") or "").strip() or None,
        "what_was_missing": str(result.get("manager_error") or "").strip() or None,
        "manager_error": str(result.get("manager_error") or "").strip() or None,
        "meaning": str(result.get("why_it_matters") or "").strip() or None,
        "proof_explanation": str(result.get("why_it_matters") or "").strip() or None,
        "next_time_action": str(result.get("next_time_action") or "").strip() or None,
        "scripts": [str(item).strip() for item in result.get("scripts") or [] if str(item).strip()],
        "supporting_quote": quote or None,
        "dialogue_turns": dialogue_turns,
        "proof_type": proof_type,
        "proof_strength": "medium",
        "quote_role": "supports_context",
        "stage_code": stage_code or None,
        "stage_label": _stage_name_for_code(stage_code, []) if stage_code else None,
        "selection_diagnostics": selection_diagnostics,
    }
    return {
        "status": "verified",
        "selected_call_id": selected_call_id,
        "situation_title": coaching_view["pattern_title"],
        "evidence_quote": {
            **ref,
            "source": SITUATION_DAY_DAILY_SOURCE,
            "stage_code": stage_code or None,
            "client_text": quote,
            "manager_text": quote,
        },
        "dialogue_excerpt": {
            **ref,
            "source": SITUATION_DAY_DAILY_SOURCE,
            "is_partial": True,
            "partial_reason": "daily_composer_selected_quote",
            "turns": dialogue_turns or ([{"speaker": "evidence", "text": quote}] if quote else []),
        },
        "coaching_view": coaching_view,
        "selection_diagnostics": selection_diagnostics,
        "raw_daily_composer_result": result,
    }


def _daily_situation_dialogue_turns(value: Any) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for raw_turn in value or []:
        if not isinstance(raw_turn, dict):
            continue
        text = _dialogue_turn_text(str(raw_turn.get("text") or raw_turn.get("quote") or ""), limit=360)
        if not text:
            continue
        speaker = str(raw_turn.get("speaker") or raw_turn.get("role") or "unknown").strip().lower()
        if speaker not in {"client", "manager", "unknown", "context", "evidence"}:
            speaker = "unknown"
        turns.append({"speaker": speaker, "text": text})
        if len(turns) >= 6:
            break
    return turns


def _registry_item_dicts(evidence_items: Any) -> list[dict[str, Any]]:
    """Return Evidence Registry items as plain dictionaries for report-layer helpers."""
    try:
        return report_evidence_registry_as_dicts(evidence_items)
    except TypeError:
        return [dict(item) for item in evidence_items or [] if isinstance(item, dict)]


def _registry_item_turns(item: dict[str, Any], *, limit: int = 320) -> list[dict[str, str]]:
    """Normalize Evidence Registry dialogue scenes to report-layer turn payloads."""
    turns: list[dict[str, str]] = []
    for raw_turn in item.get("dialogue_scene") or item.get("dialogue_fragment") or []:
        if not isinstance(raw_turn, dict):
            continue
        text = _dialogue_turn_text(str(raw_turn.get("text") or raw_turn.get("quote") or ""), limit=limit)
        if not text:
            continue
        speaker = str(raw_turn.get("speaker") or "unknown").strip().lower()
        if speaker not in {"manager", "client", "unknown"}:
            speaker = "unknown"
        turns.append({"speaker": speaker, "text": text})
        if len(turns) >= 8:
            break
    return turns


def _registry_item_quote(item: dict[str, Any], turns: list[dict[str, str]]) -> str | None:
    return (
        _dialogue_turn_text(str(item.get("supporting_quote") or ""), limit=260)
        or _report_evidence_quote_text(turns)
        or None
    )


def _registry_item_has_counter_evidence(item: dict[str, Any]) -> bool:
    counter = item.get("counter_evidence")
    if isinstance(counter, list):
        return any(str(value or "").strip() for value in counter)
    return bool(str(counter or "").strip())


def _registry_item_score(item: dict[str, Any]) -> float:
    router = item.get("router") if isinstance(item.get("router"), dict) else {}
    diagnostics = item.get("diagnostics") if isinstance(item.get("diagnostics"), dict) else {}
    for value in (router.get("score"), item.get("score"), diagnostics.get("score")):
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            continue
    priority = str(diagnostics.get("priority") or item.get("priority") or "").lower()
    if priority == "high":
        return 80.0
    if priority == "medium":
        return 60.0
    if priority == "low":
        return 40.0
    return 0.0


def _registry_manager_gap_items(evidence_items: Any) -> list[dict[str, Any]]:
    """Keep manager-gap Evidence Registry items with at least some grounded context."""
    result: list[dict[str, Any]] = []
    for item in _registry_item_dicts(evidence_items):
        evidence_type = str(item.get("evidence_type") or "").strip()
        if evidence_type not in {"manager_gap", "manager_coaching_moment", "stage_gap"}:
            continue
        suitability = item.get("block_suitability") if isinstance(item.get("block_suitability"), dict) else {}
        situation_suitability = (
            suitability.get("situation_day") if isinstance(suitability.get("situation_day"), dict) else None
        )
        if situation_suitability is not None and situation_suitability.get("eligible") is False:
            continue
        if str(item.get("proof_strength") or "").strip() == "insufficient":
            continue
        if _registry_item_has_counter_evidence(item):
            continue
        turns = _registry_item_turns(item)
        quote = _registry_item_quote(item, turns)
        if not turns and not quote:
            continue
        normalized = dict(item)
        normalized["_registry_turns"] = turns
        normalized["_registry_quote"] = quote
        result.append(normalized)
    return result


def _registry_candidate_sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
    strength_rank = {"strong": 0, "medium": 1, "weak": 2}
    return (
        strength_rank.get(str(item.get("proof_strength") or "").strip(), 9),
        -_registry_item_score(item),
        str(item.get("evidence_id") or item.get("item_id") or ""),
    )


def _build_situation_day_from_evidence_registry(
    *,
    artifacts: list[ReportArtifact],
    evidence_items: Any,
    score_by_stage: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build a conservative Situation Day fallback from the shared Evidence Registry."""
    candidates = _registry_manager_gap_items(evidence_items)
    if not candidates:
        return None

    strong_or_medium = [
        item for item in candidates if str(item.get("proof_strength") or "").strip() in {"strong", "medium"}
    ]
    selection_mode = "evidence_registry_single_manager_gap"
    pattern_count = 1
    if strong_or_medium:
        selected = sorted(strong_or_medium, key=_registry_candidate_sort_key)[0]
    else:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in candidates:
            stage_code = str(item.get("stage_code") or "").strip()
            problem_title = _summary_norm(str(item.get("problem_title") or item.get("manager_gap") or ""))
            key = stage_code or problem_title[:80]
            if not key:
                continue
            groups.setdefault(key, []).append(item)
        repeated_groups = [items for items in groups.values() if len(items) >= 2]
        if not repeated_groups:
            return None
        repeated_groups.sort(key=lambda items: (len(items), _registry_item_score(items[0])), reverse=True)
        selected = sorted(repeated_groups[0], key=_registry_candidate_sort_key)[0]
        selection_mode = "evidence_registry_repeated_weak_manager_gap"
        pattern_count = len(repeated_groups[0])

    call_id = str(selected.get("call_id") or "").strip()
    artifact = next((item for item in artifacts if str(item.interaction.id) == call_id), None)
    if artifact is None:
        return None
    turns = selected.get("_registry_turns") or []
    quote = selected.get("_registry_quote")
    if not quote:
        return None
    ref = _artifact_call_reference(artifact)
    stage_code = str(selected.get("stage_code") or "").strip()
    stage_label = _stage_name_for_code(stage_code, score_by_stage)
    diagnostics = selected.get("diagnostics") if isinstance(selected.get("diagnostics"), dict) else {}
    problem_title = _first_sentence(
        str(selected.get("problem_title") or selected.get("manager_gap") or ""),
        limit=160,
    ).rstrip(".")
    manager_gap = _first_sentence(str(selected.get("manager_gap") or problem_title), limit=260)
    what_better = _first_sentence(str(diagnostics.get("what_better") or ""), limit=260)
    customer_context = _dialogue_turn_text(
        str(selected.get("customer_context") or " ".join(turn["text"] for turn in turns)),
        limit=520,
    )
    if pattern_count > 1:
        what_happened = (
            f"В {pattern_count} звонках повторяется похожий момент: "
            f"{manager_gap or problem_title}."
        )
        proof_explanation = (
            "Это выбрано как ситуация дня не из-за одной короткой фразы, "
            "а как повторяющийся управленческий разрыв в звонках за день."
        )
    else:
        what_happened = manager_gap or problem_title
        proof_explanation = customer_context
    coaching_view = {
        "source": "report_evidence.evidence_registry.situation_day_fallback.v1",
        "pattern_title": problem_title or "Проблемная ситуация дня",
        "stage_code": stage_code or None,
        "stage_label": stage_label,
        "what_happened": what_happened,
        "what_was_missing": manager_gap,
        "next_time_action": what_better or "В похожем моменте явно зафиксировать следующий шаг и критерий решения клиента.",
        "meaning": proof_explanation,
        "proof_explanation": proof_explanation,
        "supporting_quote": quote,
        "proof_type": selected.get("proof_type") or "sequence_inference",
        "proof_strength": "medium" if pattern_count > 1 else selected.get("proof_strength"),
        "quote_role": "supports_context",
        "selection_diagnostics": {
            "selection_mode": selection_mode,
            "selected_evidence_id": selected.get("evidence_id") or selected.get("item_id"),
            "selected_call_id": call_id,
            "pattern_count": pattern_count,
            "source": selected.get("source"),
        },
    }
    return {
        "situation_title": coaching_view["pattern_title"],
        "evidence_quote": {
            **ref,
            "source": "report_evidence.evidence_registry.situation_day_fallback.v1",
            "stage_code": stage_code or None,
            "client_text": quote,
            "manager_text": quote,
            "source_evidence_id": selected.get("evidence_id") or selected.get("item_id"),
        },
        "dialogue_excerpt": {
            **ref,
            "source": "report_evidence.evidence_registry.situation_day_fallback.v1",
            "is_partial": True,
            "partial_reason": "evidence_registry_dialogue_scene",
            "turns": turns,
        },
        "coaching_view": coaching_view,
        "selection_diagnostics": coaching_view["selection_diagnostics"],
    }


def _build_call_breakdown_from_evidence_registry_route(
    *,
    artifacts: list[ReportArtifact],
    routed_items: list[dict[str, Any]],
    score_by_stage: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Compose Call Breakdown from the router-selected Evidence Registry item."""
    for item in routed_items:
        call_id = str(item.get("call_id") or "").strip()
        artifact = next((artifact for artifact in artifacts if str(artifact.interaction.id) == call_id), None)
        if artifact is None:
            continue
        turns = _registry_item_turns(item)
        quote = _registry_item_quote(item, turns)
        if not turns and not quote:
            continue
        ref = _artifact_call_reference(artifact)
        diagnostics = item.get("diagnostics") if isinstance(item.get("diagnostics"), dict) else {}
        stage_code = str(item.get("stage_code") or "").strip()
        stage_label = _stage_name_for_code(stage_code, score_by_stage)
        context_text = _dialogue_turn_text(
            " ".join(turn["text"] for turn in turns) or str(item.get("customer_context") or ""),
            limit=700,
        )
        manager_gap = _first_sentence(
            str(item.get("manager_gap") or item.get("problem_title") or ""),
            limit=300,
        )
        better = _first_sentence(str(diagnostics.get("what_better") or ""), limit=260)
        packet = {
            "status": "verified",
            "proof_strength": item.get("proof_strength") or "medium",
            "problem_claim": item.get("problem_title") or manager_gap,
            "problem_title": item.get("problem_title") or manager_gap,
            "observed_manager_behavior": manager_gap or context_text,
            "missing_action": manager_gap,
            "customer_context": context_text,
            "customer_reaction": _dialogue_turn_text(str((turns[-1] or {}).get("text") or ""), limit=260)
            if turns
            else None,
            "causal_link": item.get("customer_context") or context_text,
            "manager_lesson": better or "Зафиксировать конкретный следующий шаг и проверить понимание клиента.",
            "proof_type": item.get("proof_type") or "sequence_inference",
            "quote_role": "supports_context",
            "dialogue_excerpt": {
                **ref,
                "source": "report_evidence.evidence_registry.call_breakdown_route.v1",
                "is_partial": True,
                "partial_reason": "evidence_registry_dialogue_scene",
                "turns": turns,
            },
        }
        view = {
            "call_id": call_id,
            "stage_code": stage_code or None,
            "stage_label": stage_label,
            "pattern_title": item.get("problem_title") or manager_gap,
            "what_happened": manager_gap or context_text,
            "what_was_missing": manager_gap,
            "next_time_action": better or packet["manager_lesson"],
            "meaning": packet["causal_link"],
            "proof_type": packet["proof_type"],
            "proof_strength": packet["proof_strength"],
        }
        result = compose_call_breakdown_from_situation(
            artifacts=artifacts,
            situation_day_evidence_packet=packet,
            situation_day_coaching_view=view,
            score_by_stage=score_by_stage,
        )
        if result is None or not result.get("rows"):
            continue
        result["status"] = "verified"
        result["source_note"] = "report_evidence.evidence_registry.call_breakdown_route.v1"
        result["call_breakdown_source"] = "report_evidence.evidence_registry.call_breakdown_route.v1"
        result.setdefault("selection_diagnostics", {}).update(
            {
                "selection_mode": "evidence_registry_router_call_breakdown",
                "selected_evidence_id": item.get("evidence_id") or item.get("item_id"),
                "router_reason": (item.get("router") or {}).get("reason")
                if isinstance(item.get("router"), dict)
                else None,
                "source": item.get("source"),
            }
        )
        return result
    return None


def _build_report_evidence_registry_diagnostics(
    *,
    evidence_items: Any,
    report_block_routes: dict[str, Any],
) -> dict[str, Any]:
    items = _registry_item_dicts(evidence_items)
    source_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    strength_counts: dict[str, int] = {}
    for item in items:
        source = str(item.get("source") or "unknown")
        evidence_type = str(item.get("evidence_type") or "unknown")
        strength = str(item.get("proof_strength") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        type_counts[evidence_type] = type_counts.get(evidence_type, 0) + 1
        strength_counts[strength] = strength_counts.get(strength, 0) + 1
    return {
        "registry_version": "report_evidence_registry_v1",
        "items_count": len(items),
        "source_counts": source_counts,
        "evidence_type_counts": type_counts,
        "proof_strength_counts": strength_counts,
        "router_version": report_block_routes.get("routing_version"),
        "router_summary": (report_block_routes.get("diagnostics") or {}).get("summary"),
        "selected_call_breakdown": (report_block_routes.get("call_breakdown") or [{}])[0],
        "selected_situation_day": (report_block_routes.get("situation_day") or [{}])[0],
    }


def _apply_situation_day_writer(
    *,
    report_evidence_situation: dict[str, Any] | None,
    situation_evidence_quote: dict[str, Any] | None,
    situation_dialogue_excerpt: dict[str, Any] | None,
    situation_day_evidence_packet: dict[str, Any] | None,
    situation_day_coaching_view: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize every selected Situation Day path through one report-facing writer."""
    if not situation_day_coaching_view:
        return situation_day_coaching_view
    if str(situation_day_coaching_view.get("situation_day_evidence_status") or "").strip() == "insufficient":
        return situation_day_coaching_view

    dialogue_excerpt = (
        dict(situation_dialogue_excerpt or {})
        or dict((situation_day_evidence_packet or {}).get("dialogue_excerpt") or {})
        or dict((report_evidence_situation or {}).get("dialogue_excerpt") or {})
    )
    evidence_quote = dict(situation_evidence_quote or {})
    selected = {
        **dict(report_evidence_situation or {}),
        "coaching_view": dict(situation_day_coaching_view or {}),
        "evidence_quote": evidence_quote,
        "dialogue_excerpt": dialogue_excerpt,
    }
    call_reference = {
        key: value
        for source in (dialogue_excerpt, evidence_quote)
        for key, value in source.items()
        if key
        in {
            "call_id",
            "client_label",
            "client_name",
            "client_phone",
            "date_label",
            "time_label",
            "client_call_reference",
        }
    }
    writer_view = compose_situation_day_view(
        selected,
        dialogue_turns=[
            turn
            for turn in dialogue_excerpt.get("turns") or []
            if isinstance(turn, dict)
        ],
        call_reference=call_reference,
        source_note=str(situation_day_coaching_view.get("source") or "").strip() or None,
    )
    merged = dict(situation_day_coaching_view)
    original_source = merged.get("source")
    original_selection = dict(merged.get("selection_diagnostics") or {})
    merged.update(writer_view)
    if original_source:
        merged["source"] = original_source
    if original_selection:
        merged["selection_diagnostics"] = original_selection
    merged.setdefault("meaning", writer_view.get("evidence_explanation"))
    merged.setdefault("why_it_matters", writer_view.get("evidence_explanation"))
    merged.setdefault("how_to_improve", writer_view.get("next_time_action"))
    merged["situation_day_writer_applied"] = True
    return merged


def _no_verified_situation_day_result(
    *,
    reason: str,
    rejected: list[dict[str, Any]],
    selection_mode: str,
) -> dict[str, Any]:
    """Return an explicit empty Situation Day result after all candidates fail verification."""
    coaching_view = _build_situation_day_insufficient_view(
        reason=reason,
        previous_view=None,
    )
    diagnostics = _semantic_case_selection_diagnostics(
        block_name="situation_day",
        selected=None,
        rejected=rejected,
        selection_mode=selection_mode,
    )
    return {
        "situation_title": "Нет надежно подтвержденной ситуации дня",
        "evidence_quote": None,
        "dialogue_excerpt": None,
        "no_verified_situation_day": True,
        "coaching_view": {**coaching_view, "selection_diagnostics": diagnostics},
        "selection_diagnostics": diagnostics,
        "evidence_packet": {
            "status": "insufficient",
            "proof_strength": "insufficient",
            "insufficiency_reason": reason,
        },
    }


def _situation_breakdown_example_phrase(*, missing_action: str, next_action: str) -> str:
    """Return a concrete manager phrase for a verified Situation Day breakdown."""
    text = _dialogue_norm(" ".join((missing_action, next_action)))
    if any(token in text for token in ("роль", "масштаб", "кто принимает", "собеседник")):
        return (
            "Сказать: «Подскажите, вы сами будете подписывать/получать документы "
            "или это делает другой отдел? Сколько примерно документов проходит в месяц "
            "и кто принимает решение по подключению?»"
        )
    if "следующ" in text or "зафикс" in text:
        return (
            "Сказать: «Давайте зафиксируем следующий шаг: я отправлю короткую информацию, "
            "а завтра вернусь с уточняющими вопросами по вашему процессу. Удобно?»"
        )
    return f"Сказать: «{next_action or missing_action}»"


def _sentence_without_trailing_dot(value: str | None) -> str:
    return str(value or "").strip().rstrip(".!?;:").strip()


def _build_call_breakdown_from_situation_day_packet(
    *,
    situation_day_evidence_packet: dict[str, Any] | None,
    situation_day_coaching_view: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a concrete Call Breakdown from the verified Situation Day packet."""
    packet = dict(situation_day_evidence_packet or {})
    if packet.get("status") != "verified":
        return None
    excerpt = dict(packet.get("dialogue_excerpt") or {})
    call_id = str(excerpt.get("call_id") or "").strip()
    if not call_id:
        return None
    view = dict(situation_day_coaching_view or {})
    turns = [turn for turn in excerpt.get("turns") or [] if isinstance(turn, dict)]
    evidence_text = _dialogue_turn_text(
        " ".join(str(turn.get("text") or "") for turn in turns[:10]),
        limit=520,
    )
    missing_action = str(packet.get("missing_action") or view.get("what_was_missing") or "").strip()
    next_action = str(packet.get("manager_lesson") or view.get("next_time_action") or "").strip()
    observed = str(packet.get("observed_manager_behavior") or view.get("what_happened") or "").strip()
    causal_link = str(packet.get("causal_link") or view.get("meaning") or "").strip()
    observed_clean = _sentence_without_trailing_dot(observed) or "проблемный момент не описан"
    missing_clean = _sentence_without_trailing_dot(missing_action) or "не зафиксировано"
    causal_clean = _sentence_without_trailing_dot(causal_link)
    example_phrase = _situation_breakdown_example_phrase(
        missing_action=missing_action,
        next_action=next_action,
    )
    closing_context = _dialogue_turn_text(
        " ".join(str(turn.get("text") or "") for turn in turns[-5:]),
        limit=360,
    )
    rows = [
        [
            "Момент 1 - квалификация",
            (
                f"Что было не так: {observed_clean}. "
                f"Что не хватило: {missing_clean}."
                + (f" Почему это важно: {causal_clean}." if causal_clean else "")
            ),
            evidence_text or CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE,
            example_phrase,
        ]
    ]
    reaction = str(packet.get("customer_reaction") or "").strip()
    should_add_next_step_row = (
        reaction
        and any(token in _dialogue_norm(reaction) for token in ("до свид", "спасибо", "хорошо"))
    ) or "следующ" in _dialogue_norm(next_action)
    if should_add_next_step_row:
        rows.append(
            [
                "Момент 2 - следующий шаг",
                (
                    "Что было не так: после общего ответа клиента менеджер завершил разговор "
                    "без конкретной договоренности, кому и что он отправит, когда вернется "
                    "и какой вопрос нужно уточнить."
                ),
                closing_context or evidence_text or CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE,
                (
                    "Сказать: «Чтобы не потерять вопрос, давайте договоримся: "
                    "я уточню ваш процесс и вернусь с конкретным вариантом. Когда удобно продолжить?»"
                ),
            ]
        )
    return {
        "is_placeholder": False,
        "call_id": call_id,
        "client_label": excerpt.get("client_label"),
        "client_phone": excerpt.get("client_phone"),
        "date_label": excerpt.get("date_label"),
        "time_label": excerpt.get("time_label"),
        "client_call_reference": excerpt.get("client_call_reference"),
        "stage_code": view.get("stage_code"),
        "stage_name": view.get("stage_label"),
        "stage_steps": [],
        "worked": [],
        "to_fix": [],
        "recommendation": None,
        "rows": rows,
        "moments": [],
        "summary_line": str(excerpt.get("client_call_reference") or "Разбор звонка"),
        "source_note": "situation_day_evidence_packet",
        "call_breakdown_source": "situation_day_evidence_packet",
        "call_breakdown_evidence_strength": packet.get("proof_strength") or "medium",
        "call_breakdown_fragment_present": bool(evidence_text),
        "moment_summary": observed or None,
        "missing_action": missing_action or None,
        "why_it_matters": causal_link or None,
        "supporting_quote": evidence_text or None,
        "evidence_type": packet.get("proof_type"),
        "confidence": packet.get("proof_strength"),
        "proof_type": packet.get("proof_type"),
        "proof_explanation": causal_link or None,
        "quote_role": packet.get("quote_role"),
    }


def _situation_day_rejected_call_ids(result: dict[str, Any] | None) -> set[str]:
    """Return call ids rejected during verified Situation Day selection."""
    diagnostics = dict((result or {}).get("selection_diagnostics") or {})
    rejected = diagnostics.get("rejected_candidates") or []
    return {
        str(item.get("call_id") or "").strip()
        for item in rejected
        if isinstance(item, dict) and str(item.get("call_id") or "").strip()
    }


def _artifact_scores_detail(artifact: ReportArtifact) -> dict[str, Any]:
    """Return the best persisted analysis detail available for display metadata."""
    source_analysis = artifact.analysis or artifact.original_analysis
    return dict((getattr(source_analysis, "scores_detail", None) or {}) if source_analysis is not None else {})


def _artifact_call_metadata(artifact: ReportArtifact) -> dict[str, Any]:
    """Return merged call metadata with analysis fields taking priority."""
    detail = _artifact_scores_detail(artifact)
    call_meta = dict(detail.get("call") or {})
    interaction_meta = dict(artifact.interaction.metadata_ or {})
    raw_phone = _clean_display_part(
        call_meta.get("contact_phone")
        or call_meta.get("client_phone")
        or call_meta.get("phone")
        or interaction_meta.get("contact_phone")
        or interaction_meta.get("client_phone")
        or interaction_meta.get("phone")
    )
    name_candidates = (
        call_meta.get("contact_name"),
        call_meta.get("client_name"),
        call_meta.get("name"),
        interaction_meta.get("contact_name"),
        interaction_meta.get("client_name"),
        interaction_meta.get("contact_label"),
        interaction_meta.get("customer_name"),
        _safe_persisted_transcript_contact_name(artifact),
    )
    safe_name = next(
        (
            name
            for name in (
                _safe_client_display_name(candidate, phone=raw_phone)
                for candidate in name_candidates
            )
            if name
        ),
        "",
    )
    return {
        "contact_name": safe_name,
        "contact_phone": raw_phone,
    }


def _artifact_client_label(artifact: ReportArtifact) -> str:
    call_meta = _artifact_call_metadata(artifact)
    name = call_meta.get("contact_name")
    phone = call_meta.get("contact_phone")
    if name and not _is_phone_like_display(name):
        return str(name)
    return str(phone or name or "Клиент").strip()


def _artifact_client_phone(artifact: ReportArtifact) -> str | None:
    call_meta = _artifact_call_metadata(artifact)
    phone = str(call_meta.get("contact_phone") or "").strip()
    name = str(call_meta.get("contact_name") or "").strip()
    if not phone and _is_phone_like_display(name):
        phone = name
    return phone or None


def _artifact_client_name(artifact: ReportArtifact) -> str | None:
    call_meta = _artifact_call_metadata(artifact)
    name = str(call_meta.get("contact_name") or "").strip()
    if not name or _is_phone_like_display(name):
        return None
    return name


def _artifact_client_call_reference(artifact: ReportArtifact) -> str | None:
    return _build_client_call_reference(
        client_name_or_label=_artifact_client_name(artifact),
        phone=_artifact_client_phone(artifact),
        call_started_at=artifact.call_started_at,
    )


def _artifact_call_reference(artifact: ReportArtifact) -> dict[str, Any]:
    client_label = _artifact_client_label(artifact)
    return {
        "call_id": str(artifact.interaction.id),
        "client_label": client_label,
        "client_name": _artifact_client_name(artifact),
        "client_phone": _artifact_client_phone(artifact),
        "date_label": artifact.call_started_at.date().isoformat() if artifact.call_started_at else None,
        "time_label": artifact.call_started_at.strftime("%H:%M") if artifact.call_started_at else "—",
        "client_call_reference": _artifact_client_call_reference(artifact),
    }


def _find_call_breakdown_artifact(
    *,
    artifacts: list[ReportArtifact],
    call_breakdown: dict[str, Any] | None,
) -> ReportArtifact | None:
    """Find the persisted artifact selected by РАЗБОР ЗВОНКА."""
    if not call_breakdown or call_breakdown.get("is_placeholder"):
        return None
    call_id = str(call_breakdown.get("call_id") or "").strip()
    if call_id:
        found = next((item for item in artifacts if str(item.interaction.id) == call_id), None)
        if found is not None:
            return found

    client_label = str(call_breakdown.get("client_label") or "").strip()
    time_label = str(call_breakdown.get("time_label") or "").strip()
    for artifact in artifacts:
        if client_label and _artifact_client_label(artifact) != client_label:
            continue
        artifact_time = artifact.call_started_at.strftime("%H:%M") if artifact.call_started_at else "—"
        if time_label and artifact_time != time_label:
            continue
        return artifact
    return None


def _build_situation_evidence_quote_from_call_breakdown(
    *,
    artifacts: list[ReportArtifact],
    call_breakdown: dict[str, Any] | None,
    score_by_stage: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Fallback Situation Day quote to the selected sales-like breakdown call evidence."""
    artifact = _find_call_breakdown_artifact(artifacts=artifacts, call_breakdown=call_breakdown)
    if artifact is None or artifact.analysis is None:
        return None

    detail = dict(artifact.analysis.scores_detail or {})
    priority_stage = next((item for item in score_by_stage or [] if item.get("is_priority")), None)
    priority_stage_code = str((priority_stage or {}).get("stage_code") or "").strip()
    for frag in detail.get("evidence_fragments") or []:
        client_text = str(frag.get("client_text") or "").strip()
        if len(client_text) < 5:
            continue
        manager_text = str(
            frag.get("manager_text")
            or frag.get("manager_phrase")
            or frag.get("manager")
            or ""
        ).strip() or None
        criterion_code = str(frag.get("criterion_code") or "").strip()
        stage_code = _stage_code_from_criterion_code(criterion_code)
        if priority_stage_code and stage_code != priority_stage_code:
            continue
        return {
            **_artifact_call_reference(artifact),
            "client_text": client_text,
            "manager_text": manager_text,
            "criterion_code": criterion_code,
            "stage_code": stage_code,
            "source": "call_breakdown_evidence_fragments",
        }
    return None


def _is_dialogue_noise_line(value: str) -> bool:
    text = _dialogue_norm(value)
    compact = _dialogue_compact(text)
    if not text:
        return True
    if compact in {"алло", "да", "угу", "ага"}:
        return True
    if compact in {"телефонныйзвонок"}:
        return True
    if is_greeting_only_fragment(text):
        return True
    return False


def _build_situation_dialogue_excerpt_from_call_breakdown(
    *,
    artifacts: list[ReportArtifact],
    call_breakdown: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a bounded Situation Day transcript excerpt from the selected breakdown call."""
    artifact = _find_call_breakdown_artifact(artifacts=artifacts, call_breakdown=call_breakdown)
    if artifact is None:
        return None

    turns: list[dict[str, str]] = []
    low_information_turns: list[dict[str, str]] = []
    segments = list((artifact.interaction.metadata_ or {}).get("segments") or [])
    for segment in segments:
        segment_text = _dialogue_turn_text(str((segment or {}).get("text") or ""), limit=260)
        if _is_dialogue_noise_line(segment_text):
            continue
        if is_low_information_fragment(segment_text):
            low_information_turns.append({"speaker": "unknown", "text": segment_text})
            continue
        turns.append({"speaker": "unknown", "text": segment_text})
        if len(turns) >= 3:
            break

    if not turns:
        text = str(artifact.interaction.text or "").strip()
        for chunk in re.split(r"(?<=[.!?])\s+", text):
            chunk_text = _dialogue_turn_text(chunk, limit=260)
            if _is_dialogue_noise_line(chunk_text):
                continue
            if is_low_information_fragment(chunk_text):
                low_information_turns.append({"speaker": "unknown", "text": chunk_text})
                continue
            turns.append({"speaker": "unknown", "text": chunk_text})
            if len(turns) >= 3:
                break

    used_low_information_fallback = False
    if not turns and low_information_turns:
        turns = low_information_turns[:1]
        used_low_information_fallback = True

    if not turns:
        return None
    return {
        **_artifact_call_reference(artifact),
        "source": "call_breakdown_transcript_segments" if segments else "call_breakdown_transcript_text",
        "is_partial": True,
        "partial_reason": "low_information_fragment_only"
        if used_low_information_fallback
        else "speaker_roles_unavailable",
        "evidence_quality": "weak" if used_low_information_fallback else "indirect",
        "turns": turns,
    }


def _artifact_fallback_evidence_score(artifact: ReportArtifact) -> int:
    """Best deterministic evidence score available for legacy report fallbacks."""
    return max(
        (fragment_information_score(text) for text in _artifact_fallback_evidence_texts(artifact)),
        default=0,
    )


_FOCUS_STAGE_WHY_FALLBACKS: dict[str, str] = {
    "contact_start": "Если старт разговора не создаёт контекст и разрешение на диалог, клиент отвечает формально и быстрее выходит из контакта.",
    "qualification_primary": "Без понимания роли, процесса и задачи клиента презентация звучит общей и не привязана к реальной потребности.",
    "needs_discovery": "Если боль и ограничения текущего процесса не раскрыты, менеджер не может показать ценность продукта под задачу клиента.",
    "presentation": "Когда предложение не связано с контекстом клиента, продукт воспринимается как общая презентация, а не как решение его задачи.",
    "objection_handling": "Если возражение не разобрано по причине, клиент остаётся при сомнении и разговор не двигается к договорённости.",
    "completion_next_step": "Без конкретного следующего шага разговор остаётся открытым, а вероятность продолжения снижается.",
    "cross_stage_transition": "Если переходы между этапами не связаны, клиент теряет логику разговора и сложнее соглашается на следующий шаг.",
}

_FOCUS_STAGE_FIX_FALLBACKS: dict[str, str] = {
    "contact_start": "В начале звонка коротко обозначить причину контакта, проверить уместность разговора и роль собеседника.",
    "qualification_primary": "До презентации задать 2–3 уточняющих вопроса и только потом связывать продукт с задачей клиента.",
    "needs_discovery": "Уточнить текущий процесс, боль, ограничения и приоритет клиента перед переходом к предложению.",
    "presentation": "Связать 1–2 возможности продукта с уже названной задачей клиента и проверить, попали ли в потребность.",
    "objection_handling": "Сначала уточнить причину сомнения клиента, затем ответить по сути и проверить, снято ли возражение.",
    "completion_next_step": "В конце звонка зафиксировать конкретный следующий шаг, срок, формат контакта и ответственного.",
    "cross_stage_transition": "Перед сменой темы коротко подвести итог и согласовать с клиентом следующий логический шаг разговора.",
}

_FOCUS_STAGE_MINIMUM_FALLBACKS: dict[str, str] = {
    "contact_start": "В каждом подходящем sales-звонке проверить уместность разговора и роль собеседника до перехода к теме.",
    "qualification_primary": "В каждом подходящем sales-звонке зафиксировать роль собеседника, текущий процесс и следующий шаг.",
    "needs_discovery": "В каждом подходящем sales-звонке уточнить боль, ограничение текущего процесса и приоритет клиента.",
    "presentation": "В каждом подходящем sales-звонке связать предложение минимум с одной конкретной задачей клиента.",
    "objection_handling": "В каждом подходящем sales-звонке уточнить причину ключевого возражения и проверить, снято ли сомнение.",
    "completion_next_step": "В каждом подходящем sales-звонке зафиксировать конкретный следующий шаг, срок и ответственного.",
    "cross_stage_transition": "В каждом подходящем sales-звонке делать короткий итог перед переходом к следующему этапу.",
}

_FOCUS_STAGE_RECOMMENDATION_FALLBACKS: dict[str, str] = {
    "contact_start": "Начни звонок с причины контакта, проверки удобства разговора и уточнения роли собеседника.",
    "qualification_primary": "Перед презентацией уточни роль собеседника, текущий процесс и следующий шаг.",
    "needs_discovery": "До предложения уточни боль клиента, ограничение текущего процесса и главный приоритет.",
    "presentation": "Покажи продукт через задачу клиента и проверь, видит ли он ценность предложения.",
    "objection_handling": "Разбери причину возражения, ответь по сути и проверь, снято ли сомнение клиента.",
    "completion_next_step": "Закрой разговор конкретным следующим шагом, сроком и ответственным.",
    "cross_stage_transition": "Связывай этапы коротким итогом и согласованием следующего шага разговора.",
}

_FOCUS_STAGE_CHECKLIST_FALLBACKS: dict[str, list[str]] = {
    "contact_start": [
        "Назвать причину звонка",
        "Проверить удобство разговора",
        "Уточнить роль собеседника",
    ],
    "qualification_primary": [
        "Уточнить роль собеседника",
        "Понять текущий процесс",
        "Зафиксировать следующий шаг",
    ],
    "needs_discovery": [
        "Уточнить боль или ограничение текущего процесса",
        "Понять приоритет клиента",
        "Связать предложение с выявленной задачей",
    ],
    "presentation": [
        "Назвать задачу клиента",
        "Связать продукт с этой задачей",
        "Проверить, попали ли в потребность",
    ],
    "objection_handling": [
        "Уточнить причину возражения",
        "Ответить по сути сомнения",
        "Проверить, снято ли возражение",
    ],
    "completion_next_step": [
        "Назвать конкретный следующий шаг",
        "Зафиксировать срок",
        "Подтвердить ответственного",
    ],
    "cross_stage_transition": [
        "Коротко подвести итог этапа",
        "Согласовать переход к следующей теме",
        "Проверить понимание клиента",
    ],
}

_SITUATION_STAGE_SCRIPT_FALLBACKS: dict[str, list[str]] = {
    "contact_start": [
        "Подскажите, удобно сейчас коротко обсудить вопрос по документам?",
        "Вы сами занимаетесь этим процессом или лучше подключить коллегу, который принимает решение?",
        "Чтобы не тратить ваше время, уточню пару деталей и скажу, есть ли смысл смотреть решение дальше.",
    ],
    "qualification_primary": [
        "Подскажите, вы сами будете принимать решение по подключению или нужно будет согласовать с руководителем?",
        "Как сейчас у вас проходит работа с документами: бумага, email, WhatsApp или уже есть ЭДО?",
        "Что для вас сейчас важнее: ускорить подписание, навести порядок в документах или снизить риски при проверках?",
    ],
    "needs_discovery": [
        "Что сейчас больше всего тормозит процесс работы с документами?",
        "Где чаще всего возникают ошибки или задержки?",
        "Что будет самым важным результатом после внедрения: скорость, контроль, безопасность или экономия времени?",
    ],
    "presentation": [
        "Покажу только то, что связано с вашей задачей, чтобы не уходить в общую презентацию.",
        "Если ваша цель — ускорить работу с документами, здесь важны вот эти два сценария.",
        "Правильно понимаю, что эта функция закрывает тот вопрос, который вы описали?",
    ],
    "objection_handling": [
        "Подскажите, что именно вызывает сомнение: цена, сроки, процесс подключения или согласование внутри?",
        "Давайте разберём этот риск отдельно, чтобы было понятно, что изменится на практике.",
        "Если этот вопрос закрываем, что ещё останется важным перед решением?",
    ],
    "completion_next_step": [
        "Давайте зафиксируем следующий шаг: я отправляю информацию, а мы созваниваемся в согласованное время. Подойдёт?",
        "Кто ещё должен посмотреть информацию перед решением?",
        "Когда лучше вернуться к обсуждению, чтобы не потерять вопрос?",
    ],
    "cross_stage_transition": [
        "Я коротко подытожу, что понял, и дальше покажу только релевантную часть.",
        "Перед тем как перейти дальше, правильно ли я понял вашу задачу?",
        "Если этот пункт понятен, следующий шаг — уточнить, как у вас сейчас устроен процесс.",
    ],
}


def _focus_stage_generic_text(stage_name: str, *, kind: str) -> str:
    """Return compact manager-facing fallback for unknown focus stage codes."""
    stage = stage_name or "фокусный этап"
    if kind == "wrong":
        return f"На этапе «{stage}» менеджеру не хватило конкретики, чтобы продвинуть клиента дальше."
    if kind == "why":
        return f"Когда этап «{stage}» проседает, клиенту сложнее понять ценность предложения и согласиться на следующий шаг."
    if kind == "fix":
        return f"Усилить этап «{stage}»: задать уточняющий вопрос, связать ответ с предложением и зафиксировать следующий шаг."
    return f"В каждом подходящем sales-звонке выполнить минимум по этапу «{stage}» и проверить следующий шаг."


def _is_manager_facing_explanation(text: str) -> bool:
    """Return True when text explains business impact rather than restating the symptom."""
    value = str(text or "").strip().lower()
    if not value:
        return False
    explanation_markers = (
        "без ",
        "потому",
        "поэтому",
        "мешает",
        "снижает",
        "риск",
        "клиент",
        "презентац",
        "потребност",
        "ценност",
        "договор",
        "следующ",
    )
    return any(marker in value for marker in explanation_markers)


def _build_focus_stage_deep_dive(
    *,
    score_by_stage: list[dict[str, Any]],
    key_problem: dict[str, Any],
    recommendations: list[dict[str, Any]],
    daily_focus: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a compact deterministic deep-dive for the priority stage from existing payload data."""
    focus_stage_code = _daily_focus_stage_code(daily_focus)
    priority_stage = next(
        (
            item
            for item in score_by_stage
            if focus_stage_code and str(item.get("stage_code") or "").strip() == focus_stage_code
        ),
        None,
    )
    if priority_stage is None:
        priority_stage = next((item for item in score_by_stage if item.get("is_priority")), None)
    if priority_stage is None and _is_meaningful_key_problem(key_problem):
        scored_stages = [item for item in score_by_stage if item.get("score") is not None]
        if scored_stages:
            priority_stage = min(scored_stages, key=lambda item: float(item.get("score") or 999.0))
    if priority_stage is None:
        return None

    stage_code = str(priority_stage.get("stage_code") or "").strip()
    stage_name = str(priority_stage.get("stage_name") or "").strip()
    if not stage_code and not stage_name:
        return None

    daily_problem_statement = _first_sentence(str((daily_focus or {}).get("problem_statement") or ""))
    prefer_daily_problem = bool(
        (daily_focus or {}).get("problem_statement_source") == "situation_day_selected_case"
        or (daily_focus or {}).get("focus_override_reason")
    )
    problem_summary = (
        daily_problem_statement
        if prefer_daily_problem
        else _first_sentence(str(priority_stage.get("problem_summary") or daily_problem_statement or ""))
    )
    key_title = (
        _first_sentence(str(key_problem.get("title") or ""))
        if _is_meaningful_key_problem(key_problem)
        else ""
    )
    what_went_wrong = problem_summary or key_title or _focus_stage_generic_text(stage_name, kind="wrong")

    key_description = (
        _first_sentence(str(key_problem.get("description") or ""), limit=220)
        if _is_meaningful_key_problem(key_problem)
        else ""
    )
    if (
        key_description
        and (
            key_description.strip().lower() == what_went_wrong.strip().lower()
            or not _is_manager_facing_explanation(key_description)
        )
    ):
        key_description = ""
    why_it_matters = key_description or _FOCUS_STAGE_WHY_FALLBACKS.get(
        stage_code,
        _focus_stage_generic_text(stage_name, kind="why"),
    )

    what_to_fix = _FOCUS_STAGE_FIX_FALLBACKS.get(stage_code, _focus_stage_generic_text(stage_name, kind="fix"))
    if not what_to_fix:
        recommendation = next((item for item in recommendations if _is_meaningful_recommendation(item)), None)
        what_to_fix = _first_sentence(str((recommendation or {}).get("better_phrasing") or ""))
    if not what_to_fix:
        what_to_fix = _focus_stage_generic_text(stage_name, kind="fix")

    minimum_for_tomorrow = _FOCUS_STAGE_MINIMUM_FALLBACKS.get(
        stage_code,
        _focus_stage_generic_text(stage_name, kind="minimum"),
    )

    return {
        "stage_code": stage_code,
        "stage_name": stage_name,
        "what_went_wrong": what_went_wrong,
        "why_it_matters": why_it_matters,
        "what_to_fix": what_to_fix,
        "minimum_for_tomorrow": minimum_for_tomorrow,
    }


def _build_focus_stage_recommendation(
    *,
    focus_stage_deep_dive: dict[str, Any] | None,
    recommendations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build stage-linked next-call recommendation from the already assembled focus stage."""
    if not focus_stage_deep_dive:
        return None

    stage_code = str(focus_stage_deep_dive.get("stage_code") or "").strip()
    stage_name = str(focus_stage_deep_dive.get("stage_name") or "").strip()
    if not stage_code and not stage_name:
        return None

    problem = _first_sentence(str(focus_stage_deep_dive.get("what_went_wrong") or ""))
    recommendation = _first_sentence(str(focus_stage_deep_dive.get("what_to_fix") or ""), limit=220)
    source = "focus_stage_deep_dive" if recommendation else "stage_fallback"

    if not recommendation:
        stage_recommendation = next((item for item in recommendations if _is_meaningful_recommendation(item)), None)
        recommendation = _first_sentence(str((stage_recommendation or {}).get("better_phrasing") or ""), limit=220)
        source = "recommendations" if recommendation else "stage_fallback"

    if not recommendation:
        recommendation = _FOCUS_STAGE_RECOMMENDATION_FALLBACKS.get(
            stage_code,
            _focus_stage_generic_text(stage_name, kind="fix"),
        )

    checklist = _FOCUS_STAGE_CHECKLIST_FALLBACKS.get(stage_code)
    if checklist is None:
        checklist = [
            f"Уточнить ключевой вопрос этапа «{stage_name or 'фокусный этап'}»",
            "Связать ответ клиента с предложением",
            "Зафиксировать следующий шаг",
        ]

    return {
        "stage_code": stage_code,
        "stage_name": stage_name,
        "problem": problem,
        "recommendation": recommendation,
        "checklist": checklist[:3],
        "source": source,
    }


def _stage_score_label(score_by_stage: list[dict[str, Any]], stage_code: str) -> str | None:
    stage = next((item for item in score_by_stage if str(item.get("stage_code") or "") == stage_code), None)
    if stage is None:
        return None
    score = stage.get("score")
    if score is None:
        return None
    try:
        return f"{float(score) / 2:.1f}/5"
    except (TypeError, ValueError):
        return None


def _situation_pattern_title(
    *,
    stage_code: str,
    stage_name: str,
    what_went_wrong: str,
    client_text: str,
) -> str:
    text = f"{client_text} {what_went_wrong}".lower()
    if stage_code == "qualification_primary":
        if any(marker in text for marker in ("бумаг", "электрон", "почт", "документ")):
            return "Клиент спрашивает про формат работы, но контекст не уточнён"
        return "Клиент проявил интерес, но квалификация не раскрыта"
    if stage_code == "needs_discovery":
        return "Потребность клиента обозначена, но не раскрыта глубже"
    if stage_code == "completion_next_step":
        return "Разговор дошёл до интереса, но следующий шаг не закреплён"
    if stage_code == "contact_start":
        return "Контакт начался, но роль и контекст не зафиксированы"
    if stage_code == "presentation":
        return "Предложение прозвучало раньше, чем была понятна задача клиента"
    if stage_code == "objection_handling":
        return "Сомнение клиента прозвучало, но причина не разобрана"
    return f"Фокус на этапе «{stage_name or 'воронки'}»"


def _situation_fact_from_quote(client_text: str) -> str:
    value = str(client_text or "").strip()
    lower = value.lower()
    if any(marker in lower for marker in ("бумаг", "электрон", "почт")):
        return "Клиент уточнял, как будет работать документооборот: на бумаге или по электронной почте."
    if value:
        return f"Клиент сказал: «{_dialogue_turn_text(value, limit=180)}»."
    return ""


def _coaching_missing_text(what_went_wrong: str, stage_code: str) -> str:
    value = _first_sentence(str(what_went_wrong or ""), limit=220)
    if stage_code == "qualification_primary" and "роль" in value.lower():
        return "Менеджер не уточнил роль собеседника и текущий процесс клиента."
    return value


def _build_situation_day_coaching_view(
    *,
    score_by_stage: list[dict[str, Any]],
    situation_evidence_quote: dict[str, Any] | None,
    situation_dialogue_excerpt: dict[str, Any] | None,
    focus_stage_deep_dive: dict[str, Any] | None,
    focus_stage_recommendation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a reference-style coaching view for Situation Day from existing deterministic fields."""
    if not focus_stage_deep_dive:
        return None

    stage_code = str(focus_stage_deep_dive.get("stage_code") or "").strip()
    stage_name = str(focus_stage_deep_dive.get("stage_name") or "").strip()
    if not stage_code and not stage_name:
        return None

    client_text = str((situation_evidence_quote or {}).get("client_text") or "").strip()
    has_grounded_evidence = bool(client_text or (situation_dialogue_excerpt or {}).get("turns"))
    what_went_wrong = _first_sentence(str(focus_stage_deep_dive.get("what_went_wrong") or ""), limit=220)
    meaning = _first_sentence(str(focus_stage_deep_dive.get("why_it_matters") or ""), limit=260)
    what_was_missing = _coaching_missing_text(what_went_wrong, stage_code)
    next_time_action = _first_sentence(str(focus_stage_deep_dive.get("what_to_fix") or ""), limit=240)

    fact = _situation_fact_from_quote(client_text)
    if not has_grounded_evidence:
        what_happened = "Недостаточно evidence для показа ситуации по фокусному этапу."
    elif fact and what_was_missing:
        what_happened = f"{fact} В разговоре не хватило квалификации: {what_was_missing}"
    elif what_was_missing:
        what_happened = f"В звонке проявилась проблема фокусного этапа: {what_was_missing}"
    else:
        what_happened = ""

    scripts = _SITUATION_STAGE_SCRIPT_FALLBACKS.get(stage_code)
    if scripts is None and focus_stage_recommendation:
        scripts = list(focus_stage_recommendation.get("checklist") or [])
    if scripts is None:
        scripts = [
            "Уточните, кто принимает решение и какой процесс у клиента сейчас.",
            "Свяжите предложение с тем, что клиент уже сказал в разговоре.",
            "Зафиксируйте конкретный следующий шаг и срок.",
        ]

    return {
        "pattern_title": (
            "Недостаточно evidence по фокусному этапу"
            if not has_grounded_evidence
            else _situation_pattern_title(
                stage_code=stage_code,
                stage_name=stage_name,
                what_went_wrong=what_went_wrong,
                client_text=client_text,
            )
        ),
        "stage_code": stage_code,
        "stage_label": stage_name,
        "stage_score_label": _stage_score_label(score_by_stage, stage_code),
        "what_happened": what_happened,
        "meaning": meaning,
        "what_was_missing": what_was_missing,
        "next_time_action": next_time_action,
        "scripts": scripts[:3],
        "source": "deterministic_assembly",
        "dialogue_is_partial": bool((situation_dialogue_excerpt or {}).get("is_partial")),
    }


def _extract_score_percent(analysis: Analysis | None) -> float:
    """Read one normalized percentage from analysis payload."""
    if analysis is None:
        return 0.0
    if analysis.score_total is not None:
        return float(analysis.score_total)
    detail = dict(analysis.scores_detail or {})
    score = dict(detail.get("score") or {})
    checklist = dict(score.get("checklist_score") or {})
    return float(checklist.get("score_percent") or 0.0)


def _score_bucket(analysis: Analysis | None) -> str:
    """Map one call analysis to reporting bucket."""
    if analysis is None:
        return "problematic"
    detail = dict(analysis.scores_detail or {})
    score = dict(detail.get("score") or {})
    checklist = dict(score.get("checklist_score") or {})
    level = str(checklist.get("level") or "").lower()
    if level in {"excellent", "strong"}:
        return "strong"
    if level in {"basic"}:
        return "baseline"
    if level in {"problematic"}:
        return "problematic"
    score_percent = _extract_score_percent(analysis)
    if score_percent >= 80:
        return "strong"
    if score_percent >= 60:
        return "baseline"
    return "problematic"


def _finding_item_label(item: dict[str, Any]) -> str:
    """Return a stable manager-facing label from legacy or fresh LLM2 finding shapes."""
    label = str(
        item.get("title")
        or item.get("criterion_name")
        or item.get("criterion_code")
        or item.get("text")
        or ""
    ).strip()
    return label or "Без названия"


def _finding_item_interpretation(item: dict[str, Any]) -> str:
    """Return a readable finding explanation without relying on one contract variant."""
    value = str(
        item.get("impact")
        or item.get("comment")
        or item.get("text")
        or item.get("evidence")
        or ""
    ).strip()
    return value or "Подтверждено в нескольких звонках."


def _aggregate_finding_items(*, artifacts: list[ReportArtifact], key: str) -> list[dict[str, Any]]:
    """Aggregate repeated strength/gap findings into compact report items."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for item in detail.get(key) or []:
            raw_item = dict(item or {})
            label = _finding_item_label(raw_item)
            if key == "gaps":
                stage_code = _stage_code_from_criterion_code(str(raw_item.get("criterion_code") or ""))
                normalized = _normalize_problem_statement(
                    label,
                    stage_code=stage_code,
                    criterion_code=str(raw_item.get("criterion_code") or ""),
                    criterion_name=str(raw_item.get("criterion_name") or raw_item.get("title") or ""),
                )
                label = str(normalized.get("text") or label).strip()
                if normalized.get("source_text"):
                    raw_item = dict(raw_item)
                    raw_item["problem_normalized_from"] = normalized.get("source_text")
                    raw_item["problem_wording_warnings"] = list(normalized.get("warnings") or [])
            grouped.setdefault(label, []).append(item)
    result: list[dict[str, Any]] = []
    for label, items in sorted(grouped.items(), key=lambda pair: len(pair[1]), reverse=True)[:5]:
        first = items[0]
        first_stage_code = _stage_code_from_criterion_code(str(first.get("criterion_code") or ""))
        interpretation = _finding_item_interpretation(dict(first or {}))
        if key == "gaps":
            normalized_interpretation = _normalize_problem_statement(
                interpretation,
                stage_code=first_stage_code,
                criterion_code=str(first.get("criterion_code") or ""),
                criterion_name=str(first.get("criterion_name") or first.get("title") or ""),
                fallback=_stage_problem_fallback(first_stage_code, str(first.get("criterion_code") or "")),
            )
            interpretation = str(normalized_interpretation.get("text") or interpretation).strip()
        result.append(
            {
                "label": label,
                "signal": len(items),
                "criterion_code": str(first.get("criterion_code") or "").strip() or None,
                "interpretation": interpretation,
            }
        )
    return result


def _aggregate_recommendation_cards(*, artifacts: list[ReportArtifact]) -> list[dict[str, Any]]:
    """Build daily recommendation cards from persisted recommendation payloads."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for item in detail.get("recommendations") or []:
            title = str(item.get("criterion_name") or item.get("criterion_code") or "Рекомендация")
            better_phrase = str(
                item.get("better_phrase")
                or item.get("recommendation")
                or item.get("problem")
                or "Уточнить формулировку и закрепить следующий шаг."
            )
            key = f"{title}:{better_phrase}"
            if key in seen:
                continue
            seen.add(key)
            cards.append(
                {
                    "priority_tag": "Сделай завтра" if len(cards) < 2 else "На неделе",
                    "title": title,
                    "reason": str(item.get("reason") or item.get("problem") or "Повторяется в нескольких звонках."),
                    "how_it_sounded": str(item.get("evidence") or "Нужен более точный пример из разговора."),
                    "better_phrasing": better_phrase,
                    "why_this_works": "Помогает сделать следующий шаг понятным и управляемым.",
                }
            )
            if len(cards) >= 5:
                return cards
    if not cards:
        cards.append(
            {
                "priority_tag": "На неделе",
                "title": "Пока недостаточно рекомендаций",
                "reason": "Для этой выборки не найдено устойчивых рекомендаций в persisted payload.",
                "how_it_sounded": "—",
                "better_phrasing": "Проверить полноту анализов и повторить запуск при необходимости.",
                "why_this_works": "Поможет закрыть пробел в данных без полного rerun.",
            }
        )
    return cards


def _build_manager_daily_narrative(
    *,
    manager_name: str,
    average_score: float | None,
    calls_count: int,
    worked_items: list[dict[str, Any]],
    improve_items: list[dict[str, Any]],
) -> str:
    """Return a bounded deterministic narrative until report-composer is activated."""
    label = _performance_label(average_score)
    top_strength = worked_items[0]["label"] if worked_items else "устойчивых сильных эпизодов"
    top_gap = improve_items[0]["label"] if improve_items else "одной доминирующей зоны роста"
    return (
        f"За период у менеджера {manager_name} по {calls_count} звонкам сформировался {label.lower()} результат. "
        f"Сильная сторона выборки: {top_strength}; главный риск: {top_gap}."
    )


def _build_main_focus(
    *,
    improve_items: list[dict[str, Any]],
    recommendation_cards: list[dict[str, Any]],
) -> str:
    """Select one short focus statement for the next day."""
    if not improve_items:
        return "Сохранить текущий темп и проверить полноту фиксации следующего шага."
    next_action = recommendation_cards[0]["better_phrasing"] if recommendation_cards else None
    if next_action:
        return (
            f"Главный фокус на следующий день: усилить '{improve_items[0]['label']}' "
            f"и закрепить это через формулировку: {next_action}"
        )
    return f"Главный фокус на следующий день: усилить '{improve_items[0]['label']}' в каждом разговоре."


def _build_manager_daily_editorial_recommendations(
    *,
    recommendation_cards: list[dict[str, Any]],
) -> str:
    """Build one short editable wording block for manager recommendations."""
    if not recommendation_cards:
        return (
            "Пока в выборке недостаточно устойчивых coaching-паттернов; держим фокус на "
            "конкретном следующем шаге и понятной договорённости."
        )
    lines = [
        f"{item['title']}: {item['better_phrasing']}"
        for item in recommendation_cards[:3]
        if str(item.get("better_phrasing") or "").strip()
    ]
    return " ; ".join(lines) if lines else recommendation_cards[0]["title"]


def _is_next_step_fixed(analysis: Analysis | None) -> bool:
    """Return whether the persisted follow_up marks a fixed next step."""
    detail = dict((analysis.scores_detail or {}) if analysis is not None else {})
    follow_up = dict(detail.get("follow_up") or {})
    return bool(follow_up.get("next_step_fixed"))


CALL_LIST_STATUS_SORT_ORDER = {
    "agreed": 0,
    "rescheduled": 1,
    "refusal": 2,
    "open": 3,
    "tech_service": 4,
}

CALL_LIST_UNCLASSIFIED_SORT_ORDER = {
    "Тех/сервис": 4,
    "Не подходит для разбора": 5,
    "Без транскрипта": 6,
    "Без анализа": 6,
    "Ошибка анализа": 6,
    "Ошибка провайдера": 6,
    "Нет итога": 6,
    "Нет классификации": 6,
    "Без разбора": 6,
}


def _call_list_sort_key(row: dict[str, Any]) -> tuple[int, datetime]:
    """Sort call list by manager-facing status group, then by call time."""
    status = row.get("status")
    if status is not None:
        status_rank = CALL_LIST_STATUS_SORT_ORDER.get(str(status), 6)
    else:
        status_rank = CALL_LIST_UNCLASSIFIED_SORT_ORDER.get(
            str(row.get("unclassified_status_label") or ""),
            6,
        )
    started_at = parse_call_started_at({"call_date": row.get("time")}) or datetime.max.replace(tzinfo=UTC)
    return status_rank, started_at


def _build_meaningful_call_list(
    *,
    window_artifacts: list[ReportArtifact],
    report_evidence_index: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build СПИСОК ЗВОНКОВ ДНЯ from meaningful_calls layer (SM-3).

    Includes all calls that pass _classify_meaningful_call — sales, follow-up,
    and meaningful support/service. Excludes beep, IVR, autoanswer, no-speech noise.
    Sorted by manager-facing outcome order, then call time. Coaching blocks are unaffected
    (use usable/coaching_core).
    """
    meaningful: list[ReportArtifact] = []
    for artifact in window_artifacts:
        is_meaningful, _ = _classify_meaningful_call(artifact)
        if is_meaningful:
            meaningful.append(artifact)
    rows = [
        _build_daily_call_row(item, report_evidence_index=report_evidence_index)
        for item in meaningful
    ]
    rows.sort(key=_call_list_sort_key)
    return rows


CALL_LIST_CONTEXT_TECHNICAL_PATTERNS = (
    "до после",
    "до на этой",
    "до на следующ",
    "→ до",
    "-> до",
)
CALL_LIST_CONTEXT_LOW_INFO = {"—", "-", "нет", "да", "перезвон", "созвон", "дальше", "позже"}
CALL_LIST_RELATIVE_PERIOD_PREFIXES = (
    "после ",
    "на этой ",
    "на следующ",
    "на будущ",
    "на неделе",
    "в течение ",
    "в ближайш",
    "через ",
    "позже",
)


def _lower_first_ru(value: str) -> str:
    text = str(value or "").strip()
    return text[:1].lower() + text[1:] if text else text


def _call_list_is_relative_period(value: str) -> bool:
    normalized = _summary_norm(value).rstrip(".")
    return normalized.startswith(CALL_LIST_RELATIVE_PERIOD_PREFIXES)


def _call_list_deadline_phrase(value: Any) -> str | None:
    """Return human-readable deadline/period phrase for call-list context."""
    text = _format_iso_deadline(str(value or "").strip() or None)
    if not text:
        return None
    text = re.sub(r"\s+", " ", str(text).strip()).rstrip(".")
    if not text:
        return None
    lowered = _summary_norm(text)
    if lowered.startswith("до "):
        text = text[3:].strip()
        lowered = _summary_norm(text)
    if "конец года" in lowered:
        year_match = re.search(r"\b(20\d{2})\b", text)
        return f"в конце {year_match.group(1)} года" if year_match else "в конце года"
    if _call_list_is_relative_period(text):
        return _lower_first_ru(text)
    return f"до {text}"


def _call_list_context_reject_reason(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    normalized = _summary_norm(text)
    if not normalized:
        return "empty_context"
    if normalized in {"—", "-"}:
        return "bare_dash"
    if normalized in CALL_LIST_CONTEXT_LOW_INFO:
        return "low_information"
    if any(pattern in normalized for pattern in CALL_LIST_CONTEXT_TECHNICAL_PATTERNS):
        return "bad_deadline_wording"
    if re.search(r"\b[a-z]{2,}_[a-z0-9_]+\b", text, flags=re.IGNORECASE):
        return "technical_fragment"
    if "…" in text or "..." in text:
        return "truncated_context"
    if len(normalized) < 12:
        return "low_information"
    return None


def _call_list_context_text(value: Any, *, limit: int = 220) -> str | None:
    text = _summary_text(value, limit=limit)
    if not text:
        return None
    return None if _call_list_context_reject_reason(text) else text


def _call_list_status_fallback_context(
    *,
    status: str | None,
    call_type: str | None,
    scenario_type: str | None,
    deadline: str | None,
    next_step: str | None,
    reason: str | None,
    signal_text: str | None,
    unclassified_status_label: str | None,
    unclassified_context_label: str | None,
) -> str:
    """Build a human-readable context when summary context is missing or weak."""
    status_text = str(status or "").strip()
    call_type_text = str(call_type or "").strip()
    scenario_text = str(scenario_type or "").strip()
    deadline_phrase = _call_list_deadline_phrase(deadline)
    combined = _summary_norm(" ".join(str(part or "") for part in (next_step, reason, signal_text)))
    if not status_text:
        context_label = str(unclassified_context_label or "").strip()
        if context_label:
            return context_label
        if str(unclassified_status_label or "") == "Не подходит для разбора":
            return "Не подходит для разбора."
        return "Нет готового разбора по звонку."
    if status_text == "tech_service" or call_type_text in {"support", "internal"}:
        if scenario_text == "after_signed_document":
            return "Звонок после подписания документа, продажный потенциал не раскрыт."
        return "Технический / сервисный звонок, продажный контекст не выявлен."
    if scenario_text == "after_signed_document" and status_text in {"open", "refusal"}:
        return "Звонок после подписания документа, продажный потенциал не раскрыт."
    if status_text == "rescheduled":
        if deadline_phrase:
            return f"Клиент попросил вернуться в согласованный срок: {deadline_phrase}."
        return "Клиент попросил вернуться позже, точный срок не извлечён."
    if status_text == "agreed":
        if _contains_hotness_signal(combined, CALL_TOMORROW_INVOICE_MARKERS):
            suffix = f" Срок: {deadline_phrase}." if deadline_phrase else ""
            return f"Есть коммерческий следующий шаг: отправить счёт, подтвердить получение и согласовать оплату.{suffix}"
        if deadline_phrase:
            return f"Есть договорённость, следующий шаг нужно выполнить {deadline_phrase}."
        return "Есть договорённость, следующий шаг нужно подтвердить и довести до результата."
    if status_text == "open":
        if _contains_hotness_signal(combined, CALL_TOMORROW_MATERIALS_MARKERS):
            return "Клиент попросил материалы, следующий контакт нужно закрепить отдельно."
        return "Контакт открыт, следующий шаг не зафиксирован."
    if status_text == "refusal":
        reason_text = _call_list_context_text(reason, limit=160)
        if reason_text:
            return f"Клиент отказался: {reason_text.rstrip('.') }."
        return "Клиент отказался, причина отказа не извлечена."
    return "Контекст звонка требует уточнения по сохранённым данным."


def _select_call_list_context(
    *,
    status: str | None,
    call_type: str | None,
    scenario_type: str | None,
    deadline: str | None,
    next_step: str | None,
    reason: str | None,
    signal_text: str | None,
    summary_topic: str | None,
    summary_context: str | None,
    unclassified_status_label: str | None,
    unclassified_context_label: str | None,
) -> dict[str, Any]:
    rejected: list[dict[str, str]] = []

    def reject(source: str, value: Any) -> str | None:
        reason_code = _call_list_context_reject_reason(value)
        if reason_code:
            rejected.append({"source": source, "reason": reason_code, "value": str(value or "")[:140]})
        return reason_code

    if summary_context and _call_summary_context_usable(summary_context) and not reject(
        "report_evidence.call_report_summary.short_context",
        summary_context,
    ):
        return {
            "context": summary_context,
            "source": "report_evidence.call_report_summary.short_context",
            "rejected": rejected,
            "fallback_generated": False,
            "bare_context_retained": False,
        }
    if summary_topic and _call_summary_topic_usable(summary_topic) and not reject(
        "report_evidence.call_report_summary.short_topic",
        summary_topic,
    ):
        topic_context = summary_topic if summary_topic.endswith((".", "!", "?")) else f"{summary_topic}."
        return {
            "context": topic_context,
            "source": "report_evidence.call_report_summary.short_topic",
            "rejected": rejected,
            "fallback_generated": False,
            "bare_context_retained": False,
        }

    fallback = _call_list_status_fallback_context(
        status=status,
        call_type=call_type,
        scenario_type=scenario_type,
        deadline=deadline,
        next_step=next_step,
        reason=reason,
        signal_text=signal_text,
        unclassified_status_label=unclassified_status_label,
        unclassified_context_label=unclassified_context_label,
    )
    reject_reason = reject("deterministic_fallback", fallback)
    if reject_reason:
        fallback = "Контекст звонка требует уточнения по сохранённым данным."
    return {
        "context": fallback,
        "source": "deterministic_context_quality_gate",
        "rejected": rejected,
        "fallback_generated": True,
        "bare_context_retained": False,
    }


def _build_call_list_context_quality_diagnostics(call_list: list[dict[str, Any]]) -> dict[str, Any]:
    rejected: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    fallback_generated_count = 0
    bare_retained: list[dict[str, Any]] = []
    final_failures: list[dict[str, Any]] = []
    for row in call_list:
        source = str(row.get("call_list_context_source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        if source == "deterministic_context_quality_gate":
            fallback_generated_count += 1
        final_reason = _call_list_context_reject_reason(row.get("call_list_context"))
        if final_reason:
            final_failures.append(
                {
                    "interaction_id": row.get("interaction_id"),
                    "status": row.get("status"),
                    "reason": final_reason,
                    "value": str(row.get("call_list_context") or "")[:140],
                }
            )
        if row.get("call_list_context_bare_retained"):
            bare_retained.append(
                {
                    "interaction_id": row.get("interaction_id"),
                    "status": row.get("status"),
                    "reason": row.get("call_list_context_bare_reason") or "allowed",
                }
            )
        for item in row.get("call_list_context_rejected") or []:
            rejected.append(
                {
                    "interaction_id": row.get("interaction_id"),
                    "status": row.get("status"),
                    **dict(item),
                }
            )
    return {
        "status": "warning" if final_failures or bare_retained else "passed",
        "calls_count": len(call_list),
        "call_report_summary_context_count": source_counts.get("report_evidence.call_report_summary.short_context", 0),
        "call_report_summary_topic_count": source_counts.get("report_evidence.call_report_summary.short_topic", 0),
        "fallback_generated_count": fallback_generated_count,
        "bare_context_retained_count": len(bare_retained),
        "bare_context_retained": bare_retained,
        "final_failure_count": len(final_failures),
        "final_failures": final_failures,
        "rejected_count": len(rejected),
        "rejected_contexts": rejected,
        "source_counts": source_counts,
    }


def _reason_label(reason_code: str | None) -> str | None:
    """Return diagnostic Russian label for an unclassified reason code."""
    if not reason_code:
        return None
    return UNCLASSIFIED_REASON_LABELS.get(reason_code, UNCLASSIFIED_REASON_LABELS["unknown"])


def _manager_unclassified_status(reason_code: str | None) -> str | None:
    """Return manager-facing bucket for an unclassified diagnostic reason."""
    if not reason_code:
        return None
    return UNCLASSIFIED_MANAGER_STATUS_LABELS.get(reason_code, UNCLASSIFIED_MANAGER_STATUS_LABELS["unknown"])


def _manager_unclassified_context(reason_code: str | None) -> str | None:
    """Return compact manager-facing context for an unclassified diagnostic reason."""
    if not reason_code:
        return None
    return UNCLASSIFIED_MANAGER_CONTEXT_LABELS.get(reason_code, UNCLASSIFIED_MANAGER_CONTEXT_LABELS["unknown"])


def _is_cdr_only_probable_live(artifact: ReportArtifact) -> bool:
    """Return True when a no-transcript row entered meaningful via source-side live signal."""
    if artifact.interaction.text:
        return False
    metadata = dict(getattr(artifact.interaction, "metadata_", None) or {})
    source_status = str(metadata.get("source_status") or "").strip().lower()
    direction = str(metadata.get("direction") or "").strip().lower()
    duration = artifact.interaction.duration_sec or 0
    return (
        (not source_status or source_status == "answered")
        and (not direction or direction in {"in", "out"})
        and duration >= MEANINGFUL_NO_TRANSCRIPT_MIN_DURATION_SEC
    )


def _analysis_failure_text(analysis: Any, reuse_reason: str | None) -> str:
    """Return non-secret persisted failure context for deterministic bucket classification."""
    parts = [reuse_reason or ""]
    for attr in ("fail_reason", "error_message", "error", "status_reason"):
        value = getattr(analysis, attr, None)
        if value:
            parts.append(str(value))
    detail = getattr(analysis, "scores_detail", None)
    if isinstance(detail, dict):
        for key in ("fail_reason", "error", "error_message", "validation_error"):
            value = detail.get(key)
            if value:
                parts.append(str(value))
    return " ".join(part for part in parts if part).strip()


def _classify_failed_analysis_reason(analysis: Any, reuse_reason: str | None) -> str:
    """Classify persisted failed analysis into manager/operator buckets."""
    text = _analysis_failure_text(analysis, reuse_reason).lower()
    if any(
        token in text
        for token in (
            "not_coachable_or_reportable",
            "not_coachable",
            "not_reportable",
            "semantic_empty",
            "semantically empty",
        )
    ):
        return "semantic_empty" if "semantic" in text else "not_coachable_or_reportable"
    if any(
        token in text
        for token in (
            "insufficient_quota",
            "quota",
            "429",
            "rate limit",
            "rate_limited",
            "timeout",
            "provider",
            "openai",
            "auth",
            "401",
            "403",
            "5xx",
            "500",
            "502",
            "503",
            "504",
        )
    ):
        return "analysis_failed_provider"
    if any(
        token in text
        for token in (
            "criterion",
            "missing required fields",
            "validation",
            "contract",
            "parser",
            "parse",
            "schema",
        )
    ):
        return "analysis_failed_contract"
    return "analysis_failed_unknown"


def _derive_unclassified_reason(artifact: ReportArtifact) -> tuple[str | None, str | None]:
    """Explain why a meaningful call has no manager-facing classification."""
    if artifact.analysis is not None:
        detail = dict(artifact.analysis.scores_detail or {})
        classification = dict(detail.get("classification") or {})
        call_type = str(classification.get("call_type") or "").strip().lower()
        eligibility = str(classification.get("analysis_eligibility") or "").strip().lower()
        follow_up = detail.get("follow_up")
        if not classification or not call_type:
            reason_code = "missing_classification"
        elif call_type in {"support", "internal"}:
            reason_code = "support_or_internal"
        elif eligibility == "not_eligible":
            reason_code = "not_eligible"
        elif eligibility in {"not_coachable", "not_reportable", "not_coachable_or_reportable"}:
            reason_code = "not_coachable_or_reportable"
        elif not isinstance(follow_up, dict) or not follow_up:
            reason_code = "no_follow_up_outcome"
        else:
            reason_code = None
        return reason_code, _reason_label(reason_code)

    original_analysis = artifact.original_analysis
    reuse_reason = str(artifact.analysis_reuse_reason or "").strip()
    if original_analysis is not None:
        if bool(getattr(original_analysis, "is_failed", False)):
            reason_code = _classify_failed_analysis_reason(original_analysis, reuse_reason)
        elif any(token in reuse_reason for token in ("not_coachable", "not_reportable", "not_coachable_or_reportable", "semantic_empty")):
            reason_code = "semantic_empty" if "semantic_empty" in reuse_reason else "not_coachable_or_reportable"
        elif reuse_reason and reuse_reason not in {"missing_analysis", "reusable"}:
            reason_code = "analysis_not_reusable"
        else:
            reason_code = "no_analysis"
        return reason_code, _reason_label(reason_code)

    if not artifact.interaction.text:
        reason_code = "no_transcript" if getattr(artifact.interaction, "raw_ref", None) else "cdr_only_probable_live"
        if not _is_cdr_only_probable_live(artifact):
            reason_code = "no_transcript"
        return reason_code, _reason_label(reason_code)

    return "no_analysis", _reason_label("no_analysis")


def _build_unclassified_breakdown(*, artifacts: list[ReportArtifact]) -> dict[str, Any]:
    """Build structured diagnostics for report-day meaningful calls without classification."""
    by_reason: dict[str, int] = {}
    sample_calls: list[dict[str, Any]] = []
    total = 0
    for artifact in sorted(artifacts, key=lambda a: a.call_started_at or datetime.min.replace(tzinfo=UTC)):
        row = _build_daily_call_row(artifact)
        if row.get("status") is not None:
            continue
        reason_code = row.get("unclassified_reason_code") or "unknown"
        reason_label = row.get("unclassified_reason_label") or UNCLASSIFIED_REASON_LABELS["unknown"]
        total += 1
        by_reason[reason_code] = by_reason.get(reason_code, 0) + 1
        if len(sample_calls) < 10:
            sample_calls.append(
                {
                    "time": _short_time_label(row.get("time")),
                    "client": row.get("client_or_phone"),
                    "reason_code": reason_code,
                    "reason_label": reason_label,
                    "status_label": row.get("unclassified_status_label"),
                }
            )
    return {
        "total": total,
        "by_reason": by_reason,
        "sample_calls": sample_calls,
    }


def _build_manager_facing_completeness_gate(*, call_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Return whether a manager_daily call list is ready for business delivery."""
    blocking_counts = {
        "no_transcript": 0,
        "no_analysis": 0,
        "analysis_error": 0,
        "provider_error": 0,
    }
    counts_by_bucket = {bucket: 0 for bucket in sorted(MANAGER_FACING_COMPLETENESS_BLOCKING_BUCKETS)}
    affected_calls: list[dict[str, Any]] = []
    for row in call_list:
        if row.get("status") is not None:
            continue
        bucket = str(row.get("unclassified_status_label") or _manager_unclassified_status(row.get("unclassified_reason_code")) or "")
        if bucket not in MANAGER_FACING_COMPLETENESS_BLOCKING_BUCKETS:
            continue
        reason_code = str(row.get("unclassified_reason_code") or "unknown")
        counts_by_bucket[bucket] += 1
        if bucket == "Без транскрипта":
            blocking_counts["no_transcript"] += 1
        elif bucket == "Без анализа":
            blocking_counts["no_analysis"] += 1
        elif bucket == "Ошибка провайдера":
            blocking_counts["provider_error"] += 1
        else:
            blocking_counts["analysis_error"] += 1
        affected_calls.append(
            {
                "time": _short_time_label(row.get("time")),
                "client": row.get("client_or_phone"),
                "duration_sec": row.get("duration_sec"),
                "reason_code": reason_code,
                "reason_label": row.get("unclassified_reason_label") or _reason_label(reason_code),
                "bucket": bucket,
                "required_action": MANAGER_FACING_COMPLETENESS_REQUIRED_ACTIONS.get(
                    bucket,
                    "Проверить звонок перед отправкой менеджеру.",
                ),
            }
        )
    total_blocking = sum(blocking_counts.values())
    passed = total_blocking == 0
    return {
        "status": "passed" if passed else "review_required",
        "manager_report_allowed": passed,
        "reason": None if passed else "incomplete_day_call_processing",
        "blocking_counts": blocking_counts,
        "counts": counts_by_bucket,
        "affected_calls_count": total_blocking,
        "affected_calls": affected_calls,
    }


def _short_time_label(value: Any) -> str | None:
    """Return HH:MM from an ISO datetime-ish value for diagnostics samples."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%H:%M")
    except ValueError:
        if len(raw) >= 16 and raw[10] in {"T", " "}:
            return raw[11:16]
        return raw


def _build_daily_call_row(
    artifact: ReportArtifact,
    *,
    report_evidence_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one short daily call row."""
    source_analysis = artifact.analysis or artifact.original_analysis
    detail = dict((getattr(source_analysis, "scores_detail", None) or {}) if source_analysis is not None else {})
    call = dict(detail.get("call") or {})
    follow_up = dict(detail.get("follow_up") or {})
    classification = dict(detail.get("classification") or {})
    call_type = classification.get("call_type")
    outcome = BusinessOutcomeResolver().resolve(artifact)
    status = outcome.final_status
    deadline = outcome.deadline
    unclassified_reason_code = None
    unclassified_reason_label = None
    if status is None:
        unclassified_reason_code = outcome.reason_code
        unclassified_reason_label = _reason_label(unclassified_reason_code)
    unclassified_status_label = _manager_unclassified_status(unclassified_reason_code)
    unclassified_context_label = _manager_unclassified_context(unclassified_reason_code)
    ref = _artifact_call_reference(artifact)
    summary, _summary_evidence = _valid_call_report_summary_for_interaction(
        interaction_id=str(artifact.interaction.id),
        report_evidence_index=report_evidence_index,
    )
    summary_topic_raw = _summary_text((summary or {}).get("short_topic"), limit=120) if summary else None
    summary_topic = summary_topic_raw.rstrip(".") if summary_topic_raw else None
    summary_context = _summary_text((summary or {}).get("short_context"), limit=280) if summary else None
    topic_used = bool(summary_topic and _call_summary_topic_usable(summary_topic))
    next_step = follow_up.get("next_step_text")
    reason = str(follow_up.get("reason_not_fixed") or "").strip() or None
    signal_text = _summary_text(getattr(artifact.interaction, "text", None), limit=500)
    scenario_type = classification.get("scenario_type")
    context_selection = _select_call_list_context(
        status=status,
        call_type=str(call_type or "").strip() or None,
        scenario_type=str(scenario_type or "").strip() or None,
        deadline=deadline,
        next_step=str(next_step or "").strip() or None,
        reason=reason,
        signal_text=signal_text,
        summary_topic=summary_topic,
        summary_context=summary_context,
        unclassified_status_label=unclassified_status_label,
        unclassified_context_label=unclassified_context_label,
    )
    return {
        "interaction_id": str(artifact.interaction.id),
        "time": artifact.call_started_at.isoformat() if artifact.call_started_at else None,
        "client_or_phone": call.get("contact_name") or call.get("contact_phone") or (artifact.interaction.metadata_ or {}).get("contact_phone"),
        "client_name": ref.get("client_name"),
        "client_phone": ref.get("client_phone"),
        "client_call_reference": ref.get("client_call_reference"),
        "date_label": ref.get("date_label"),
        "time_label": ref.get("time_label"),
        "duration_sec": artifact.interaction.duration_sec,
        "call_signal_text": signal_text,
        "call_type": call_type,
        "scenario_type": scenario_type,
        "status": status,
        "next_step": next_step,
        "deadline": deadline,
        "reason": reason,
        "score_percent": _extract_score_percent(artifact.analysis),
        "unclassified_reason_code": unclassified_reason_code,
        "unclassified_reason_label": unclassified_reason_label,
        "unclassified_status_label": unclassified_status_label,
        "unclassified_context_label": unclassified_context_label,
        "business_outcome_reason_code": outcome.reason_code,
        "business_outcome_evidence": outcome.evidence,
        "business_outcome_confidence": outcome.confidence,
        "call_report_summary_available": bool(summary),
        "call_report_summary_short_topic": summary_topic,
        "call_report_summary_short_context": summary_context,
        "call_list_topic": summary_topic if topic_used else None,
        "call_list_context": context_selection["context"],
        "call_list_topic_source": "report_evidence.call_report_summary.short_topic" if topic_used else "deterministic_fallback",
        "call_list_context_source": context_selection["source"],
        "call_list_context_quality": {
            "source": context_selection["source"],
            "fallback_generated": context_selection["fallback_generated"],
            "rejected_count": len(context_selection["rejected"]),
        },
        "call_list_context_rejected": context_selection["rejected"],
        "call_list_context_fallback_generated": context_selection["fallback_generated"],
        "call_list_context_bare_retained": context_selection["bare_context_retained"],
    }


def _build_weekly_dashboard_row(group: list[ReportArtifact]) -> dict[str, Any]:
    """Build one dashboard row for one manager."""
    manager_name = group[0].manager.name if group[0].manager is not None else _fallback_manager_name(group[0])
    scores = [_extract_score_percent(item.analysis) for item in group]
    avg_score = round(sum(scores) / len(scores), 1) if scores else None
    strong = sum(1 for item in group if _score_bucket(item.analysis) == "strong")
    problematic = sum(1 for item in group if _score_bucket(item.analysis) == "problematic")
    stop_flags = sum(1 for item in group if _has_stop_flag(item.analysis))
    status_signal = _weekly_status_signal(avg_score=avg_score, problematic_pct=_pct(problematic, len(group)))
    return {
        "manager_id": str(group[0].interaction.manager_id) if group[0].interaction.manager_id else None,
        "manager_name": manager_name,
        "department": str((group[0].interaction.metadata_ or {}).get("department_name") or "Отдел продаж"),
        "calls_count": len(group),
        "average_score": avg_score,
        "trend_label": "n/a",
        "strong_calls_pct": _pct(strong, len(group)),
        "problematic_calls_pct": _pct(problematic, len(group)),
        "stop_flags_pct": _pct(stop_flags, len(group)),
        "status_signal": status_signal,
    }


def _build_risk_zone_card(group: list[ReportArtifact]) -> dict[str, Any]:
    """Build one bounded risk card for a manager."""
    row = _build_weekly_dashboard_row(group)
    improve = _aggregate_finding_items(artifacts=group, key="gaps")
    return {
        "manager_name": row["manager_name"],
        "department": row["department"],
        "calls_count": row["calls_count"],
        "average_score": row["average_score"],
        "core_problem_statement": improve[0]["label"] if improve else "Нужна дополнительная проверка качества звонков",
        "action_for_rop": (
            f"Разобрать с менеджером тему '{improve[0]['label']}' и проверить фиксацию следующего шага."
            if improve
            else "Проверить выборку звонков и зафиксировать конкретную зону риска."
        ),
        "stage_profile_snapshot": improve[:3],
    }


def _build_systemic_problems(artifacts: list[ReportArtifact]) -> list[dict[str, Any]]:
    """Aggregate repeated weekly team problems."""
    grouped: dict[str, int] = {}
    for item in _aggregate_finding_items(artifacts=artifacts, key="gaps"):
        grouped[item["label"]] = int(item["signal"])
    result: list[dict[str, Any]] = []
    for label, count in sorted(grouped.items(), key=lambda pair: pair[1], reverse=True)[:5]:
        result.append(
            {
                "affected_managers_count": count,
                "problem_title": label,
                "explanation": "Проблема повторяется в нескольких звонках недели и требует системной реакции.",
                "recommended_systemic_action": f"Добавить целевую разборку по теме '{label}' на ближайшую неделю.",
                "timing_note": "На ближайшей неделе",
            }
        )
    return result


def _build_top_blocks(dashboard_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pick compact top and anti-top blocks."""
    if not dashboard_rows:
        empty = {
            "manager": None,
            "supporting_metrics": {},
            "interpretation": "Нет данных",
            "recommendation_to_rop": "Проверить, почему нет weekly выборки.",
        }
        return empty, empty
    sorted_rows = sorted(
        dashboard_rows,
        key=lambda item: item["average_score"] if item["average_score"] is not None else -1,
        reverse=True,
    )
    best = sorted_rows[0]
    worst = sorted_rows[-1]
    return (
        {
            "manager": best["manager_name"],
            "supporting_metrics": {
                "average_score": best["average_score"],
                "calls_count": best["calls_count"],
            },
            "interpretation": "Лучший результат недели по текущему качеству звонков.",
            "recommendation_to_rop": "Использовать как внутренний ориентир и источник удачных формулировок.",
        },
        {
            "manager": worst["manager_name"],
            "supporting_metrics": {
                "average_score": worst["average_score"],
                "calls_count": worst["calls_count"],
            },
            "interpretation": "Требует внимания по качеству звонков уже в ближайшую неделю.",
            "recommendation_to_rop": "Назначить короткий разбор и проверить, закреплён ли фокус на исправление.",
        },
    )


def _build_rop_tasks(
    *,
    risk_zone_cards: list[dict[str, Any]],
    systemic_team_problems: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a compact next-week ROP task list."""
    tasks: list[dict[str, Any]] = []
    for card in risk_zone_cards[:5]:
        tasks.append(
            {
                "manager": card["manager_name"],
                "priority": "Высокий",
                "task_for_next_week": card["action_for_rop"],
                "how_to_verify": "Проверить 2-3 следующих звонка после разбора.",
                "deadline": "На следующей неделе",
            }
        )
    if systemic_team_problems:
        tasks.append(
            {
                "manager": "Команда",
                "priority": "Средний",
                "task_for_next_week": systemic_team_problems[0]["recommended_systemic_action"],
                "how_to_verify": "Сравнить повторяемость проблемы в следующем weekly отчёте.",
                "deadline": "На следующей неделе",
            }
        )
    if not tasks:
        tasks.append(
            {
                "manager": "Команда",
                "priority": "Поддержка",
                "task_for_next_week": "Поддерживать текущий уровень и собрать ещё одну weekly выборку.",
                "how_to_verify": "Сравнить quality snapshot следующей недели.",
                "deadline": "Следующая неделя",
            }
        )
    return tasks


def _select_stable_analysis_for_reporting(
    analyses: list[Analysis],
    *,
    include_controlled_samples: bool = False,
    analysis_instruction_version: str | None = None,
) -> Analysis | None:
    """Pick the newest reusable analysis allowed by the reporting selection policy.

    Input rows must be sorted newest first. If no reusable allowed row exists,
    return the newest allowed row so the existing rejection diagnostics can
    explain why the call has no reusable analysis. With an exact instruction
    version guard, a mismatched row can be returned only as that diagnostic
    candidate; _is_analysis_reusable_for_reporting must still reject it.
    """
    allowed = [
        analysis
        for analysis in analyses
        if include_controlled_samples or not is_controlled_analysis(analysis)
    ]
    required_instruction_version = _normalize_analysis_instruction_version(
        analysis_instruction_version
    )
    if required_instruction_version:
        matching_version = [
            analysis
            for analysis in allowed
            if _analysis_instruction_version(analysis) == required_instruction_version
        ]
        if matching_version:
            allowed = matching_version
        elif allowed:
            return allowed[0]
    if not allowed:
        return None
    fallback = allowed[0]
    for analysis in allowed:
        reusable, _reason = _is_analysis_reusable_for_reporting(
            analysis,
            required_instruction_version=required_instruction_version,
        )
        if reusable:
            return analysis
    return fallback


def _is_analysis_reusable_for_reporting(
    analysis: Analysis | None,
    *,
    required_instruction_version: str | None = None,
) -> tuple[bool, str]:
    """Return whether the persisted analysis is reusable for reporting."""
    if analysis is None:
        return False, "missing_analysis"
    instruction_version = _analysis_instruction_version(analysis)
    normalized_required_version = _normalize_analysis_instruction_version(
        required_instruction_version
    )
    if normalized_required_version and instruction_version != normalized_required_version:
        return False, _instruction_version_mismatch_reason(
            expected=normalized_required_version,
            actual=instruction_version,
        )
    if bool(getattr(analysis, "is_failed", False)):
        fail_reason = str(getattr(analysis, "fail_reason", "") or "").strip()
        if fail_reason:
            return False, fail_reason
        return False, "analysis_marked_failed"
    if not instruction_version:
        return False, "missing_instruction_version"
    detail = getattr(analysis, "scores_detail", None)
    if not isinstance(detail, dict) or not detail:
        return False, "scores_detail_missing"
    missing_keys = [key for key in REPORTING_REQUIRED_ANALYSIS_KEYS if key not in detail]
    if missing_keys:
        return False, f"missing_required_keys:{','.join(missing_keys)}"
    checklist_score = dict(dict(detail.get("score") or {}).get("checklist_score") or {})
    if checklist_score.get("score_percent") is None:
        return False, "missing_checklist_score_percent"
    if not isinstance(detail.get("follow_up"), dict):
        return False, "invalid_follow_up_shape"
    if (
        not (detail.get("score_by_stage") or [])
        and not (detail.get("strengths") or [])
        and not (detail.get("gaps") or [])
        and not (detail.get("recommendations") or [])
    ):
        return False, SEMANTIC_EMPTY_ANALYSIS_REASON
    return True, "reusable"


def _normalize_analysis_instruction_version(value: str | None) -> str | None:
    """Normalize an optional exact instruction-version guard."""
    normalized = str(value or "").strip()
    return normalized or None


def _analysis_instruction_version(analysis: Analysis | None) -> str:
    """Return the normalized persisted instruction version for diagnostics."""
    return str(getattr(analysis, "instruction_version", "") or "").strip()


def _instruction_version_mismatch_reason(*, expected: str, actual: str) -> str:
    """Build a stable reuse rejection reason for exact-version guards."""
    return f"instruction_version_mismatch:expected={expected}:actual={actual or 'missing'}"


def _is_instruction_version_mismatch_reason(reason: str | None) -> bool:
    """Return True for instruction-version guard rejection tokens."""
    return str(reason or "").startswith("instruction_version_mismatch:")


def _is_coaching_core_eligible(artifact: ReportArtifact) -> bool:
    """Return whether an artifact may enter manager_daily coaching_core."""
    detail = getattr(artifact.analysis, "scores_detail", None)
    if not isinstance(detail, dict):
        return False
    classification = dict(detail.get("classification") or {})
    call_type = str(classification.get("call_type") or "").strip().lower()
    eligibility = str(classification.get("analysis_eligibility") or "").strip().lower()
    if eligibility == "not_eligible":
        return False
    if call_type in {"support", "internal"} and eligibility == "not_eligible":
        return False
    return True


def _is_interaction_source_build_eligible(interaction: Interaction) -> bool:
    """Return True when a persisted source call can enter audio/STT build."""
    metadata = dict(interaction.metadata_ or {})
    source_status = str(metadata.get("source_status") or "").strip().lower()
    direction = str(metadata.get("direction") or "").strip().lower()
    if source_status and source_status not in calls_config.allowed_statuses:
        return False
    if direction and direction not in calls_config.allowed_directions:
        return False
    if not interaction.raw_ref and not _onlinepbx_canonical_call_id(interaction):
        return False
    return True


def _build_focus_of_week(
    *,
    improve_items: list[dict[str, Any]],
    worked_items: list[dict[str, Any]],
) -> str | None:
    """Build a short focus line from the strongest repeated pattern."""
    if improve_items:
        return f"Сквозной фокус периода: {improve_items[0]['label']} повторяется чаще всего и должен стать темой ближайших разборов."
    if worked_items:
        return f"Сквозной опорный паттерн периода: {worked_items[0]['label']} стоит сохранять как образец для следующих звонков."
    return None


def _latest_call_score(artifacts: list[ReportArtifact]) -> float | None:
    """Return score of the latest call in the current group."""
    latest = max(
        artifacts,
        key=lambda item: item.call_started_at or datetime.min.replace(tzinfo=UTC),
        default=None,
    )
    if latest is None:
        return None
    return _extract_score_percent(latest.analysis)


def _build_voice_of_customer(*, artifacts: list[ReportArtifact]) -> dict[str, Any]:
    """Build up to 3 client situation snapshots from evidence_fragments and product_signals.

    Selection rule: prefer evidence_fragments with meaningful client_text (≥15 chars),
    prioritise missed_opportunity type first across all artifacts, then fill with
    product_signal quotes. Deduplicates by quote text.
    """
    situations: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _client_meta(artifact: ReportArtifact) -> dict[str, Any]:
        return _artifact_call_reference(artifact)

    def _add_from_fragments(frag_type_priority: str | None) -> None:
        for artifact in artifacts:
            detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
            for frag in (detail.get("evidence_fragments") or []):
                if frag_type_priority and str(frag.get("fragment_type") or "") != frag_type_priority:
                    continue
                client_text = str(frag.get("client_text") or "").strip()
                if len(client_text) < 15 or client_text in seen:
                    continue
                seen.add(client_text)
                ref = _client_meta(artifact)
                why = str(frag.get("why") or "").strip()
                action, action_source, category = _voice_customer_manager_action(
                    quote=client_text,
                    topic=frag.get("fragment_type"),
                    meaning=why,
                    context=why,
                )
                context = _voice_customer_context_with_action(meaning=why, action=action)
                situations.append({
                    "client_label": ref["client_label"],
                    "client_phone": ref["client_phone"],
                    "date_label": ref["date_label"],
                    "time_label": ref["time_label"],
                    "client_call_reference": ref["client_call_reference"],
                    "quote": client_text[:120] + ("…" if len(client_text) > 120 else ""),
                    "context": context[:257].rstrip() + "…" if context and len(context) > 260 else context,
                    "interpretation": context[:257].rstrip() + "…" if context and len(context) > 260 else context,
                    "manager_action": action,
                    "manager_action_source": action_source,
                    "customer_signal": category,
                })
                if len(situations) >= 3:
                    return

    _add_from_fragments("missed_opportunity")
    if len(situations) < 3:
        _add_from_fragments(None)

    if len(situations) < 3:
        for artifact in artifacts:
            detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
            ref = _client_meta(artifact)
            for sig in (detail.get("product_signals") or []):
                quote = str(sig.get("quote") or "").strip()
                if len(quote) < 10 or quote in seen:
                    continue
                seen.add(quote)
                topic = str(sig.get("topic") or "").strip()
                action, action_source, category = _voice_customer_manager_action(
                    quote=quote,
                    topic=topic,
                    meaning=topic,
                )
                context = _voice_customer_context_with_action(meaning=topic, action=action)
                situations.append({
                    "client_label": ref["client_label"],
                    "client_phone": ref["client_phone"],
                    "date_label": ref["date_label"],
                    "time_label": ref["time_label"],
                    "client_call_reference": ref["client_call_reference"],
                    "quote": quote[:120] + ("…" if len(quote) > 120 else ""),
                    "context": context[:257].rstrip() + "…" if context and len(context) > 260 else context,
                    "interpretation": context[:257].rstrip() + "…" if context and len(context) > 260 else context,
                    "manager_action": action,
                    "manager_action_source": action_source,
                    "customer_signal": category,
                })
                if len(situations) >= 3:
                    break
            if len(situations) >= 3:
                break

    return {
        "is_placeholder": len(situations) == 0,
        "situations": situations[:3],
    }


def _build_additional_situations(
    *,
    improve_items: list[dict[str, Any]],
    worked_items: list[dict[str, Any]],
    top_gap_title: str | None,
) -> dict[str, Any]:
    """Build up to 3 additional coaching situations, excluding the top gap already shown in СИТУАЦИЯ ДНЯ.

    Priority: secondary gaps (improve_items[1:]) first, then strengths (worked_items) as reinforcement.
    Each situation has: kind ("gap" or "strength"), title, signal (count), interpretation.
    """
    situations: list[dict[str, Any]] = []
    seen_titles: set[str] = {str(top_gap_title or "").strip().lower()}

    for item in improve_items:
        if len(situations) >= 3:
            break
        stage_code = _stage_code_from_criterion_code(str(item.get("criterion_code") or ""))
        normalized_label = _normalize_problem_statement(
            item.get("label"),
            stage_code=stage_code,
            criterion_code=str(item.get("criterion_code") or ""),
            fallback=_stage_problem_fallback(stage_code),
        )
        label = str(normalized_label.get("text") or item.get("label") or "").strip()
        if not label or label.strip().lower() in seen_titles:
            continue
        seen_titles.add(label.strip().lower())
        normalized_interpretation = _normalize_problem_statement(
            item.get("interpretation"),
            stage_code=stage_code,
            criterion_code=str(item.get("criterion_code") or ""),
            fallback=label,
        )
        situations.append({
            "kind": "gap",
            "title": label,
            "stage_id": _stage_funnel_label_for_code(stage_code),
            "stage_code": stage_code,
            "problem_signal": _focus_problem_signal(
                " ".join(part for part in (stage_code or "", label) if part),
                fallback=stage_code or "additional_gap",
            ),
            "title_normalized_from": normalized_label.get("source_text"),
            "body_normalized_from": normalized_interpretation.get("source_text"),
            "problem_wording_warnings": sorted(
                set(list(normalized_label.get("warnings") or []) + list(normalized_interpretation.get("warnings") or []))
            ),
            "signal": int(item.get("signal") or 0),
            "interpretation": str(normalized_interpretation.get("text") or "Выявлено в нескольких звонках."),
        })

    for item in worked_items:
        if len(situations) >= 3:
            break
        label = str(item.get("label") or "").strip()
        if not label or label.strip().lower() in seen_titles:
            continue
        seen_titles.add(label.strip().lower())
        situations.append({
            "kind": "strength",
            "title": label,
            "problem_signal": _focus_problem_signal(label, fallback="additional_strength"),
            "signal": int(item.get("signal") or 0),
            "interpretation": str(item.get("interpretation") or "Хорошо отработано в нескольких звонках."),
        })

    return {
        "is_placeholder": len(situations) == 0,
        "situations": situations[:3],
    }


def _call_tomorrow_opening_script(
    *,
    status: str,
    deadline: str | None,
    next_step: str,
    scenario_type: str,
) -> str:
    """Build a short manager-facing opening phrase for a follow-up call."""
    if status == "rescheduled":
        if deadline:
            return f"Добрый день! Звоню, как и договорились ({deadline})."
        return "Добрый день! Продолжаем наш разговор — готов ответить на вопросы."
    if status == "agreed":
        if next_step:
            step_short = next_step[:60].rstrip() + ("…" if len(next_step) > 60 else "")
            return f"Добрый день! Звоню уточнить детали: {step_short}"
        return "Добрый день! Готов двигаться дальше по нашей договорённости."
    if scenario_type in ("cold_outbound",):
        return "Добрый день! Хотел(а) подвести итог нашего разговора и уточнить ваш интерес."
    return "Добрый день! Звоню завершить нашу беседу — осталось уточнить пару деталей."


FINAL_SALES_LIKE_STATUSES = {"agreed", "rescheduled", "open"}
CALL_TOMORROW_HOTNESS_ORDER = ("hot", "rescheduled", "warm", "low")
CALL_TOMORROW_HOTNESS_RANK = {value: index for index, value in enumerate(CALL_TOMORROW_HOTNESS_ORDER)}
CALL_TOMORROW_HOTNESS_LABELS = {
    "hot": "Горячий",
    "warm": "Тёплый",
    "rescheduled": "Перенос",
    "low": "Низкий",
}
REPORT_EVIDENCE_USABLE_QUALITIES = {"direct", "indirect", "weak"}
REPORT_EVIDENCE_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
REPORT_EVIDENCE_QUALITY_RANK = {"direct": 0, "indirect": 1, "weak": 2, "insufficient": 9}
CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE = "Нет подтверждающего фрагмента в сохранённых данных."
CALL_BREAKDOWN_INSUFFICIENT_EVIDENCE_MESSAGE = (
    "Недостаточно подтверждённых фрагментов для детального разбора по фокусному этапу."
)
CALL_BREAKDOWN_EVIDENCE_STRENGTH_RANK = {"strong": 0, "medium": 1, "weak": 2, "missing": 3}
CALL_BREAKDOWN_POSITIVE_ONLY_RECOMMENDATION_MARKERS = (
    "продолжать",
    "продолжить использовать",
    "сохранять",
    "сохранить",
    "использовать четкое представление",
    "использовать чёткое представление",
)
CALL_BREAKDOWN_CORRECTIVE_RECOMMENDATION_MARKERS = (
    "уточ",
    "спрос",
    "зафикс",
    "соглас",
    "провер",
    "связ",
    "адапт",
    "объяс",
    "пояс",
    "конкрет",
    "предлож",
    "сформулир",
)
SEMANTIC_CASE_PROBLEM_TYPES = {"growth_zone", "missed_opportunity"}
SEMANTIC_CASE_BLOCK_MIN_SCORE = {
    "situation_day": 65,
    "call_breakdown": 55,
    "voice_of_customer": 50,
    "additional_situations": 50,
    "call_tomorrow": 50,
}
SEMANTIC_CASE_POSITIVE_DIAGNOSIS_MARKERS = (
    "правильно отреагировал",
    "правильно отреагировала",
    "корректно отреагировал",
    "корректно отреагировала",
    "успешно",
    "эффективно",
    "хорошо",
    "верно",
    "продемонстрировал эффективные",
    "продемонстрировала эффективные",
)
SEMANTIC_CASE_MANAGER_GAP_MARKERS = (
    "не уточ",
    "не выяс",
    "не выяв",
    "не закреп",
    "не зафикс",
    "не подытож",
    "не провер",
    "не соглас",
    "не предлож",
    "не перев",
    "без конкрет",
    "отсутств",
    "не хват",
    "слаб",
    "упущ",
    "риск",
)
SEMANTIC_CASE_BLOCK_EXPECTED_ROLES = {
    "situation_day": {"coaching_problem"},
    "call_breakdown": {"coaching_problem", "strong_practice"},
    "voice_of_customer": {"customer_signal"},
    "additional_situations": {"coaching_problem", "customer_signal", "neutral_summary", "strong_practice"},
    "call_tomorrow": {"follow_up_action"},
}
SEMANTIC_CASE_PROBLEM_FIT_MIN_SCORE = {
    "situation_day": 70,
    "call_breakdown": 65,
    "additional_situations": 55,
}
REPORT_BLOCK_CANDIDATE_MIN_SCORE = {
    "situation_day": 70,
    "call_breakdown": 65,
    "voice_of_customer": 50,
    "money_on_table": 50,
    "tomorrow_follow_up": 50,
    "tomorrow_challenge": 50,
    "call_list_context": 50,
}
REPORT_BLOCK_CANDIDATE_PROOF_TYPES = {
    "direct_gap",
    "sequence_inference",
    "absence_in_context",
    "context_support",
}
REPORT_BLOCK_CANDIDATE_PROBLEM_BLOCKS = {"situation_day", "call_breakdown"}
REPORT_BLOCK_CANDIDATE_STAGE_CODES = {
    *(stage_code for stage_code, _label, _name in _STAGE_FUNNEL_ORDER),
    "sale_processing",
    "sale_final",
}
REPORT_BLOCK_CANDIDATE_SOURCE_PREFIX = "report_evidence.block_candidates"
PROBLEM_SIGNAL_CATEGORY_MARKERS: dict[str, tuple[str, ...]] = {
    "next_step_owner_timing": (
        "кто делает",
        "кто будет",
        "когда",
        "срок",
        "дат",
        "время",
        "следующ",
        "следующий шаг",
        "закреп",
        "договоренн",
        "подытож",
        "итог",
        "ответствен",
        "созвон",
        "перезвон",
        "вернуться",
        "подтверд",
    ),
    "needs_discovery": (
        "потребност",
        "задач",
        "контекст",
        "процесс",
        "ситуац",
        "боль",
        "уточн",
        "выясн",
    ),
    "qualification": (
        "роль",
        "лпр",
        "решени",
        "юрист",
        "руковод",
        "актуальн",
        "интерес",
        "уместн",
    ),
    "value_proposition": (
        "ценност",
        "выгод",
        "предлож",
        "презентац",
        "демо",
        "адапт",
        "продукт",
        "решени",
    ),
    "trust_contact": (
        "довер",
        "безопас",
        "незнаком",
        "мошен",
        "канал",
        "whatsapp",
        "ватсап",
    ),
    "objection": (
        "возраж",
        "отказ",
        "сомнен",
        "дорого",
        "не актуал",
        "неактуал",
        "не интересно",
    ),
}


def _call_list_rows_by_interaction_id(call_list: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index final report-day call rows by interaction id."""
    rows: dict[str, dict[str, Any]] = {}
    for row in call_list:
        interaction_id = str(row.get("interaction_id") or "").strip()
        if interaction_id:
            rows[interaction_id] = row
    return rows


def _filter_coaching_artifacts_by_final_outcome(
    *,
    artifacts: list[ReportArtifact],
    call_list_by_interaction_id: dict[str, dict[str, Any]],
) -> list[ReportArtifact]:
    """Exclude report-day service/refusal rows from normal sales coaching examples.

    The filter is activated only when at least one report-day coaching artifact has
    a final sales-like outcome. If not, the previous fallback behavior is kept so
    sparse reports do not lose every coaching block.
    """
    report_day_status_by_artifact: dict[str, str | None] = {}
    has_sales_like_report_day_candidate = False
    for artifact in artifacts:
        interaction_id = str(artifact.interaction.id)
        row = call_list_by_interaction_id.get(interaction_id)
        if row is None:
            continue
        status = row.get("status")
        status_value = str(status) if status is not None else None
        report_day_status_by_artifact[interaction_id] = status_value
        if status_value in FINAL_SALES_LIKE_STATUSES:
            has_sales_like_report_day_candidate = True

    if not has_sales_like_report_day_candidate:
        return artifacts

    filtered = [
        artifact
        for artifact in artifacts
        if report_day_status_by_artifact.get(str(artifact.interaction.id)) in FINAL_SALES_LIKE_STATUSES
        or str(artifact.interaction.id) not in report_day_status_by_artifact
    ]
    return filtered or artifacts


def _issue_payloads(issues: list[Any]) -> list[dict[str, str]]:
    """Return JSON-safe validation issue diagnostics."""
    return [
        {
            "code": str(getattr(issue, "code", "") or ""),
            "path": str(getattr(issue, "path", "") or ""),
            "message": str(getattr(issue, "message", "") or ""),
        }
        for issue in issues
    ]


def _raw_semantic_case_available(detail: dict[str, Any]) -> bool:
    evidence = detail.get("report_evidence")
    return isinstance(evidence, dict) and isinstance(evidence.get("semantic_case"), dict)


def _semantic_case_diagnostic_state(
    *,
    semantic_case_available: bool,
    report_evidence_valid: bool,
    report_evidence: dict[str, Any],
) -> tuple[bool, str | None]:
    if not semantic_case_available:
        return False, "semantic_case_missing"
    if not report_evidence_valid:
        return False, "report_evidence_invalid"
    semantic_case = report_evidence.get("semantic_case")
    if not isinstance(semantic_case, dict):
        return False, "semantic_case_missing"
    if semantic_case.get("usable_in_report") is not True:
        return False, "semantic_case_unusable"
    if str(semantic_case.get("case_type") or "").strip().lower() == "insufficient_evidence":
        return False, "semantic_case_insufficient_evidence"
    quality = str(semantic_case.get("evidence_quality") or "").strip().lower()
    if quality not in REPORT_EVIDENCE_USABLE_QUALITIES:
        return False, "semantic_case_unsupported_quality"
    return True, None


def _report_evidence_source_for_state(
    *,
    report_evidence_valid: bool,
    block_candidates_valid: bool = False,
    semantic_case_valid: bool,
) -> str:
    if block_candidates_valid:
        return "block_candidates"
    if semantic_case_valid:
        return "semantic_case"
    if report_evidence_valid:
        return "report_evidence_v1"
    return "legacy_fallback"


def _stage_code_from_problem_categories(
    *,
    text: Any,
    score_by_stage: list[dict[str, Any]] | None = None,
) -> str | None:
    """Infer a report stage from a proven block-candidate problem when LLM2 omitted stage_code."""
    normalized = _summary_norm(text)
    if not normalized:
        return None
    available_codes = {
        str(item.get("stage_code") or "").strip()
        for item in score_by_stage or []
        if str(item.get("stage_code") or "").strip()
    }

    if any(marker in normalized for marker in ("уместн", "возможность говорить", "удобно говорить")):
        preferred = ["contact_start"]
    else:
        categories = _problem_signal_categories(normalized)
        preferred = []
        if "next_step_owner_timing" in categories:
            preferred.extend(["completion_next_step"])
        if "needs_discovery" in categories:
            preferred.extend(["needs_discovery", "qualification_primary"])
        if "qualification" in categories:
            preferred.extend(["qualification_primary"])
        if "value_proposition" in categories:
            preferred.extend(["presentation", "qualification_primary"])
        if "objection" in categories:
            preferred.extend(["objection_handling"])
        if "trust_contact" in categories:
            preferred.extend(["contact_start", "cross_stage_transition"])

    deduped = list(dict.fromkeys(preferred))
    if available_codes:
        for code in deduped:
            if code in available_codes:
                return code
    return deduped[0] if deduped else None


def _report_block_candidate_issue(*, block_name: str, reason: str) -> dict[str, str]:
    return {
        "block": block_name,
        "reason": reason,
        "path": f"{REPORT_BLOCK_CANDIDATE_SOURCE_PREFIX}.{block_name}",
    }


def _coerced_report_block_candidate_score(value: Any) -> int | None:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, score))


def _report_block_candidate_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "да"}
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return False


def _report_block_candidate_text(
    candidate: dict[str, Any],
    *keys: str,
    limit: int = 260,
) -> str | None:
    for key in keys:
        value = candidate.get(key)
        if isinstance(value, dict):
            value = (
                value.get("text")
                or value.get("summary")
                or value.get("quote")
                or value.get("value")
            )
        text = _first_sentence(str(value or ""), limit=limit)
        if text:
            return text
    return None


def _report_block_candidate_quote(value: Any, *, limit: int = 220) -> str | None:
    if isinstance(value, dict):
        for key in ("quote", "text", "client_text", "manager_text", "supporting_quote"):
            text = _dialogue_turn_text(str(value.get(key) or ""), limit=limit)
            if text:
                return text
        return None
    text = _dialogue_turn_text(str(value or ""), limit=limit)
    return text or None


def _report_block_candidate_quote_is_grounded(*, quote: str | None, transcript: str | None) -> bool:
    quote_text = _summary_norm(quote)
    if not quote_text:
        return True
    transcript_text = _summary_norm(transcript)
    if not transcript_text:
        return True
    return quote_text in transcript_text


def _report_block_candidate_turns(candidate: dict[str, Any], *, limit: int = 320) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    raw_turns: Any = None
    for key in ("dialogue_fragment", "best_dialogue_fragment"):
        if isinstance(candidate.get(key), list):
            raw_turns = candidate.get(key)
            break
    if raw_turns is None and isinstance(candidate.get("dialogue_excerpt"), dict):
        raw_turns = candidate["dialogue_excerpt"].get("turns")
    for turn in raw_turns or []:
        if not isinstance(turn, dict):
            continue
        text = _dialogue_turn_text(str(turn.get("text") or ""), limit=limit)
        if not text:
            continue
        speaker = str(turn.get("speaker") or "unknown").strip().lower()
        if speaker not in {"manager", "client", "unknown"}:
            speaker = "unknown"
        turns.append({"speaker": speaker, "text": text})
        if len(turns) >= 4:
            break
    if turns:
        return turns
    quote = _report_block_candidate_quote(
        candidate.get("supporting_quote")
        or candidate.get("quote")
        or candidate.get("evidence_quote"),
        limit=limit,
    )
    if not quote:
        return []
    speaker = str(candidate.get("evidence_speaker") or candidate.get("speaker") or "unknown").strip().lower()
    if speaker not in {"manager", "client", "unknown"}:
        speaker = "unknown"
    return [{"speaker": speaker, "text": quote}]


def _default_report_block_candidate_role(block_name: str) -> str | None:
    if block_name in {"situation_day", "call_breakdown", "tomorrow_challenge"}:
        return "coaching_problem"
    if block_name == "voice_of_customer":
        return "customer_signal"
    if block_name == "tomorrow_follow_up":
        return "follow_up_action"
    return None


def _normalize_report_block_candidate_moment(
    *,
    raw_moment: dict[str, Any],
    parent: dict[str, Any],
    block_name: str,
    transcript: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    proof_type = str(raw_moment.get("proof_type") or parent.get("proof_type") or "").strip().lower()
    if proof_type not in REPORT_BLOCK_CANDIDATE_PROOF_TYPES:
        return None, "unsupported_proof_type"
    quote_role = str(raw_moment.get("quote_role") or parent.get("quote_role") or "").strip().lower() or None
    supporting_quote = _report_block_candidate_quote(
        raw_moment.get("supporting_quote")
        or raw_moment.get("quote")
        or raw_moment.get("evidence_quote")
        or parent.get("supporting_quote")
    )
    if quote_role == "counter_evidence":
        return None, "proof_quote_marked_counter_evidence"
    if proof_type == "direct_gap" and quote_role == "supports_context":
        return None, "proof_quote_supports_context_only"
    if proof_type == "direct_gap" and not supporting_quote:
        return None, "direct_gap_quote_missing"
    if proof_type == "direct_gap" and not _report_block_candidate_quote_is_grounded(
        quote=supporting_quote,
        transcript=transcript,
    ):
        return None, "direct_gap_quote_ungrounded"
    if block_name in REPORT_BLOCK_CANDIDATE_PROBLEM_BLOCKS and proof_type == "context_support":
        return None, "proof_context_support_only"

    what = (
        _report_block_candidate_text(raw_moment, "situation", "what_happened", "what", "problem", limit=220)
        or str(parent.get("what_happened") or "").strip()
        or str(parent.get("main_thesis") or "").strip()
    )
    essence = (
        _report_block_candidate_text(
            raw_moment,
            "essence",
            "moment_summary",
            "summary",
            "proof",
            "proof_explanation",
            limit=260,
        )
        or str(parent.get("proof_explanation") or "").strip()
        or str(parent.get("why_it_matters") or "").strip()
    )
    better = (
        _report_block_candidate_text(
            raw_moment,
            "better_action",
            "better_next_action",
            "what_better",
            "recommendation",
            "next_action",
            limit=240,
        )
        or str(parent.get("better_next_action") or "").strip()
    )
    if not (what and essence and better):
        return None, "moment_missing_required_text"
    return {
        "situation": _first_sentence(str(what), limit=220),
        "essence": _first_sentence(str(essence), limit=260),
        "better_action": _first_sentence(str(better), limit=240),
        "proof_type": proof_type,
        "proof_explanation": _report_block_candidate_text(
            raw_moment,
            "proof_explanation",
            "proof",
            limit=360,
        )
        or parent.get("proof_explanation"),
        "supporting_quote": supporting_quote,
        "quote_role": quote_role,
    }, None


def _normalize_report_block_candidate(
    *,
    block_name: str,
    raw_candidate: Any,
    transcript: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw_candidate, dict):
        return None, "candidate_not_object"
    if not _report_block_candidate_bool(raw_candidate.get("fit")):
        return None, str(raw_candidate.get("insufficiency_reason") or "").strip() or "fit_false"
    score = _coerced_report_block_candidate_score(raw_candidate.get("score"))
    if score is None:
        return None, "score_missing_or_invalid"
    if score < REPORT_BLOCK_CANDIDATE_MIN_SCORE.get(block_name, 50):
        return None, "score_below_threshold"

    role = str(
        raw_candidate.get("role")
        or raw_candidate.get("block_role")
        or _default_report_block_candidate_role(block_name)
        or ""
    ).strip() or None
    expected_roles = SEMANTIC_CASE_BLOCK_EXPECTED_ROLES.get(block_name)
    if role and expected_roles and role not in expected_roles:
        return None, "block_role_mismatch"
    title_mode = str(raw_candidate.get("title_mode") or ("problem" if block_name == "situation_day" else "")).strip() or None
    if block_name == "situation_day" and title_mode != "problem":
        return None, "title_mode_not_problem"

    stage_code = str(raw_candidate.get("stage_code") or raw_candidate.get("stage") or "").strip()
    if not stage_code:
        return None, "stage_code_missing"
    if stage_code not in REPORT_BLOCK_CANDIDATE_STAGE_CODES:
        return None, "invalid_stage_code"

    proof_type = str(raw_candidate.get("proof_type") or "").strip().lower()
    if block_name in REPORT_BLOCK_CANDIDATE_PROBLEM_BLOCKS:
        if proof_type not in REPORT_BLOCK_CANDIDATE_PROOF_TYPES:
            return None, "unsupported_proof_type"
        if proof_type == "context_support":
            return None, "proof_context_support_only"
    quote_role = str(raw_candidate.get("quote_role") or "").strip().lower() or None
    supporting_quote = _report_block_candidate_quote(
        raw_candidate.get("supporting_quote")
        or raw_candidate.get("quote")
        or raw_candidate.get("evidence_quote")
    )
    if quote_role == "counter_evidence":
        return None, "proof_quote_marked_counter_evidence"
    if proof_type == "direct_gap" and quote_role == "supports_context":
        return None, "proof_quote_supports_context_only"
    if proof_type == "direct_gap" and not supporting_quote:
        return None, "direct_gap_quote_missing"
    if proof_type == "direct_gap" and not _report_block_candidate_quote_is_grounded(
        quote=supporting_quote,
        transcript=transcript,
    ):
        return None, "direct_gap_quote_ungrounded"

    counter_evidence = [
        _first_sentence(str(item or ""), limit=220)
        for item in raw_candidate.get("counter_evidence") or []
        if _first_sentence(str(item or ""), limit=220)
    ][:3]
    if block_name in REPORT_BLOCK_CANDIDATE_PROBLEM_BLOCKS and counter_evidence:
        return None, "proof_counter_evidence_present"

    normalized = dict(raw_candidate)
    normalized.update(
        {
            "fit": True,
            "score": score,
            "role": role,
            "block_role": role,
            "title_mode": title_mode,
            "stage_code": stage_code,
            "priority": str(raw_candidate.get("priority") or "high").strip().lower(),
            "evidence_quality": str(raw_candidate.get("evidence_quality") or ("direct" if proof_type == "direct_gap" else "indirect")).strip().lower(),
            "main_thesis": _report_block_candidate_text(raw_candidate, "main_thesis", "title", "situation_title", limit=220),
            "what_happened": _report_block_candidate_text(raw_candidate, "what_happened", "situation", "manager_behavior", limit=300),
            "why_it_matters": _report_block_candidate_text(raw_candidate, "why_it_matters", "meaning", "what_it_means", limit=300),
            "what_was_missing": _report_block_candidate_text(raw_candidate, "what_was_missing", "missing_action", "missing", limit=260),
            "better_next_action": _report_block_candidate_text(raw_candidate, "better_next_action", "next_time_action", "recommended_next_action", "next_action", limit=260),
            "proof_type": proof_type or None,
            "proof_explanation": _report_block_candidate_text(raw_candidate, "proof_explanation", "proof", limit=360),
            "supporting_quote": supporting_quote,
            "quote_role": quote_role,
            "counter_evidence": counter_evidence,
        }
    )
    if normalized["priority"] not in REPORT_EVIDENCE_PRIORITY_RANK:
        normalized["priority"] = "medium"
    if normalized["evidence_quality"] not in REPORT_EVIDENCE_QUALITY_RANK:
        normalized["evidence_quality"] = "indirect"

    if block_name == "situation_day":
        if role != "coaching_problem":
            return None, "block_role_not_coaching_problem"
        if not (
            (normalized.get("main_thesis") or normalized.get("what_happened"))
            and normalized.get("why_it_matters")
            and normalized.get("better_next_action")
        ):
            return None, "missing_required_text"
        if _summary_norm(normalized.get("what_was_missing")) and (
            _summary_norm(normalized.get("what_was_missing"))
            == _summary_norm(normalized.get("better_next_action"))
        ):
            return None, "duplicated_missing_and_action"

    if block_name == "call_breakdown":
        raw_moments = raw_candidate.get("moments") or raw_candidate.get("breakdown_moments")
        if not isinstance(raw_moments, list) or not raw_moments:
            raw_moments = [raw_candidate]
        moments: list[dict[str, Any]] = []
        for raw_moment in raw_moments[:3]:
            if not isinstance(raw_moment, dict):
                continue
            moment, reason = _normalize_report_block_candidate_moment(
                raw_moment=raw_moment,
                parent=normalized,
                block_name=block_name,
                transcript=transcript,
            )
            if moment is None:
                return None, reason or "invalid_moment"
            moments.append(moment)
        if not moments:
            return None, "moments_missing"
        normalized["_normalized_moments"] = moments

    return normalized, None


def _validated_report_block_candidates(
    *,
    raw_report_evidence: Any,
    transcript: str | None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    if not isinstance(raw_report_evidence, dict):
        return {}, [], []
    raw_candidates = raw_report_evidence.get("block_candidates")
    if not isinstance(raw_candidates, dict):
        return {}, [], []
    normalized: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for block_name, raw_candidate in raw_candidates.items():
        block = str(block_name or "").strip()
        if not block:
            continue
        candidate, reason = _normalize_report_block_candidate(
            block_name=block,
            raw_candidate=raw_candidate,
            transcript=transcript,
        )
        if candidate is None:
            errors.append(_report_block_candidate_issue(block_name=block, reason=reason or "invalid_candidate"))
            continue
        if block not in REPORT_BLOCK_CANDIDATE_MIN_SCORE:
            warnings.append(_report_block_candidate_issue(block_name=block, reason="unknown_block_name"))
        normalized[block] = candidate
    return normalized, errors, warnings


def _semantic_case_block_fit_diagnostic_from_entry(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("report_evidence")
    if not isinstance(evidence, dict):
        return {}
    semantic_case = evidence.get("semantic_case")
    if not isinstance(semantic_case, dict):
        return {}
    block_fit = semantic_case.get("report_block_fit")
    if not isinstance(block_fit, dict):
        return {}
    diagnostic: dict[str, Any] = {}
    for block_name, value in block_fit.items():
        if not isinstance(value, dict):
            continue
        diagnostic[str(block_name)] = {
            "fit": value.get("fit"),
            "score": value.get("score"),
            "reason_code": value.get("reason_code"),
            "evidence_type": value.get("evidence_type"),
            "block_role": value.get("block_role"),
            "title_mode": value.get("title_mode"),
            "problem_fit": value.get("problem_fit") if isinstance(value.get("problem_fit"), dict) else None,
            "evidence_target": value.get("evidence_target"),
            "gap_proven": value.get("gap_proven"),
        }
    return diagnostic


def _report_block_candidates_diagnostic_from_entry(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("report_evidence")
    if not isinstance(evidence, dict):
        return {}
    block_candidates = evidence.get("block_candidates")
    if not isinstance(block_candidates, dict):
        return {}
    diagnostic: dict[str, Any] = {}
    for block_name, value in block_candidates.items():
        if not isinstance(value, dict):
            continue
        diagnostic[str(block_name)] = {
            "fit": value.get("fit"),
            "score": value.get("score"),
            "role": value.get("role") or value.get("block_role"),
            "title_mode": value.get("title_mode"),
            "stage_code": value.get("stage_code"),
            "proof_type": value.get("proof_type"),
            "quote_role": value.get("quote_role"),
            "counter_evidence_count": len(value.get("counter_evidence") or []),
        }
    return diagnostic


def _build_report_evidence_index(*, artifacts: list[ReportArtifact]) -> dict[str, dict[str, Any]]:
    """Validate report_evidence once per report-day artifact and keep diagnostics."""
    index: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        source_analysis = artifact.analysis or artifact.original_analysis
        detail = dict((getattr(source_analysis, "scores_detail", None) or {}) if source_analysis is not None else {})
        available = isinstance(detail.get("report_evidence"), dict)
        semantic_case_available = _raw_semantic_case_available(detail)
        raw_report_evidence = detail.get("report_evidence") if available else None
        (
            block_candidates,
            block_candidate_errors,
            block_candidate_warnings,
        ) = _validated_report_block_candidates(
            raw_report_evidence=raw_report_evidence,
            transcript=getattr(artifact.interaction, "text", None),
        )
        validation_detail = dict(detail)
        if isinstance(raw_report_evidence, dict) and "block_candidates" in raw_report_evidence:
            stripped_report_evidence = dict(raw_report_evidence)
            stripped_report_evidence.pop("block_candidates", None)
            validation_detail["report_evidence"] = stripped_report_evidence
        validation = validate_report_evidence(validation_detail, getattr(artifact.interaction, "text", None))
        valid = bool(available and validation.is_valid)
        normalized = dict(validation.normalized or {}) if valid else {}
        report_evidence = dict(normalized.get("report_evidence") or {}) if valid else {}
        if block_candidates:
            report_evidence["block_candidates"] = block_candidates
        semantic_case_valid, semantic_case_filtered_reason = _semantic_case_diagnostic_state(
            semantic_case_available=semantic_case_available,
            report_evidence_valid=valid,
            report_evidence=report_evidence,
        )
        interaction_id = str(artifact.interaction.id)
        index[interaction_id] = {
            "interaction_id": interaction_id,
            "analysis_id": str(getattr(source_analysis, "id", "") or "") or None,
            "instruction_version": str(getattr(source_analysis, "instruction_version", "") or "") or None,
            "report_evidence_available": available,
            "report_evidence_valid": valid,
            "report_evidence_errors": _issue_payloads(list(validation.errors or [])),
            "report_evidence_warnings": _issue_payloads(list(validation.warnings or [])),
            "report_evidence_source": _report_evidence_source_for_state(
                report_evidence_valid=valid,
                block_candidates_valid=bool(block_candidates),
                semantic_case_valid=semantic_case_valid,
            ),
            "report_evidence_version": validation.version,
            "block_candidates_available": isinstance(raw_report_evidence, dict)
            and isinstance(raw_report_evidence.get("block_candidates"), dict),
            "block_candidates_valid_blocks": sorted(block_candidates.keys()),
            "block_candidates_errors": block_candidate_errors,
            "block_candidates_warnings": block_candidate_warnings,
            "semantic_case_available": semantic_case_available,
            "semantic_case_valid": semantic_case_valid,
            "semantic_case_filtered_reason": semantic_case_filtered_reason,
            "normalized": normalized,
            "report_evidence": report_evidence,
        }
    return index


def _build_report_evidence_diagnostics(
    *,
    index: dict[str, dict[str, Any]],
    semantic_case_used_call_ids: set[str] | None = None,
    semantic_case_block_sources: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return payload-level report_evidence validation diagnostics."""
    used_call_ids = {str(item) for item in semantic_case_used_call_ids or set() if str(item or "").strip()}
    rows = [
        {
            "interaction_id": item["interaction_id"],
            "analysis_id": item.get("analysis_id"),
            "instruction_version": item.get("instruction_version"),
            "report_evidence_available": bool(item.get("report_evidence_available")),
            "report_evidence_valid": bool(item.get("report_evidence_valid")),
            "report_evidence_errors": list(item.get("report_evidence_errors") or []),
            "report_evidence_warnings": list(item.get("report_evidence_warnings") or []),
            "report_evidence_source": item.get("report_evidence_source") or "legacy_fallback",
            "report_evidence_version": item.get("report_evidence_version"),
            "call_report_summary_available": _valid_call_report_summary_from_entry(item) is not None,
            "block_candidates_available": bool(item.get("block_candidates_available")),
            "block_candidates_valid_blocks": list(item.get("block_candidates_valid_blocks") or []),
            "block_candidates_errors": list(item.get("block_candidates_errors") or []),
            "block_candidates_warnings": list(item.get("block_candidates_warnings") or []),
            "block_candidates_report_block_fit": _report_block_candidates_diagnostic_from_entry(item),
            "semantic_case_available": bool(item.get("semantic_case_available")),
            "semantic_case_valid": bool(item.get("semantic_case_valid")),
            "semantic_case_used": str(item.get("interaction_id") or "") in used_call_ids,
            "semantic_case_report_block_fit": _semantic_case_block_fit_diagnostic_from_entry(item),
            "semantic_case_filtered_reason": (
                None
                if str(item.get("interaction_id") or "") in used_call_ids
                else (
                    "not_selected_for_final_blocks"
                    if item.get("semantic_case_valid")
                    else item.get("semantic_case_filtered_reason")
                )
            ),
        }
        for item in index.values()
    ]
    source_counts: dict[str, int] = {
        "block_candidates": 0,
        "semantic_case": 0,
        "report_evidence_v1": 0,
        "legacy_fallback": 0,
    }
    for item in rows:
        source = str(item.get("report_evidence_source") or "legacy_fallback")
        source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "summary": {
            "calls_checked": len(rows),
            "available_count": sum(1 for item in rows if item["report_evidence_available"]),
            "valid_count": sum(1 for item in rows if item["report_evidence_valid"]),
            "invalid_count": sum(
                1 for item in rows if item["report_evidence_available"] and not item["report_evidence_valid"]
            ),
            "missing_count": sum(1 for item in rows if not item["report_evidence_available"]),
            "call_report_summary_available_count": sum(1 for item in rows if item["call_report_summary_available"]),
            "block_candidates_available_count": sum(1 for item in rows if item["block_candidates_available"]),
            "block_candidates_valid_count": sum(
                1 for item in rows if item["block_candidates_valid_blocks"]
            ),
            "semantic_case_available_count": sum(1 for item in rows if item["semantic_case_available"]),
            "semantic_case_valid_count": sum(1 for item in rows if item["semantic_case_valid"]),
            "semantic_case_used_count": sum(1 for item in rows if item["semantic_case_used"]),
            "semantic_case_filtered_count": sum(
                1 for item in rows if item["semantic_case_filtered_reason"] is not None
            ),
            "report_evidence_source_counts": source_counts,
            "source_policy": "valid_block_candidates_else_valid_semantic_case_with_role_problem_fit_else_report_evidence_v1_else_step8w_fallback",
        },
        "blocks": dict(semantic_case_block_sources or {}),
        "calls": sorted(rows, key=lambda item: str(item.get("interaction_id") or "")),
    }


def _report_source_from_paths(paths: list[Any]) -> str:
    normalized = " ".join(str(item or "") for item in paths)
    if "report_evidence.block_candidates" in normalized:
        return "block_candidates"
    if "report_evidence.semantic_case" in normalized:
        return "semantic_case"
    if "report_evidence" in normalized:
        return "report_evidence_v1"
    return "legacy_fallback"


def _semantic_case_fallback_reason(
    *,
    index: dict[str, dict[str, Any]],
    report_evidence_source: str,
    semantic_case_used: bool,
) -> str | None:
    if semantic_case_used:
        return None
    if report_evidence_source == "semantic_case":
        return "quality_gate_filtered_semantic_case"
    if any(item.get("semantic_case_valid") for item in index.values()):
        return "semantic_case_not_selected_for_block"
    reasons = [
        str(item.get("semantic_case_filtered_reason") or "")
        for item in index.values()
        if str(item.get("semantic_case_filtered_reason") or "").strip()
    ]
    return reasons[0] if reasons else "semantic_case_missing"


def _source_block_diagnostic(
    *,
    index: dict[str, dict[str, Any]],
    source_paths: list[Any],
    call_ids: list[Any] | None = None,
    semantic_case_used: bool | None = None,
    quality_status: str | None = None,
    selection_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report_evidence_source = _report_source_from_paths(source_paths)
    if semantic_case_used is None:
        semantic_case_used = report_evidence_source == "semantic_case"
    reason = _semantic_case_fallback_reason(
        index=index,
        report_evidence_source=report_evidence_source,
        semantic_case_used=semantic_case_used,
    )
    return {
        "report_evidence_source": report_evidence_source,
        "source_paths": [str(item) for item in source_paths if str(item or "").strip()],
        "semantic_case_used": semantic_case_used,
        "semantic_case_filtered_reason": reason,
        "quality_status": quality_status,
        "call_ids": [str(item) for item in call_ids or [] if str(item or "").strip()],
        "selection_diagnostics": dict(selection_diagnostics or {}),
    }


def _build_semantic_case_block_sources(
    *,
    index: dict[str, dict[str, Any]],
    situation_evidence_quote: dict[str, Any] | None,
    situation_day_coaching_view: dict[str, Any] | None,
    call_breakdown: dict[str, Any] | None,
    call_breakdown_quality: dict[str, Any] | None,
    voice_of_customer: dict[str, Any] | None,
    additional_situations: dict[str, Any] | None,
    call_tomorrow: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    voice_rows = [
        item for item in (voice_of_customer or {}).get("situations") or []
        if isinstance(item, dict)
    ]
    tomorrow_rows = [
        item for item in (call_tomorrow or {}).get("contacts") or []
        if isinstance(item, dict)
    ]
    additional_rows = [
        item for item in (additional_situations or {}).get("situations") or []
        if isinstance(item, dict)
    ]
    call_breakdown_quality_status = str((call_breakdown_quality or {}).get("status") or "").strip() or None
    call_breakdown_source_paths = [
        (call_breakdown or {}).get("call_breakdown_source"),
        (call_breakdown or {}).get("source_note"),
        (call_breakdown_quality or {}).get("source"),
    ]
    call_breakdown_semantic_used = (
        _report_source_from_paths(call_breakdown_source_paths) == "semantic_case"
        and call_breakdown_quality_status != "insufficient_evidence"
        and not (call_breakdown or {}).get("is_placeholder")
    )
    return {
        "situation_day": _source_block_diagnostic(
            index=index,
            source_paths=[
                (situation_evidence_quote or {}).get("source"),
                (situation_day_coaching_view or {}).get("source"),
            ],
            call_ids=[(situation_evidence_quote or {}).get("call_id")],
            selection_diagnostics=(situation_day_coaching_view or {}).get("selection_diagnostics"),
        ),
        "call_breakdown": _source_block_diagnostic(
            index=index,
            source_paths=call_breakdown_source_paths,
            call_ids=[(call_breakdown or {}).get("call_id")],
            semantic_case_used=call_breakdown_semantic_used,
            quality_status=call_breakdown_quality_status,
            selection_diagnostics=(call_breakdown or {}).get("selection_diagnostics"),
        ),
        "voice_of_customer": _source_block_diagnostic(
            index=index,
            source_paths=[
                (voice_of_customer or {}).get("source_note"),
                *[item.get("source") for item in voice_rows],
            ],
            call_ids=[item.get("call_id") for item in voice_rows],
            selection_diagnostics=(voice_of_customer or {}).get("selection_diagnostics"),
        ),
        "additional_situations": _source_block_diagnostic(
            index=index,
            source_paths=[
                (additional_situations or {}).get("source_note"),
                *[item.get("source") for item in additional_rows],
            ],
        ),
        "call_tomorrow": _source_block_diagnostic(
            index=index,
            source_paths=[item.get("source") for item in tomorrow_rows],
            call_ids=[item.get("interaction_id") for item in tomorrow_rows],
        ),
    }


def _semantic_case_used_call_ids_from_block_sources(
    block_sources: dict[str, dict[str, Any]],
) -> set[str]:
    used: set[str] = set()
    for item in block_sources.values():
        if item.get("semantic_case_used"):
            used.update(str(call_id) for call_id in item.get("call_ids") or [] if str(call_id or "").strip())
    return used


def _build_call_report_summary_diagnostics(
    *,
    call_list: list[dict[str, Any]],
    call_tomorrow: dict[str, Any],
    voice_of_customer: dict[str, Any],
) -> dict[str, Any]:
    """Summarize guarded call_report_summary usage in manager-facing blocks."""
    call_list_topic_used = sum(
        1 for row in call_list
        if row.get("call_list_topic_source") == "report_evidence.call_report_summary.short_topic"
    )
    call_list_context_used = sum(
        1 for row in call_list
        if row.get("call_list_context_source") == "report_evidence.call_report_summary.short_context"
    )
    tomorrow_used = sum(
        1 for item in call_tomorrow.get("contacts") or []
        if item.get("call_report_summary_used")
    )
    voice_used = sum(
        1 for item in voice_of_customer.get("situations") or []
        if "call_report_summary" in str(item.get("source") or "")
    )
    available_rows = sum(1 for row in call_list if row.get("call_report_summary_available"))
    used_rows = sum(
        1 for row in call_list
        if row.get("call_list_topic_source") == "report_evidence.call_report_summary.short_topic"
        or row.get("call_list_context_source") == "report_evidence.call_report_summary.short_context"
    )
    used_total = call_list_topic_used + call_list_context_used + tomorrow_used + voice_used
    return {
        "summary": {
            "call_report_summary_available_count": available_rows,
            "call_report_summary_used_count": used_total,
            "call_report_summary_fallback_count": max(available_rows - used_rows, 0),
            "source_policy": "use_valid_call_report_summary_else_deterministic_fallback",
        },
        "blocks": {
            "call_list_topic_used_count": call_list_topic_used,
            "call_list_context_used_count": call_list_context_used,
            "call_tomorrow_used_count": tomorrow_used,
            "voice_of_customer_used_count": voice_used,
        },
    }


CALL_REPORT_SUMMARY_BROAD_PREFIXES = (
    "обсуждение",
    "разговор",
    "звонок",
    "продажи",
    "холодный звонок",
)
CALL_REPORT_SUMMARY_GENERIC_VALUES = {
    "—",
    "-",
    "нет",
    "нет данных",
    "нет контекста",
    "контекст не уточнен",
    "контекст не уточнён",
    "не указано",
}
MANAGER_PHRASE_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
MANAGER_PHRASE_DATETIME_RE = re.compile(
    r"\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b|\b20\d{2}-\d{2}-\d{2}\b"
)


def _summary_norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).replace("ё", "е").lower()


def _summary_text(value: Any, *, limit: int) -> str | None:
    text = _first_sentence(str(value or ""), limit=limit).strip()
    return text or None


def _call_summary_topic_usable(value: Any) -> bool:
    text = _summary_text(value, limit=120)
    if not text:
        return False
    normalized = _summary_norm(text).rstrip(".")
    if normalized in CALL_REPORT_SUMMARY_GENERIC_VALUES:
        return False
    return not any(normalized.startswith(prefix) for prefix in CALL_REPORT_SUMMARY_BROAD_PREFIXES)


def _call_summary_context_usable(value: Any) -> bool:
    text = _summary_text(value, limit=280)
    if not text:
        return False
    normalized = _summary_norm(text).rstrip(".")
    if normalized in CALL_REPORT_SUMMARY_GENERIC_VALUES:
        return False
    if len(normalized) < 18:
        return False
    return not any(normalized == prefix for prefix in CALL_REPORT_SUMMARY_BROAD_PREFIXES)


def _call_summary_action_usable(value: Any) -> bool:
    text = _summary_text(value, limit=240)
    if not text:
        return False
    normalized = _summary_norm(text).rstrip(".")
    if normalized in CALL_REPORT_SUMMARY_GENERIC_VALUES:
        return False
    return len(normalized) >= 8


def _valid_call_report_summary_from_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry or not entry.get("report_evidence_valid"):
        return None
    evidence = entry.get("report_evidence")
    if not isinstance(evidence, dict):
        return None
    summary = evidence.get("call_report_summary")
    return dict(summary) if isinstance(summary, dict) and summary else None


def _valid_call_report_summary_for_interaction(
    *,
    interaction_id: str | None,
    report_evidence_index: dict[str, dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not interaction_id or not report_evidence_index:
        return None, None
    entry = report_evidence_index.get(str(interaction_id)) or {}
    summary = _valid_call_report_summary_from_entry(entry)
    evidence = entry.get("report_evidence") if summary is not None else None
    return summary, dict(evidence) if isinstance(evidence, dict) else None


def _known_client_quotes_from_evidence(evidence: dict[str, Any] | None) -> set[str]:
    if not isinstance(evidence, dict):
        return set()
    quotes: set[str] = set()
    outcome = dict(evidence.get("business_outcome") or {})
    if str(outcome.get("evidence_speaker") or "").strip().lower() == "client":
        quotes.add(_summary_norm(outcome.get("evidence_quote")))
    for key in ("voice_of_customer", "quote_bank"):
        for item in evidence.get(key) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("speaker") or "").strip().lower() == "client":
                quotes.add(_summary_norm(item.get("quote")))
    return {quote for quote in quotes if quote}


def _safe_manager_phrase_from_summary(
    *,
    summary: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
) -> str | None:
    phrase = re.sub(
        r"\s+",
        " ",
        str((summary or {}).get("suggested_manager_phrase") or "").strip(),
    )
    if len(phrase) > 220:
        phrase = phrase[:217].rstrip() + "…"
    if not phrase:
        return None
    normalized = _summary_norm(phrase)
    if normalized in _known_client_quotes_from_evidence(evidence):
        return None
    if MANAGER_PHRASE_PHONE_RE.search(phrase) or MANAGER_PHRASE_DATETIME_RE.search(phrase):
        return None
    if normalized.startswith(("да,", "выставляйте", "отправьте", "скиньте", "посовет", "не нужно", "нет,")):
        return None
    return phrase.strip(" «»\"")


VOICE_CUSTOMER_INTERNAL_DISCUSSION_MARKERS = (
    "совет",
    "обсуд",
    "подума",
    "руковод",
    "коллег",
)
VOICE_CUSTOMER_CURRENT_SOLUTION_MARKERS = (
    "достаточ",
    "хватает",
    "устраива",
    "используем",
    "текущее решение",
    "свое решение",
    "свое решение",
)
VOICE_CUSTOMER_TRUST_MARKERS = (
    "мошен",
    "незнаком",
    "довер",
    "безопас",
    "подтверд",
    "провер",
)
VOICE_CUSTOMER_MATERIALS_MARKERS = (
    "whatsapp",
    "ватс",
    "уатс",
    "материал",
    "кп",
    "коммерчес",
    "информац",
    "прайс",
    "стоимост",
    "цен",
    "счет",
    "счёт",
    "почт",
    "email",
)
VOICE_CUSTOMER_REFUSAL_MARKERS = (
    "не актуал",
    "неактуал",
    "не интерес",
    "не надо",
    "не нужно",
    "отказ",
    "нет потребност",
    "не рассматри",
)
VOICE_CUSTOMER_SERVICE_MARKERS = (
    "подписать",
    "подписание",
    "подписан",
    "подписыв",
    "qr",
    "ncalayer",
    "нцал",
    "эцп",
    "документ",
    "ошиб",
    "сервис",
    "тех",
    "помог",
)

VOICE_CUSTOMER_SIGNAL_ACTIONS = {
    "internal_discussion": (
        "Уточнить, с кем клиент будет обсуждать решение, отправить короткие аргументы "
        "для коллег и договориться о дате следующего контакта."
    ),
    "current_solution": (
        "Уточнить, что именно закрывает текущее решение, какие ограничения остаются "
        "и при каких условиях клиент готов рассмотреть альтернативу."
    ),
    "trust_barrier": (
        "Подтвердить компанию и цель звонка, предложить безопасный канал продолжения — "
        "WhatsApp, email или звонок в согласованное время."
    ),
    "materials_request": (
        "Отправить материал в согласованный канал и сразу зафиксировать дату возврата к обсуждению."
    ),
    "refusal": (
        "Коротко уточнить причину отказа и не продолжать коммерческое давление; зафиксировать причину в CRM."
    ),
    "service_issue": (
        "Закрыть сервисный вопрос, убедиться, что клиент смог подписать или отправить документ, "
        "и не переводить разговор в продажу без нового запроса."
    ),
}
VOICE_CUSTOMER_ACTION_ALIGNMENT_MARKERS = {
    "internal_discussion": ("обсуд", "совет", "коллег", "руковод", "аргумент", "дата следующ"),
    "current_solution": ("текущее", "огранич", "альтернатив", "закрыва", "хватает", "устраива"),
    "trust_barrier": ("безопас", "канал", "довер", "подтверд", "провер"),
    "materials_request": ("отправ", "материал", "кп", "коммерчес", "информац", "whatsapp", "почт", "email"),
    "refusal": ("причин", "отказ", "давлен", "crm"),
    "service_issue": ("сервис", "подпис", "документ", "ошиб", "помог"),
}


def _voice_customer_signal_category(
    *,
    quote: Any,
    topic: Any = None,
    meaning: Any = None,
    context: Any = None,
) -> str | None:
    """Classify a client quote into a deterministic manager-action signal."""
    normalized = _summary_norm(" ".join(str(part or "") for part in (quote, topic, meaning, context)))
    topic_norm = _summary_norm(topic)
    if topic_norm == "service_issue" or any(marker in normalized for marker in VOICE_CUSTOMER_SERVICE_MARKERS):
        return "service_issue"
    if topic_norm == "refusal" or any(marker in normalized for marker in VOICE_CUSTOMER_REFUSAL_MARKERS):
        return "refusal"
    if any(marker in normalized for marker in VOICE_CUSTOMER_TRUST_MARKERS):
        return "trust_barrier"
    if any(marker in normalized for marker in VOICE_CUSTOMER_CURRENT_SOLUTION_MARKERS):
        return "current_solution"
    if any(marker in normalized for marker in VOICE_CUSTOMER_INTERNAL_DISCUSSION_MARKERS):
        return "internal_discussion"
    if topic_norm in {"product_interest", "price"} or any(
        marker in normalized for marker in VOICE_CUSTOMER_MATERIALS_MARKERS
    ):
        return "materials_request"
    return None


def _voice_customer_summary_action_specific(action: Any, *, category: str | None) -> bool:
    if not _call_summary_action_usable(action):
        return False
    normalized = _summary_norm(action)
    passive_only = (
        "ждать" in normalized
        or "ожид" in normalized
        or "дождаться" in normalized
        or normalized in {"перезвонить клиенту", "связаться с клиентом", "продолжить общение"}
    )
    generic_only = any(
        marker in normalized
        for marker in (
            "уточнить задачу клиента",
            "выяснить потребность",
            "привязать предложение",
            "дать больше конкретики",
        )
    )
    if category is not None and (passive_only or generic_only):
        return False
    if category == "materials_request":
        has_send = any(
            marker in normalized
            for marker in ("отправ", "материал", "кп", "коммерчес", "информац", "whatsapp", "почт", "email")
        )
        has_return = any(
            marker in normalized
            for marker in ("дат", "завтра", "уточн", "вернут", "возврат", "следующ", "обсужд", "вопрос")
        )
        return has_send and has_return
    alignment_markers = VOICE_CUSTOMER_ACTION_ALIGNMENT_MARKERS.get(category or "")
    if alignment_markers and not any(marker in normalized for marker in alignment_markers):
        return False
    return True


def _voice_customer_manager_action(
    *,
    quote: Any,
    topic: Any = None,
    meaning: Any = None,
    context: Any = None,
    summary_action: Any = None,
) -> tuple[str | None, str | None, str | None]:
    """Return a quote-specific manager action, preferring specific safe summary action."""
    category = _voice_customer_signal_category(
        quote=quote,
        topic=topic,
        meaning=meaning,
        context=context,
    )
    if _voice_customer_summary_action_specific(summary_action, category=category):
        return _summary_text(summary_action, limit=220), "call_report_summary.manager_next_action", category
    if category is not None:
        return VOICE_CUSTOMER_SIGNAL_ACTIONS[category], "deterministic_customer_signal", category
    return None, None, None


def _voice_customer_context_with_action(*, meaning: Any, action: str | None) -> str | None:
    meaning_text = _first_sentence(str(meaning or ""), limit=180)
    if action:
        return f"{meaning_text} Что сделать: {action}" if meaning_text else f"Что сделать: {action}"
    return meaning_text or None


def _valid_report_evidence_for_artifact(
    *,
    artifact: ReportArtifact,
    report_evidence_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    entry = report_evidence_index.get(str(artifact.interaction.id)) or {}
    if not entry.get("report_evidence_valid") and not entry.get("block_candidates_valid_blocks"):
        return None
    evidence = entry.get("report_evidence")
    return dict(evidence) if isinstance(evidence, dict) else None


def _valid_semantic_case_from_evidence(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a usable semantic_case from validated report_evidence."""
    if not isinstance(evidence, dict):
        return None
    semantic_case = evidence.get("semantic_case")
    if not isinstance(semantic_case, dict) or semantic_case.get("usable_in_report") is not True:
        return None
    if str(semantic_case.get("case_type") or "").strip().lower() == "insufficient_evidence":
        return None
    quality = str(semantic_case.get("evidence_quality") or "").strip().lower()
    if quality not in REPORT_EVIDENCE_USABLE_QUALITIES:
        return None
    return dict(semantic_case)


def _final_status_for_artifact(
    *,
    artifact: ReportArtifact,
    call_list_by_interaction_id: dict[str, dict[str, Any]],
) -> str | None:
    row = call_list_by_interaction_id.get(str(artifact.interaction.id))
    if row is not None:
        status = row.get("status")
        return str(status) if status is not None else None
    return BusinessOutcomeResolver().resolve(artifact).final_status


def _is_report_evidence_sales_like(
    *,
    artifact: ReportArtifact,
    call_list_by_interaction_id: dict[str, dict[str, Any]],
) -> bool:
    return _final_status_for_artifact(
        artifact=artifact,
        call_list_by_interaction_id=call_list_by_interaction_id,
    ) in FINAL_SALES_LIKE_STATUSES


def _stage_name_for_code(stage_code: str, score_by_stage: list[dict[str, Any]]) -> str:
    code = str(stage_code or "").strip()
    for item in score_by_stage:
        if str(item.get("stage_code") or "").strip() == code:
            return str(item.get("stage_name") or "").strip()
    for known_code, _funnel_label, stage_name in _STAGE_FUNNEL_ORDER:
        if known_code == code:
            return stage_name
    return code or "Фокусный этап"


def _report_evidence_stage_score_label(stage_code: str, score_by_stage: list[dict[str, Any]]) -> str | None:
    for item in score_by_stage:
        if str(item.get("stage_code") or "").strip() == str(stage_code or "").strip():
            score = item.get("score")
            if score is None:
                return None
            try:
                return f"{float(score) / 2:.1f}/5"
            except (TypeError, ValueError):
                return None
    return None


def _report_evidence_turns(
    candidate: dict[str, Any],
    *,
    key: str = "dialogue_fragment",
    limit: int = 320,
) -> list[dict[str, str]]:
    """Return bounded report_evidence dialogue turns without inventing roles."""
    turns: list[dict[str, str]] = []
    for turn in candidate.get(key) or []:
        if not isinstance(turn, dict):
            continue
        text = _dialogue_turn_text(str(turn.get("text") or ""), limit=limit)
        if not text:
            continue
        speaker = str(turn.get("speaker") or "unknown").strip().lower()
        if speaker not in {"manager", "client", "unknown"}:
            speaker = "unknown"
        turns.append({"speaker": speaker, "text": text})
        if len(turns) >= 4:
            break
    return turns


def _semantic_case_turns(semantic_case: dict[str, Any], *, limit: int = 320) -> list[dict[str, str]]:
    return _report_evidence_turns(semantic_case, key="best_dialogue_fragment", limit=limit)


def _semantic_supporting_quote_text(value: Any) -> str | None:
    """Return optional quote text from coaching_moment without requiring it."""
    if isinstance(value, dict):
        for key in ("quote", "text", "client_text", "manager_text", "supporting_quote"):
            text = _dialogue_turn_text(str(value.get(key) or ""), limit=220)
            if text:
                return text
        return None
    text = _dialogue_turn_text(str(value or ""), limit=220)
    return text or None


def _semantic_case_coaching_moment(
    semantic_case: dict[str, Any],
    *,
    block_name: str | None = None,
) -> dict[str, Any] | None:
    """Extract the report-facing coaching moment, falling back to legacy semantic_case fields."""
    fit_item = (
        _semantic_case_block_fit_item(semantic_case, block_name or "")
        if block_name
        else None
    )
    raw = (fit_item or {}).get("coaching_moment") if fit_item is not None else None
    if not isinstance(raw, dict):
        raw = semantic_case.get("coaching_moment")
    has_explicit_coaching_moment = isinstance(raw, dict)
    coaching_moment = raw if isinstance(raw, dict) else {}
    summary = _first_sentence(
        str(
            semantic_case.get("moment_summary")
            or coaching_moment.get("summary")
            or coaching_moment.get("moment_summary")
            or semantic_case.get("manager_behavior")
            or semantic_case.get("core_meaning")
            or ""
        ),
        limit=260,
    )
    missing_action = _first_sentence(
        str(
            coaching_moment.get("missing_action")
            or semantic_case.get("missing_action")
            or semantic_case.get("coaching_diagnosis")
            or ""
        ),
        limit=260,
    )
    why_it_matters = _first_sentence(
        str(
            coaching_moment.get("why_it_matters")
            or semantic_case.get("why_it_matters")
            or semantic_case.get("why_this_call_matters")
            or semantic_case.get("core_meaning")
            or ""
        ),
        limit=260,
    )
    supporting_quote = _semantic_supporting_quote_text(
        coaching_moment.get("supporting_quote")
        or semantic_case.get("supporting_quote")
        or coaching_moment.get("quote")
    )
    if not any((summary, missing_action, why_it_matters, supporting_quote)):
        return None
    confidence = str(
        coaching_moment.get("confidence")
        or semantic_case.get("confidence")
        or ""
    ).strip().lower() or None
    evidence_type = str(
        coaching_moment.get("evidence_type")
        or semantic_case.get("evidence_type")
        or (fit_item or {}).get("evidence_type")
        or ""
    ).strip() or None
    return {
        "moment_summary": summary or None,
        "missing_action": missing_action or None,
        "why_it_matters": why_it_matters or None,
        "supporting_quote": supporting_quote,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "gap_claim": _first_sentence(str(coaching_moment.get("gap_claim") or ""), limit=260) or None,
        "proof_type": str(coaching_moment.get("proof_type") or "").strip() or None,
        "proof_explanation": _first_sentence(str(coaching_moment.get("proof_explanation") or ""), limit=360) or None,
        "quote_role": str(coaching_moment.get("quote_role") or "").strip() or None,
        "counter_evidence": [
            _first_sentence(str(item or ""), limit=220)
            for item in coaching_moment.get("counter_evidence") or []
            if _first_sentence(str(item or ""), limit=220)
        ][:3],
        "has_explicit_coaching_moment": has_explicit_coaching_moment,
    }


def _semantic_case_supporting_quote(
    *,
    semantic_case: dict[str, Any],
    turns: list[dict[str, str]],
    block_name: str | None = None,
) -> str | None:
    moment = _semantic_case_coaching_moment(semantic_case, block_name=block_name) or {}
    return (
        str(moment.get("supporting_quote") or "").strip()
        or _report_evidence_quote_text(turns)
        or None
    )


def _report_evidence_quote_text(turns: list[dict[str, str]]) -> str:
    """Choose one grounded text line for legacy quote-shaped payloads."""
    for preferred in ("client", "unknown", "manager"):
        found = next((turn for turn in turns if turn.get("speaker") == preferred), None)
        if found:
            return str(found.get("text") or "").strip()
    return ""


def _call_breakdown_fragment_strength(
    *,
    fragment: str | None,
    evidence_quality: str | None,
) -> str:
    """Classify how safe a call-breakdown fragment is as proof."""
    text = _dialogue_turn_text(str(fragment or ""), limit=220)
    if not text:
        return "missing"
    quality = str(evidence_quality or "").strip().lower()
    if is_greeting_only_fragment(text) or _dialogue_compact(text) == "телефонныйзвонок":
        return "weak"
    info_score = fragment_information_score(text)
    if quality in {"direct", "indirect"} and info_score >= 4:
        return "strong"
    if quality in {"direct", "indirect"}:
        return "medium"
    return "weak"


def _call_breakdown_fragment_from_turns(turns: list[dict[str, str]]) -> str | None:
    """Pick a bounded dialogue line for `РАЗБОР ЗВОНКА` without inventing evidence."""
    quote = _report_evidence_quote_text(turns)
    if not quote:
        return None
    return _dialogue_turn_text(quote, limit=180) or None


def _manager_text_from_turns(turns: list[dict[str, str]]) -> str | None:
    found = next((turn for turn in turns if turn.get("speaker") == "manager"), None)
    return str(found.get("text") or "").strip() if found else None


def _report_evidence_candidate_rank(
    *,
    candidate: dict[str, Any],
    score_by_stage: list[dict[str, Any]],
    artifact: ReportArtifact,
) -> tuple[int, int, int, float, datetime]:
    priority_stage = next((item for item in score_by_stage if item.get("is_priority")), None)
    priority_stage_code = str((priority_stage or {}).get("stage_code") or "").strip()
    stage_code = str(candidate.get("stage_code") or "").strip()
    return (
        0 if priority_stage_code and stage_code == priority_stage_code else 1,
        REPORT_EVIDENCE_PRIORITY_RANK.get(str(candidate.get("priority") or "").lower(), 9),
        REPORT_EVIDENCE_QUALITY_RANK.get(str(candidate.get("evidence_quality") or "").lower(), 9),
        _extract_score_percent(artifact.analysis),
        artifact.call_started_at or datetime.max.replace(tzinfo=UTC),
    )


def _semantic_case_matches_focus(
    *,
    semantic_case: dict[str, Any],
    focus_stage_code: str | None,
) -> bool:
    if not focus_stage_code:
        return True
    case_stage = str(semantic_case.get("stage_code") or "").strip()
    return not case_stage or case_stage == focus_stage_code


def _semantic_case_stage_code(
    *,
    semantic_case: dict[str, Any],
    focus_stage_code: str | None,
) -> str:
    return str(semantic_case.get("stage_code") or "").strip() or str(focus_stage_code or "").strip()


def _semantic_case_block_fit_item(semantic_case: dict[str, Any], block_name: str) -> dict[str, Any] | None:
    block_fit = semantic_case.get("report_block_fit")
    if not isinstance(block_fit, dict):
        return None
    item = block_fit.get(block_name)
    return item if isinstance(item, dict) else None


def _semantic_case_block_fit_score(semantic_case: dict[str, Any], block_name: str) -> int | None:
    item = _semantic_case_block_fit_item(semantic_case, block_name)
    if item is None:
        return None
    try:
        score = int(item.get("score"))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, score))


def _semantic_case_block_fit_value(semantic_case: dict[str, Any], block_name: str, key: str) -> str | None:
    item = _semantic_case_block_fit_item(semantic_case, block_name)
    if item is None:
        return None
    value = str(item.get(key) or "").strip()
    return value or None


def _semantic_case_problem_fit_item(semantic_case: dict[str, Any], block_name: str) -> dict[str, Any] | None:
    item = _semantic_case_block_fit_item(semantic_case, block_name)
    if item is None:
        return None
    problem_fit = item.get("problem_fit")
    return problem_fit if isinstance(problem_fit, dict) else None


def _semantic_case_problem_fit_score(semantic_case: dict[str, Any], block_name: str) -> int | None:
    problem_fit = _semantic_case_problem_fit_item(semantic_case, block_name)
    if problem_fit is None:
        return None
    try:
        score = int(problem_fit.get("score"))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, score))


def _semantic_case_problem_fit_text(semantic_case: dict[str, Any], block_name: str) -> str:
    problem_fit = _semantic_case_problem_fit_item(semantic_case, block_name) or {}
    return " ".join(
        str(value or "")
        for value in (
            problem_fit.get("problem_signal"),
            problem_fit.get("explanation"),
            semantic_case.get("case_title"),
            semantic_case.get("coaching_diagnosis"),
            semantic_case.get("recommended_next_action"),
        )
    )


def _problem_signal_categories(*values: Any) -> set[str]:
    text = _summary_norm(" ".join(str(value or "") for value in values))
    categories: set[str] = set()
    for category, markers in PROBLEM_SIGNAL_CATEGORY_MARKERS.items():
        if any(marker in text for marker in markers):
            categories.add(category)
    return categories


def _problem_signal_token_overlap(left: Any, right: Any) -> float:
    left_tokens = {
        token
        for token in re.findall(r"[a-zа-яё0-9]+", _summary_norm(left))
        if len(token) >= 4
    }
    right_tokens = {
        token
        for token in re.findall(r"[a-zа-яё0-9]+", _summary_norm(right))
        if len(token) >= 4
    }
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(min(len(left_tokens), len(right_tokens)), 1)


def _semantic_case_problem_matches_daily_focus(
    *,
    semantic_case: dict[str, Any],
    block_name: str,
    daily_focus: dict[str, Any] | None,
) -> bool:
    problem_statement = str((daily_focus or {}).get("problem_statement") or "").strip()
    problem_signal = str((daily_focus or {}).get("problem_signal") or "").strip()
    if not problem_statement and not problem_signal:
        return True
    case_problem_text = _semantic_case_problem_fit_text(semantic_case, block_name)
    if not _summary_norm(case_problem_text):
        return True
    focus_categories = _problem_signal_categories(problem_statement, problem_signal)
    case_categories = _problem_signal_categories(case_problem_text)
    if focus_categories and case_categories:
        return bool(focus_categories & case_categories)
    return _problem_signal_token_overlap(
        " ".join((problem_statement, problem_signal)),
        case_problem_text,
    ) >= 0.25


def _semantic_case_turn_has_speaker(turns: list[dict[str, str]], speaker: str) -> bool:
    expected = str(speaker or "").strip().lower()
    return any(
        str(turn.get("speaker") or "").strip().lower() == expected
        and bool(str(turn.get("text") or "").strip())
        for turn in turns
    )


def _semantic_case_text_bundle(semantic_case: dict[str, Any]) -> str:
    return _summary_norm(
        " ".join(
            str(semantic_case.get(key) or "")
            for key in (
                "case_title",
                "case_type",
                "core_meaning",
                "why_this_call_matters",
                "customer_signal",
                "manager_behavior",
                "coaching_diagnosis",
                "recommended_next_action",
            )
        )
    )


def _semantic_case_has_positive_diagnosis(semantic_case: dict[str, Any]) -> bool:
    diagnosis = _summary_norm(semantic_case.get("coaching_diagnosis"))
    if not diagnosis:
        return False
    return any(marker in diagnosis for marker in SEMANTIC_CASE_POSITIVE_DIAGNOSIS_MARKERS)


def _semantic_case_has_manager_gap(semantic_case: dict[str, Any]) -> bool:
    text = _semantic_case_text_bundle(semantic_case)
    case_type = str(semantic_case.get("case_type") or "").strip().lower()
    if case_type in SEMANTIC_CASE_PROBLEM_TYPES and any(marker in text for marker in SEMANTIC_CASE_MANAGER_GAP_MARKERS):
        return True
    evidence_type = _semantic_case_block_fit_value(semantic_case, "situation_day", "evidence_type")
    return evidence_type == "manager_gap"


def _semantic_case_problem_proof_rejection_reason(
    *,
    semantic_case: dict[str, Any],
    block_name: str,
) -> str | None:
    if block_name not in {"situation_day", "call_breakdown"}:
        return None
    fit_item = _semantic_case_block_fit_item(semantic_case, block_name) or {}
    if fit_item.get("evidence_type") != "manager_gap":
        return None
    if fit_item.get("block_role") not in {None, "coaching_problem"}:
        return None
    coaching_moment = _semantic_case_coaching_moment(semantic_case, block_name=block_name) or {}
    counter_evidence = [
        str(item or "").strip()
        for item in coaching_moment.get("counter_evidence") or []
        if str(item or "").strip()
    ]
    if counter_evidence:
        return "proof_counter_evidence_present"
    quote_role = str(coaching_moment.get("quote_role") or "").strip()
    proof_type = str(coaching_moment.get("proof_type") or "").strip()
    if quote_role == "counter_evidence":
        return "proof_quote_marked_counter_evidence"
    if (
        quote_role == "supports_context"
        and proof_type not in {"absence_in_context", "sequence_inference"}
    ):
        return "proof_quote_supports_context_only"
    if proof_type == "context_support":
        return "proof_context_support_only"
    if (
        str(coaching_moment.get("evidence_type") or "").strip() == "direct_quote"
        and _semantic_quote_looks_like_counter_evidence_for_gap(coaching_moment)
    ):
        return "proof_quote_looks_like_counter_evidence"
    return None


def _semantic_quote_looks_like_counter_evidence_for_gap(coaching_moment: dict[str, Any]) -> bool:
    quote = _summary_norm(coaching_moment.get("supporting_quote"))
    if not quote:
        return False
    claim = _summary_norm(
        " ".join(
            str(value or "")
            for value in (
                coaching_moment.get("gap_claim"),
                coaching_moment.get("moment_summary"),
                coaching_moment.get("missing_action"),
                coaching_moment.get("proof_explanation"),
            )
        )
    )
    if not claim:
        return False
    checks = (
        (
            ("роль", "лпр", "решени", "кем", "руковод", "должност"),
            ("кем являет", "кем вы", "какая роль", "роль", "принимаете решение", "руковод", "являетесь"),
        ),
        (
            ("удоб", "уместн", "не провер"),
            ("удобно", "можете говорить", "сейчас говорить", "вам удобно"),
        ),
        (
            ("срок", "дат", "время", "следующ", "ответствен", "когда", "созвон", "перезвон"),
            ("когда", "срок", "дат", "время", "завтра", "понедельник", "вторник", "сред", "четверг", "пятниц", "перезвон", "созвон"),
        ),
        (
            ("процесс", "как сейчас", "документ", "потребност", "задач"),
            ("как сейчас", "как у вас", "какой процесс", "документ", "задач", "потребност"),
        ),
    )
    return any(
        any(marker in claim for marker in claim_markers)
        and any(marker in quote for marker in quote_markers)
        for claim_markers, quote_markers in checks
    )


def _semantic_case_problem_fragment_rejection_reason(
    *,
    turns: list[dict[str, str]],
    min_information_score: int = 3,
) -> str | None:
    manager_text = _manager_text_from_turns(turns)
    if not manager_text:
        return "manager_fragment_missing"
    if is_greeting_only_fragment(manager_text) or _dialogue_compact(manager_text) == "телефонныйзвонок":
        return "problem_fragment_low_information"
    if fragment_information_score(manager_text) < min_information_score:
        return "problem_fragment_low_information"
    return None


def _semantic_case_block_rejection_reason(
    *,
    semantic_case: dict[str, Any],
    turns: list[dict[str, str]],
    block_name: str,
    focus_stage_code: str | None,
    daily_focus: dict[str, Any] | None = None,
) -> str | None:
    if focus_stage_code and not _semantic_case_matches_focus(
        semantic_case=semantic_case,
        focus_stage_code=focus_stage_code,
    ):
        return "stage_mismatch"
    coaching_moment = _semantic_case_coaching_moment(semantic_case, block_name=block_name)
    has_moment_summary = bool(
        str((coaching_moment or {}).get("moment_summary") or "").strip()
        or str((coaching_moment or {}).get("missing_action") or "").strip()
    )
    quote_required_blocks = {"voice_of_customer", "call_tomorrow"}
    if not turns and not (has_moment_summary and block_name not in quote_required_blocks):
        return "missing_grounded_fragment"

    fit_item = _semantic_case_block_fit_item(semantic_case, block_name)
    fit_score = _semantic_case_block_fit_score(semantic_case, block_name)
    reason_code = _semantic_case_block_fit_value(semantic_case, block_name, "reason_code")
    evidence_type = _semantic_case_block_fit_value(semantic_case, block_name, "evidence_type")
    block_role = _semantic_case_block_fit_value(semantic_case, block_name, "block_role")
    title_mode = _semantic_case_block_fit_value(semantic_case, block_name, "title_mode")
    gap_proven_raw = fit_item.get("gap_proven") if fit_item is not None else None
    problem_fit_score = _semantic_case_problem_fit_score(semantic_case, block_name)
    min_score = SEMANTIC_CASE_BLOCK_MIN_SCORE.get(block_name, 50)
    if fit_item is not None:
        if fit_item.get("fit") is not True:
            return reason_code or "report_block_fit_false"
        if fit_score is None or fit_score < min_score:
            return "report_block_fit_score_below_threshold"
        expected_roles = SEMANTIC_CASE_BLOCK_EXPECTED_ROLES.get(block_name)
        if block_role and expected_roles and block_role not in expected_roles:
            return "block_role_mismatch"
        min_problem_score = SEMANTIC_CASE_PROBLEM_FIT_MIN_SCORE.get(block_name)
        if (
            min_problem_score is not None
            and problem_fit_score is not None
            and problem_fit_score < min_problem_score
        ):
            return "problem_fit_score_below_threshold"

    case_type = str(semantic_case.get("case_type") or "").strip().lower()
    positive_diagnosis = _semantic_case_has_positive_diagnosis(semantic_case)

    if block_name == "situation_day":
        if block_role and block_role != "coaching_problem":
            return "block_role_not_coaching_problem"
        if title_mode and title_mode != "problem":
            return "title_mode_not_problem"
        if case_type not in SEMANTIC_CASE_PROBLEM_TYPES:
            return (
                "positive_diagnosis_not_problem_case"
                if positive_diagnosis
                else "case_type_not_problem_case"
            )
        if evidence_type is not None and evidence_type != "manager_gap":
            return "situation_day_requires_manager_gap"
        if gap_proven_raw is False:
            return "manager_gap_not_proven"
        if positive_diagnosis:
            return "positive_diagnosis_not_problem_case"
        if not _semantic_case_has_manager_gap(semantic_case):
            return "manager_gap_missing"
        if (
            not has_moment_summary
            and not _semantic_case_turn_has_speaker(turns, "manager")
            and evidence_type != "manager_gap"
        ):
            return "manager_evidence_missing"
        proof_rejection_reason = _semantic_case_problem_proof_rejection_reason(
            semantic_case=semantic_case,
            block_name=block_name,
        )
        if proof_rejection_reason:
            return proof_rejection_reason
        problem_fragment_reason = (
            None
            if has_moment_summary
            else _semantic_case_problem_fragment_rejection_reason(turns=turns)
        )
        if problem_fragment_reason:
            return problem_fragment_reason
        if not _semantic_case_problem_matches_daily_focus(
            semantic_case=semantic_case,
            block_name=block_name,
            daily_focus=daily_focus,
        ):
            return "problem_signal_mismatch"
        return None

    if block_name == "call_breakdown":
        if block_role and block_role not in {"coaching_problem", "strong_practice"}:
            return "block_role_mismatch"
        if block_role == "coaching_problem" and title_mode and title_mode != "problem":
            return "title_mode_not_problem"
        if case_type in {"customer_signal", "service_issue"} and fit_item is None:
            return "case_type_not_coachable_moment"
        if positive_diagnosis and case_type != "strong_practice":
            return "positive_diagnosis_not_problem_case"
        if (
            not has_moment_summary
            and not _semantic_case_turn_has_speaker(turns, "manager")
            and case_type != "strong_practice"
        ):
            return "manager_fragment_missing"
        if block_role == "coaching_problem" and gap_proven_raw is False:
            return "manager_gap_not_proven"
        if block_role == "coaching_problem":
            proof_rejection_reason = _semantic_case_problem_proof_rejection_reason(
                semantic_case=semantic_case,
                block_name=block_name,
            )
            if proof_rejection_reason:
                return proof_rejection_reason
            problem_fragment_reason = None if has_moment_summary else _semantic_case_problem_fragment_rejection_reason(
                turns=turns,
                min_information_score=3,
            )
            if problem_fragment_reason:
                return problem_fragment_reason
        if block_role == "coaching_problem" and not _semantic_case_problem_matches_daily_focus(
            semantic_case=semantic_case,
            block_name=block_name,
            daily_focus=daily_focus,
        ):
            return "problem_signal_mismatch"
        return None

    if block_name == "voice_of_customer":
        if block_role and block_role != "customer_signal":
            return "block_role_not_customer_signal"
        if not _semantic_case_turn_has_speaker(turns, "client") and not _semantic_case_turn_has_speaker(turns, "unknown"):
            return "customer_quote_missing"
        return None

    if block_name == "additional_situations":
        if block_role and block_role not in SEMANTIC_CASE_BLOCK_EXPECTED_ROLES["additional_situations"]:
            return "block_role_mismatch"
        if block_role == "coaching_problem":
            if title_mode and title_mode != "problem":
                return "title_mode_not_problem"
            if gap_proven_raw is False:
                return "manager_gap_not_proven"
        return None

    if block_name == "call_tomorrow":
        if block_role and block_role != "follow_up_action":
            return "block_role_not_follow_up_action"
        return None

    return None


def _semantic_case_candidate_diagnostic(
    *,
    artifact: ReportArtifact,
    semantic_case: dict[str, Any],
    block_name: str,
    rejection_reason: str | None,
) -> dict[str, Any]:
    ref = _artifact_call_reference(artifact)
    fit_item = _semantic_case_block_fit_item(semantic_case, block_name) or {}
    problem_fit = _semantic_case_problem_fit_item(semantic_case, block_name) or {}
    coaching_moment = _semantic_case_coaching_moment(semantic_case, block_name=block_name) or {}
    return {
        "call_id": ref["call_id"],
        "client_call_reference": ref["client_call_reference"],
        "case_title": str(semantic_case.get("case_title") or "").strip(),
        "case_type": str(semantic_case.get("case_type") or "").strip() or None,
        "stage_code": str(semantic_case.get("stage_code") or "").strip() or None,
        "fit": fit_item.get("fit") if fit_item else None,
        "fit_score": _semantic_case_block_fit_score(semantic_case, block_name),
        "reason_code": str(fit_item.get("reason_code") or "").strip() or None,
        "evidence_type": str(fit_item.get("evidence_type") or "").strip() or None,
        "block_role": str(fit_item.get("block_role") or "").strip() or None,
        "title_mode": str(fit_item.get("title_mode") or "").strip() or None,
        "problem_fit_score": _semantic_case_problem_fit_score(semantic_case, block_name),
        "problem_fit_signal": str(problem_fit.get("problem_signal") or "").strip() or None,
        "evidence_target": str(fit_item.get("evidence_target") or "").strip() or None,
        "gap_proven": fit_item.get("gap_proven") if fit_item else None,
        "proof_type": coaching_moment.get("proof_type"),
        "quote_role": coaching_moment.get("quote_role"),
        "counter_evidence_count": len(coaching_moment.get("counter_evidence") or []),
        "rejection_reason": rejection_reason,
    }


def _semantic_case_selection_diagnostics(
    *,
    block_name: str,
    selected: dict[str, Any] | None,
    rejected: list[dict[str, Any]],
    selection_mode: str | None = None,
) -> dict[str, Any]:
    diagnostics = {
        "block": block_name,
        "selected_candidate": selected,
        "rejected_candidates": rejected[:12],
    }
    if selection_mode:
        diagnostics["selection_mode"] = selection_mode
    return diagnostics


def _semantic_case_scripts(*, semantic_case: dict[str, Any], stage_code: str) -> list[str]:
    scripts: list[str] = []
    action = _first_sentence(str(semantic_case.get("recommended_next_action") or ""), limit=220)
    if _looks_like_manager_speech_script(action):
        scripts.append(action)
    for item in _SITUATION_STAGE_SCRIPT_FALLBACKS.get(stage_code) or []:
        phrase = _first_sentence(str(item or ""), limit=220)
        if phrase and phrase not in scripts:
            scripts.append(phrase)
        if len(scripts) >= 3:
            break
    return scripts[:3]


def _looks_like_manager_speech_script(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if "?" in text or "пожалуйста" in lower or "подскажите" in lower:
        return True
    if re.match(
        r"^(уточнить|зафиксировать|согласовать|отправить|проверить|поднять|спросить|объяснить|закрыть|сделать)\b",
        lower,
    ):
        return False
    return any(
        marker in lower
        for marker in ("добрый день", "давайте", "я отправлю", "могу", "предлагаю")
    )


def _call_breakdown_summary_line(
    *,
    ref: dict[str, Any],
    evidence_strength: str,
) -> str:
    summary = str(ref.get("client_call_reference") or "").strip()
    if not summary:
        summary = f"{ref.get('client_label') or 'Клиент'} · {ref.get('time_label') or '—'}"
    if evidence_strength in {"weak", "missing"}:
        return f"{summary} · зона для разбора; подтверждающий фрагмент ограничен"
    return summary


def _clean_call_breakdown_cell(value: Any) -> str:
    """Normalize manager-facing call breakdown text and punctuation artifacts."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    text = re.sub(r"([.!?])\s*:\s+", r"\1 ", text)
    text = re.sub(r":\s*:\s*", ": ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


def _call_breakdown_fragment_reject_reason(value: Any) -> str | None:
    """Return why a call breakdown fragment is unsafe for manager-facing proof."""
    text = _clean_call_breakdown_cell(value)
    if not text or text in {"—", "-"}:
        return "missing_evidence"
    if _summary_norm(text).rstrip(".") == _summary_norm(CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE).rstrip("."):
        return "no_confirming_fragment"
    if is_greeting_only_fragment(text) or _dialogue_compact(text) == "телефонныйзвонок":
        return "low_information"
    if fragment_information_score(text) < 3:
        return "low_information"
    return None


def _call_breakdown_problem_is_growth(value: Any) -> bool:
    normalized = _summary_norm(value)
    return any(
        marker in normalized
        for marker in (
            "не ",
            "небыл",
            "небыла",
            "недостат",
            "остался общ",
            "общим",
            "без ",
            "не уточ",
            "не зафикс",
            "не связан",
            "не провер",
            "проблем",
            "зона",
            "требует",
        )
    )


def _call_breakdown_positive_only_recommendation(value: Any) -> bool:
    normalized = _summary_norm(value)
    if not normalized:
        return False
    has_positive_only_marker = any(
        marker in normalized
        for marker in CALL_BREAKDOWN_POSITIVE_ONLY_RECOMMENDATION_MARKERS
    )
    if not has_positive_only_marker:
        return False
    return not any(
        marker in normalized
        for marker in CALL_BREAKDOWN_CORRECTIVE_RECOMMENDATION_MARKERS
    )


def _call_breakdown_recommendation_polarity_mismatch(*, what: Any, recommendation: Any) -> bool:
    return _call_breakdown_problem_is_growth(what) and _call_breakdown_positive_only_recommendation(recommendation)


def _call_breakdown_duplicate_problem_wording(*, what: Any, recommendation: Any) -> bool:
    what_norm = _summary_norm(what).rstrip(".")
    rec_norm = _summary_norm(recommendation).rstrip(".")
    if not what_norm or not rec_norm:
        return False
    return what_norm == rec_norm or (
        len(rec_norm) >= 32 and rec_norm in what_norm
    ) or (
        len(what_norm) >= 32 and what_norm in rec_norm
    )


def _call_breakdown_quality_fallback(
    *,
    call_breakdown: dict[str, Any],
    quality: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return an explicit insufficient-evidence Call Breakdown block."""
    result = dict(call_breakdown)
    result["is_placeholder"] = False
    result["rows"] = []
    result["summary_line"] = CALL_BREAKDOWN_INSUFFICIENT_EVIDENCE_MESSAGE
    result["call_breakdown_evidence_strength"] = "missing"
    result["call_breakdown_fragment_present"] = False
    result["call_breakdown_quality"] = quality
    return result, quality


def _apply_call_breakdown_quality_gate(
    *,
    call_breakdown: dict[str, Any] | None,
    daily_focus: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Filter Call Breakdown rows so only evidence-backed, aligned moments render."""
    source = str((call_breakdown or {}).get("call_breakdown_source") or (call_breakdown or {}).get("source_note") or "")
    rows = [
        list(row)
        for row in ((call_breakdown or {}).get("rows") or [])
        if isinstance(row, (list, tuple))
    ]
    quality: dict[str, Any] = {
        "status": "passed",
        "source": source or "unknown",
        "input_rows_count": len(rows),
        "rendered_rows_count": 0,
        "filtered_rows_count": 0,
        "filtered_reasons": {},
        "filtered_rows": [],
        "rendered_rows": [],
    }
    if not call_breakdown:
        quality["status"] = "insufficient_evidence"
        return _call_breakdown_quality_fallback(call_breakdown={}, quality=quality)

    focus_stage = _daily_focus_stage_code(daily_focus)
    block_stage = str(call_breakdown.get("stage_code") or "").strip()
    selection_mode = str(
        dict(call_breakdown.get("selection_diagnostics") or {}).get("selection_mode")
        or ""
    ).strip()
    allow_focus_stage_mismatch = (
        source == "report_evidence.semantic_case"
        and selection_mode == "best_semantic_case_after_focus_mismatch"
    ) or (
        source == "report_evidence.call_breakdown_composer.v1"
        and selection_mode == "same_call_as_verified_situation_day"
    ) or (
        source == "report_evidence.evidence_registry.call_breakdown_route.v1"
        and selection_mode == "evidence_registry_router_call_breakdown"
    )
    source_allows_optional_quote = source in {
        "report_evidence.block_candidates.call_breakdown",
        "report_evidence.semantic_case",
        "report_evidence.manager_coaching_moments",
        "report_evidence.call_breakdown_composer.v1",
        "report_evidence.evidence_registry.call_breakdown_route.v1",
    }
    optional_quote_evidence_type = str(call_breakdown.get("evidence_type") or "").strip().lower()
    quote_optional = bool(
        source_allows_optional_quote
        and str(call_breakdown.get("moment_summary") or "").strip()
        and optional_quote_evidence_type
        in {"absence_in_context", "sequence_inference", "inferred_from_dialogue", "manager_gap", ""}
    )
    fallback_moment_summary = _clean_call_breakdown_cell(
        (call_breakdown or {}).get("moment_summary")
    )

    rendered: list[list[str]] = []
    rendered_fragment_present = False

    def reject(index: int, reason: str, row: list[Any]) -> None:
        quality["filtered_rows_count"] += 1
        reasons = quality["filtered_reasons"]
        reasons[reason] = int(reasons.get(reason) or 0) + 1
        quality["filtered_rows"].append(
            {
                "index": index,
                "reason": reason,
                "what": _first_sentence(str(row[1] if len(row) > 1 else ""), limit=180),
                "fragment": _first_sentence(str(row[2] if len(row) > 2 else ""), limit=120),
                "recommendation": _first_sentence(str(row[3] if len(row) > 3 else ""), limit=180),
            }
        )

    for index, row in enumerate(rows, start=1):
        if (
            focus_stage
            and block_stage
            and block_stage != focus_stage
            and not allow_focus_stage_mismatch
        ):
            reject(index, "stage_mismatch", row)
            continue
        padded = [*row, "", "", "", ""][:4]
        moment, what, fragment, recommendation = [
            _clean_call_breakdown_cell(item)
            for item in padded
        ]
        fragment_reason = _call_breakdown_fragment_reject_reason(fragment)
        if fragment_reason:
            missing_optional_quote = quote_optional and fragment_reason in {
                "missing_evidence",
                "no_confirming_fragment",
            }
            if not missing_optional_quote:
                reject(index, fragment_reason, row)
                continue
        if _call_breakdown_recommendation_polarity_mismatch(what=what, recommendation=recommendation):
            reject(index, "recommendation_polarity_mismatch", row)
            continue
        if _call_breakdown_duplicate_problem_wording(what=what, recommendation=recommendation):
            reject(index, "duplicate_problem_wording", row)
            continue
        moment_cell = fragment
        if fragment_reason and quote_optional:
            moment_cell = fallback_moment_summary or what or fragment
        cleaned_row = [moment or f"Момент {len(rendered) + 1}", what, moment_cell, recommendation]
        rendered.append(cleaned_row)
        if not fragment_reason:
            rendered_fragment_present = True
        quality["rendered_rows"].append(
            {
                "index": len(rendered),
                "moment": cleaned_row[0],
                "fragment_present": not fragment_reason,
                "quote_optional": bool(fragment_reason and quote_optional),
            }
        )

    quality["rendered_rows_count"] = len(rendered)
    if not rendered:
        quality["status"] = "insufficient_evidence"
        return _call_breakdown_quality_fallback(call_breakdown=call_breakdown, quality=quality)

    if quality["filtered_rows_count"]:
        quality["status"] = "warning"
    result = dict(call_breakdown)
    result["rows"] = rendered
    result["call_breakdown_fragment_present"] = rendered_fragment_present
    if rendered_fragment_present and result.get("call_breakdown_evidence_strength") == "missing":
        result["call_breakdown_evidence_strength"] = "medium"
    result["call_breakdown_quality"] = quality
    return result, quality


def _reduce_situation_call_breakdown_repetition(
    *,
    situation_day_coaching_view: dict[str, Any] | None,
    situation_evidence_quote: dict[str, Any] | None,
    call_breakdown: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Avoid rendering the same proof text in Situation Day and Call Breakdown."""
    if not call_breakdown or not situation_day_coaching_view:
        return call_breakdown
    situation_call_id = str((situation_evidence_quote or {}).get("call_id") or "").strip()
    breakdown_call_id = str(call_breakdown.get("call_id") or "").strip()
    if situation_call_id and breakdown_call_id and situation_call_id != breakdown_call_id:
        return call_breakdown
    situation_source = _report_source_from_paths(
        [
            (situation_evidence_quote or {}).get("source"),
            situation_day_coaching_view.get("source"),
        ]
    )
    breakdown_source = _report_source_from_paths(
        [
            call_breakdown.get("call_breakdown_source"),
            call_breakdown.get("source_note"),
        ]
    )
    if situation_source != breakdown_source or situation_source != "block_candidates":
        return call_breakdown
    proof_type = str(call_breakdown.get("proof_type") or situation_day_coaching_view.get("proof_type") or "").strip()
    quote_role = str(call_breakdown.get("quote_role") or situation_day_coaching_view.get("quote_role") or "").strip()
    if proof_type == "direct_gap" and quote_role != "supports_context":
        return call_breakdown

    situation_texts = [
        situation_day_coaching_view.get("what_happened"),
        situation_day_coaching_view.get("moment_summary"),
        situation_day_coaching_view.get("supporting_quote"),
        (situation_evidence_quote or {}).get("client_text"),
        (situation_evidence_quote or {}).get("manager_text"),
    ]
    alternatives = [
        call_breakdown.get("proof_explanation"),
        call_breakdown.get("why_it_matters"),
        call_breakdown.get("missing_action"),
        call_breakdown.get("moment_summary"),
    ]
    result = dict(call_breakdown)
    rows = [list(row) for row in call_breakdown.get("rows") or [] if isinstance(row, (list, tuple))]
    changed = False
    for row in rows:
        if len(row) < 3:
            continue
        fragment = str(row[2] or "").strip()
        if not fragment or not any(
            _summary_norm(fragment) and _summary_norm(fragment) == _summary_norm(text)
            for text in situation_texts
        ):
            continue
        replacement = next(
            (
                _first_sentence(str(item or ""), limit=260)
                for item in alternatives
                if _summary_norm(item)
                and _summary_norm(item) != _summary_norm(fragment)
                and _summary_norm(item) != _summary_norm(row[1] if len(row) > 1 else "")
            ),
            "",
        )
        if replacement:
            row[2] = replacement
            changed = True
    moments = [
        dict(moment)
        for moment in call_breakdown.get("moments") or []
        if isinstance(moment, dict)
    ]
    for moment in moments:
        quote = str(moment.get("supporting_quote") or "").strip()
        if quote and any(
            _summary_norm(quote) and _summary_norm(quote) == _summary_norm(text)
            for text in situation_texts
        ):
            moment["supporting_quote_repeated_with_situation_day"] = True
            changed = True
        summary = str(moment.get("moment_summary") or "").strip()
        if summary and any(
            _summary_norm(summary) and _summary_norm(summary) == _summary_norm(text)
            for text in situation_texts
        ):
            replacement = next(
                (
                    _first_sentence(str(item or ""), limit=260)
                    for item in alternatives
                    if _summary_norm(item)
                    and _summary_norm(item) != _summary_norm(summary)
                    and _summary_norm(item) != _summary_norm(moment.get("what"))
                ),
                "",
            )
            if replacement:
                moment["moment_summary"] = replacement
                changed = True
    if changed:
        result["rows"] = rows
        if moments:
            result["moments"] = moments
        result["repetition_reduced_with_situation_day"] = True
        result["repetition_reduction_source"] = "same_call_same_report_evidence_source"
    return result


def _artifact_fallback_evidence_texts(artifact: ReportArtifact) -> list[str]:
    """Return persisted text fragments that may prove a legacy call-breakdown row."""
    texts: list[str] = []
    detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})

    for frag in detail.get("evidence_fragments") or []:
        if not isinstance(frag, dict):
            continue
        texts.extend(
            str(frag.get(key) or "").strip()
            for key in ("client_text", "manager_text", "manager_phrase", "evidence")
            if str(frag.get(key) or "").strip()
        )

    for segment in (artifact.interaction.metadata_ or {}).get("segments") or []:
        if isinstance(segment, dict):
            text = str(segment.get("text") or "").strip()
            if text:
                texts.append(text)

    transcript = str(artifact.interaction.text or "").strip()
    if transcript:
        texts.extend(
            chunk.strip()
            for chunk in re.split(r"(?<=[.!?])\s+", transcript)
            if chunk.strip()
        )
    return texts


def _artifact_fallback_evidence_fragment(artifact: ReportArtifact) -> str | None:
    """Pick the strongest persisted legacy fragment, excluding boilerplate."""
    best_text = ""
    best_score = 0
    for text in _artifact_fallback_evidence_texts(artifact):
        score = fragment_information_score(text)
        if score > best_score:
            best_text = text
            best_score = score
    if best_score < 4:
        return None
    return _dialogue_turn_text(best_text, limit=180) or None


CLIENT_REACTION_SITUATION_MARKERS = (
    "барьер",
    "возраж",
    "довер",
    "недовер",
    "не актуал",
    "неактуал",
    "не беру",
    "не интересно",
    "незнаком",
    "отказ",
    "ответ клиента",
    "перенос",
    "позвон",
    "потребност",
    "процесс клиент",
    "реакц",
    "сказал",
    "сомнен",
    "текущ",
    "удоб",
    "мошен",
)
CLIENT_TRUST_BARRIER_MARKERS = (
    "довер",
    "мошен",
    "незнаком",
    "не беру",
    "безопас",
)
CLIENT_TIMING_BARRIER_MARKERS = (
    "позвон",
    "сейчас",
    "позже",
    "потом",
    "удоб",
    "занят",
)
CLIENT_OBJECTION_MARKERS = (
    "не актуал",
    "неактуал",
    "не интересно",
    "нет необходимости",
    "нет потребности",
    "сомнен",
    "дорого",
    "отказ",
)
CLIENT_PROCESS_MARKERS = (
    "бумаг",
    "документ",
    "процесс",
    "использ",
    "достаточ",
    "электрон",
    "эдо",
)


def _situation_candidate_text(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("situation_title"),
        candidate.get("stage_code"),
        candidate.get("what_happened"),
        candidate.get("what_it_means"),
        candidate.get("what_was_missing"),
        candidate.get("next_time_action"),
    ]
    return _summary_norm(" ".join(str(part or "") for part in parts))


def _situation_requires_client_signal(candidate: dict[str, Any]) -> bool:
    """Return True when the situation conclusion depends on client reaction/state."""
    text = _situation_candidate_text(candidate)
    if any(marker in text for marker in CLIENT_REACTION_SITUATION_MARKERS):
        return True
    stage_code = str(candidate.get("stage_code") or "").strip()
    return stage_code in {"contact_start", "needs_discovery", "objection_handling"}


def _client_turn_from_turns(turns: list[dict[str, str]]) -> dict[str, str] | None:
    for turn in turns:
        if str(turn.get("speaker") or "").strip().lower() == "client" and str(turn.get("text") or "").strip():
            return turn
    return None


def _client_signal_kind(text: Any) -> str | None:
    normalized = _summary_norm(text)
    if any(marker in normalized for marker in CLIENT_TRUST_BARRIER_MARKERS):
        return "trust_barrier"
    if any(marker in normalized for marker in CLIENT_OBJECTION_MARKERS):
        return "objection"
    if any(marker in normalized for marker in CLIENT_TIMING_BARRIER_MARKERS):
        return "timing_barrier"
    if any(marker in normalized for marker in CLIENT_PROCESS_MARKERS):
        return "process_context"
    return None


def _client_quote_relevance_for_situation(*, quote: str, item: dict[str, Any], candidate: dict[str, Any]) -> int:
    """Score whether a client quote can ground the situation candidate."""
    normalized_quote = _summary_norm(quote)
    if len(normalized_quote) < 8:
        return 0
    candidate_text = _situation_candidate_text(candidate)
    score = 1
    signal_kind = _client_signal_kind(normalized_quote)
    if signal_kind:
        score += 2
    topic = _summary_norm(item.get("topic"))
    if topic and topic not in {"other", "unknown"}:
        score += 1
    if any(marker in candidate_text for marker in ("ответ клиента", "реакц", "удоб", "позвон")) and (
        signal_kind in {"trust_barrier", "timing_barrier"} or "позвон" in normalized_quote
    ):
        score += 3
    if any(marker in candidate_text for marker in ("довер", "недовер", "барьер")) and signal_kind == "trust_barrier":
        score += 3
    if any(marker in candidate_text for marker in ("возраж", "отказ", "сомнен")) and signal_kind == "objection":
        score += 3
    if any(marker in candidate_text for marker in ("потребност", "процесс", "текущ")) and signal_kind == "process_context":
        score += 3
    if str(candidate.get("stage_code") or "").strip() == "contact_start" and signal_kind in {"trust_barrier", "timing_barrier"}:
        score += 2
    return score


def _select_client_grounded_situation_quote(
    *,
    evidence: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    """Pick a relevant client quote from report_evidence when the situation needs one."""
    best: tuple[int, dict[str, Any]] | None = None
    for source_key in ("voice_of_customer", "quote_bank"):
        for item in evidence.get(source_key) or []:
            if not isinstance(item, dict):
                continue
            if source_key == "voice_of_customer" and item.get("usable_in_report") is not True:
                continue
            if item.get("usable_in_report") is False:
                continue
            speaker = str(item.get("speaker") or "").strip().lower()
            quote = _dialogue_turn_text(str(item.get("quote") or ""), limit=220)
            if speaker not in {"client", "unknown"} or not quote:
                continue
            relevance = _client_quote_relevance_for_situation(
                quote=quote,
                item=item,
                candidate=candidate,
            )
            if relevance < 3:
                continue
            speaker_rank = 0 if speaker == "client" else 1
            signal_rank = {"high": 0, "medium": 1, "low": 2}.get(
                str(item.get("business_signal") or "").strip().lower(),
                1,
            )
            rank = relevance * -10 + speaker_rank + signal_rank
            if best is None or rank < best[0]:
                best = (rank, {"source_key": source_key, "item": item, "quote": quote, "relevance": relevance})
    if best is None:
        return None, 0
    return best[1], int(best[1]["relevance"])


def _client_grounded_situation_coaching_view(
    *,
    candidate: dict[str, Any],
    quote: str,
    stage_code: str,
    stage_name: str,
    score_by_stage: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build aligned Situation Day copy when client evidence replaces manager-only proof."""
    signal_kind = _client_signal_kind(quote)
    if signal_kind == "trust_barrier":
        pattern_title = "Клиент обозначил барьер доверия к незнакомому звонку"
        what_happened = "Клиент прямо обозначил недоверие к звонкам с незнакомых номеров."
        meaning = "Перед продажей нужно снять риск недоверия и закрепить безопасный канал продолжения."
        what_was_missing = "Не хватило фиксации удобного и доверенного способа связи: WhatsApp, знакомый номер или точное время следующего контакта."
        next_time_action = "Коротко подтвердить, кто звонит и зачем, затем предложить безопасный способ продолжить разговор."
        scripts = [
            "Понимаю, сейчас много подозрительных звонков. Я из Договор-24, пишу вам в WhatsApp, чтобы вы могли проверить контакт.",
            "Давайте я отправлю короткое сообщение с темой разговора, а потом созвонимся в удобное для вас время.",
            "Какой канал для продолжения вам надёжнее: WhatsApp, email или звонок в конкретное время?",
        ]
    elif signal_kind == "timing_barrier":
        pattern_title = "Клиент обозначил ограничение по времени или каналу связи"
        what_happened = f"Клиент сказал: «{_dialogue_turn_text(quote, limit=180)}»."
        meaning = "Интерес можно потерять, если не закрепить удобный формат и срок продолжения."
        what_was_missing = "Не хватило конкретной договорённости о времени или канале следующего контакта."
        next_time_action = "Уточнить удобный канал и зафиксировать конкретное время следующего касания."
        scripts = [
            "Поняла, сейчас неудобно. Когда лучше вернуться к разговору?",
            "Могу отправить короткую информацию в WhatsApp и договориться о точном времени звонка.",
            "Давайте зафиксируем удобный слот, чтобы не отвлекать вас неожиданным звонком.",
        ]
    else:
        fact = f"Клиент сказал: «{_dialogue_turn_text(quote, limit=180)}»."
        normalized_title = _normalize_problem_statement(
            candidate.get("situation_title"),
            stage_code=stage_code,
            fallback=_stage_problem_fallback(stage_code),
        )
        pattern_title = str(normalized_title.get("text") or "").strip() or "Ситуация дня с клиентской репликой"
        what_happened = fact
        meaning = _first_sentence(str(candidate.get("what_it_means") or ""), limit=260)
        what_was_missing = _first_sentence(str(candidate.get("what_was_missing") or ""), limit=260)
        next_time_action = _first_sentence(str(candidate.get("next_time_action") or ""), limit=260)
        scripts = [
            _first_sentence(str(item or ""), limit=220)
            for item in list(candidate.get("scripts") or [])[:3]
            if str(item or "").strip()
        ]

    return {
        "pattern_title": pattern_title,
        "stage_code": stage_code,
        "stage_label": stage_name,
        "stage_score_label": _report_evidence_stage_score_label(stage_code, score_by_stage),
        "what_happened": what_happened,
        "meaning": meaning,
        "what_was_missing": what_was_missing,
        "next_time_action": next_time_action,
        "scripts": scripts[:3],
        "source": "report_evidence.client_grounded_situation",
        "dialogue_is_partial": True,
    }


def _report_evidence_situation_candidate_rank(
    *,
    candidate: dict[str, Any],
    turns: list[dict[str, str]],
    evidence: dict[str, Any],
    score_by_stage: list[dict[str, Any]],
    artifact: ReportArtifact,
) -> tuple[int, int, int, int, float, datetime]:
    base = _report_evidence_candidate_rank(
        candidate=candidate,
        score_by_stage=score_by_stage,
        artifact=artifact,
    )
    if not _situation_requires_client_signal(candidate):
        client_grounding_rank = 0
    elif _client_turn_from_turns(turns) is not None:
        client_grounding_rank = 0
    else:
        _quote, relevance = _select_client_grounded_situation_quote(
            evidence=evidence,
            candidate=candidate,
        )
        client_grounding_rank = 1 if relevance >= 3 else 3
    return (base[0], client_grounding_rank, *base[1:])


def _semantic_case_situation_rank(
    *,
    semantic_case: dict[str, Any],
    score_by_stage: list[dict[str, Any]],
    artifact: ReportArtifact,
) -> tuple[Any, ...]:
    base = _report_evidence_candidate_rank(
        candidate=semantic_case,
        score_by_stage=score_by_stage,
        artifact=artifact,
    )
    fit_score = _semantic_case_block_fit_score(semantic_case, "situation_day")
    problem_fit_score = _semantic_case_problem_fit_score(semantic_case, "situation_day")
    case_type = str(semantic_case.get("case_type") or "").strip().lower()
    evidence_type = _semantic_case_block_fit_value(semantic_case, "situation_day", "evidence_type")
    block_role = _semantic_case_block_fit_value(semantic_case, "situation_day", "block_role")
    title_mode = _semantic_case_block_fit_value(semantic_case, "situation_day", "title_mode")
    case_type_rank = {"missed_opportunity": 0, "growth_zone": 1}.get(case_type, 9)
    evidence_type_rank = 0 if evidence_type == "manager_gap" else 1 if evidence_type is None else 5
    return (
        base[0],
        0 if block_role == "coaching_problem" else 1 if block_role is None else 5,
        0 if title_mode == "problem" else 1 if title_mode is None else 5,
        100 - (problem_fit_score if problem_fit_score is not None else 60),
        100 - (fit_score if fit_score is not None else 60),
        case_type_rank,
        evidence_type_rank,
        base[1],
        base[3],
        base[4],
    )


def _valid_block_candidate_from_evidence(
    evidence: dict[str, Any] | None,
    block_name: str,
) -> dict[str, Any] | None:
    if not isinstance(evidence, dict):
        return None
    block_candidates = evidence.get("block_candidates")
    if not isinstance(block_candidates, dict):
        return None
    candidate = block_candidates.get(block_name)
    return dict(candidate) if isinstance(candidate, dict) and candidate.get("fit") is True else None


def _block_candidate_problem_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(candidate.get(key) or "")
        for key in (
            "main_thesis",
            "what_happened",
            "why_it_matters",
            "what_was_missing",
            "better_next_action",
            "proof_explanation",
        )
    )


def _block_candidate_problem_matches_daily_focus(
    *,
    candidate: dict[str, Any],
    daily_focus: dict[str, Any] | None,
) -> bool:
    problem_statement = str((daily_focus or {}).get("problem_statement") or "").strip()
    problem_signal = str((daily_focus or {}).get("problem_signal") or "").strip()
    if not problem_statement and not problem_signal:
        return True
    candidate_text = _block_candidate_problem_text(candidate)
    if not _summary_norm(candidate_text):
        return True
    focus_categories = _problem_signal_categories(problem_statement, problem_signal)
    candidate_categories = _problem_signal_categories(candidate_text)
    if focus_categories and candidate_categories:
        return bool(focus_categories & candidate_categories)
    return _problem_signal_token_overlap(
        " ".join((problem_statement, problem_signal)),
        candidate_text,
    ) >= 0.25


def _block_candidate_rejection_reason(
    *,
    candidate: dict[str, Any],
    block_name: str,
    focus_stage_code: str | None,
    daily_focus: dict[str, Any] | None,
) -> str | None:
    stage_code = str(candidate.get("stage_code") or "").strip()
    if focus_stage_code and stage_code and stage_code != focus_stage_code:
        return "stage_mismatch"
    if (
        block_name in REPORT_BLOCK_CANDIDATE_PROBLEM_BLOCKS
        and str(candidate.get("role") or candidate.get("block_role") or "").strip() == "coaching_problem"
        and not _block_candidate_problem_matches_daily_focus(
            candidate=candidate,
            daily_focus=daily_focus,
        )
    ):
        return "problem_signal_mismatch"
    return None


def _block_candidate_rank(
    *,
    candidate: dict[str, Any],
    block_name: str,
    score_by_stage: list[dict[str, Any]],
    artifact: ReportArtifact,
) -> tuple[Any, ...]:
    base = _report_evidence_candidate_rank(
        candidate=candidate,
        score_by_stage=score_by_stage,
        artifact=artifact,
    )
    score = _coerced_report_block_candidate_score(candidate.get("score")) or 50
    role = str(candidate.get("role") or candidate.get("block_role") or "").strip()
    title_mode = str(candidate.get("title_mode") or "").strip()
    proof_type = str(candidate.get("proof_type") or "").strip()
    return (
        base[0],
        0 if role == _default_report_block_candidate_role(block_name) else 1 if not role else 5,
        0 if title_mode in {"problem", ""} else 5,
        0 if proof_type in {"sequence_inference", "absence_in_context", "direct_gap"} else 2,
        100 - score,
        base[1],
        base[3],
        base[4],
    )


def _block_candidate_diagnostic(
    *,
    artifact: ReportArtifact,
    candidate: dict[str, Any],
    block_name: str,
    rejection_reason: str | None,
) -> dict[str, Any]:
    ref = _artifact_call_reference(artifact)
    return {
        "call_id": ref["call_id"],
        "client_call_reference": ref["client_call_reference"],
        "case_title": str(candidate.get("main_thesis") or candidate.get("title") or "").strip(),
        "stage_code": str(candidate.get("stage_code") or "").strip() or None,
        "fit": candidate.get("fit"),
        "fit_score": _coerced_report_block_candidate_score(candidate.get("score")),
        "evidence_type": str(candidate.get("evidence_type") or "").strip() or None,
        "block_role": str(candidate.get("role") or candidate.get("block_role") or "").strip() or None,
        "title_mode": str(candidate.get("title_mode") or "").strip() or None,
        "proof_type": candidate.get("proof_type"),
        "quote_role": candidate.get("quote_role"),
        "counter_evidence_count": len(candidate.get("counter_evidence") or []),
        "source": f"{REPORT_BLOCK_CANDIDATE_SOURCE_PREFIX}.{block_name}",
        "rejection_reason": rejection_reason,
    }


def _block_candidate_selection_diagnostics(
    *,
    block_name: str,
    selected: dict[str, Any] | None,
    rejected: list[dict[str, Any]],
    selection_mode: str | None = None,
) -> dict[str, Any]:
    diagnostics = _semantic_case_selection_diagnostics(
        block_name=block_name,
        selected=selected,
        rejected=rejected,
        selection_mode=selection_mode,
    )
    diagnostics["candidate_source"] = "report_evidence.block_candidates"
    return diagnostics


def _build_block_candidate_situation(
    *,
    artifact: ReportArtifact,
    candidate: dict[str, Any],
    score_by_stage: list[dict[str, Any]],
    focus_stage_code: str | None,
) -> dict[str, Any]:
    ref = _artifact_call_reference(artifact)
    stage_code = str(
        candidate.get("stage_code")
        or focus_stage_code
        or _stage_code_from_problem_categories(
            text=_block_candidate_problem_text(candidate),
            score_by_stage=score_by_stage,
        )
        or ""
    ).strip()
    stage_name = _stage_name_for_code(stage_code, score_by_stage)
    turns = _report_block_candidate_turns(candidate)
    quote_text = str(candidate.get("supporting_quote") or "").strip() or _report_evidence_quote_text(turns)
    dialogue_is_partial = bool(turns) and any(turn.get("speaker") == "unknown" for turn in turns)
    source = f"{REPORT_BLOCK_CANDIDATE_SOURCE_PREFIX}.situation_day"
    coaching_view = {
        "pattern_title": str(candidate.get("main_thesis") or "").strip()
        or "Ситуация дня из block_candidates",
        "stage_code": stage_code,
        "stage_label": stage_name,
        "stage_score_label": _report_evidence_stage_score_label(stage_code, score_by_stage),
        "what_happened": str(candidate.get("what_happened") or candidate.get("main_thesis") or "").strip(),
        "meaning": str(candidate.get("why_it_matters") or "").strip(),
        "what_was_missing": str(candidate.get("what_was_missing") or "").strip(),
        "next_time_action": str(candidate.get("better_next_action") or "").strip(),
        "scripts": [
            _first_sentence(str(item or ""), limit=220)
            for item in list(candidate.get("scripts") or [])[:3]
            if str(item or "").strip()
        ],
        "moment_summary": str(candidate.get("main_thesis") or "").strip() or None,
        "missing_action": str(candidate.get("what_was_missing") or "").strip() or None,
        "why_it_matters": str(candidate.get("why_it_matters") or "").strip() or None,
        "supporting_quote": quote_text or None,
        "evidence_type": candidate.get("evidence_type") or candidate.get("proof_type"),
        "confidence": candidate.get("confidence"),
        "gap_claim": candidate.get("gap_claim"),
        "proof_type": candidate.get("proof_type"),
        "proof_explanation": candidate.get("proof_explanation"),
        "quote_role": candidate.get("quote_role"),
        "counter_evidence": candidate.get("counter_evidence") or [],
        "source": source,
        "dialogue_is_partial": dialogue_is_partial,
    }
    return {
        "situation_title": str(candidate.get("main_thesis") or candidate.get("title") or "").strip(),
        "evidence_quote": {
            **ref,
            "client_text": quote_text,
            "manager_text": _manager_text_from_turns(turns),
            "criterion_code": None,
            "stage_code": stage_code,
            "source": source,
            "evidence_quality": candidate.get("evidence_quality"),
            "client_grounded": _client_turn_from_turns(turns) is not None,
            "proof_type": candidate.get("proof_type"),
            "quote_role": candidate.get("quote_role"),
        },
        "dialogue_excerpt": {
            **ref,
            "source": source,
            "is_partial": dialogue_is_partial,
            "partial_reason": "speaker_roles_unavailable" if dialogue_is_partial else None,
            "turns": turns,
        },
        "coaching_view": coaching_view,
    }


def _build_block_candidate_call_breakdown(
    *,
    artifact: ReportArtifact,
    candidate: dict[str, Any],
    score_by_stage: list[dict[str, Any]],
    focus_stage_code: str | None,
) -> dict[str, Any]:
    ref = _artifact_call_reference(artifact)
    stage_code = str(
        candidate.get("stage_code")
        or focus_stage_code
        or _stage_code_from_problem_categories(
            text=_block_candidate_problem_text(candidate),
            score_by_stage=score_by_stage,
        )
        or ""
    ).strip()
    stage_name = _stage_name_for_code(stage_code, score_by_stage)
    source = f"{REPORT_BLOCK_CANDIDATE_SOURCE_PREFIX}.call_breakdown"
    proof_type = str(candidate.get("proof_type") or "").strip() or None
    moments: list[dict[str, Any]] = []
    rows: list[list[str]] = []
    fragment_present = False
    for index, moment in enumerate(candidate.get("_normalized_moments") or [], start=1):
        moment_proof_type = str(moment.get("proof_type") or proof_type or "").strip() or None
        what = _first_sentence(str(moment.get("situation") or ""), limit=220)
        essence = _first_sentence(
            str(moment.get("essence") or moment.get("proof_explanation") or ""),
            limit=260,
        )
        supporting_quote = str(moment.get("supporting_quote") or "").strip() or None
        quote_role = str(moment.get("quote_role") or candidate.get("quote_role") or "").strip() or None
        if supporting_quote:
            fragment_present = True
        moment_cell = essence
        if moment_proof_type == "direct_gap" and supporting_quote:
            moment_cell = supporting_quote
        elif moment_proof_type == "absence_in_context":
            moment_cell = _first_sentence(
                str(moment.get("essence") or candidate.get("what_was_missing") or essence),
                limit=260,
            )
        rows.append(
            [
                f"{index}",
                f"{stage_name}: {what}".strip(),
                moment_cell or supporting_quote or CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE,
                str(moment.get("better_action") or "").strip()
                or "Закрепить следующий шаг конкретной формулировкой.",
            ]
        )
        moments.append(
            {
                "moment": f"Момент {index}",
                "what": f"{stage_name}: {what}".strip(),
                "moment_summary": essence or moment_cell,
                "supporting_quote": supporting_quote,
                "supporting_quote_proof_type": "context_support"
                if quote_role == "supports_context"
                else moment_proof_type,
                "better": str(moment.get("better_action") or "").strip(),
                "proof_type": moment_proof_type,
                "quote_role": quote_role,
                "proof_explanation": moment.get("proof_explanation"),
            }
        )
    first_moment = moments[0] if moments else {}
    first_fragment = str(first_moment.get("supporting_quote") or (rows[0][2] if rows else ""))
    evidence_strength = _call_breakdown_fragment_strength(
        fragment=first_fragment,
        evidence_quality=str(candidate.get("evidence_quality") or ""),
    )
    return {
        "is_placeholder": False,
        "call_id": ref["call_id"],
        "client_label": ref["client_label"],
        "client_phone": ref["client_phone"],
        "date_label": ref["date_label"],
        "time_label": ref["time_label"],
        "client_call_reference": ref["client_call_reference"],
        "stage_code": stage_code,
        "stage_name": stage_name,
        "stage_steps": [],
        "worked": [],
        "to_fix": [],
        "recommendation": None,
        "rows": rows,
        "moments": moments,
        "summary_line": _call_breakdown_summary_line(ref=ref, evidence_strength=evidence_strength),
        "source_note": source,
        "call_breakdown_source": source,
        "call_breakdown_evidence_strength": evidence_strength,
        "call_breakdown_fragment_present": fragment_present,
        "moment_summary": str(candidate.get("main_thesis") or first_moment.get("moment_summary") or "").strip() or None,
        "missing_action": str(candidate.get("what_was_missing") or "").strip() or None,
        "why_it_matters": str(candidate.get("why_it_matters") or "").strip() or None,
        "supporting_quote": str(first_moment.get("supporting_quote") or candidate.get("supporting_quote") or "").strip() or None,
        "evidence_type": candidate.get("evidence_type") or proof_type,
        "confidence": candidate.get("confidence"),
        "proof_type": proof_type,
        "proof_explanation": candidate.get("proof_explanation"),
        "quote_role": candidate.get("quote_role"),
    }


def _build_semantic_case_situation(
    *,
    artifact: ReportArtifact,
    semantic_case: dict[str, Any],
    turns: list[dict[str, str]],
    score_by_stage: list[dict[str, Any]],
    focus_stage_code: str | None,
) -> dict[str, Any]:
    """Build Situation Day from one coherent validated semantic_case."""
    ref = _artifact_call_reference(artifact)
    stage_code = _semantic_case_stage_code(
        semantic_case=semantic_case,
        focus_stage_code=focus_stage_code,
    )
    stage_name = _stage_name_for_code(stage_code, score_by_stage)
    coaching_moment = (
        _semantic_case_coaching_moment(semantic_case, block_name="situation_day")
        or {}
    )
    quote_text = _semantic_case_supporting_quote(
        semantic_case=semantic_case,
        turns=turns,
        block_name="situation_day",
    ) or ""
    dialogue_is_partial = any(turn.get("speaker") == "unknown" for turn in turns)
    client_grounded = _client_turn_from_turns(turns) is not None
    moment_summary = str(coaching_moment.get("moment_summary") or "").strip()
    missing_action = str(coaching_moment.get("missing_action") or "").strip()
    why_it_matters = (
        str(coaching_moment.get("why_it_matters") or "").strip()
        if coaching_moment.get("has_explicit_coaching_moment")
        else ""
    )
    coaching_view = {
        "pattern_title": _first_sentence(str(semantic_case.get("case_title") or ""), limit=180)
        or "Ситуация дня из semantic_case",
        "stage_code": stage_code,
        "stage_label": stage_name,
        "stage_score_label": _report_evidence_stage_score_label(stage_code, score_by_stage),
        "what_happened": moment_summary
        or _first_sentence(str(semantic_case.get("manager_behavior") or ""), limit=260),
        "meaning": _first_sentence(
            str(
                why_it_matters
                or semantic_case.get("core_meaning")
                or semantic_case.get("why_this_call_matters")
                or ""
            ),
            limit=260,
        ),
        "what_was_missing": missing_action
        or _first_sentence(str(semantic_case.get("coaching_diagnosis") or ""), limit=260),
        "next_time_action": _first_sentence(
            str(semantic_case.get("recommended_next_action") or ""),
            limit=260,
        ),
        "scripts": _semantic_case_scripts(semantic_case=semantic_case, stage_code=stage_code),
        "moment_summary": moment_summary or None,
        "missing_action": missing_action or None,
        "why_it_matters": why_it_matters or None,
        "supporting_quote": quote_text or None,
        "evidence_type": coaching_moment.get("evidence_type")
        or _semantic_case_block_fit_value(semantic_case, "situation_day", "evidence_type"),
        "confidence": coaching_moment.get("confidence"),
        "gap_claim": coaching_moment.get("gap_claim"),
        "proof_type": coaching_moment.get("proof_type"),
        "proof_explanation": coaching_moment.get("proof_explanation"),
        "quote_role": coaching_moment.get("quote_role"),
        "counter_evidence": coaching_moment.get("counter_evidence") or [],
        "source": "report_evidence.semantic_case",
        "dialogue_is_partial": dialogue_is_partial,
    }
    return {
        "situation_title": str(semantic_case.get("case_title") or "").strip(),
        "evidence_quote": {
            **ref,
            "client_text": quote_text,
            "manager_text": _manager_text_from_turns(turns),
            "criterion_code": None,
            "stage_code": stage_code,
            "source": "report_evidence.semantic_case",
            "evidence_quality": semantic_case.get("evidence_quality"),
            "client_grounded": client_grounded,
            "quote_role": coaching_moment.get("quote_role"),
        },
        "dialogue_excerpt": {
            **ref,
            "source": "report_evidence.semantic_case",
            "is_partial": dialogue_is_partial,
            "partial_reason": "speaker_roles_unavailable" if dialogue_is_partial else None,
            "turns": turns,
        },
        "coaching_view": coaching_view,
    }


def _build_report_evidence_situation(
    *,
    artifacts: list[ReportArtifact],
    report_evidence_index: dict[str, dict[str, Any]],
    call_list_by_interaction_id: dict[str, dict[str, Any]],
    score_by_stage: list[dict[str, Any]],
    daily_focus: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build Situation Day from block_candidates first, then semantic_case and legacy arrays."""
    block_candidates: list[tuple[tuple[Any, ...], ReportArtifact, dict[str, Any]]] = []
    block_relaxed_candidates: list[tuple[tuple[Any, ...], ReportArtifact, dict[str, Any]]] = []
    block_rejections: list[dict[str, Any]] = []
    block_relaxed_rejections: list[dict[str, Any]] = []
    semantic_candidates: list[tuple[tuple[Any, ...], ReportArtifact, dict[str, Any], list[dict[str, str]]]] = []
    semantic_relaxed_candidates: list[
        tuple[tuple[Any, ...], ReportArtifact, dict[str, Any], list[dict[str, str]]]
    ] = []
    semantic_rejections: list[dict[str, Any]] = []
    semantic_relaxed_rejections: list[dict[str, Any]] = []
    candidates: list[tuple[tuple[int, int, int, int, float, datetime], ReportArtifact, dict[str, Any], dict[str, Any], list[dict[str, str]]]] = []
    focus_stage_code = _daily_focus_stage_code(daily_focus)
    for artifact in artifacts:
        if not _is_report_evidence_sales_like(
            artifact=artifact,
            call_list_by_interaction_id=call_list_by_interaction_id,
        ):
            continue
        evidence = _valid_report_evidence_for_artifact(
            artifact=artifact,
            report_evidence_index=report_evidence_index,
        )
        if evidence is None:
            continue
        block_candidate = _valid_block_candidate_from_evidence(evidence, "situation_day")
        if block_candidate is not None:
            rejection_reason = _block_candidate_rejection_reason(
                candidate=block_candidate,
                block_name="situation_day",
                focus_stage_code=focus_stage_code,
                daily_focus=daily_focus,
            )
            if rejection_reason:
                block_rejections.append(
                    _block_candidate_diagnostic(
                        artifact=artifact,
                        candidate=block_candidate,
                        block_name="situation_day",
                        rejection_reason=rejection_reason,
                    )
                )
                if rejection_reason in {"stage_mismatch", "problem_signal_mismatch"}:
                    relaxed_rejection_reason = _block_candidate_rejection_reason(
                        candidate=block_candidate,
                        block_name="situation_day",
                        focus_stage_code=None,
                        daily_focus=None,
                    )
                    if relaxed_rejection_reason:
                        block_relaxed_rejections.append(
                            _block_candidate_diagnostic(
                                artifact=artifact,
                                candidate=block_candidate,
                                block_name="situation_day",
                                rejection_reason=relaxed_rejection_reason,
                            )
                        )
                    else:
                        block_relaxed_candidates.append(
                            (
                                _block_candidate_rank(
                                    candidate=block_candidate,
                                    block_name="situation_day",
                                    score_by_stage=score_by_stage,
                                    artifact=artifact,
                                ),
                                artifact,
                                block_candidate,
                            )
                        )
            else:
                block_candidates.append(
                    (
                        _block_candidate_rank(
                            candidate=block_candidate,
                            block_name="situation_day",
                            score_by_stage=score_by_stage,
                            artifact=artifact,
                        ),
                        artifact,
                        block_candidate,
                    )
                )
        semantic_case = _valid_semantic_case_from_evidence(evidence)
        if semantic_case is not None:
            turns = _semantic_case_turns(semantic_case)
            rejection_reason = _semantic_case_block_rejection_reason(
                semantic_case=semantic_case,
                turns=turns,
                block_name="situation_day",
                focus_stage_code=focus_stage_code,
                daily_focus=daily_focus,
            )
            if rejection_reason:
                semantic_rejections.append(
                    _semantic_case_candidate_diagnostic(
                        artifact=artifact,
                        semantic_case=semantic_case,
                        block_name="situation_day",
                        rejection_reason=rejection_reason,
                    )
                )
                if rejection_reason in {"stage_mismatch", "problem_signal_mismatch"}:
                    relaxed_rejection_reason = _semantic_case_block_rejection_reason(
                        semantic_case=semantic_case,
                        turns=turns,
                        block_name="situation_day",
                        focus_stage_code=None,
                        daily_focus=None,
                    )
                    if relaxed_rejection_reason:
                        semantic_relaxed_rejections.append(
                            _semantic_case_candidate_diagnostic(
                                artifact=artifact,
                                semantic_case=semantic_case,
                                block_name="situation_day",
                                rejection_reason=relaxed_rejection_reason,
                            )
                        )
                    else:
                        semantic_relaxed_candidates.append(
                            (
                                _semantic_case_situation_rank(
                                    semantic_case=semantic_case,
                                    score_by_stage=score_by_stage,
                                    artifact=artifact,
                                ),
                                artifact,
                                semantic_case,
                                turns,
                            )
                        )
            else:
                semantic_candidates.append(
                    (
                        _semantic_case_situation_rank(
                            semantic_case=semantic_case,
                            score_by_stage=score_by_stage,
                            artifact=artifact,
                        ),
                        artifact,
                        semantic_case,
                        turns,
                    )
                )
        for candidate in evidence.get("situation_candidates") or []:
            if not isinstance(candidate, dict) or candidate.get("usable_in_report") is not True:
                continue
            if focus_stage_code and str(candidate.get("stage_code") or "").strip() != focus_stage_code:
                continue
            quality = str(candidate.get("evidence_quality") or "").strip().lower()
            if quality not in REPORT_EVIDENCE_USABLE_QUALITIES:
                continue
            turns = _report_evidence_turns(candidate)
            if not turns:
                continue
            candidates.append(
                (
                    _report_evidence_situation_candidate_rank(
                        candidate=candidate,
                        turns=turns,
                        evidence=evidence,
                        score_by_stage=score_by_stage,
                        artifact=artifact,
                    ),
                    artifact,
                    evidence,
                    candidate,
                    turns,
                )
            )
    selected_block_candidates = block_candidates
    block_selection_mode = "daily_focus"
    block_build_focus_stage_code = focus_stage_code
    if not selected_block_candidates and block_relaxed_candidates:
        selected_block_candidates = block_relaxed_candidates
        block_selection_mode = "best_block_candidate_after_focus_mismatch"
        block_build_focus_stage_code = None
    if selected_block_candidates:
        selected_block_candidates.sort(key=lambda item: item[0])
        verification_rejections: list[dict[str, Any]] = []
        for _rank, artifact, candidate in selected_block_candidates:
            result = _build_block_candidate_situation(
                artifact=artifact,
                candidate=candidate,
                score_by_stage=score_by_stage,
                focus_stage_code=block_build_focus_stage_code,
            )
            verified_result, rejection_reason = _verified_situation_day_result(
                artifacts=artifacts,
                result=result,
            )
            if verified_result is not None:
                verified_result["selection_diagnostics"] = _block_candidate_selection_diagnostics(
                    block_name="situation_day",
                    selected=_block_candidate_diagnostic(
                        artifact=artifact,
                        candidate=candidate,
                        block_name="situation_day",
                        rejection_reason=None,
                    ),
                    rejected=block_rejections + block_relaxed_rejections + verification_rejections,
                    selection_mode=block_selection_mode,
                )
                verified_result.setdefault("coaching_view", {})["selection_diagnostics"] = (
                    verified_result["selection_diagnostics"]
                )
                return verified_result
            verification_rejections.append(
                _block_candidate_diagnostic(
                    artifact=artifact,
                    candidate=candidate,
                    block_name="situation_day",
                    rejection_reason=rejection_reason or "situation_day_not_verified",
                )
            )
        block_rejections.extend(verification_rejections)

    selected_semantic_candidates = semantic_candidates
    semantic_selection_mode = "daily_focus"
    semantic_build_focus_stage_code = focus_stage_code
    if not selected_semantic_candidates and semantic_relaxed_candidates:
        selected_semantic_candidates = semantic_relaxed_candidates
        semantic_selection_mode = "best_semantic_case_after_focus_mismatch"
        semantic_build_focus_stage_code = None
    if selected_semantic_candidates:
        selected_semantic_candidates.sort(key=lambda item: item[0])
        verification_rejections = []
        for _rank, artifact, semantic_case, turns in selected_semantic_candidates:
            result = _build_semantic_case_situation(
                artifact=artifact,
                semantic_case=semantic_case,
                turns=turns,
                score_by_stage=score_by_stage,
                focus_stage_code=semantic_build_focus_stage_code,
            )
            verified_result, rejection_reason = _verified_situation_day_result(
                artifacts=artifacts,
                result=result,
            )
            if verified_result is not None:
                verified_result["selection_diagnostics"] = _semantic_case_selection_diagnostics(
                    block_name="situation_day",
                    selected=_semantic_case_candidate_diagnostic(
                        artifact=artifact,
                        semantic_case=semantic_case,
                        block_name="situation_day",
                        rejection_reason=None,
                    ),
                    rejected=semantic_rejections + semantic_relaxed_rejections + verification_rejections,
                    selection_mode=semantic_selection_mode,
                )
                verified_result.setdefault("coaching_view", {})["selection_diagnostics"] = (
                    verified_result["selection_diagnostics"]
                )
                return verified_result
            verification_rejections.append(
                _semantic_case_candidate_diagnostic(
                    artifact=artifact,
                    semantic_case=semantic_case,
                    block_name="situation_day",
                    rejection_reason=rejection_reason or "situation_day_not_verified",
                )
            )
        semantic_rejections.extend(verification_rejections)
    if block_rejections or semantic_rejections or block_relaxed_rejections or semantic_relaxed_rejections:
        return _no_verified_situation_day_result(
            reason="no_verified_situation_day_candidate",
            rejected=(
                block_rejections
                + block_relaxed_rejections
                + semantic_rejections
                + semantic_relaxed_rejections
            ),
            selection_mode="all_candidates_failed_verification",
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    _rank, artifact, evidence, candidate, turns = candidates[0]
    ref = _artifact_call_reference(artifact)
    stage_code = str(candidate.get("stage_code") or "").strip()
    stage_name = _stage_name_for_code(stage_code, score_by_stage)
    quote_text = _report_evidence_quote_text(turns)
    dialogue_turns = turns
    dialogue_source = "report_evidence.situation_candidates"
    dialogue_partial_reason = None
    coaching_view_source = "report_evidence"
    coaching_view: dict[str, Any] | None = None
    selected_client_quote: dict[str, Any] | None = None
    if _situation_requires_client_signal(candidate) and _client_turn_from_turns(turns) is None:
        selected_client_quote, _relevance = _select_client_grounded_situation_quote(
            evidence=evidence,
            candidate=candidate,
        )
        if selected_client_quote is not None:
            quote_text = str(selected_client_quote.get("quote") or "").strip()
            dialogue_turns = [{"speaker": "client", "text": quote_text}]
            dialogue_source = f"report_evidence.{selected_client_quote.get('source_key')}"
            dialogue_partial_reason = "client_quote_without_adjacent_manager_turn"
            coaching_view = _client_grounded_situation_coaching_view(
                candidate=candidate,
                quote=quote_text,
                stage_code=stage_code,
                stage_name=stage_name,
                score_by_stage=score_by_stage,
            )
            coaching_view_source = "report_evidence.client_grounded_situation"
    dialogue_is_partial = any(turn.get("speaker") == "unknown" for turn in dialogue_turns) or bool(dialogue_partial_reason)
    if coaching_view is None:
        normalized_title = _normalize_problem_statement(
            candidate.get("situation_title"),
            stage_code=stage_code,
            fallback=_stage_problem_fallback(stage_code),
        )
        normalized_what_happened = _normalize_problem_statement(
            candidate.get("what_happened"),
            stage_code=stage_code,
            fallback=_stage_problem_fallback(stage_code),
        )
        coaching_view = {
            "pattern_title": str(normalized_title.get("text") or "").strip()
            or "Ситуация дня из report_evidence",
            "stage_code": stage_code,
            "stage_label": stage_name,
            "stage_score_label": _report_evidence_stage_score_label(stage_code, score_by_stage),
            "what_happened": _first_sentence(str(normalized_what_happened.get("text") or ""), limit=260),
            "meaning": _first_sentence(str(candidate.get("what_it_means") or ""), limit=260),
            "what_was_missing": _first_sentence(str(candidate.get("what_was_missing") or ""), limit=260),
            "next_time_action": _first_sentence(str(candidate.get("next_time_action") or ""), limit=260),
            "scripts": [
                _first_sentence(str(item or ""), limit=220)
                for item in list(candidate.get("scripts") or [])[:3]
                if str(item or "").strip()
            ],
            "source": coaching_view_source,
            "dialogue_is_partial": dialogue_is_partial,
        }
    return {
        "situation_title": str(candidate.get("situation_title") or "").strip(),
        "evidence_quote": {
            **ref,
            "client_text": quote_text,
            "manager_text": _manager_text_from_turns(turns),
            "criterion_code": None,
            "stage_code": stage_code,
            "source": "report_evidence.client_grounded_situation"
            if selected_client_quote is not None
            else "report_evidence.situation_candidates",
            "evidence_quality": "direct" if selected_client_quote is not None else candidate.get("evidence_quality"),
            "client_grounded": selected_client_quote is not None or _client_turn_from_turns(turns) is not None,
        },
        "dialogue_excerpt": {
            **ref,
            "source": dialogue_source,
            "is_partial": dialogue_is_partial,
            "partial_reason": dialogue_partial_reason or ("speaker_roles_unavailable" if dialogue_is_partial else None),
            "turns": dialogue_turns,
        },
        "coaching_view": coaching_view,
    }


def _build_call_breakdown_from_report_evidence(
    *,
    artifacts: list[ReportArtifact],
    report_evidence_index: dict[str, dict[str, Any]],
    call_list_by_interaction_id: dict[str, dict[str, Any]],
    score_by_stage: list[dict[str, Any]],
    daily_focus: dict[str, Any] | None = None,
    excluded_call_ids: set[str] | None = None,
    preferred_call_id: str | None = None,
) -> dict[str, Any] | None:
    """Build РАЗБОР ЗВОНКА from block_candidates first, then semantic_case and moments."""
    excluded_call_ids = {str(item).strip() for item in (excluded_call_ids or set()) if str(item).strip()}
    preferred_call_id = str(preferred_call_id or "").strip() or None
    block_candidates: list[
        tuple[
            tuple[Any, ...],
            ReportArtifact,
            dict[str, Any],
        ]
    ] = []
    block_relaxed_candidates: list[
        tuple[
            tuple[Any, ...],
            ReportArtifact,
            dict[str, Any],
        ]
    ] = []
    block_rejections: list[dict[str, Any]] = []
    block_relaxed_rejections: list[dict[str, Any]] = []
    semantic_candidates: list[
        tuple[
            tuple[Any, ...],
            ReportArtifact,
            dict[str, Any],
            list[dict[str, str]],
            str | None,
            str,
        ]
    ] = []
    semantic_relaxed_candidates: list[
        tuple[
            tuple[Any, ...],
            ReportArtifact,
            dict[str, Any],
            list[dict[str, str]],
            str | None,
            str,
        ]
    ] = []
    semantic_rejections: list[dict[str, Any]] = []
    semantic_relaxed_rejections: list[dict[str, Any]] = []
    candidates: list[
        tuple[
            tuple[int, int, int, int, float, datetime],
            ReportArtifact,
            dict[str, Any],
            list[dict[str, str]],
            str | None,
            str,
        ]
    ] = []
    focus_stage_code = _daily_focus_stage_code(daily_focus)
    for artifact in artifacts:
        artifact_call_id = str(artifact.interaction.id)
        if artifact_call_id in excluded_call_ids:
            continue
        if not _is_report_evidence_sales_like(
            artifact=artifact,
            call_list_by_interaction_id=call_list_by_interaction_id,
        ):
            continue
        evidence = _valid_report_evidence_for_artifact(
            artifact=artifact,
            report_evidence_index=report_evidence_index,
        )
        if evidence is None:
            continue
        block_candidate = _valid_block_candidate_from_evidence(evidence, "call_breakdown")
        if block_candidate is not None:
            rejection_reason = _block_candidate_rejection_reason(
                candidate=block_candidate,
                block_name="call_breakdown",
                focus_stage_code=focus_stage_code,
                daily_focus=daily_focus,
            )
            if rejection_reason:
                block_rejections.append(
                    _block_candidate_diagnostic(
                        artifact=artifact,
                        candidate=block_candidate,
                        block_name="call_breakdown",
                        rejection_reason=rejection_reason,
                    )
                )
                if rejection_reason in {"stage_mismatch", "problem_signal_mismatch"}:
                    relaxed_rejection_reason = _block_candidate_rejection_reason(
                        candidate=block_candidate,
                        block_name="call_breakdown",
                        focus_stage_code=None,
                        daily_focus=None,
                    )
                    if relaxed_rejection_reason:
                        block_relaxed_rejections.append(
                            _block_candidate_diagnostic(
                                artifact=artifact,
                                candidate=block_candidate,
                                block_name="call_breakdown",
                                rejection_reason=relaxed_rejection_reason,
                            )
                        )
                    else:
                        block_relaxed_candidates.append(
                            (
                                _block_candidate_rank(
                                    candidate=block_candidate,
                                    block_name="call_breakdown",
                                    score_by_stage=score_by_stage,
                                    artifact=artifact,
                                ),
                                artifact,
                                block_candidate,
                            )
                        )
            else:
                block_candidates.append(
                    (
                        _block_candidate_rank(
                            candidate=block_candidate,
                            block_name="call_breakdown",
                            score_by_stage=score_by_stage,
                            artifact=artifact,
                        ),
                        artifact,
                        block_candidate,
                    )
                )
        semantic_case = _valid_semantic_case_from_evidence(evidence)
        if semantic_case is not None:
            turns = _semantic_case_turns(semantic_case)
            rejection_reason = _semantic_case_block_rejection_reason(
                semantic_case=semantic_case,
                turns=turns,
                block_name="call_breakdown",
                focus_stage_code=focus_stage_code,
                daily_focus=daily_focus,
            )
            if rejection_reason:
                semantic_rejections.append(
                    _semantic_case_candidate_diagnostic(
                        artifact=artifact,
                        semantic_case=semantic_case,
                        block_name="call_breakdown",
                        rejection_reason=rejection_reason,
                    )
                )
                if rejection_reason in {"stage_mismatch", "problem_signal_mismatch"}:
                    relaxed_rejection_reason = _semantic_case_block_rejection_reason(
                        semantic_case=semantic_case,
                        turns=turns,
                        block_name="call_breakdown",
                        focus_stage_code=None,
                        daily_focus=None,
                    )
                    if relaxed_rejection_reason:
                        semantic_relaxed_rejections.append(
                            _semantic_case_candidate_diagnostic(
                                artifact=artifact,
                                semantic_case=semantic_case,
                                block_name="call_breakdown",
                                rejection_reason=relaxed_rejection_reason,
                            )
                        )
                    else:
                        fragment = _semantic_case_supporting_quote(
                            semantic_case=semantic_case,
                            turns=turns,
                            block_name="call_breakdown",
                        )
                        evidence_strength = _call_breakdown_fragment_strength(
                            fragment=fragment,
                            evidence_quality=str(semantic_case.get("evidence_quality") or ""),
                        )
                        fit_score = _semantic_case_block_fit_score(semantic_case, "call_breakdown")
                        problem_fit_score = _semantic_case_problem_fit_score(semantic_case, "call_breakdown")
                        block_role = _semantic_case_block_fit_value(
                            semantic_case,
                            "call_breakdown",
                            "block_role",
                        )
                        title_mode = _semantic_case_block_fit_value(
                            semantic_case,
                            "call_breakdown",
                            "title_mode",
                        )
                        semantic_relaxed_candidates.append(
                            (
                                (
                                    CALL_BREAKDOWN_EVIDENCE_STRENGTH_RANK.get(evidence_strength, 9),
                                    (
                                        0
                                        if block_role == "coaching_problem"
                                        else 1
                                        if block_role == "strong_practice"
                                        else 2
                                    ),
                                    0 if title_mode == "problem" else 1 if title_mode is None else 5,
                                    100 - (problem_fit_score if problem_fit_score is not None else 60),
                                    100 - (fit_score if fit_score is not None else 60),
                                    *_report_evidence_candidate_rank(
                                        candidate=semantic_case,
                                        score_by_stage=score_by_stage,
                                        artifact=artifact,
                                    ),
                                ),
                                artifact,
                                semantic_case,
                                turns,
                                fragment,
                                evidence_strength,
                            )
                        )
                continue
            fragment = _semantic_case_supporting_quote(
                semantic_case=semantic_case,
                turns=turns,
                block_name="call_breakdown",
            )
            evidence_strength = _call_breakdown_fragment_strength(
                fragment=fragment,
                evidence_quality=str(semantic_case.get("evidence_quality") or ""),
            )
            fit_score = _semantic_case_block_fit_score(semantic_case, "call_breakdown")
            problem_fit_score = _semantic_case_problem_fit_score(semantic_case, "call_breakdown")
            block_role = _semantic_case_block_fit_value(
                semantic_case,
                "call_breakdown",
                "block_role",
            )
            title_mode = _semantic_case_block_fit_value(
                semantic_case,
                "call_breakdown",
                "title_mode",
            )
            semantic_candidates.append(
                (
                    (
                        CALL_BREAKDOWN_EVIDENCE_STRENGTH_RANK.get(evidence_strength, 9),
                        (
                            0
                            if block_role == "coaching_problem"
                            else 1
                            if block_role == "strong_practice"
                            else 2
                        ),
                        0 if title_mode == "problem" else 1 if title_mode is None else 5,
                        100 - (problem_fit_score if problem_fit_score is not None else 60),
                        100 - (fit_score if fit_score is not None else 60),
                        *_report_evidence_candidate_rank(
                            candidate=semantic_case,
                            score_by_stage=score_by_stage,
                            artifact=artifact,
                        ),
                    ),
                    artifact,
                    semantic_case,
                    turns,
                    fragment,
                    evidence_strength,
                )
            )
        for moment in evidence.get("manager_coaching_moments") or []:
            if not isinstance(moment, dict) or moment.get("usable_in_report") is not True:
                continue
            if focus_stage_code and str(moment.get("stage_code") or "").strip() != focus_stage_code:
                continue
            quality = str(moment.get("evidence_quality") or "").strip().lower()
            if quality not in REPORT_EVIDENCE_USABLE_QUALITIES:
                continue
            turns = _report_evidence_turns(moment)
            fragment = _call_breakdown_fragment_from_turns(turns)
            evidence_strength = _call_breakdown_fragment_strength(
                fragment=fragment,
                evidence_quality=quality,
            )
            candidates.append(
                (
                    (
                        CALL_BREAKDOWN_EVIDENCE_STRENGTH_RANK.get(evidence_strength, 9),
                        *_report_evidence_candidate_rank(
                            candidate=moment,
                            score_by_stage=score_by_stage,
                            artifact=artifact,
                        ),
                    ),
                    artifact,
                    moment,
                    turns,
                    fragment,
                    evidence_strength,
                )
            )
    selected_block_candidates = block_candidates
    block_selection_mode = "daily_focus"
    block_build_focus_stage_code = focus_stage_code
    if not selected_block_candidates and block_relaxed_candidates:
        selected_block_candidates = block_relaxed_candidates
        block_selection_mode = "best_block_candidate_after_focus_mismatch"
        block_build_focus_stage_code = None
    if preferred_call_id:
        preferred_block_candidates = [
            item
            for item in selected_block_candidates
            if str(item[1].interaction.id) == preferred_call_id
        ]
        if preferred_block_candidates:
            selected_block_candidates = preferred_block_candidates
            block_selection_mode = f"{block_selection_mode}_preferred_situation_call"
    if selected_block_candidates:
        selected_block_candidates.sort(key=lambda item: item[0])
        _rank, best_artifact, best_candidate = selected_block_candidates[0]
        result = _build_block_candidate_call_breakdown(
            artifact=best_artifact,
            candidate=best_candidate,
            score_by_stage=score_by_stage,
            focus_stage_code=block_build_focus_stage_code,
        )
        result["selection_diagnostics"] = _block_candidate_selection_diagnostics(
            block_name="call_breakdown",
            selected=_block_candidate_diagnostic(
                artifact=best_artifact,
                candidate=best_candidate,
                block_name="call_breakdown",
                rejection_reason=None,
            ),
            rejected=block_rejections + block_relaxed_rejections,
            selection_mode=block_selection_mode,
        )
        return result

    selected_semantic_candidates = semantic_candidates
    semantic_selection_mode = "daily_focus"
    semantic_build_focus_stage_code = focus_stage_code
    if not selected_semantic_candidates and semantic_relaxed_candidates:
        selected_semantic_candidates = semantic_relaxed_candidates
        semantic_selection_mode = "best_semantic_case_after_focus_mismatch"
        semantic_build_focus_stage_code = None
    if preferred_call_id:
        preferred_semantic_candidates = [
            item
            for item in selected_semantic_candidates
            if str(item[1].interaction.id) == preferred_call_id
        ]
        if preferred_semantic_candidates:
            selected_semantic_candidates = preferred_semantic_candidates
            semantic_selection_mode = f"{semantic_selection_mode}_preferred_situation_call"
    if selected_semantic_candidates:
        selected_semantic_candidates.sort(key=lambda item: item[0])
        _rank, best_artifact, best_case, _turns, fragment, best_strength = selected_semantic_candidates[0]
        ref = _artifact_call_reference(best_artifact)
        stage_code = _semantic_case_stage_code(
            semantic_case=best_case,
            focus_stage_code=semantic_build_focus_stage_code,
        )
        stage_name = _stage_name_for_code(stage_code, score_by_stage)
        coaching_moment = (
            _semantic_case_coaching_moment(best_case, block_name="call_breakdown")
            or {}
        )
        moment_summary = str(coaching_moment.get("moment_summary") or "").strip()
        missing_action = str(coaching_moment.get("missing_action") or "").strip()
        why_it_matters = str(coaching_moment.get("why_it_matters") or "").strip()
        what = _first_sentence(
            str(
                moment_summary
                or best_case.get("manager_behavior")
                or best_case.get("core_meaning")
                or ""
            ),
            limit=220,
        )
        better = _first_sentence(str(best_case.get("recommended_next_action") or ""), limit=240)
        result = {
            "is_placeholder": False,
            "call_id": ref["call_id"],
            "client_label": ref["client_label"],
            "client_phone": ref["client_phone"],
            "date_label": ref["date_label"],
            "time_label": ref["time_label"],
            "client_call_reference": ref["client_call_reference"],
            "stage_code": stage_code,
            "stage_name": stage_name,
            "stage_steps": [],
            "worked": [],
            "to_fix": [],
            "recommendation": None,
            "rows": [
                [
                    "1",
                    f"{stage_name}: {what}".strip(),
                    fragment or CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE,
                    better or "Закрепить следующий шаг конкретной формулировкой.",
                ]
            ],
            "summary_line": _call_breakdown_summary_line(ref=ref, evidence_strength=best_strength),
            "source_note": "report_evidence.semantic_case",
            "call_breakdown_source": "report_evidence.semantic_case",
            "call_breakdown_evidence_strength": best_strength,
            "call_breakdown_fragment_present": fragment is not None,
            "moment_summary": moment_summary or None,
            "missing_action": missing_action or None,
            "why_it_matters": why_it_matters or None,
            "supporting_quote": fragment,
            "evidence_type": coaching_moment.get("evidence_type")
            or _semantic_case_block_fit_value(best_case, "call_breakdown", "evidence_type"),
            "confidence": coaching_moment.get("confidence"),
        }
        result["selection_diagnostics"] = _semantic_case_selection_diagnostics(
            block_name="call_breakdown",
            selected=_semantic_case_candidate_diagnostic(
                artifact=best_artifact,
                semantic_case=best_case,
                block_name="call_breakdown",
                rejection_reason=None,
            ),
            rejected=semantic_rejections + semantic_relaxed_rejections,
            selection_mode=semantic_selection_mode,
        )
        return result
    if not candidates:
        return None
    if preferred_call_id:
        preferred_candidates = [
            item
            for item in candidates
            if str(item[1].interaction.id) == preferred_call_id
        ]
        if preferred_candidates:
            candidates = preferred_candidates
    candidates.sort(key=lambda item: item[0])
    _rank, best_artifact, best_moment, _turns, _best_fragment, best_strength = candidates[0]
    best_candidates = [
        (rank, moment, turns, fragment, strength)
        for rank, artifact, moment, turns, fragment, strength in candidates
        if str(artifact.interaction.id) == str(best_artifact.interaction.id)
    ]
    best_candidates.sort(key=lambda item: item[0])
    rows: list[list[str]] = []
    fragment_present = False
    for index, (_moment_rank, moment, _turns, fragment, _strength) in enumerate(
        best_candidates[:3],
        start=1,
    ):
        moment_stage_code = str(moment.get("stage_code") or "").strip()
        stage_name = _stage_name_for_code(moment_stage_code, score_by_stage)
        if fragment:
            fragment_present = True
        normalized_what = _normalize_problem_statement(
            moment.get("what_happened"),
            stage_code=moment_stage_code,
            fallback=_stage_problem_fallback(moment_stage_code),
        )
        what = _first_sentence(str(normalized_what.get("text") or ""), limit=220)
        better = _first_sentence(str(moment.get("what_better") or ""), limit=240)
        rows.append(
            [
                f"{index}",
                f"{stage_name}: {what}".strip(),
                fragment or CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE,
                better or "Закрепить следующий шаг конкретной формулировкой.",
            ]
        )
    if not rows:
        return None
    ref = _artifact_call_reference(best_artifact)
    best_moment_summary = _first_sentence(
        str(best_moment.get("moment_summary") or best_moment.get("what_happened") or ""),
        limit=260,
    )
    best_missing_action = _first_sentence(
        str(best_moment.get("missing_action") or best_moment.get("what_better") or ""),
        limit=260,
    )
    best_why_it_matters = _first_sentence(str(best_moment.get("why_it_matters") or ""), limit=260)
    return {
        "is_placeholder": False,
        "call_id": ref["call_id"],
        "client_label": ref["client_label"],
        "client_phone": ref["client_phone"],
        "date_label": ref["date_label"],
        "time_label": ref["time_label"],
        "client_call_reference": ref["client_call_reference"],
        "stage_code": str(best_moment.get("stage_code") or "").strip(),
        "stage_name": _stage_name_for_code(
            str(best_moment.get("stage_code") or ""),
            score_by_stage,
        ),
        "stage_steps": [],
        "worked": [],
        "to_fix": [],
        "recommendation": None,
        "rows": rows,
        "summary_line": _call_breakdown_summary_line(ref=ref, evidence_strength=best_strength),
        "source_note": "report_evidence.manager_coaching_moments",
        "call_breakdown_source": "report_evidence.manager_coaching_moments",
        "call_breakdown_evidence_strength": best_strength,
        "call_breakdown_fragment_present": fragment_present,
        "moment_summary": best_moment_summary or None,
        "missing_action": best_missing_action or None,
        "why_it_matters": best_why_it_matters or None,
        "supporting_quote": _best_fragment,
        "evidence_type": best_moment.get("evidence_type"),
        "confidence": best_moment.get("confidence"),
    }


def _build_voice_of_customer_from_report_evidence(
    *,
    artifacts: list[ReportArtifact],
    report_evidence_index: dict[str, dict[str, Any]],
    call_list_by_interaction_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Build Голос клиента from semantic_case first, then voice_of_customer candidates."""
    rows: list[tuple[tuple[int, int, int, datetime], dict[str, Any]]] = []
    seen: set[str] = set()
    signal_rank = {"high": 0, "medium": 1, "low": 2}
    semantic_used = False
    semantic_rejections: list[dict[str, Any]] = []
    semantic_selections: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not _is_report_evidence_sales_like(
            artifact=artifact,
            call_list_by_interaction_id=call_list_by_interaction_id,
        ):
            continue
        evidence = _valid_report_evidence_for_artifact(
            artifact=artifact,
            report_evidence_index=report_evidence_index,
        )
        if evidence is None:
            continue
        summary, _summary_evidence = _valid_call_report_summary_for_interaction(
            interaction_id=str(artifact.interaction.id),
            report_evidence_index=report_evidence_index,
        )
        summary_action = _summary_text((summary or {}).get("manager_next_action"), limit=220)
        ref = _artifact_call_reference(artifact)
        semantic_case = _valid_semantic_case_from_evidence(evidence)
        if semantic_case is not None:
            semantic_turns = _semantic_case_turns(semantic_case)
            rejection_reason = _semantic_case_block_rejection_reason(
                semantic_case=semantic_case,
                turns=semantic_turns,
                block_name="voice_of_customer",
                focus_stage_code=None,
            )
            if rejection_reason:
                semantic_rejections.append(
                    _semantic_case_candidate_diagnostic(
                        artifact=artifact,
                        semantic_case=semantic_case,
                        block_name="voice_of_customer",
                        rejection_reason=rejection_reason,
                    )
                )
                semantic_turns = []
            semantic_turn = next(
                (
                    turn
                    for turn in semantic_turns
                    if turn.get("speaker") in {"client", "unknown"} and str(turn.get("text") or "").strip()
                ),
                None,
            )
            quote = _dialogue_turn_text(str((semantic_turn or {}).get("text") or ""), limit=180)
            if len(quote) >= 5 and quote not in seen:
                seen.add(quote)
                semantic_used = True
                semantic_selections.append(
                    _semantic_case_candidate_diagnostic(
                        artifact=artifact,
                        semantic_case=semantic_case,
                        block_name="voice_of_customer",
                        rejection_reason=None,
                    )
                )
                meaning = _first_sentence(
                    str(
                        semantic_case.get("customer_signal")
                        or semantic_case.get("core_meaning")
                        or semantic_case.get("why_this_call_matters")
                        or ""
                    ),
                    limit=180,
                )
                category = _voice_customer_signal_category(
                    quote=quote,
                    meaning=meaning,
                    context=semantic_case.get("core_meaning"),
                )
                semantic_action = _summary_text(semantic_case.get("recommended_next_action"), limit=220)
                if _voice_customer_summary_action_specific(semantic_action, category=category):
                    action = semantic_action
                    action_source = "semantic_case.recommended_next_action"
                elif category is not None:
                    action = VOICE_CUSTOMER_SIGNAL_ACTIONS[category]
                    action_source = "deterministic_customer_signal"
                else:
                    action = None
                    action_source = None
                context = _voice_customer_context_with_action(meaning=meaning, action=action)
                context_value = context[:257].rstrip() + "…" if context and len(context) > 260 else context
                quote_context = _voice_customer_contextual_quote(
                    artifact=artifact,
                    quote=quote,
                )
                rows.append(
                    (
                        (
                            0,
                            REPORT_EVIDENCE_PRIORITY_RANK.get(str(semantic_case.get("priority") or "").lower(), 9),
                            0 if str((semantic_turn or {}).get("speaker") or "").lower() == "client" else 1,
                            artifact.call_started_at or datetime.max.replace(tzinfo=UTC),
                        ),
                        {
                            "call_id": ref["call_id"],
                            "client_label": ref["client_label"],
                            "client_phone": ref["client_phone"],
                            "date_label": ref["date_label"],
                            "time_label": ref["time_label"],
                            "client_call_reference": ref["client_call_reference"],
                            "quote": quote,
                            "quote_context": quote_context,
                            "quote_context_source": "transcript_excerpt" if quote_context else None,
                            "context": context_value,
                            "interpretation": context_value,
                            "manager_action": action,
                            "manager_action_source": action_source,
                            "customer_signal": category,
                            "source": "report_evidence.semantic_case",
                        },
                    )
                )
        for item in evidence.get("voice_of_customer") or []:
            if not isinstance(item, dict) or item.get("usable_in_report") is not True:
                continue
            if str(item.get("speaker") or "").strip().lower() not in {"client", "unknown"}:
                continue
            if str(item.get("business_signal") or "").strip().lower() not in {"high", "medium"}:
                continue
            quote = _dialogue_turn_text(str(item.get("quote") or ""), limit=180)
            if len(quote) < 5 or quote in seen:
                continue
            seen.add(quote)
            meaning = _first_sentence(str(item.get("meaning") or ""), limit=180)
            action, action_source, category = _voice_customer_manager_action(
                quote=quote,
                topic=item.get("topic"),
                meaning=meaning,
                summary_action=summary_action,
            )
            context = _voice_customer_context_with_action(meaning=meaning, action=action)
            if action_source == "call_report_summary.manager_next_action":
                source = "report_evidence.voice_of_customer+call_report_summary.manager_next_action"
            elif action_source == "deterministic_customer_signal":
                source = "report_evidence.voice_of_customer+deterministic_customer_signal"
            else:
                source = "report_evidence.voice_of_customer"
            context_value = context[:257].rstrip() + "…" if context and len(context) > 260 else context
            quote_context = _voice_customer_contextual_quote(
                artifact=artifact,
                quote=quote,
            )
            rows.append(
                (
                    (
                        1,
                        signal_rank.get(str(item.get("business_signal") or "").lower(), 9),
                        0 if str(item.get("speaker") or "").lower() == "client" else 1,
                        artifact.call_started_at or datetime.max.replace(tzinfo=UTC),
                    ),
                    {
                        "call_id": ref["call_id"],
                        "client_label": ref["client_label"],
                        "client_phone": ref["client_phone"],
                        "date_label": ref["date_label"],
                        "time_label": ref["time_label"],
                        "client_call_reference": ref["client_call_reference"],
                        "quote": quote,
                        "quote_context": quote_context,
                        "quote_context_source": "transcript_excerpt" if quote_context else None,
                        "context": context_value,
                        "interpretation": context_value,
                        "manager_action": action,
                        "manager_action_source": action_source,
                        "customer_signal": category,
                        "source": source,
                    },
                )
            )
    if not rows:
        return None
    rows.sort(key=lambda item: item[0])
    return {
        "is_placeholder": False,
        "situations": [item for _rank, item in rows[:3]],
        "source_note": (
            "report_evidence.semantic_case+voice_of_customer"
            if semantic_used
            else "report_evidence.voice_of_customer"
        ),
        "selection_diagnostics": _semantic_case_selection_diagnostics(
            block_name="voice_of_customer",
            selected=semantic_selections[0] if semantic_selections else None,
            rejected=semantic_rejections,
        ),
    }


def _build_additional_situations_from_report_evidence(
    *,
    artifacts: list[ReportArtifact],
    report_evidence_index: dict[str, dict[str, Any]],
    call_list_by_interaction_id: dict[str, dict[str, Any]],
    top_situation_title: str | None,
) -> dict[str, Any] | None:
    """Build additional situations from semantic_case, then report_evidence items."""
    rows: list[tuple[tuple[int, int, datetime], dict[str, Any]]] = []
    seen_titles = {str(top_situation_title or "").strip().lower()}
    semantic_used = False
    semantic_rejections: list[dict[str, Any]] = []
    semantic_selection: dict[str, Any] | None = None
    for artifact in artifacts:
        if not _is_report_evidence_sales_like(
            artifact=artifact,
            call_list_by_interaction_id=call_list_by_interaction_id,
        ):
            continue
        evidence = _valid_report_evidence_for_artifact(
            artifact=artifact,
            report_evidence_index=report_evidence_index,
        )
        if evidence is None:
            continue
        ref = _artifact_call_reference(artifact)
        semantic_case = _valid_semantic_case_from_evidence(evidence)
        if semantic_case is not None:
            turns = _semantic_case_turns(semantic_case)
            rejection_reason = _semantic_case_block_rejection_reason(
                semantic_case=semantic_case,
                turns=turns,
                block_name="additional_situations",
                focus_stage_code=None,
            )
            if rejection_reason:
                semantic_rejections.append(
                    _semantic_case_candidate_diagnostic(
                        artifact=artifact,
                        semantic_case=semantic_case,
                        block_name="additional_situations",
                        rejection_reason=rejection_reason,
                    )
                )
            else:
                coaching_moment = _semantic_case_coaching_moment(
                    semantic_case,
                    block_name="additional_situations",
                ) or {}
                stage_code = _semantic_case_stage_code(
                    semantic_case=semantic_case,
                    focus_stage_code=None,
                )
                title = _first_sentence(
                    str(semantic_case.get("case_title") or ""),
                    limit=120,
                ).rstrip(".")
                title_key = title.strip().lower()
                moment_summary = str(coaching_moment.get("moment_summary") or "").strip()
                supporting_quote = str(
                    _semantic_case_supporting_quote(
                        semantic_case=semantic_case,
                        turns=turns,
                        block_name="additional_situations",
                    ) or ""
                ).strip()
                if title and title_key not in seen_titles and moment_summary:
                    seen_titles.add(title_key)
                    semantic_used = True
                    semantic_selection = _semantic_case_candidate_diagnostic(
                        artifact=artifact,
                        semantic_case=semantic_case,
                        block_name="additional_situations",
                        rejection_reason=None,
                    )
                    rows.append(
                        (
                            (
                                REPORT_EVIDENCE_PRIORITY_RANK.get(
                                    str(semantic_case.get("priority") or "").lower(),
                                    9,
                                ),
                                REPORT_EVIDENCE_QUALITY_RANK.get(
                                    str(semantic_case.get("evidence_quality") or "").lower(),
                                    9,
                                ),
                                artifact.call_started_at or datetime.max.replace(tzinfo=UTC),
                            ),
                            {
                                "kind": (
                                    "strength"
                                    if str(semantic_case.get("case_type") or "").strip().lower()
                                    == "strong_practice"
                                    else "gap"
                                ),
                                "title": title,
                                "stage_id": _stage_funnel_label_for_code(stage_code),
                                "stage_code": stage_code,
                                "problem_signal": _focus_problem_signal(
                                    " ".join(part for part in (stage_code, title) if part),
                                    fallback=stage_code or "additional_semantic_case",
                                ),
                                "signal": 1,
                                "evidence_call_id": str(artifact.interaction.id),
                                "client_call_reference": ref["client_call_reference"],
                                "evidence_quote": supporting_quote or None,
                                "supporting_quote": supporting_quote or None,
                                "evidence_quality": semantic_case.get("evidence_quality"),
                                "evidence_type": coaching_moment.get("evidence_type")
                                or _semantic_case_block_fit_value(
                                    semantic_case,
                                    "additional_situations",
                                    "evidence_type",
                                ),
                                "confidence": coaching_moment.get("confidence"),
                                "moment_summary": moment_summary,
                                "missing_action": coaching_moment.get("missing_action"),
                                "why_it_matters": coaching_moment.get("why_it_matters"),
                                "interpretation": coaching_moment.get("why_it_matters"),
                                "client_said": moment_summary,
                                "meant": coaching_moment.get("why_it_matters"),
                                "how_to": _first_sentence(
                                    str(semantic_case.get("recommended_next_action") or ""),
                                    limit=180,
                                ),
                                "why": coaching_moment.get("why_it_matters"),
                                "source": "report_evidence.semantic_case",
                            },
                        )
                    )
        for item in evidence.get("additional_situations") or []:
            if not isinstance(item, dict) or item.get("usable_in_report") is not True:
                continue
            quality = str(item.get("evidence_quality") or "").strip().lower()
            priority = str(item.get("priority") or "").strip().lower()
            if quality not in REPORT_EVIDENCE_USABLE_QUALITIES or priority not in {"high", "medium"}:
                continue
            kind = "strength" if str(item.get("type") or "") == "strength" else "gap"
            stage_code = str(item.get("stage_code") or "").strip()
            raw_title = _first_sentence(str(item.get("title") or ""), limit=120).rstrip(".")
            title = raw_title
            title_normalized_from = None
            wording_warnings: list[str] = []
            if kind == "gap":
                normalized_title = _normalize_problem_statement(
                    raw_title,
                    stage_code=stage_code,
                    fallback=_stage_problem_fallback(stage_code),
                )
                title = str(normalized_title.get("text") or raw_title).strip().rstrip(".")
                title_normalized_from = normalized_title.get("source_text")
                wording_warnings.extend(str(item) for item in normalized_title.get("warnings") or [])
            title_key = title.strip().lower()
            if not title or title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            raw_what_happened = _first_sentence(str(item.get("what_happened") or ""), limit=180)
            body_normalized_from = None
            if kind == "gap":
                normalized_happened = _normalize_problem_statement(
                    raw_what_happened,
                    stage_code=stage_code,
                    fallback=title,
                )
                what_happened = str(normalized_happened.get("text") or raw_what_happened).strip()
                body_normalized_from = normalized_happened.get("source_text")
                wording_warnings.extend(str(item) for item in normalized_happened.get("warnings") or [])
            else:
                what_happened = raw_what_happened
            rows.append(
                (
                    (
                        REPORT_EVIDENCE_PRIORITY_RANK.get(priority, 9),
                        REPORT_EVIDENCE_QUALITY_RANK.get(quality, 9),
                        artifact.call_started_at or datetime.max.replace(tzinfo=UTC),
                    ),
                    {
                        "kind": kind,
                        "title": title,
                        "stage_id": _stage_funnel_label_for_code(stage_code),
                        "stage_code": stage_code,
                        "problem_signal": _focus_problem_signal(
                            " ".join(part for part in (stage_code, title) if part),
                            fallback=stage_code or f"additional_{kind}",
                        ),
                        "title_normalized_from": title_normalized_from,
                        "body_normalized_from": body_normalized_from,
                        "problem_wording_warnings": sorted(set(wording_warnings)),
                        "signal": 1,
                        "evidence_call_id": str(artifact.interaction.id),
                        "client_call_reference": ref["client_call_reference"],
                        "evidence_quote": raw_what_happened if quality in {"direct", "indirect"} else None,
                        "evidence_quality": quality,
                        "interpretation": _first_sentence(str(item.get("why_it_matters") or ""), limit=180),
                        "client_said": what_happened,
                        "meant": _first_sentence(str(item.get("why_it_matters") or ""), limit=180),
                        "how_to": _first_sentence(str(item.get("recommended_action") or ""), limit=180),
                        "why": _first_sentence(str(item.get("why_it_matters") or ""), limit=180),
                        "source": "report_evidence.additional_situations",
                    },
                )
            )
    if not rows:
        return None
    rows.sort(key=lambda item: item[0])
    return {
        "is_placeholder": False,
        "situations": [item for _rank, item in rows[:3]],
        "source_note": (
            "report_evidence.semantic_case+additional_situations"
            if semantic_used
            else "report_evidence.additional_situations"
        ),
        "selection_diagnostics": _semantic_case_selection_diagnostics(
            block_name="additional_situations",
            selected=semantic_selection,
            rejected=semantic_rejections,
        ),
    }


def _select_report_evidence_follow_up(
    *,
    interaction_id: str,
    final_status: str,
    report_evidence_index: dict[str, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not report_evidence_index:
        return None
    entry = report_evidence_index.get(interaction_id) or {}
    if not entry.get("report_evidence_valid"):
        return None
    evidence = dict(entry.get("report_evidence") or {})
    expected_status = {
        "agreed": "agreement",
        "rescheduled": "rescheduled",
        "open": "open",
    }.get(final_status)
    if not expected_status:
        return None
    for candidate in evidence.get("follow_up_candidates") or []:
        if not isinstance(candidate, dict) or candidate.get("usable_in_report") is not True:
            continue
        if str(candidate.get("status") or "").strip().lower() != expected_status:
            continue
        return candidate
    return None


def _normalize_hotness_text(*values: Any) -> str:
    """Normalize persisted follow-up/context text for deterministic hotness checks."""
    return re.sub(
        r"\s+",
        " ",
        " ".join(str(value or "") for value in values).replace("ё", "е").strip().lower(),
    )


def _contains_hotness_signal(text: str, signals: tuple[str, ...]) -> bool:
    """Return whether any normalized signal is present in text."""
    return any(signal.replace("ё", "е").lower() in text for signal in signals)


COMMERCIAL_HOTNESS_SIGNALS = (
    "счет",
    "счёт",
    "оплат",
    "выставить",
    "выставляйте",
    "zoom",
    "зум",
    "встреч",
    "демо",
    "презентац",
    "коммерческое предложение",
    "кп",
    "покуп",
    "подключ",
    "подписк",
)

WARM_HOTNESS_SIGNALS = (
    "скиньте",
    "отправьте",
    "информац",
    "материал",
    "whatsapp",
    "ватсап",
    "коммерческое предложение",
    "кп",
    "посмотрю",
    "подумаем",
    "совет",
    "напишите",
    "обратной связи",
    "интерес",
)

CALL_TOMORROW_INVOICE_MARKERS = (
    "счет",
    "счёт",
    "оплат",
    "выстав",
    "получение счет",
    "получение счёт",
)
CALL_TOMORROW_MEETING_MARKERS = (
    "встреч",
    "демо",
    "демонстрац",
    "презентац",
    "zoom",
    "зум",
)
CALL_TOMORROW_MATERIALS_MARKERS = (
    "whatsapp",
    "ватсап",
    "материал",
    "информац",
    "коммерческое предложение",
    "кп",
    "скинь",
    "отправ",
    "напиш",
)
CALL_TOMORROW_INTERNAL_DISCUSSION_MARKERS = (
    "совет",
    "обсуд",
    "подума",
    "согласу",
    "перезвон",
    "коллег",
    "руковод",
)
CALL_TOMORROW_TRUST_MARKERS = (
    "мошен",
    "незнаком",
    "не беру",
    "не отвечаю",
    "довер",
    "проверить контакт",
    "безопасн",
)
CALL_TOMORROW_GENERIC_ACTION_MARKERS = (
    "понять текущий интерес",
    "договориться о конкретном следующем шаге",
    "уточнить актуальность",
    "ожидать",
    "ждать",
    "поддерживать связь",
    "общий follow-up",
)
CALL_TOMORROW_ACTION_ALIGNMENT_MARKERS: dict[str, tuple[str, ...]] = {
    "invoice_payment": ("счет", "счёт", "оплат", "выстав", "получ", "срок", "следующ"),
    "meeting_demo": ("встреч", "демо", "презентац", "zoom", "зум", "участ", "повест"),
    "materials_request": ("материал", "информац", "коммерческ", "кп", "whatsapp", "ватсап", "отправ", "обсужд", "вопрос"),
    "internal_discussion": ("обсуд", "коллег", "аргумент", "вопрос", "соглас", "следующ", "решени"),
    "rescheduled": ("вернуться", "перезвон", "продолж", "напомн", "следующ", "согласован"),
    "trust_barrier": ("довер", "безопас", "канал", "whatsapp", "ватсап", "email", "почт", "провер", "компан"),
    "agreement": ("договор", "подтверд", "соглас", "следующ"),
}
CALL_TOMORROW_SIGNAL_PROFILES: dict[str, dict[str, str]] = {
    "invoice_payment": {
        "context": "Клиент согласовал коммерческий следующий шаг: нужен счёт, подтверждение получения и срок оплаты.",
        "recommendation": "Отправить счёт, подтвердить получение и согласовать срок оплаты или следующий шаг.",
        "phrase": "Добрый день. Отправляю счёт, как договорились. Подскажите, когда удобно сверить получение и сроки оплаты?",
    },
    "meeting_demo": {
        "context": "Клиент готов к встрече или демонстрации, поэтому важно заранее закрепить участников и повестку.",
        "recommendation": "Подтвердить встречу, участников и короткую повестку.",
        "phrase": "Добрый день. Подтверждаю встречу по ЭДО. Подскажите, кто ещё будет участвовать и какие вопросы важно разобрать?",
    },
    "materials_request": {
        "context": "Клиент попросил материалы или предложение, но следующий контакт нужно закрепить отдельно.",
        "recommendation": "Отправить материал в согласованный канал и сразу зафиксировать дату возврата к обсуждению.",
        "phrase": "Добрый день. Отправил материалы, как договорились. Когда удобно вернуться к обсуждению и ответить на вопросы?",
    },
    "internal_discussion": {
        "context": "Клиенту нужно обсудить решение внутри, поэтому без активного follow-up контакт легко зависнет.",
        "recommendation": "Уточнить, с кем клиент будет обсуждать решение, помочь сформулировать аргументы и согласовать дату следующего контакта.",
        "phrase": "Добрый день. Удалось обсудить предложение с коллегами? Могу коротко помочь с аргументами и ответить на вопросы.",
    },
    "rescheduled": {
        "context": "Клиент перенёс разговор или попросил вернуться позже, поэтому важно напомнить контекст и закрыть следующий шаг.",
        "recommendation": "Вернуться в согласованный срок, напомнить контекст прошлого разговора и зафиксировать следующий шаг.",
        "phrase": "Добрый день. Договаривались вернуться к вопросу. Удобно сейчас коротко продолжить и зафиксировать следующий шаг?",
    },
    "trust_barrier": {
        "context": "Клиент обозначил барьер доверия или удобного канала связи.",
        "recommendation": "Подтвердить компанию и цель контакта, предложить безопасный канал продолжения — WhatsApp, email или звонок в согласованное время.",
        "phrase": "Добрый день. Это Договор-24 по вашему обращению. Могу отправить короткое сообщение в WhatsApp, чтобы вам было удобно проверить контакт?",
    },
    "weak_open": {
        "context": "Контакт открыт, но явный коммерческий следующий шаг пока не зафиксирован.",
        "recommendation": "Уточнить актуальность вопроса и либо зафиксировать следующий шаг, либо снять контакт с активного follow-up.",
        "phrase": "Добрый день. Хочу уточнить, актуален ли ещё вопрос, и понять, есть ли смысл двигаться дальше.",
    },
    "agreement": {
        "context": "Есть договорённость, которую нужно подтвердить и довести до следующего шага.",
        "recommendation": "Подтвердить договорённость и довести контакт до следующего шага.",
        "phrase": "Добрый день. Хочу подтвердить нашу договорённость и уточнить один следующий шаг.",
    },
}


def _follow_up_hotness(
    *,
    final_status: str,
    deadline: str | None,
    next_step: str | None,
    reason: str | None,
    evidence_follow_up: dict[str, Any] | None,
    row: dict[str, Any],
) -> dict[str, str]:
    """Return deterministic follow-up hotness without changing final business outcome."""
    evidence = dict(evidence_follow_up or {})
    text = _normalize_hotness_text(
        next_step,
        reason,
        evidence.get("next_step"),
        evidence.get("why_follow_up"),
        evidence.get("first_phrase"),
        row.get("business_outcome_evidence"),
        row.get("next_step"),
        row.get("reason"),
    )
    if final_status == "agreed":
        return {
            "code": "hot",
            "label": CALL_TOMORROW_HOTNESS_LABELS["hot"],
            "reason": (
                "final_agreed_commercial_signal"
                if _contains_hotness_signal(text, COMMERCIAL_HOTNESS_SIGNALS) or deadline
                else "final_agreed"
            ),
        }
    if final_status == "rescheduled":
        return {
            "code": "rescheduled",
            "label": CALL_TOMORROW_HOTNESS_LABELS["rescheduled"],
            "reason": "final_rescheduled",
        }
    if final_status == "open" and (
        _contains_hotness_signal(text, WARM_HOTNESS_SIGNALS)
        or str(evidence.get("status") or "").strip().lower() == "open"
    ):
        return {
            "code": "warm",
            "label": CALL_TOMORROW_HOTNESS_LABELS["warm"],
            "reason": "open_with_explicit_interest_or_materials_request",
        }
    return {
        "code": "low",
        "label": CALL_TOMORROW_HOTNESS_LABELS["low"],
        "reason": "open_without_clear_follow_up_signal",
    }


def _call_tomorrow_signal_category(*, final_status: str, text: str) -> str:
    """Classify tomorrow action context without changing inclusion or hotness."""
    if final_status == "rescheduled":
        return "rescheduled"
    if _contains_hotness_signal(text, CALL_TOMORROW_INVOICE_MARKERS):
        return "invoice_payment"
    if _contains_hotness_signal(text, CALL_TOMORROW_MEETING_MARKERS):
        return "meeting_demo"
    if _contains_hotness_signal(text, CALL_TOMORROW_TRUST_MARKERS):
        return "trust_barrier"
    if _contains_hotness_signal(text, CALL_TOMORROW_MATERIALS_MARKERS):
        return "materials_request"
    if _contains_hotness_signal(text, CALL_TOMORROW_INTERNAL_DISCUSSION_MARKERS):
        return "internal_discussion"
    if final_status == "agreed":
        return "agreement"
    return "weak_open"


def _call_tomorrow_summary_action_specific(action: str | None, *, category: str) -> bool:
    """Allow LLM2 manager action only when it is specific and aligned to the signal."""
    if not _call_summary_action_usable(action):
        return False
    normalized = _summary_norm(action)
    if any(marker in normalized for marker in CALL_TOMORROW_GENERIC_ACTION_MARKERS):
        return False
    if category == "materials_request":
        sends_material = any(
            marker in normalized
            for marker in ("отправ", "скин", "материал", "кп", "предлож", "информац")
        )
        fixes_return = any(
            marker in normalized
            for marker in ("дат", "вернуться", "возврат", "обсужд", "вопрос", "следующ", "уточн")
        )
        return sends_material and fixes_return
    if category == "trust_barrier":
        return any(
            marker in normalized
            for marker in ("довер", "безопас", "канал", "провер", "компан", "цель")
        )
    alignment = CALL_TOMORROW_ACTION_ALIGNMENT_MARKERS.get(category)
    if not alignment:
        return False
    return any(marker in normalized for marker in alignment)


def _call_tomorrow_profile(
    *,
    final_status: str,
    deadline: str | None,
    next_step: str | None,
    raw_reason: str | None,
    summary_next_action: str | None,
    summary_context: str | None,
    summary_hotness_reason: str | None,
    evidence_follow_up: dict[str, Any] | None,
    row: dict[str, Any],
) -> dict[str, str | bool]:
    """Return one signal profile for tomorrow context, recommendation and phrase."""
    evidence = dict(evidence_follow_up or {})
    signal_text = _normalize_hotness_text(
        next_step,
        raw_reason,
        summary_next_action,
        summary_context,
        summary_hotness_reason,
        evidence.get("next_step"),
        evidence.get("why_follow_up"),
        evidence.get("first_phrase"),
        row.get("business_outcome_evidence"),
        row.get("next_step"),
        row.get("reason"),
        row.get("call_list_topic"),
        row.get("call_list_context"),
        row.get("call_signal_text"),
    )
    category = _call_tomorrow_signal_category(final_status=final_status, text=signal_text)
    profile = dict(CALL_TOMORROW_SIGNAL_PROFILES.get(category) or CALL_TOMORROW_SIGNAL_PROFILES["weak_open"])
    action_source = "deterministic_call_tomorrow_signal"
    action = profile["recommendation"]
    if _call_tomorrow_summary_action_specific(summary_next_action, category=category):
        action = _summary_text(summary_next_action, limit=240) or action
        action_source = "call_report_summary.manager_next_action"

    context = profile["context"]
    context_source = "deterministic_call_tomorrow_signal"
    if category != "weak_open" and _call_summary_context_usable(summary_context):
        context = _summary_text(summary_context, limit=280) or context
        context_source = "call_report_summary.short_context"
    elif category != "weak_open" and _call_summary_action_usable(summary_hotness_reason):
        context = _summary_text(summary_hotness_reason, limit=220) or context
        context_source = "call_report_summary.hotness_reason"

    if category == "rescheduled" and deadline and "согласованный срок" not in context.lower():
        context = f"{context} Срок возврата: {deadline}."

    return {
        "category": category,
        "context": context,
        "recommendation": action if action.endswith((".", "!", "?")) else f"{action}.",
        "opening_script": profile["phrase"],
        "action_source": action_source,
        "context_source": context_source,
        "used_call_report_summary": action_source.startswith("call_report_summary")
        or context_source.startswith("call_report_summary"),
    }


def _follow_up_deadline_sort_value(value: str | None) -> str:
    """Return a stable value where empty deadlines sort after explicit deadlines."""
    raw = str(value or "").strip()
    return raw or "9999-12-31"


def _build_call_tomorrow(
    *,
    call_list: list[dict[str, Any]],
    report_evidence_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА from final report-day outcomes.

    Selection rule (deterministic):
    - Include only final Договорённость, Перенос, Открыт
    - Exclude final Отказ, Тех/сервис and unclassified technical buckets
    - Priority groups: Горячий → Перенос → Тёплый → Низкий
    - Within group: soonest deadline first, then call time
    - Deduplicate by client_label
    - Cap at 5 contacts total
    """
    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in CALL_TOMORROW_HOTNESS_ORDER}

    for row in call_list:
        status = str(row.get("status") or "")
        if status not in FINAL_SALES_LIKE_STATUSES:
            continue

        client_label = str(
            row.get("client_or_phone")
            or row.get("client_name")
            or row.get("client_phone")
            or row.get("client_call_reference")
            or ""
        ).strip()
        if not client_label:
            continue

        interaction_id = str(row.get("interaction_id") or "").strip()
        evidence_follow_up = _select_report_evidence_follow_up(
            interaction_id=interaction_id,
            final_status=status,
            report_evidence_index=report_evidence_index,
        )
        summary, summary_evidence = _valid_call_report_summary_for_interaction(
            interaction_id=interaction_id,
            report_evidence_index=report_evidence_index,
        )
        summary_next_action = _summary_text((summary or {}).get("manager_next_action"), limit=240)
        summary_context = _summary_text((summary or {}).get("short_context"), limit=280)
        summary_hotness_reason = _summary_text((summary or {}).get("hotness_reason"), limit=220)
        safe_summary_phrase = _safe_manager_phrase_from_summary(
            summary=summary,
            evidence=summary_evidence,
        )
        next_step = str(
            (summary_next_action if _call_summary_action_usable(summary_next_action) else None)
            or (evidence_follow_up or {}).get("next_step")
            or row.get("next_step")
            or ""
        ).strip()
        scenario_type = str(row.get("scenario_type") or "").lower()
        time_label = _short_time_label(row.get("time")) or "—"
        deadline = str(
            (evidence_follow_up or {}).get("deadline")
            or row.get("deadline")
            or ""
        ).strip() or None
        raw_reason = str(
            (summary_context if _call_summary_context_usable(summary_context) else None)
            or (summary_hotness_reason if _call_summary_action_usable(summary_hotness_reason) else None)
            or (evidence_follow_up or {}).get("why_follow_up")
            or row.get("reason")
            or ""
        ).strip() or None
        hotness = _follow_up_hotness(
            final_status=status,
            deadline=deadline,
            next_step=next_step,
            reason=raw_reason,
            evidence_follow_up=evidence_follow_up,
            row=row,
        )
        profile = _call_tomorrow_profile(
            final_status=status,
            deadline=deadline,
            next_step=next_step,
            raw_reason=raw_reason,
            summary_next_action=summary_next_action,
            summary_context=summary_context,
            summary_hotness_reason=summary_hotness_reason,
            evidence_follow_up=evidence_follow_up,
            row=row,
        )
        next_step = str(profile["recommendation"])
        reason = str(profile["context"])
        opening_script = str(
            safe_summary_phrase
            if safe_summary_phrase and str(profile["action_source"]) == "call_report_summary.manager_next_action"
            else profile["opening_script"]
            or _call_tomorrow_opening_script(
                status=status,
                deadline=deadline,
                next_step=next_step,
                scenario_type=scenario_type,
            )
        ).strip()
        call_report_summary_used = bool(
            summary
            and (
                profile["used_call_report_summary"]
                or (
                    safe_summary_phrase
                    and str(profile["action_source"]) == "call_report_summary.manager_next_action"
                )
            )
        )

        grouped[hotness["code"]].append({
            "interaction_id": interaction_id,
            "client_label": client_label,
            "client_call_reference": str(row.get("client_call_reference") or "").strip() or client_label,
            "client_phone": row.get("client_phone"),
            "date_label": row.get("date_label"),
            "time_label": time_label,
            "status": status,
            "priority_code": hotness["code"],
            "priority_label": hotness["label"],
            "priority_reason": hotness["reason"],
            "deadline": deadline,
            "next_step": next_step,
            "reason": reason,
            "scenario_type": scenario_type,
            "opening_script": opening_script,
            "recommendation": str(profile["recommendation"]),
            "action_profile": str(profile["category"]),
            "action_source": str(profile["action_source"]),
            "context_source": str(profile["context_source"]),
            "call_report_summary_used": call_report_summary_used,
            "source": (
                "report_evidence.call_report_summary"
                if call_report_summary_used
                else "report_evidence.follow_up_candidates"
                if evidence_follow_up
                else "final_call_list"
            ),
            "_sort_key": (
                CALL_TOMORROW_HOTNESS_RANK.get(hotness["code"], 99),
                _follow_up_deadline_sort_value(deadline),
                time_label,
            ),
        })

    seen: set[str] = set()
    contacts: list[dict[str, Any]] = []
    for priority_code in CALL_TOMORROW_HOTNESS_ORDER:
        for item in sorted(grouped[priority_code], key=lambda x: x["_sort_key"]):
            if item["client_label"] in seen:
                continue
            seen.add(item["client_label"])
            contacts.append({
                "interaction_id": item["interaction_id"],
                "client_label": item["client_label"],
                "client_call_reference": item["client_call_reference"],
                "client_phone": item["client_phone"],
                "date_label": item["date_label"],
                "time_label": item["time_label"],
                "status": item["status"],
                "priority_code": item["priority_code"],
                "priority_label": item["priority_label"],
                "priority_reason": item["priority_reason"],
                "deadline": item["deadline"],
                "next_step": item["next_step"],
                "reason": item["reason"],
                "opening_script": item["opening_script"],
                "recommendation": item["recommendation"],
                "action_profile": item["action_profile"],
                "action_source": item["action_source"],
                "context_source": item["context_source"],
                "call_report_summary_used": item["call_report_summary_used"],
                "source": item["source"],
            })
            if len(contacts) >= 5:
                break
        if len(contacts) >= 5:
            break

    return {
        "is_placeholder": len(contacts) == 0,
        "contacts": contacts,
        "empty_state": "Нет коммерческих звонков для работы завтра по итогам отчётного дня.",
        "source_note": "derived_from_final_business_outcome_call_list_prefers_valid_report_evidence",
    }


def _build_call_breakdown(
    *,
    improve_items: list[dict[str, Any]],
    artifacts: list[ReportArtifact],
    daily_focus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build compact step-by-step breakdown of the most representative problem call.

    Selection rule: among calls containing the top gap label, prefer calls with
    usable business evidence, then pick the lowest overall score.
    """
    _empty: dict[str, Any] = {
        "is_placeholder": True,
        "call_id": None,
        "client_label": None,
        "client_phone": None,
        "date_label": None,
        "time_label": None,
        "stage_code": _daily_focus_stage_code(daily_focus) or None,
        "stage_name": (daily_focus or {}).get("stage_name"),
        "stage_steps": [],
        "worked": [],
        "to_fix": [],
        "recommendation": None,
        "rows": [
            [
                "1",
                "Недостаточно evidence для показа разбора по фокусному этапу.",
                CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE,
                _first_sentence(str((daily_focus or {}).get("problem_statement") or ""), limit=220)
                or "Повторите разбор после следующего полного запуска.",
            ]
        ],
        "summary_line": "Звонок по фокусному этапу не выбран: подтверждающее evidence ограничено.",
        "source_note": "focus_evidence_missing",
        "call_breakdown_source": "focus_evidence_missing",
        "call_breakdown_evidence_strength": "missing",
        "call_breakdown_fragment_present": False,
    }
    if not improve_items or not artifacts:
        return _empty

    gap_label = improve_items[0]["label"]
    focus_stage_code = _daily_focus_stage_code(daily_focus)
    candidates: list[tuple[int, float, int, datetime, ReportArtifact]] = []
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        if focus_stage_code:
            has_gap = False
            for item in detail.get("gaps") or []:
                criterion_code = str((item or {}).get("criterion_code") or "").strip()
                gap_stage = _stage_code_from_criterion_code(criterion_code)
                if gap_stage == focus_stage_code:
                    has_gap = True
                    break
                if not criterion_code and (
                    _finding_item_label(dict(item or {})) != "Без названия"
                    or _finding_item_interpretation(dict(item or {}))
                ):
                    has_gap = True
                    break
        else:
            has_gap = any(
                _finding_item_label(dict(item or {})) == gap_label
                for item in (detail.get("gaps") or [])
            )
        if has_gap:
            s = _extract_score_percent(artifact.analysis)
            evidence_score = _artifact_fallback_evidence_score(artifact)
            evidence_rank = 0 if evidence_score >= 4 else 1
            candidates.append(
                (
                    evidence_rank,
                    s,
                    -evidence_score,
                    artifact.call_started_at or datetime.max.replace(tzinfo=UTC),
                    artifact,
                )
            )

    if not candidates:
        return _empty
    candidates.sort(key=lambda item: item[:4])
    best_evidence_rank, _best_score, best_negative_evidence_score, _best_started_at, best_artifact = candidates[0]
    best_evidence_score = abs(best_negative_evidence_score)

    detail = dict((best_artifact.analysis.scores_detail or {}) if best_artifact.analysis is not None else {})
    ref = _artifact_call_reference(best_artifact)
    fallback_fragment = _artifact_fallback_evidence_fragment(best_artifact)
    fallback_strength = _call_breakdown_fragment_strength(
        fragment=fallback_fragment,
        evidence_quality="indirect" if best_evidence_rank == 0 else "weak",
    )

    # Build stage steps ordered by funnel
    raw_stages = detail.get("score_by_stage") or []
    stage_lookup = {str(s.get("stage_code") or ""): s for s in raw_stages}
    stage_steps: list[dict[str, Any]] = []
    for code, funnel_label, stage_name in _STAGE_FUNNEL_ORDER:
        if code not in stage_lookup:
            continue
        s = stage_lookup[code]
        s_score = int(s.get("stage_score") or 0)
        max_s = int(s.get("max_stage_score") or 0)
        if max_s > 0:
            normalized = round(s_score / max_s * 10, 1)
            stage_steps.append({
                "funnel_label": funnel_label,
                "stage_name": stage_name,
                "score": normalized,
                "is_weak": normalized < 4.0,
            })

    worked = [
        {
            "label": _finding_item_label(dict(i or {})),
            "interpretation": _finding_item_interpretation(dict(i or {})),
        }
        for i in (detail.get("strengths") or [])[:2]
        if _finding_item_label(dict(i or {})) != "Без названия"
    ]
    to_fix_source = list(detail.get("gaps") or [])
    if focus_stage_code:
        to_fix_source = [
            item
            for item in to_fix_source
            if _stage_code_from_criterion_code(str((item or {}).get("criterion_code") or "")) == focus_stage_code
            or not str((item or {}).get("criterion_code") or "").strip()
        ]
    to_fix = [
        {
            "label": str(
                _normalize_problem_statement(
                    _finding_item_label(dict(i or {})),
                    stage_code=focus_stage_code,
                    criterion_code=str((i or {}).get("criterion_code") or ""),
                    fallback=_stage_problem_fallback(focus_stage_code),
                ).get("text")
                or _finding_item_label(dict(i or {}))
            ),
            "interpretation": str(
                _normalize_problem_statement(
                    _finding_item_interpretation(dict(i or {})),
                    stage_code=focus_stage_code,
                    criterion_code=str((i or {}).get("criterion_code") or ""),
                    fallback=_stage_problem_fallback(focus_stage_code),
                ).get("text")
                or _finding_item_interpretation(dict(i or {}))
            ),
        }
        for i in to_fix_source[:2]
        if _finding_item_label(dict(i or {})) != "Без названия"
    ]

    recs = detail.get("recommendations") or []
    recommendation = None
    if recs:
        r = recs[0]
        better_phrase = str(r.get("better_phrase") or r.get("recommendation") or r.get("problem") or "").strip()
        if better_phrase:
            recommendation = {
                "title": str(r.get("criterion_name") or r.get("criterion_code") or "Рекомендация"),
                "better_phrasing": better_phrase,
            }

    rows: list[list[str]] = []
    for idx, item in enumerate(to_fix[:3], start=1):
        row_recommendation = ""
        if idx - 1 < len(recs):
            rec = recs[idx - 1]
            row_recommendation = str(
                rec.get("better_phrase")
                or rec.get("recommendation")
                or rec.get("problem")
                or ""
            ).strip()
        if not row_recommendation:
            row_recommendation = str((recommendation or {}).get("better_phrasing") or "").strip()
        rows.append(
            [
                f"{idx}",
                f"{item.get('label') or 'Момент разговора'}: {item.get('interpretation') or 'Требует уточнения.'}",
                fallback_fragment if idx == 1 and fallback_fragment else CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE,
                row_recommendation or "Следующий шаг нужно формулировать конкретнее.",
            ]
        )
    if not rows:
        rows.append(
            [
                "1",
                "Недостаточно данных для детального покадрового разбора звонка.",
                fallback_fragment or CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE,
                str((recommendation or {}).get("better_phrasing") or "Повторите разбор после следующего полного запуска."),
            ]
        )

    return {
        "is_placeholder": not stage_steps and not worked and not to_fix,
        "call_id": str(best_artifact.interaction.id),
        "client_label": ref["client_label"],
        "client_phone": ref["client_phone"],
        "date_label": ref["date_label"],
        "time_label": ref["time_label"],
        "client_call_reference": ref["client_call_reference"],
        "stage_code": focus_stage_code or None,
        "stage_name": (daily_focus or {}).get("stage_name"),
        "stage_steps": stage_steps,
        "worked": worked,
        "to_fix": to_fix,
        "recommendation": recommendation,
        "rows": rows,
        "summary_line": _call_breakdown_summary_line(ref=ref, evidence_strength=fallback_strength),
        "source_note": "legacy_fallback",
        "fallback_evidence_score": best_evidence_score,
        "fallback_evidence_quality": "weak" if best_evidence_rank else "indirect",
        "call_breakdown_source": "legacy_fallback",
        "call_breakdown_evidence_strength": fallback_strength,
        "call_breakdown_fragment_present": fallback_fragment is not None,
    }


def _build_problem_call_example(
    *,
    gap_label: str,
    artifacts: list[ReportArtifact],
) -> dict[str, Any] | None:
    """Pick one representative call that illustrates the top gap.

    Selection rule: among calls that contain the gap label, pick the one with the
    lowest overall score (most problematic illustrator). Falls back to any artifact
    with any gap if none match specifically.
    """
    candidates: list[tuple[float, ReportArtifact, str]] = []
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for gap_item in detail.get("gaps") or []:
            item_label = _finding_item_label(dict(gap_item or {}))
            if item_label == gap_label:
                reason = _finding_item_interpretation(dict(gap_item or {}))
                score = _extract_score_percent(artifact.analysis)
                candidates.append((score, artifact, reason))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    _score, best, reason_text = candidates[0]
    ref = _artifact_call_reference(best)
    reason_short = reason_text[:80] + "…" if len(reason_text) > 80 else reason_text
    return {
        "client_label": ref["client_label"],
        "client_phone": ref["client_phone"],
        "date_label": ref["date_label"],
        "time_label": ref["time_label"],
        "client_call_reference": ref["client_call_reference"],
        "reason_short": reason_short or None,
    }


def _build_manager_daily_key_problem(
    *,
    improve_items: list[dict[str, Any]],
    artifacts: list[ReportArtifact],
    calls_count: int,
) -> dict[str, Any]:
    """Build a richer key problem card from the most repeated gap."""
    if not improve_items:
        return {
            "title": MANAGER_DAILY_FALLBACK_KEY_PROBLEM_TITLE,
            "description": MANAGER_DAILY_FALLBACK_KEY_PROBLEM_DESCRIPTION,
            "pattern_count": None,
            "total_calls": calls_count,
            "call_example": None,
        }
    top_gap = improve_items[0]
    affected_calls = int(top_gap.get("signal") or 0)
    example = _first_gap_evidence(artifacts=artifacts, label=top_gap["label"])
    description = (
        f"{top_gap['interpretation']} Повторяемость: {affected_calls} звонк(ов)."
        f"{' Пример: ' + example if example else ''}"
    )
    call_example = _build_problem_call_example(gap_label=top_gap["label"], artifacts=artifacts)
    return {
        "title": top_gap["label"],
        "description": description,
        "pattern_count": affected_calls if affected_calls > 0 else None,
        "total_calls": calls_count,
        "call_example": call_example,
    }


def _build_signal_reason(
    *,
    product_signal: dict[str, Any] | None,
    worked_items: list[dict[str, Any]],
) -> str:
    """Explain why the selected signal matters."""
    if product_signal is not None:
        topic = str(product_signal.get("topic") or "ключевой теме клиента")
        importance = str(product_signal.get("importance") or "medium")
        return f"В этом эпизоде уже прозвучал важный сигнал по теме '{topic}' (importance={importance})."
    if worked_items:
        return f"Лучший звонок дня показывает рабочий паттерн по теме '{worked_items[0]['label']}'."
    return "Лучший звонок дня показывает, какие формулировки стоит повторять."


def _select_most_important_product_signal(artifacts: list[ReportArtifact]) -> dict[str, Any] | None:
    """Return the most important product signal found in the selected artifacts."""
    best: dict[str, Any] | None = None
    best_rank = -1
    rank = {"high": 3, "medium": 2, "low": 1}
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for item in detail.get("product_signals") or []:
            score = rank.get(str(item.get("importance") or "").lower(), 0)
            if score > best_rank:
                best_rank = score
                best = dict(item)
    return best


def _select_evidence_fragment(artifacts: list[ReportArtifact]) -> dict[str, Any] | None:
    """Return one evidence fragment to enrich signal text when available."""
    for artifact in sorted(
        artifacts,
        key=lambda item: _extract_score_percent(item.analysis),
        reverse=True,
    ):
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        fragments = detail.get("evidence_fragments") or []
        if fragments:
            return dict(fragments[0])
    return None


def _build_focus_criterion_dynamics(
    *,
    artifacts: list[ReportArtifact],
    improve_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build deterministic focus-criterion dynamics from current period calls."""
    focus_name = improve_items[0]["label"] if improve_items else None
    if not focus_name:
        return {
            "focus_criterion_name": None,
            "current_period_value": None,
            "previous_period_value": None,
            "delta": None,
            "is_placeholder": True,
        }
    chronological = sorted(
        artifacts,
        key=lambda item: item.call_started_at or datetime.min.replace(tzinfo=UTC),
    )
    midpoint = max(1, len(chronological) // 2)
    previous = _average_criterion_score(chronological[:midpoint], focus_name)
    current = _average_criterion_score(chronological[midpoint:], focus_name)
    if current is None:
        current = previous
    return {
        "focus_criterion_name": focus_name,
        "current_period_value": current,
        "previous_period_value": previous,
        "delta": round(current - previous, 1) if current is not None and previous is not None else None,
        "is_placeholder": current is None and previous is None,
    }


def _average_criterion_score(artifacts: list[ReportArtifact], criterion_name: str) -> float | None:
    """Average one criterion score across a slice of artifacts."""
    values: list[float] = []
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for stage in detail.get("score_by_stage") or []:
            for criterion in stage.get("criteria_results") or []:
                if str(criterion.get("criterion_name") or "").strip() == criterion_name:
                    values.append(float(criterion.get("score") or 0))
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _build_call_outcomes_summary(*, artifacts: list[ReportArtifact]) -> dict[str, Any]:
    """Build richer outcome counters from follow_up metadata and call classification.

    Counts only report-day meaningful artifacts. Calls without analysis are counted as
    unclassified (not as "open") to avoid inflating the open bucket with unanalyzed calls.
    """
    agreed = 0
    rescheduled = 0
    refusal = 0
    open_count = 0
    tech_service = 0
    unclassified = 0
    unclassified_by_bucket: dict[str, int] = {}
    for artifact in artifacts:
        row = _build_daily_call_row(artifact)
        status = row.get("status")
        if status is None:
            unclassified += 1
            bucket = str(row.get("unclassified_status_label") or UNCLASSIFIED_MANAGER_STATUS_LABELS["unknown"])
            unclassified_by_bucket[bucket] = unclassified_by_bucket.get(bucket, 0) + 1
            continue
        if status == "tech_service":
            tech_service += 1
        elif status == "agreed":
            agreed += 1
        elif status == "rescheduled":
            rescheduled += 1
        elif status == "refusal":
            refusal += 1
        else:
            open_count += 1
    return {
        "agreed_count": agreed,
        "rescheduled_count": rescheduled,
        "refusal_count": refusal,
        "open_count": open_count,
        "tech_service_count": tech_service,
        "unclassified_count": unclassified,
        "unclassified_by_bucket": unclassified_by_bucket,
        "source_note": "derived_from_business_outcome_resolver",
    }


_MONTH_SHORT_RU_REP = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
_MONTH_FULL_RU_REP = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def _format_iso_deadline(value: str | None) -> str | None:
    """Format ISO datetime/date to short Russian label for manager-facing deadline field."""
    import re as _re
    if not value:
        return None
    text = str(value).strip()
    m = _re.match(r"\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})", text)
    if m:
        month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        mon = _MONTH_SHORT_RU_REP[month - 1] if 1 <= month <= 12 else str(month)
        return f"{day} {mon} {hour:02d}:{minute:02d}"
    m = _re.match(r"\d{4}-(\d{2})-(\d{2})$", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        mon = _MONTH_SHORT_RU_REP[month - 1] if 1 <= month <= 12 else str(month)
        return f"{day} {mon}"
    return text


def _clean_display_part(value: Any) -> str:
    """Return a compact reader-facing display fragment."""
    return re.sub(r"\s+", " ", str(value or "").strip())


def _is_phone_like_display(value: Any) -> bool:
    """Return True when a display fragment is effectively a phone number."""
    text = _clean_display_part(value)
    digits = re.sub(r"\D", "", text)
    return len(digits) >= 7


def _same_phone_display(left: Any, right: Any) -> bool:
    """Return True when two values point to the same phone number."""
    left_digits = re.sub(r"\D", "", _clean_display_part(left))
    right_digits = re.sub(r"\D", "", _clean_display_part(right))
    return bool(left_digits and right_digits and left_digits == right_digits)


UNSAFE_CLIENT_DISPLAY_NAME_VALUES = {
    "абонент",
    "алло",
    "да",
    "договор",
    "добрый день",
    "заявка",
    "здравствуйте",
    "клиент",
    "менеджер",
    "не знаю",
    "неизвестно",
    "нет",
    "поддержка",
    "продажи",
    "ага",
    "слушаю",
    "техподдержка",
    "угу",
    "ужас",
    "эдо",
}


def _safe_client_display_name(
    value: Any,
    *,
    phone: Any = None,
    confidence: Any = None,
    allow_low_confidence_without_phone: bool = True,
) -> str | None:
    """Return a manager-facing client name only when it is safe enough to show."""
    text = _clean_display_part(value).strip(".,:;!?«»\"'()[]{} ")
    if not text or _is_phone_like_display(text) or _same_phone_display(text, phone):
        return None
    normalized = text.lower().replace("ё", "е")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized in UNSAFE_CLIENT_DISPLAY_NAME_VALUES:
        return None
    if str(confidence or "").strip().lower() == "low" and (phone or not allow_low_confidence_without_phone):
        return None
    if len(text) > 60:
        return None
    if len(normalized) < 2:
        return None
    if any(marker in normalized for marker in ("http://", "https://", "www.", "@")):
        return None
    if re.search(r"\d", text):
        return None
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё -]{1,59}", text):
        return None
    return text


def _format_call_started_human(value: datetime | None) -> str | None:
    """Format call start as '4 мая 2026, 11:46' for unified call references."""
    if value is None:
        return None
    month = value.month
    month_label = _MONTH_FULL_RU_REP[month - 1] if 1 <= month <= 12 else str(month)
    return f"{value.day} {month_label} {value.year}, {value.strftime('%H:%M')}"


def _build_client_call_reference(
    *,
    client_name_or_label: Any = None,
    phone: Any = None,
    call_started_at: datetime | None = None,
) -> str | None:
    """Build the unified manager_daily client/call display label.

    Format: name/label · phone · date, time. The helper does not invent a
    fallback name and avoids repeating the phone when the label already is one.
    """
    phone_text = _clean_display_part(phone)
    label = _safe_client_display_name(client_name_or_label, phone=phone_text) or ""
    if label in {"Клиент", "Клиент не определён", "—"}:
        label = ""
    if phone_text in {"Клиент", "Клиент не определён", "—"}:
        phone_text = ""
    if _is_phone_like_display(label) and not phone_text:
        phone_text = label
        label = ""
    elif label and phone_text and _same_phone_display(label, phone_text):
        label = ""

    parts = [part for part in (label, phone_text, _format_call_started_human(call_started_at)) if part]
    return " · ".join(parts) if parts else None


def _safe_persisted_transcript_contact_name(artifact: ReportArtifact) -> str | None:
    """Return a contact name only when persisted transcript metadata states it directly."""
    metadata = dict(artifact.interaction.metadata_ or {})
    segments = [dict(item or {}) for item in list(metadata.get("segments") or []) if isinstance(item, dict)]
    segment_texts = [_clean_display_part(item.get("text")) for item in segments]
    for index, text in enumerate(segment_texts[:-1]):
        lowered = text.lower().replace("ё", "е")
        if "как могу к вам обращаться" not in lowered and "как к вам обращаться" not in lowered:
            continue
        candidate = _safe_contact_name_candidate(segment_texts[index + 1])
        if candidate:
            return candidate

    full_text = _clean_display_part(" ".join(segment_texts) or artifact.interaction.text)
    match = re.search(
        r"(?:как могу к вам обращаться|как к вам обращаться)[^А-Яа-яЁё]{0,40}"
        r"([А-ЯЁ][А-Яа-яЁё-]{1,30}(?:\s+[А-ЯЁ][А-Яа-яЁё-]{1,30}){0,2})",
        full_text,
    )
    if match:
        return _safe_contact_name_candidate(match.group(1))
    return None


def _safe_contact_name_candidate(value: Any) -> str | None:
    """Validate a short persisted transcript answer as a name/label, not a guessed identity."""
    text = _safe_client_display_name(value)
    if not text or len(text) > 40:
        return None
    return text


def _derive_call_status_and_deadline(*, follow_up: dict[str, Any]) -> tuple[str, str | None]:
    """Classify call outcome from follow_up fields."""
    raw = str(follow_up.get("due_date_text") or follow_up.get("due_date_iso") or "").strip() or None
    deadline = _format_iso_deadline(raw)
    if follow_up.get("next_step_fixed"):
        return "agreed", deadline
    reason = str(follow_up.get("reason_not_fixed") or "").lower()
    if any(token in reason for token in ("позже", "перезвон", "перен", "созвон")):
        return "rescheduled", deadline
    if any(token in reason for token in ("не интересно", "отказ", "неакту", "нет надобности", "не нужно")):
        return "refusal", deadline
    return "open", deadline


def _has_stop_flag(analysis: Analysis | None) -> bool:
    """Return True when the call contains a strong stop signal for weekly aggregation."""
    detail = dict((analysis.scores_detail or {}) if analysis is not None else {})
    follow_up = dict(detail.get("follow_up") or {})
    status, _deadline = _derive_call_status_and_deadline(follow_up=follow_up)
    if status in {"refusal", "open"}:
        return True
    for item in detail.get("product_signals") or []:
        if str(item.get("signal_type") or "").lower() == "objection" and str(item.get("importance") or "").lower() == "high":
            return True
    return False


def _build_weekly_best_commentary(
    *,
    dashboard_rows: list[dict[str, Any]],
    top_block: dict[str, Any],
) -> str:
    """Build bounded positive commentary for weekly dynamics."""
    if not dashboard_rows:
        return "Недостаточно данных для weekly commentary."
    return (
        f"Опорный менеджер недели: {top_block.get('manager') or 'не определён'}. "
        "Его звонки можно использовать как источник удачных формулировок для разбора команды."
    )


def _build_weekly_alarm_commentary(
    *,
    anti_top_block: dict[str, Any],
    systemic_team_problems: list[dict[str, Any]],
) -> str:
    """Build bounded alarm commentary for weekly dynamics."""
    if systemic_team_problems:
        return (
            f"Главный системный риск недели: {systemic_team_problems[0]['problem_title']}. "
            f"Сначала стоит разобрать менеджера {anti_top_block.get('manager') or 'из зоны риска'}, затем дать общекомандное упражнение."
        )
    return (
        f"Главная зона внимания недели: {anti_top_block.get('manager') or 'не определена'}. "
        "Нужен короткий персональный разбор и повторная проверка следующих звонков."
    )


def _build_rop_weekly_executive_summary(
    *,
    department_name: str,
    dashboard_rows: list[dict[str, Any]],
    current_period_score: float | None,
) -> str:
    """Build short executive summary for weekly report."""
    score_label = "n/a" if current_period_score is None else str(current_period_score)
    return (
        f"По команде {department_name} в отчёт вошло {len(dashboard_rows)} менеджеров; "
        f"текущий средний уровень качества звонков — {score_label}."
    )


def _build_rop_weekly_team_risks(
    *,
    systemic_team_problems: list[dict[str, Any]],
    anti_top_block: dict[str, Any],
) -> str:
    """Build short wording for team risks."""
    if systemic_team_problems:
        return str(
            systemic_team_problems[0].get("explanation")
            or "Есть повторяющийся командный риск, который требует отдельного внимания РОПа."
        )
    return str(
        anti_top_block.get("interpretation")
        or "Критичных командных рисков на этой неделе не выделилось."
    )


def _build_rop_weekly_tasks_commentary(*, tasks: list[dict[str, Any]]) -> str:
    """Build one editorial wording block for ROP tasks."""
    if not tasks:
        return "На этой неделе нет новых обязательных задач сверх стандартного управленческого контроля."
    first = tasks[0]
    task_label = str(first.get("task_for_next_week") or "не определён")
    verify_label = str(first.get("how_to_verify") or "не определена")
    return (
        f"Главный управленческий фокус недели: {task_label}. "
        f"Проверка: {verify_label}."
    )


def _build_rop_weekly_final_commentary(
    *,
    top_block: dict[str, Any],
    anti_top_block: dict[str, Any],
) -> str:
    """Build final managerial commentary for weekly report."""
    top_manager = str(top_block.get("manager") or "команды")
    anti_top_manager = str(anti_top_block.get("manager") or "ключевого менеджера")
    return (
        f"Сохранить сильный паттерн у {top_manager} и отдельно "
        f"отработать зону риска у {anti_top_manager}."
    )


def _first_gap_evidence(*, artifacts: list[ReportArtifact], label: str) -> str | None:
    """Return one concrete gap evidence snippet for the selected label."""
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for item in detail.get("gaps") or []:
            item_label = _finding_item_label(dict(item or {}))
            if item_label == label:
                return _finding_item_interpretation(dict(item or {})) or None
    return None


def _render_manager_daily_text(payload: dict[str, Any]) -> str:
    """Render manager_daily plain-text email."""
    header = payload["header"]
    kpi = payload["kpi_overview"]
    recommendations = payload["recommendations"]
    call_rows = payload["call_list"]
    worked = payload["analysis_worked"]
    improve = payload["analysis_improve"]
    worked_lines = [f"- {item['label']}: {item['interpretation']}" for item in worked[:5]] or ["- Нет данных"]
    improve_lines = [f"- {item['label']}: {item['interpretation']}" for item in improve[:5]] or ["- Нет данных"]
    recommendation_lines = [
        f"- [{item['priority_tag']}] {item['title']}: {item['better_phrasing']}"
        for item in recommendations[:5]
    ]
    call_lines = [
        (
            f"- {row['time']}: {row['client_or_phone']} | {row['duration_sec']} сек | "
            f"статус {row['status']} | балл {row['score_percent']}"
        )
        for row in call_rows[:10]
    ]
    return "\n".join(
        [
            header["report_title"],
            f"Менеджер: {header['manager_name']}",
            f"Дата: {header['report_date']}",
            f"Отдел: {header['department_name']}",
            "",
            f"Звонков: {kpi['calls_count']}",
            f"Средний балл: {kpi['average_score']}",
            (
                "Доли звонков: "
                f"сильные {kpi['strong_calls_pct']}%, "
                f"базовые {kpi['baseline_calls_pct']}%, "
                f"проблемные {kpi['problematic_calls_pct']}%"
            ),
            "",
            f"Итог дня: {payload['narrative_day_conclusion']['text']}",
            f"Фокус на завтра: {payload['main_focus_for_tomorrow']['text']}",
            "",
            "Что получилось:",
            *worked_lines,
            "",
            "Над чем работать:",
            *improve_lines,
            "",
            "Рекомендации:",
            *recommendation_lines,
            "",
            "Короткий список звонков:",
            *call_lines,
        ]
    )


def _render_rop_weekly_text(payload: dict[str, Any]) -> str:
    """Render rop_weekly plain-text email."""
    header = payload["header"]
    dashboard_rows = payload["dashboard_rows"]
    risk_cards = payload["risk_zone_cards"]
    systemic = payload["systemic_team_problems"]
    tasks = payload["rop_tasks_next_week"]
    dashboard_lines = [
        (
            f"- {row['manager_name']}: {row['calls_count']} звонков | "
            f"средний балл {row['average_score']} | статус {row['status_signal']}"
        )
        for row in dashboard_rows
    ]
    risk_lines = [
        f"- {item['manager_name']}: {item['core_problem_statement']} -> {item['action_for_rop']}"
        for item in risk_cards
    ] or ["- Нет менеджеров в явной зоне риска"]
    systemic_lines = [
        f"- {item['problem_title']}: {item['recommended_systemic_action']}"
        for item in systemic
    ] or ["- Не выявлены"]
    task_lines = [
        f"- [{item['priority']}] {item['manager']}: {item['task_for_next_week']}"
        for item in tasks
    ]
    return "\n".join(
        [
            header["report_title"],
            header["subtitle"],
            f"Период: {header['week_label']}",
            f"Отдел: {header['department_name']}",
            "",
            "Dashboard недели:",
            *dashboard_lines,
            "",
            "Зона внимания:",
            *risk_lines,
            "",
            "Системные проблемы:",
            *systemic_lines,
            "",
            "Задачи РОПа на неделю:",
            *task_lines,
            "",
            "CRM-блок: пока placeholder до подключения данных результата продаж.",
        ]
    )

def _fallback_manager_name(artifact: ReportArtifact) -> str:
    """Return a readable manager fallback for unmapped rows."""
    metadata = dict(artifact.interaction.metadata_ or {})
    return str(metadata.get("manager_name") or metadata.get("extension") or "Не сопоставлен")


def _pct(numerator: int, denominator: int) -> float:
    """Return percentage rounded to one decimal place."""
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _format_period_label(period: dict[str, str]) -> str:
    """Return a compact report-period label."""
    if period.get("date_from") == period.get("date_to"):
        return str(period["date_from"])
    return f"{period['date_from']}..{period['date_to']}"


def _performance_label(score: float | None) -> str:
    """Return a compact performance label for daily report."""
    if score is None:
        return "неполный"
    if score >= 80:
        return "сильный"
    if score >= 60:
        return "базовый"
    return "зона внимания"


def _best_call_time(artifacts: list[ReportArtifact]) -> str | None:
    """Return one best-call time candidate."""
    best = sorted(
        artifacts,
        key=lambda item: _extract_score_percent(item.analysis),
        reverse=True,
    )[0]
    return best.call_started_at.isoformat() if best.call_started_at else None


def _best_contact(artifacts: list[ReportArtifact]) -> str | None:
    """Return one contact marker for the best daily signal."""
    best = sorted(
        artifacts,
        key=lambda item: _extract_score_percent(item.analysis),
        reverse=True,
    )[0]
    detail = dict((best.analysis.scores_detail or {}) if best.analysis is not None else {})
    call = dict(detail.get("call") or {})
    return call.get("contact_name") or call.get("contact_phone") or (best.interaction.metadata_ or {}).get("contact_phone")


def _best_signal_text(
    artifacts: list[ReportArtifact],
    *,
    evidence_fragment: dict[str, Any] | None = None,
) -> str:
    """Return one short best-call explanation."""
    if evidence_fragment is not None:
        fragment = str(
            evidence_fragment.get("manager_text")
            or evidence_fragment.get("client_text")
            or evidence_fragment.get("summary")
            or ""
        ).strip()
        if fragment:
            return fragment
    best = sorted(
        artifacts,
        key=lambda item: _extract_score_percent(item.analysis),
        reverse=True,
    )[0]
    detail = dict((best.analysis.scores_detail or {}) if best.analysis is not None else {})
    strengths = detail.get("strengths") or []
    if strengths:
        return str(strengths[0].get("comment") or strengths[0].get("evidence") or "Сильный разговор дня.")
    return "Сильный разговор дня по совокупному баллу."


def _weekly_status_signal(*, avg_score: float | None, problematic_pct: float) -> str:
    """Map one manager weekly summary to the bounded status vocabulary."""
    if avg_score is None:
        return "Наблюдение"
    if avg_score >= 85 and problematic_pct < 10:
        return "Эталон"
    if avg_score >= 75:
        return "Растёт"
    if avg_score >= 60:
        return "Стабильно"
    if avg_score >= 45:
        return "Наблюдение"
    return "Зона риска"


def format_report_preview_timestamp() -> str:
    """Return RFC 2822-like timestamp for delivery previews if needed later."""
    return format_datetime(datetime.now(UTC))
