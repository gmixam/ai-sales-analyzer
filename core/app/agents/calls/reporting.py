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

from app.agents.calls.analyzer import (
    APPROVED_CHECKLIST_VERSION,
    CallsAnalyzer,
    SEMANTIC_EMPTY_ANALYSIS_REASON,
)
from app.agents.calls.bitrix_readonly import Bitrix24ReadOnlyClient, BitrixReadOnlyError
from app.agents.calls.config import calls_config
from app.agents.calls.delivery import CallsDelivery
from app.agents.calls.extractor import CallsExtractor
from app.agents.calls.intake import OnlinePBXIntake
from app.agents.calls.orchestrator import (
    CallsManualPilotOrchestrator,
    analysis_contract_failure_reason,
)
from app.agents.calls.report_templates import get_active_template_version, render_report_artifact
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
        "посоветуюсь",
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
        deadline = _format_iso_deadline(
            str(follow_up.get("due_date_text") or follow_up.get("due_date_iso") or "").strip() or None
        )

        tech = self._resolve_tech_service(text=text, call_type=call_type)
        if tech is not None:
            return tech

        refusal = self._resolve_refusal(text=text, follow_up=follow_up)
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
            "missing_transcripts_before_build": 0,
            "missing_analyses_before_build": 0,
            "transcript_build_failed": 0,
            "analysis_build_failed": 0,
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
    ) -> tuple[list[ReportArtifact], dict[str, Any], list[str]]:
        """Reuse persisted artifacts and optionally build only missing ones."""
        analyses_by_interaction = self._load_latest_analyses_by_interaction(interactions=interactions)
        managers_by_id = self._load_managers_by_id(interactions=interactions)

        built_transcripts = 0
        reused_transcripts = 0
        built_analyses = 0
        reused_analyses = 0
        analyses_rejected_for_reuse = 0
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
            reusable_analysis, analysis_reuse_reason = _is_analysis_reusable_for_reporting(analysis)
            if reusable_analysis:
                reused_analyses += 1
            else:
                missing_analyses_before_build += 1
                if analysis is not None:
                    analyses_rejected_for_reuse += 1
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
                "missing_transcripts_before_build": missing_transcripts_before_build,
                "missing_analyses_before_build": missing_analyses_before_build,
                "transcript_build_failed": failed_transcripts,
                "analysis_build_failed": failed_analyses,
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
    ) -> dict[UUID, Analysis]:
        """Return the latest analysis row for each selected interaction."""
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
        latest: dict[UUID, Analysis] = {}
        for row in rows:
            latest.setdefault(row.interaction_id, row)
        return latest

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
                    f"preset=manager_daily",
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
    call_outcomes_summary = _build_call_outcomes_summary(artifacts=operational_meaningful_artifacts)
    unclassified_breakdown = _build_unclassified_breakdown(artifacts=operational_meaningful_artifacts)
    call_list = _build_meaningful_call_list(
        window_artifacts=operational_day_artifacts,
    )
    call_list_by_interaction_id = _call_list_rows_by_interaction_id(call_list)
    coaching_content_artifacts = _filter_coaching_artifacts_by_final_outcome(
        artifacts=artifacts,
        call_list_by_interaction_id=call_list_by_interaction_id,
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
    call_breakdown = _build_call_breakdown(improve_items=improve_items, artifacts=coaching_content_artifacts)
    voice_of_customer = _build_voice_of_customer(artifacts=coaching_content_artifacts)
    additional_situations = _build_additional_situations(
        improve_items=improve_items,
        worked_items=worked_items,
        top_gap_title=(improve_items[0]["label"] if improve_items else None),
    )
    call_tomorrow = _build_call_tomorrow(call_list=call_list)
    focus_dynamics = _build_focus_criterion_dynamics(
        artifacts=coaching_content_artifacts,
        improve_items=improve_items,
    )
    score_by_stage = _aggregate_stage_scores(artifacts=coaching_content_artifacts)
    situation_evidence_quote = _build_situation_evidence_quote(
        artifacts=coaching_content_artifacts,
        score_by_stage=score_by_stage,
        improve_items=improve_items,
    )
    situation_dialogue_excerpt = _build_situation_dialogue_excerpt(
        artifacts=coaching_content_artifacts,
        situation_evidence_quote=situation_evidence_quote,
    )
    focus_stage_deep_dive = _build_focus_stage_deep_dive(
        score_by_stage=score_by_stage,
        key_problem=key_problem,
        recommendations=recommendation_cards,
    )
    focus_stage_recommendation = _build_focus_stage_recommendation(
        focus_stage_deep_dive=focus_stage_deep_dive,
        recommendations=recommendation_cards,
    )
    situation_day_coaching_view = _build_situation_day_coaching_view(
        score_by_stage=score_by_stage,
        situation_evidence_quote=situation_evidence_quote,
        situation_dialogue_excerpt=situation_dialogue_excerpt,
        focus_stage_deep_dive=focus_stage_deep_dive,
        focus_stage_recommendation=focus_stage_recommendation,
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
        "manager_facing_completeness": manager_facing_completeness,
        "score_by_stage": score_by_stage,
        "situation_evidence_quote": situation_evidence_quote,
        "situation_dialogue_excerpt": situation_dialogue_excerpt,
        "focus_stage_deep_dive": focus_stage_deep_dive,
        "focus_stage_recommendation": focus_stage_recommendation,
        "situation_day_coaching_view": situation_day_coaching_view,
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


def _stage_problem_text_from_issue(issue: dict[str, Any]) -> str:
    """Build one bounded stage problem sentence from already persisted analysis data."""
    for key in ("comment", "interpretation", "impact", "evidence", "title", "criterion_name"):
        text = _first_sentence(str(issue.get(key) or ""))
        if text:
            return text
    return ""


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
                    candidate_text = _stage_problem_text_from_issue(dict(crit))
                    if candidate_text:
                        stage_problem_candidates.setdefault(code, []).append(
                            {
                                "source": "criteria_comment",
                                "score": normalized,
                                "text": candidate_text,
                                "criterion_code": ccode,
                                "criterion_name": cname,
                            }
                        )
        for item in detail.get("gaps") or []:
            item_code = str(item.get("criterion_code") or "").strip()
            stage_code = _stage_code_from_criterion_code(item_code)
            candidate_text = _stage_problem_text_from_issue(dict(item))
            if stage_code and candidate_text:
                stage_problem_candidates.setdefault(stage_code, []).append(
                    {
                        "source": "gap",
                        "score": 0.0,
                        "text": candidate_text,
                        "criterion_code": item_code,
                        "criterion_name": str(item.get("criterion_name") or item.get("title") or "").strip(),
                    }
                )
        for item in detail.get("evidence_fragments") or []:
            item_code = str(item.get("criterion_code") or "").strip()
            stage_code = _stage_code_from_criterion_code(item_code)
            candidate_text = _stage_problem_text_from_issue(dict(item))
            if stage_code and candidate_text:
                stage_problem_candidates.setdefault(stage_code, []).append(
                    {
                        "source": "evidence",
                        "score": 5.0,
                        "text": candidate_text,
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
        rows.append({
            "stage_code": stage_code,
            "funnel_label": funnel_label,
            "stage_name": stage_name,
            "score": avg,
            "is_priority": is_priority,
            "criteria_detail": criteria_detail,
            "problem_summary": problem_summary,
            "problem_source": problem_source,
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
            call_meta = dict(detail.get("call") or {})
            client_phone = str(
                call_meta.get("contact_phone")
                or (artifact.interaction.metadata_ or {}).get("contact_phone")
                or ""
            ).strip() or None
            client_label = str(
                call_meta.get("contact_name") or client_phone
                or "Клиент"
            ).strip()
            time_label = artifact.call_started_at.strftime("%H:%M") if artifact.call_started_at else "—"
            date_label = artifact.call_started_at.date().isoformat() if artifact.call_started_at else None
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
                        "call_id": str(artifact.interaction.id),
                        "client_label": client_label,
                        "client_phone": client_phone,
                        "date_label": date_label,
                        "time_label": time_label,
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
) -> dict[str, Any] | None:
    """Build a compact deterministic deep-dive for the priority stage from existing payload data."""
    priority_stage = next((item for item in score_by_stage if item.get("is_priority")), None)
    if priority_stage is None:
        return None

    stage_code = str(priority_stage.get("stage_code") or "").strip()
    stage_name = str(priority_stage.get("stage_name") or "").strip()
    if not stage_code and not stage_name:
        return None

    problem_summary = _first_sentence(str(priority_stage.get("problem_summary") or ""))
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
    what_went_wrong = _first_sentence(str(focus_stage_deep_dive.get("what_went_wrong") or ""), limit=220)
    meaning = _first_sentence(str(focus_stage_deep_dive.get("why_it_matters") or ""), limit=260)
    what_was_missing = _coaching_missing_text(what_went_wrong, stage_code)
    next_time_action = _first_sentence(str(focus_stage_deep_dive.get("what_to_fix") or ""), limit=240)

    fact = _situation_fact_from_quote(client_text)
    if fact and what_was_missing:
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
        "pattern_title": _situation_pattern_title(
            stage_code=stage_code,
            stage_name=stage_name,
            what_went_wrong=what_went_wrong,
            client_text=client_text,
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


def _aggregate_finding_items(*, artifacts: list[ReportArtifact], key: str) -> list[dict[str, Any]]:
    """Aggregate repeated strength/gap findings into compact report items."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for item in detail.get(key) or []:
            label = str(
                item.get("title")
                or item.get("criterion_name")
                or item.get("criterion_code")
                or "Без названия"
            )
            grouped.setdefault(label, []).append(item)
    result: list[dict[str, Any]] = []
    for label, items in sorted(grouped.items(), key=lambda pair: len(pair[1]), reverse=True)[:5]:
        first = items[0]
        result.append(
            {
                "label": label,
                "signal": len(items),
                "criterion_code": str(first.get("criterion_code") or "").strip() or None,
                "interpretation": str(
                    first.get("impact")
                    or first.get("comment")
                    or first.get("evidence")
                    or "Подтверждено в нескольких звонках."
                ),
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


def _build_meaningful_call_list(*, window_artifacts: list[ReportArtifact]) -> list[dict[str, Any]]:
    """Build СПИСОК ЗВОНКОВ ДНЯ from meaningful_calls layer (SM-3).

    Includes all calls that pass _classify_meaningful_call — sales, follow-up,
    and meaningful support/service. Excludes beep, IVR, autoanswer, no-speech noise.
    Sorted by call time ascending. Coaching blocks are unaffected (use usable/coaching_core).
    """
    meaningful: list[ReportArtifact] = []
    for artifact in window_artifacts:
        is_meaningful, _ = _classify_meaningful_call(artifact)
        if is_meaningful:
            meaningful.append(artifact)
    meaningful.sort(key=lambda a: a.call_started_at or datetime.min.replace(tzinfo=UTC))
    return [_build_daily_call_row(item) for item in meaningful]


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


def _build_daily_call_row(artifact: ReportArtifact) -> dict[str, Any]:
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
    return {
        "interaction_id": str(artifact.interaction.id),
        "time": artifact.call_started_at.isoformat() if artifact.call_started_at else None,
        "client_or_phone": call.get("contact_name") or call.get("contact_phone") or (artifact.interaction.metadata_ or {}).get("contact_phone"),
        "duration_sec": artifact.interaction.duration_sec,
        "call_type": call_type,
        "scenario_type": classification.get("scenario_type"),
        "status": status,
        "next_step": follow_up.get("next_step_text"),
        "deadline": deadline,
        "reason": str(follow_up.get("reason_not_fixed") or "").strip() or None,
        "score_percent": _extract_score_percent(artifact.analysis),
        "unclassified_reason_code": unclassified_reason_code,
        "unclassified_reason_label": unclassified_reason_label,
        "unclassified_status_label": unclassified_status_label,
        "unclassified_context_label": unclassified_context_label,
        "business_outcome_reason_code": outcome.reason_code,
        "business_outcome_evidence": outcome.evidence,
        "business_outcome_confidence": outcome.confidence,
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


def _is_analysis_reusable_for_reporting(analysis: Analysis | None) -> tuple[bool, str]:
    """Return whether the persisted analysis is reusable for reporting."""
    if analysis is None:
        return False, "missing_analysis"
    if bool(getattr(analysis, "is_failed", False)):
        fail_reason = str(getattr(analysis, "fail_reason", "") or "").strip()
        if fail_reason:
            return False, fail_reason
        return False, "analysis_marked_failed"
    instruction_version = str(getattr(analysis, "instruction_version", "") or "").strip()
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

    def _client_meta(artifact: ReportArtifact) -> tuple[str, str]:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        call_meta = dict(detail.get("call") or {})
        name = str(call_meta.get("contact_name") or call_meta.get("contact_phone")
                   or (artifact.interaction.metadata_ or {}).get("contact_phone") or "Клиент").strip()
        ts = artifact.call_started_at.strftime("%H:%M") if artifact.call_started_at else "—"
        return name, ts

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
                name, ts = _client_meta(artifact)
                why = str(frag.get("why") or "").strip()
                situations.append({
                    "client_label": name,
                    "time_label": ts,
                    "quote": client_text[:120] + ("…" if len(client_text) > 120 else ""),
                    "context": why[:100] + ("…" if len(why) > 100 else "") if why else None,
                })
                if len(situations) >= 3:
                    return

    _add_from_fragments("missed_opportunity")
    if len(situations) < 3:
        _add_from_fragments(None)

    if len(situations) < 3:
        for artifact in artifacts:
            detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
            name, ts = _client_meta(artifact)
            for sig in (detail.get("product_signals") or []):
                quote = str(sig.get("quote") or "").strip()
                if len(quote) < 10 or quote in seen:
                    continue
                seen.add(quote)
                topic = str(sig.get("topic") or "").strip()
                situations.append({
                    "client_label": name,
                    "time_label": ts,
                    "quote": quote[:120] + ("…" if len(quote) > 120 else ""),
                    "context": topic[:100] if topic else None,
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
        label = str(item.get("label") or "").strip()
        if not label or label.strip().lower() in seen_titles:
            continue
        seen_titles.add(label.strip().lower())
        situations.append({
            "kind": "gap",
            "title": label,
            "signal": int(item.get("signal") or 0),
            "interpretation": str(item.get("interpretation") or "Выявлено в нескольких звонках."),
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
CALL_TOMORROW_STATUS_ORDER = ("agreed", "rescheduled", "open")


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


def _build_call_tomorrow(*, call_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Build КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА from final report-day outcomes.

    Selection rule (deterministic):
    - Include only final Договорённость, Перенос, Открыт
    - Exclude final Отказ, Тех/сервис and unclassified technical buckets
    - Priority groups: agreed → rescheduled → open
    - Within group: soonest deadline first, then call time
    - Deduplicate by client_label
    - Cap at 5 contacts total
    """
    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in CALL_TOMORROW_STATUS_ORDER}

    for row in call_list:
        status = str(row.get("status") or "")
        if status not in FINAL_SALES_LIKE_STATUSES:
            continue

        client_label = str(row.get("client_or_phone") or "").strip()
        if not client_label:
            continue

        next_step = str(row.get("next_step") or "").strip()
        scenario_type = str(row.get("scenario_type") or "").lower()
        time_label = _short_time_label(row.get("time")) or "—"
        deadline = str(row.get("deadline") or "").strip() or None

        grouped[status].append({
            "client_label": client_label,
            "time_label": time_label,
            "status": status,
            "deadline": deadline,
            "next_step": next_step,
            "reason": str(row.get("reason") or "").strip() or None,
            "scenario_type": scenario_type,
            "_sort_key": (str(deadline or "z"), time_label),
        })

    seen: set[str] = set()
    contacts: list[dict[str, Any]] = []
    for status in CALL_TOMORROW_STATUS_ORDER:
        for item in sorted(grouped[status], key=lambda x: x["_sort_key"]):
            if item["client_label"] in seen:
                continue
            seen.add(item["client_label"])
            contacts.append({
                "client_label": item["client_label"],
                "time_label": item["time_label"],
                "status": item["status"],
                "deadline": item["deadline"],
                "next_step": item["next_step"],
                "reason": item["reason"],
                "opening_script": _call_tomorrow_opening_script(
                    status=item["status"],
                    deadline=item["deadline"],
                    next_step=item["next_step"],
                    scenario_type=item["scenario_type"],
                ),
            })
            if len(contacts) >= 5:
                break
        if len(contacts) >= 5:
            break

    return {
        "is_placeholder": len(contacts) == 0,
        "contacts": contacts,
        "empty_state": "Нет коммерческих звонков для работы завтра по итогам отчётного дня.",
        "source_note": "derived_from_final_business_outcome_call_list",
    }


def _build_call_breakdown(
    *,
    improve_items: list[dict[str, Any]],
    artifacts: list[ReportArtifact],
) -> dict[str, Any]:
    """Build compact step-by-step breakdown of the most representative problem call.

    Selection rule: among calls containing the top gap label, pick the one with the
    lowest overall score (best illustrator of the problem).
    """
    _empty: dict[str, Any] = {
        "is_placeholder": True,
        "client_label": None,
        "time_label": None,
        "stage_steps": [],
        "worked": [],
        "to_fix": [],
        "recommendation": None,
    }
    if not improve_items or not artifacts:
        return _empty

    gap_label = improve_items[0]["label"]
    best_artifact: ReportArtifact | None = None
    best_score = float("inf")
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        has_gap = any(
            str(item.get("title") or item.get("criterion_name") or item.get("criterion_code") or "").strip() == gap_label
            for item in (detail.get("gaps") or [])
        )
        if has_gap:
            s = _extract_score_percent(artifact.analysis)
            if s < best_score:
                best_score = s
                best_artifact = artifact

    if best_artifact is None:
        return _empty

    detail = dict((best_artifact.analysis.scores_detail or {}) if best_artifact.analysis is not None else {})
    call_meta = dict(detail.get("call") or {})
    client_label = str(
        call_meta.get("contact_name") or call_meta.get("contact_phone")
        or (best_artifact.interaction.metadata_ or {}).get("contact_phone")
        or "Клиент"
    ).strip()
    time_label = best_artifact.call_started_at.strftime("%H:%M") if best_artifact.call_started_at else "—"

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
            "label": str(i.get("title") or i.get("criterion_name") or ""),
            "interpretation": str(i.get("impact") or i.get("comment") or i.get("evidence") or ""),
        }
        for i in (detail.get("strengths") or [])[:2]
        if str(i.get("title") or i.get("criterion_name") or "").strip()
    ]
    to_fix = [
        {
            "label": str(i.get("title") or i.get("criterion_name") or ""),
            "interpretation": str(i.get("impact") or i.get("comment") or i.get("evidence") or ""),
        }
        for i in (detail.get("gaps") or [])[:2]
        if str(i.get("title") or i.get("criterion_name") or "").strip()
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

    return {
        "is_placeholder": not stage_steps and not worked and not to_fix,
        "client_label": client_label,
        "time_label": time_label,
        "stage_steps": stage_steps,
        "worked": worked,
        "to_fix": to_fix,
        "recommendation": recommendation,
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
            item_label = str(
                gap_item.get("title") or gap_item.get("criterion_name") or gap_item.get("criterion_code") or ""
            ).strip()
            if item_label == gap_label:
                reason = str(
                    gap_item.get("comment") or gap_item.get("evidence") or gap_item.get("impact") or ""
                ).strip()
                score = _extract_score_percent(artifact.analysis)
                candidates.append((score, artifact, reason))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    _score, best, reason_text = candidates[0]
    detail = dict((best.analysis.scores_detail or {}) if best.analysis is not None else {})
    call_meta = dict(detail.get("call") or {})
    client_label = str(
        call_meta.get("contact_name") or call_meta.get("contact_phone")
        or (best.interaction.metadata_ or {}).get("contact_phone")
        or "Клиент"
    ).strip()
    time_label = (
        best.call_started_at.strftime("%H:%M") if best.call_started_at else "—"
    )
    reason_short = reason_text[:80] + "…" if len(reason_text) > 80 else reason_text
    return {
        "client_label": client_label,
        "time_label": time_label,
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
            item_label = str(item.get("title") or item.get("criterion_name") or item.get("criterion_code") or "").strip()
            if item_label == label:
                return str(item.get("comment") or item.get("evidence") or item.get("impact") or "").strip() or None
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
