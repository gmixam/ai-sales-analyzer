"""Schema and validation helpers for additive LLM2 report evidence."""

from __future__ import annotations

from copy import deepcopy
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.calls.analyzer import CHECKLIST_DEFINITION


SUPPORTED_REPORT_EVIDENCE_VERSION = "v1"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceQuality(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    WEAK = "weak"
    INSUFFICIENT = "insufficient"


class Speaker(StrEnum):
    MANAGER = "manager"
    CLIENT = "client"
    UNKNOWN = "unknown"


class BusinessSignal(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BusinessOutcomeStatus(StrEnum):
    AGREEMENT = "agreement"
    RESCHEDULED = "rescheduled"
    REFUSAL = "refusal"
    OPEN = "open"
    TECH_SERVICE = "tech_service"
    NOT_SUITABLE = "not_suitable"


class ProblemType(StrEnum):
    MISSING_ROLE = "missing_role"
    MISSING_PROCESS = "missing_process"
    MISSING_NEED = "missing_need"
    EARLY_PRESENTATION = "early_presentation"
    WEAK_NEXT_STEP = "weak_next_step"
    WEAK_CONTACT_START = "weak_contact_start"
    OTHER = "other"


class MomentType(StrEnum):
    WORKED = "worked"
    MISSED = "missed"
    RISK = "risk"


class VoiceTopic(StrEnum):
    NEED = "need"
    OBJECTION = "objection"
    RISK = "risk"
    PRICE = "price"
    PROCESS = "process"
    TIMING = "timing"
    PRODUCT_INTEREST = "product_interest"
    SERVICE_ISSUE = "service_issue"
    REFUSAL = "refusal"


class AdditionalSituationType(StrEnum):
    STRENGTH = "strength"
    GROWTH_ZONE = "growth_zone"
    RISK = "risk"
    MISSED_OPPORTUNITY = "missed_opportunity"
    SERVICE_ISSUE = "service_issue"
    CUSTOMER_SIGNAL = "customer_signal"


class FollowUpStatus(StrEnum):
    AGREEMENT = "agreement"
    RESCHEDULED = "rescheduled"
    OPEN = "open"


class FollowUpPriority(StrEnum):
    HOT = "hot"
    RESCHEDULED = "rescheduled"
    OPEN = "open"


class ClientNameConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SummaryHotness(StrEnum):
    HOT = "hot"
    WARM = "warm"
    LOW = "low"


class SemanticCaseType(StrEnum):
    GROWTH_ZONE = "growth_zone"
    MISSED_OPPORTUNITY = "missed_opportunity"
    STRONG_PRACTICE = "strong_practice"
    CUSTOMER_SIGNAL = "customer_signal"
    SERVICE_ISSUE = "service_issue"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ReportBlockEvidenceType(StrEnum):
    MANAGER_GAP = "manager_gap"
    CUSTOMER_SIGNAL = "customer_signal"
    STRONG_PRACTICE = "strong_practice"
    FOLLOW_UP = "follow_up"
    SERVICE_ISSUE = "service_issue"
    INSUFFICIENT = "insufficient"
    NONE = "none"


class CoachingMomentEvidenceType(StrEnum):
    DIRECT_QUOTE = "direct_quote"
    ABSENCE_IN_CONTEXT = "absence_in_context"
    INFERRED_FROM_DIALOGUE = "inferred_from_dialogue"


class ReportBlockRole(StrEnum):
    COACHING_PROBLEM = "coaching_problem"
    CUSTOMER_SIGNAL = "customer_signal"
    FOLLOW_UP_ACTION = "follow_up_action"
    NEUTRAL_SUMMARY = "neutral_summary"
    STRONG_PRACTICE = "strong_practice"


class ReportBlockTitleMode(StrEnum):
    PROBLEM = "problem"
    NEUTRAL = "neutral"
    POSITIVE = "positive"


class ReportBlockFitReason(StrEnum):
    MANAGER_GAP_WITH_DIRECT_EVIDENCE = "manager_gap_with_direct_evidence"
    MANAGER_GAP_WITH_INDIRECT_EVIDENCE = "manager_gap_with_indirect_evidence"
    MISSED_OPPORTUNITY_WITH_CUSTOMER_SIGNAL = "missed_opportunity_with_customer_signal"
    COACHABLE_MANAGER_MOMENT = "coachable_manager_moment"
    DIRECT_CUSTOMER_SIGNAL = "direct_customer_signal"
    CLIENT_REQUESTED_NEXT_ACTION = "client_requested_next_action"
    STRONG_MANAGER_PRACTICE = "strong_manager_practice"
    SERVICE_CONTEXT = "service_context"
    CUSTOMER_SIGNAL_WITHOUT_MANAGER_GAP = "customer_signal_without_manager_gap"
    POSITIVE_DIAGNOSIS_NOT_PROBLEM_CASE = "positive_diagnosis_not_problem_case"
    WEAK_MANAGER_EVIDENCE = "weak_manager_evidence"
    WEAK_CUSTOMER_EVIDENCE = "weak_customer_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_RELEVANT_FOR_BLOCK = "not_relevant_for_block"
    NO_FOLLOW_UP_NEEDED = "no_follow_up_needed"


class _ReportEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DialogueTurn(_ReportEvidenceModel):
    speaker: Speaker
    text: str
    timestamp_start: float | int | str | None = None
    timestamp_end: float | int | str | None = None


class BusinessOutcomeEvidence(_ReportEvidenceModel):
    status: BusinessOutcomeStatus
    confidence: Priority
    reason: str
    evidence_quote: str | None = None
    evidence_speaker: Speaker = Speaker.UNKNOWN
    needs_human_review: bool = False


class SituationCandidate(_ReportEvidenceModel):
    stage_code: str
    problem_type: ProblemType
    situation_title: str
    priority: Priority
    evidence_quality: EvidenceQuality
    dialogue_fragment: list[DialogueTurn] = Field(default_factory=list)
    what_happened: str
    what_it_means: str
    what_was_missing: str
    next_time_action: str
    scripts: list[str] = Field(default_factory=list)
    usable_in_report: bool = True


class ManagerCoachingMoment(_ReportEvidenceModel):
    stage_code: str
    moment_type: MomentType
    priority: Priority
    evidence_quality: EvidenceQuality
    dialogue_fragment: list[DialogueTurn] = Field(default_factory=list)
    what_happened: str
    what_better: str
    usable_in_report: bool = True


class VoiceOfCustomerItem(_ReportEvidenceModel):
    quote: str
    speaker: Speaker
    topic: VoiceTopic
    meaning: str
    business_signal: BusinessSignal
    stage_code: str
    usable_in_report: bool = True


class AdditionalSituationItem(_ReportEvidenceModel):
    type: AdditionalSituationType
    title: str
    priority: Priority
    evidence_quality: EvidenceQuality
    what_happened: str
    why_it_matters: str
    recommended_action: str
    stage_code: str
    usable_in_report: bool = True


class FollowUpCandidate(_ReportEvidenceModel):
    status: FollowUpStatus
    client_label: str
    next_step: str
    deadline: str | None = None
    priority: FollowUpPriority
    first_phrase: str
    why_follow_up: str
    usable_in_report: bool = True


class QuoteBankItem(_ReportEvidenceModel):
    quote: str
    speaker: Speaker
    topic: str
    stage_code: str
    evidence_quality: EvidenceQuality
    usable_in_report: bool = True


class CallReportSummary(_ReportEvidenceModel):
    short_topic: str | None = Field(default=None, max_length=120)
    short_context: str | None = Field(default=None, max_length=280)
    client_display_name: str | None = Field(default=None, max_length=120)
    client_name_confidence: ClientNameConfidence | None = None
    hotness: SummaryHotness | None = None
    hotness_reason: str | None = Field(default=None, max_length=280)
    manager_next_action: str | None = Field(default=None, max_length=280)
    suggested_manager_phrase: str | None = Field(default=None, max_length=240)


class ReportBlockFitItem(_ReportEvidenceModel):
    fit: bool
    score: int = Field(ge=0, le=100)
    reason_code: ReportBlockFitReason
    evidence_type: ReportBlockEvidenceType
    block_role: ReportBlockRole | None = None
    title_mode: ReportBlockTitleMode | None = None
    problem_fit: "ReportBlockProblemFit | None" = None
    evidence_target: str | None = Field(default=None, max_length=280)
    gap_proven: bool | None = None
    coaching_moment: "CoachingMoment | None" = None


class ReportBlockProblemFit(_ReportEvidenceModel):
    score: int = Field(ge=0, le=100)
    problem_signal: str | None = Field(default=None, max_length=160)
    explanation: str | None = Field(default=None, max_length=320)


class CoachingMoment(_ReportEvidenceModel):
    summary: str
    missing_action: str | None = None
    why_it_matters: str | None = None
    supporting_quote: str | None = None
    evidence_type: CoachingMomentEvidenceType
    confidence: Priority


class ReportBlockFit(_ReportEvidenceModel):
    situation_day: ReportBlockFitItem
    call_breakdown: ReportBlockFitItem
    voice_of_customer: ReportBlockFitItem
    additional_situations: ReportBlockFitItem
    call_tomorrow: ReportBlockFitItem


class SemanticCase(_ReportEvidenceModel):
    case_title: str
    case_type: SemanticCaseType
    stage_code: str | None = None
    priority: Priority
    evidence_quality: EvidenceQuality
    core_meaning: str
    why_this_call_matters: str
    customer_signal: str | None = None
    manager_behavior: str
    coaching_diagnosis: str
    recommended_next_action: str
    best_dialogue_fragment: list[DialogueTurn] = Field(default_factory=list)
    report_block_fit: ReportBlockFit | None = None
    usable_in_report: bool = True


class ReportEvidence(_ReportEvidenceModel):
    business_outcome: BusinessOutcomeEvidence | None = None
    call_report_summary: CallReportSummary | None = None
    semantic_case: SemanticCase | None = None
    situation_candidates: list[SituationCandidate] = Field(default_factory=list)
    manager_coaching_moments: list[ManagerCoachingMoment] = Field(default_factory=list)
    voice_of_customer: list[VoiceOfCustomerItem] = Field(default_factory=list)
    additional_situations: list[AdditionalSituationItem] = Field(default_factory=list)
    follow_up_candidates: list[FollowUpCandidate] = Field(default_factory=list)
    quote_bank: list[QuoteBankItem] = Field(default_factory=list)


class ReportEvidencePackage(_ReportEvidenceModel):
    report_evidence_version: str
    report_evidence: ReportEvidence = Field(default_factory=ReportEvidence)


class ReportEvidenceValidationIssue(_ReportEvidenceModel):
    code: str
    path: str
    message: str


class ReportEvidenceValidationResult(_ReportEvidenceModel):
    is_valid: bool
    version: str | None = None
    errors: list[ReportEvidenceValidationIssue] = Field(default_factory=list)
    warnings: list[ReportEvidenceValidationIssue] = Field(default_factory=list)
    normalized: dict[str, Any] = Field(default_factory=dict)


def canonical_report_stage_codes() -> set[str]:
    """Return stage codes from the approved MVP-1 checklist definition."""

    return {
        str(stage.get("stage_code") or "").strip()
        for stage in CHECKLIST_DEFINITION.get("stages", [])
        if str(stage.get("stage_code") or "").strip()
    }


def validate_report_evidence(
    scores_detail: dict[str, Any] | None,
    transcript: str | None,
) -> ReportEvidenceValidationResult:
    """Validate additive `report_evidence v1` without changing analysis reuse/rendering behavior."""

    detail = dict(scores_detail or {})
    errors: list[ReportEvidenceValidationIssue] = []
    warnings: list[ReportEvidenceValidationIssue] = []
    version = _as_non_empty_str(detail.get("report_evidence_version"))
    raw_report_evidence = detail.get("report_evidence")

    if raw_report_evidence in (None, ""):
        if version:
            warnings.append(
                _issue(
                    code="version_without_report_evidence",
                    path="report_evidence_version",
                    message="report_evidence_version is present but report_evidence is missing.",
                )
            )
        return ReportEvidenceValidationResult(
            is_valid=True,
            version=version,
            errors=[],
            warnings=warnings,
            normalized={},
        )

    if not version:
        errors.append(
            _issue(
                code="missing_report_evidence_version",
                path="report_evidence_version",
                message="report_evidence_version is required when report_evidence is present.",
            )
        )
    elif version != SUPPORTED_REPORT_EVIDENCE_VERSION:
        errors.append(
            _issue(
                code="unsupported_report_evidence_version",
                path="report_evidence_version",
                message=f"Unsupported report_evidence_version: {version}",
            )
        )

    normalized_report_evidence = _normalize_report_evidence_payload(
        raw_report_evidence=raw_report_evidence,
        transcript=transcript,
        warnings=warnings,
    )

    package_payload = {
        "report_evidence_version": version or SUPPORTED_REPORT_EVIDENCE_VERSION,
        "report_evidence": normalized_report_evidence,
    }
    package: ReportEvidencePackage | None = None
    if version == SUPPORTED_REPORT_EVIDENCE_VERSION:
        try:
            package = ReportEvidencePackage.model_validate(package_payload)
        except ValidationError as exc:
            for err in exc.errors():
                errors.append(
                    _issue(
                        code="schema_validation_error",
                        path=_format_pydantic_location(err.get("loc", ())),
                        message=str(err.get("msg") or "Invalid report_evidence payload."),
                    )
                )
    elif version:
        # Avoid validating future unsupported versions against the v1 shape.
        package = None
    else:
        try:
            package = ReportEvidencePackage.model_validate(package_payload)
        except ValidationError as exc:
            for err in exc.errors():
                errors.append(
                    _issue(
                        code="schema_validation_error",
                        path=_format_pydantic_location(err.get("loc", ())),
                        message=str(err.get("msg") or "Invalid report_evidence payload."),
                    )
                )

    if package is not None:
        _validate_package_semantics(
            package=package,
            transcript=transcript,
            errors=errors,
            warnings=warnings,
        )

    return ReportEvidenceValidationResult(
        is_valid=not errors,
        version=version,
        errors=errors,
        warnings=warnings,
        normalized=package.model_dump(mode="json") if package is not None and not errors else {},
    )


def _validate_package_semantics(
    *,
    package: ReportEvidencePackage,
    transcript: str | None,
    errors: list[ReportEvidenceValidationIssue],
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    stage_codes = canonical_report_stage_codes()
    evidence = package.report_evidence

    if evidence.business_outcome and evidence.business_outcome.evidence_quote:
        _validate_grounded_text(
            text=evidence.business_outcome.evidence_quote,
            transcript=transcript,
            path="report_evidence.business_outcome.evidence_quote",
            evidence_quality=None,
            usable_in_report=True,
            errors=errors,
            warnings=warnings,
        )

    if evidence.call_report_summary is not None:
        _validate_call_report_summary(
            evidence=evidence,
            errors=errors,
            warnings=warnings,
        )

    if evidence.semantic_case is not None:
        _validate_semantic_case(
            semantic_case=evidence.semantic_case,
            stage_codes=stage_codes,
            transcript=transcript,
            errors=errors,
            warnings=warnings,
        )

    for index, item in enumerate(evidence.situation_candidates):
        base = f"report_evidence.situation_candidates[{index}]"
        _validate_stage_code(item.stage_code, stage_codes, f"{base}.stage_code", errors)
        _validate_insufficient_evidence(
            evidence_quality=item.evidence_quality,
            usable_in_report=item.usable_in_report,
            path=base,
            errors=errors,
            warnings=warnings,
        )
        for turn_index, turn in enumerate(item.dialogue_fragment):
            _validate_grounded_text(
                text=turn.text,
                transcript=transcript,
                path=f"{base}.dialogue_fragment[{turn_index}].text",
                evidence_quality=item.evidence_quality,
                usable_in_report=item.usable_in_report,
                errors=errors,
                warnings=warnings,
            )
        if _normalized_text(item.what_happened) == _normalized_text(item.what_was_missing):
            warnings.append(
                _issue(
                    code="duplicated_situation_fields",
                    path=base,
                    message="what_happened and what_was_missing should not be identical.",
                )
            )

    for index, item in enumerate(evidence.manager_coaching_moments):
        base = f"report_evidence.manager_coaching_moments[{index}]"
        _validate_stage_code(item.stage_code, stage_codes, f"{base}.stage_code", errors)
        _validate_insufficient_evidence(
            evidence_quality=item.evidence_quality,
            usable_in_report=item.usable_in_report,
            path=base,
            errors=errors,
            warnings=warnings,
        )
        for turn_index, turn in enumerate(item.dialogue_fragment):
            _validate_grounded_text(
                text=turn.text,
                transcript=transcript,
                path=f"{base}.dialogue_fragment[{turn_index}].text",
                evidence_quality=item.evidence_quality,
                usable_in_report=item.usable_in_report,
                errors=errors,
                warnings=warnings,
            )

    for index, item in enumerate(evidence.voice_of_customer):
        base = f"report_evidence.voice_of_customer[{index}]"
        _validate_stage_code(item.stage_code, stage_codes, f"{base}.stage_code", errors)
        _validate_grounded_text(
            text=item.quote,
            transcript=transcript,
            path=f"{base}.quote",
            evidence_quality=None,
            usable_in_report=item.usable_in_report,
            errors=errors,
            warnings=warnings,
        )

    for index, item in enumerate(evidence.additional_situations):
        base = f"report_evidence.additional_situations[{index}]"
        _validate_stage_code(item.stage_code, stage_codes, f"{base}.stage_code", errors)
        _validate_insufficient_evidence(
            evidence_quality=item.evidence_quality,
            usable_in_report=item.usable_in_report,
            path=base,
            errors=errors,
            warnings=warnings,
        )

    for index, item in enumerate(evidence.quote_bank):
        base = f"report_evidence.quote_bank[{index}]"
        _validate_stage_code(item.stage_code, stage_codes, f"{base}.stage_code", errors)
        _validate_insufficient_evidence(
            evidence_quality=item.evidence_quality,
            usable_in_report=item.usable_in_report,
            path=base,
            errors=errors,
            warnings=warnings,
        )
        _validate_grounded_text(
            text=item.quote,
            transcript=transcript,
            path=f"{base}.quote",
            evidence_quality=item.evidence_quality,
            usable_in_report=item.usable_in_report,
            errors=errors,
            warnings=warnings,
        )


REPORT_BLOCK_FIT_ITEM_NAMES = (
    "situation_day",
    "call_breakdown",
    "voice_of_customer",
    "additional_situations",
    "call_tomorrow",
)

COACHING_MOMENT_DIRECT_QUOTE_ALIASES = {
    "direct",
    "direct_evidence",
    "direct_quote",
    "dialogue_quote",
    "quote",
    "verbatim",
    "verbatim_quote",
}

COACHING_MOMENT_ABSENCE_ALIASES = {
    "absence",
    "absence_context",
    "absence_in_context",
    "missing",
    "missing_in_context",
    "not_found",
    "not_present",
}

COACHING_MOMENT_INFERRED_ALIASES = {
    "",
    "indirect",
    "inferred",
    "inferred_from_dialogue",
    "insufficient",
    "insufficient_evidence",
    "n_a",
    "na",
    "no_direct_quote",
    "no_evidence",
    "none",
    "not_applicable",
    "summary",
    "weak",
}

COACHING_MOMENT_ABSENCE_TEXT_MARKERS = (
    "в доступной записи не",
    "в фрагменте не",
    "не было",
    "не зафикс",
    "не прозвуч",
    "не соглас",
    "не уточн",
    "не хватило",
    "отсутств",
    "без срока",
    "без даты",
    "without",
    "missing",
    "not captured",
)


def _normalize_report_evidence_payload(
    *,
    raw_report_evidence: Any,
    transcript: str | None,
    warnings: list[ReportEvidenceValidationIssue],
) -> Any:
    payload = deepcopy(raw_report_evidence)
    if not isinstance(payload, dict):
        return payload
    semantic_case = payload.get("semantic_case")
    if not isinstance(semantic_case, dict):
        return payload
    block_fit = semantic_case.get("report_block_fit")
    if not isinstance(block_fit, dict):
        return payload

    for block_name in REPORT_BLOCK_FIT_ITEM_NAMES:
        item = block_fit.get(block_name)
        if not isinstance(item, dict):
            continue
        _normalize_report_block_fit_coaching_moment(
            item=item,
            path=f"report_evidence.semantic_case.report_block_fit.{block_name}.coaching_moment",
            transcript=transcript,
            warnings=warnings,
        )
    return payload


def _normalize_report_block_fit_coaching_moment(
    *,
    item: dict[str, Any],
    path: str,
    transcript: str | None,
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    if "coaching_moment" not in item:
        return

    moment = item.get("coaching_moment")
    if moment in (None, ""):
        item["coaching_moment"] = None
        return

    item_fit = _coerced_bool(item.get("fit"))
    if item_fit is False:
        item["coaching_moment"] = None
        warnings.append(
            _issue(
                code="coaching_moment_ignored_for_non_fit_block",
                path=path,
                message=(
                    "coaching_moment was ignored because the report_block_fit item "
                    "has fit=false."
                ),
            )
        )
        return

    if not isinstance(moment, dict):
        return

    original_evidence_type = _coaching_moment_evidence_type_key(
        moment.get("evidence_type")
    )
    normalized_evidence_type = _normalized_coaching_moment_evidence_type(moment)
    if normalized_evidence_type is not None:
        moment["evidence_type"] = normalized_evidence_type
        if normalized_evidence_type != original_evidence_type:
            warnings.append(
                _issue(
                    code="coaching_moment_evidence_type_normalized",
                    path=f"{path}.evidence_type",
                    message=(
                        "Unsupported coaching_moment.evidence_type was normalized "
                        "to a supported non-quote/direct evidence type."
                    ),
                )
            )

    if (
        moment.get("evidence_type") != CoachingMomentEvidenceType.DIRECT_QUOTE.value
        and _normalized_text(moment.get("supporting_quote"))
        and not _text_is_grounded(moment.get("supporting_quote"), transcript)
    ):
        moment["supporting_quote"] = None
        warnings.append(
            _issue(
                code="coaching_moment_supporting_quote_dropped",
                path=f"{path}.supporting_quote",
                message=(
                    "Ungrounded supporting_quote was dropped from a non-direct "
                    "coaching_moment."
                ),
            )
        )


def _normalized_coaching_moment_evidence_type(moment: dict[str, Any]) -> str | None:
    evidence_type = _coaching_moment_evidence_type_key(moment.get("evidence_type"))
    if evidence_type in COACHING_MOMENT_DIRECT_QUOTE_ALIASES:
        return CoachingMomentEvidenceType.DIRECT_QUOTE.value
    if evidence_type in COACHING_MOMENT_ABSENCE_ALIASES:
        return CoachingMomentEvidenceType.ABSENCE_IN_CONTEXT.value
    if evidence_type in COACHING_MOMENT_INFERRED_ALIASES:
        return _infer_non_quote_coaching_moment_evidence_type(moment)
    if "quote" in evidence_type:
        return CoachingMomentEvidenceType.DIRECT_QUOTE.value
    if _normalized_text(moment.get("summary")):
        return _infer_non_quote_coaching_moment_evidence_type(moment)
    return None


def _infer_non_quote_coaching_moment_evidence_type(moment: dict[str, Any]) -> str:
    text = " ".join(
        _normalized_text(moment.get(field))
        for field in ("summary", "missing_action", "why_it_matters")
    )
    if any(marker in text for marker in COACHING_MOMENT_ABSENCE_TEXT_MARKERS):
        return CoachingMomentEvidenceType.ABSENCE_IN_CONTEXT.value
    return CoachingMomentEvidenceType.INFERRED_FROM_DIALOGUE.value


def _coaching_moment_evidence_type_key(value: Any) -> str:
    text = _normalized_text(value)
    return re.sub(r"[\s/.-]+", "_", text)


def _coerced_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = _normalized_text(value)
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return None


SEMANTIC_CASE_GENERIC_TEXT_MARKERS = (
    "нужно улучшить",
    "нужно лучше",
    "улучшить качество",
    "повысить качество",
    "более качественно",
    "работать с клиентом",
    "выявлять потребности",
    "закрывать потребности",
    "задать уточняющие вопросы",
    "зафиксировать следующий шаг",
    "требует внимания",
    "требует доработки",
    "в целом",
    "общий",
    "generic",
)


def _validate_semantic_case(
    *,
    semantic_case: SemanticCase,
    stage_codes: set[str],
    transcript: str | None,
    errors: list[ReportEvidenceValidationIssue],
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    base = "report_evidence.semantic_case"
    if semantic_case.stage_code:
        _validate_stage_code(semantic_case.stage_code, stage_codes, f"{base}.stage_code", errors)

    _validate_insufficient_evidence(
        evidence_quality=semantic_case.evidence_quality,
        usable_in_report=semantic_case.usable_in_report,
        path=base,
        errors=errors,
        warnings=warnings,
    )

    if (
        semantic_case.case_type == SemanticCaseType.INSUFFICIENT_EVIDENCE
        and semantic_case.usable_in_report
    ):
        errors.append(
            _issue(
                code="semantic_case_insufficient_marked_usable",
                path=base,
                message="semantic_case with case_type=insufficient_evidence must not be usable in report.",
            )
        )

    for turn_index, turn in enumerate(semantic_case.best_dialogue_fragment):
        _validate_grounded_text(
            text=turn.text,
            transcript=transcript,
            path=f"{base}.best_dialogue_fragment[{turn_index}].text",
            evidence_quality=semantic_case.evidence_quality,
            usable_in_report=semantic_case.usable_in_report,
            errors=errors,
            warnings=warnings,
        )

    if not semantic_case.usable_in_report:
        return

    if semantic_case.evidence_quality in {EvidenceQuality.DIRECT, EvidenceQuality.INDIRECT}:
        if (
            not semantic_case.best_dialogue_fragment
            and not _semantic_case_has_non_quote_coaching_moment(semantic_case)
        ):
            errors.append(
                _issue(
                    code="semantic_case_missing_grounded_fragment",
                    path=f"{base}.best_dialogue_fragment",
                    message=(
                        "Usable semantic_case with direct/indirect evidence must include a grounded "
                        "best_dialogue_fragment or a non-quote coaching_moment for absence/inferred evidence."
                    ),
                )
            )

    required_fields = {
        "case_title": semantic_case.case_title,
        "core_meaning": semantic_case.core_meaning,
        "why_this_call_matters": semantic_case.why_this_call_matters,
        "manager_behavior": semantic_case.manager_behavior,
        "coaching_diagnosis": semantic_case.coaching_diagnosis,
        "recommended_next_action": semantic_case.recommended_next_action,
    }
    for field, value in required_fields.items():
        if _semantic_case_text_is_generic(value, allow_short=(field == "case_title")):
            errors.append(
                _issue(
                    code="semantic_case_generic_field",
                    path=f"{base}.{field}",
                    message=f"semantic_case.{field} must be concrete and non-generic when usable_in_report=true.",
                )
            )

    if (
        semantic_case.customer_signal is not None
        and _semantic_case_text_is_generic(semantic_case.customer_signal, allow_short=False)
    ):
        errors.append(
            _issue(
                code="semantic_case_generic_field",
                path=f"{base}.customer_signal",
                message="semantic_case.customer_signal must be concrete and non-generic when provided.",
            )
        )

    if semantic_case.report_block_fit is not None:
        _validate_semantic_case_block_fit(
            semantic_case=semantic_case,
            transcript=transcript,
            base=base,
            errors=errors,
            warnings=warnings,
        )

    normalized_values = {
        field: _normalized_text(value)
        for field, value in required_fields.items()
        if _normalized_text(value)
    }
    duplicates = {
        text
        for text in normalized_values.values()
        if list(normalized_values.values()).count(text) > 1
    }
    if duplicates:
        warnings.append(
            _issue(
                code="semantic_case_duplicated_fields",
                path=base,
                message="semantic_case meaning fields should not repeat identical text.",
            )
        )


def _validate_semantic_case_block_fit(
    *,
    semantic_case: SemanticCase,
    transcript: str | None,
    base: str,
    errors: list[ReportEvidenceValidationIssue],
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    block_fit = semantic_case.report_block_fit
    if block_fit is None:
        return
    fit_items = {
        "situation_day": block_fit.situation_day,
        "call_breakdown": block_fit.call_breakdown,
        "voice_of_customer": block_fit.voice_of_customer,
        "additional_situations": block_fit.additional_situations,
        "call_tomorrow": block_fit.call_tomorrow,
    }
    for block_name, item in fit_items.items():
        item_path = f"{base}.report_block_fit.{block_name}"
        if item.fit and item.score < 50:
            warnings.append(
                _issue(
                    code="report_block_fit_low_positive_score",
                    path=f"{item_path}.score",
                    message="report_block_fit item is marked fit=true but score is below 50.",
                )
            )
        if not item.fit and item.score > 60:
            warnings.append(
                _issue(
                    code="report_block_fit_high_negative_score",
                    path=f"{item_path}.score",
                    message="report_block_fit item is marked fit=false but score is above 60.",
                )
            )
        if item.problem_fit is not None and item.problem_fit.score < 50 and item.fit:
            warnings.append(
                _issue(
                    code="report_block_problem_fit_low_score",
                    path=f"{item_path}.problem_fit.score",
                    message="report_block_fit problem_fit is weak for a block marked fit=true.",
                )
            )
        if item.evidence_target is not None and _semantic_case_text_is_generic(item.evidence_target, allow_short=False):
            warnings.append(
                _issue(
                    code="report_block_evidence_target_generic",
                    path=f"{item_path}.evidence_target",
                    message="report_block_fit.evidence_target should explain what the fragment proves.",
                )
            )
        if item.coaching_moment is not None:
            _validate_coaching_moment(
                coaching_moment=item.coaching_moment,
                transcript=transcript,
                path=f"{item_path}.coaching_moment",
                errors=errors,
                warnings=warnings,
            )

    situation_fit = block_fit.situation_day
    if situation_fit.fit:
        if (
            situation_fit.block_role is not None
            and situation_fit.block_role != ReportBlockRole.COACHING_PROBLEM
        ):
            warnings.append(
                _issue(
                    code="situation_day_fit_without_coaching_problem_role",
                    path=f"{base}.report_block_fit.situation_day.block_role",
                    message="situation_day fit should use block_role=coaching_problem.",
                )
            )
        if (
            situation_fit.title_mode is not None
            and situation_fit.title_mode != ReportBlockTitleMode.PROBLEM
        ):
            warnings.append(
                _issue(
                    code="situation_day_fit_without_problem_title_mode",
                    path=f"{base}.report_block_fit.situation_day.title_mode",
                    message="situation_day fit should use a problem-oriented title mode.",
                )
            )
        if situation_fit.gap_proven is False:
            warnings.append(
                _issue(
                    code="situation_day_fit_gap_not_proven",
                    path=f"{base}.report_block_fit.situation_day.gap_proven",
                    message="situation_day fit should have gap_proven=true when a manager gap is claimed.",
                )
            )
        if semantic_case.case_type not in {
            SemanticCaseType.GROWTH_ZONE,
            SemanticCaseType.MISSED_OPPORTUNITY,
        }:
            warnings.append(
                _issue(
                    code="situation_day_fit_without_problem_case",
                    path=f"{base}.report_block_fit.situation_day",
                    message=(
                        "situation_day should usually be fit=true only for growth_zone or "
                        "missed_opportunity semantic cases."
                    ),
                )
            )
        if situation_fit.evidence_type != ReportBlockEvidenceType.MANAGER_GAP:
            warnings.append(
                _issue(
                    code="situation_day_fit_without_manager_gap",
                    path=f"{base}.report_block_fit.situation_day.evidence_type",
                    message="situation_day fit should be grounded in a manager_gap evidence type.",
                )
            )

    call_breakdown_fit = block_fit.call_breakdown
    if call_breakdown_fit.fit:
        if (
            call_breakdown_fit.block_role is not None
            and call_breakdown_fit.block_role
            not in {ReportBlockRole.COACHING_PROBLEM, ReportBlockRole.STRONG_PRACTICE}
        ):
            warnings.append(
                _issue(
                    code="call_breakdown_fit_wrong_role",
                    path=f"{base}.report_block_fit.call_breakdown.block_role",
                    message="call_breakdown fit should be a coaching_problem or strong_practice role.",
                )
            )
        if (
            call_breakdown_fit.block_role == ReportBlockRole.COACHING_PROBLEM
            and call_breakdown_fit.title_mode is not None
            and call_breakdown_fit.title_mode != ReportBlockTitleMode.PROBLEM
        ):
            warnings.append(
                _issue(
                    code="call_breakdown_problem_fit_without_problem_title_mode",
                    path=f"{base}.report_block_fit.call_breakdown.title_mode",
                    message="problem call_breakdown fit should use title_mode=problem.",
                )
            )

    voice_fit = block_fit.voice_of_customer
    if (
        voice_fit.fit
        and voice_fit.block_role is not None
        and voice_fit.block_role != ReportBlockRole.CUSTOMER_SIGNAL
    ):
        warnings.append(
            _issue(
                code="voice_of_customer_fit_wrong_role",
                path=f"{base}.report_block_fit.voice_of_customer.block_role",
                message="voice_of_customer fit should use block_role=customer_signal.",
            )
        )

    tomorrow_fit = block_fit.call_tomorrow
    if (
        tomorrow_fit.fit
        and tomorrow_fit.block_role is not None
        and tomorrow_fit.block_role != ReportBlockRole.FOLLOW_UP_ACTION
    ):
        warnings.append(
            _issue(
                code="call_tomorrow_fit_wrong_role",
                path=f"{base}.report_block_fit.call_tomorrow.block_role",
                message="call_tomorrow fit should use block_role=follow_up_action.",
            )
        )

    if semantic_case.case_type == SemanticCaseType.INSUFFICIENT_EVIDENCE:
        for block_name, item in fit_items.items():
            if item.fit:
                errors.append(
                    _issue(
                        code="insufficient_semantic_case_block_fit_true",
                        path=f"{base}.report_block_fit.{block_name}.fit",
                        message="insufficient_evidence semantic_case cannot be fit=true for report blocks.",
                    )
                )


def _semantic_case_has_non_quote_coaching_moment(semantic_case: SemanticCase) -> bool:
    block_fit = semantic_case.report_block_fit
    if block_fit is None:
        return False
    return any(
        item.fit
        and item.coaching_moment is not None
        and item.coaching_moment.evidence_type
        in {
            CoachingMomentEvidenceType.ABSENCE_IN_CONTEXT,
            CoachingMomentEvidenceType.INFERRED_FROM_DIALOGUE,
        }
        for item in (
            block_fit.situation_day,
            block_fit.call_breakdown,
            block_fit.voice_of_customer,
            block_fit.additional_situations,
            block_fit.call_tomorrow,
        )
    )


def _validate_coaching_moment(
    *,
    coaching_moment: CoachingMoment,
    transcript: str | None,
    path: str,
    errors: list[ReportEvidenceValidationIssue],
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    if _semantic_case_text_is_generic(coaching_moment.summary, allow_short=False):
        errors.append(
            _issue(
                code="coaching_moment_generic_summary",
                path=f"{path}.summary",
                message="coaching_moment.summary must describe the concrete moment, not a generic coaching principle.",
            )
        )
    if (
        coaching_moment.evidence_type == CoachingMomentEvidenceType.DIRECT_QUOTE
        and coaching_moment.supporting_quote
    ):
        _validate_grounded_text(
            text=coaching_moment.supporting_quote,
            transcript=transcript,
            path=f"{path}.supporting_quote",
            evidence_quality=None,
            usable_in_report=True,
            errors=errors,
            warnings=warnings,
        )
    elif coaching_moment.supporting_quote and not _text_is_grounded(
        coaching_moment.supporting_quote,
        transcript,
    ):
        coaching_moment.supporting_quote = None
        warnings.append(
            _issue(
                code="coaching_moment_supporting_quote_dropped",
                path=f"{path}.supporting_quote",
                message=(
                    "Ungrounded supporting_quote was dropped from a non-direct "
                    "coaching_moment."
                ),
            )
        )
    if (
        coaching_moment.evidence_type == CoachingMomentEvidenceType.DIRECT_QUOTE
        and not coaching_moment.supporting_quote
    ):
        warnings.append(
            _issue(
                code="coaching_moment_direct_quote_without_quote",
                path=f"{path}.supporting_quote",
                message="coaching_moment with evidence_type=direct_quote should include a grounded supporting_quote.",
            )
        )


def _semantic_case_text_is_generic(value: str | None, *, allow_short: bool) -> bool:
    text = _normalized_text(value)
    if not text:
        return True
    if not allow_short and len(text) < 18:
        return True
    return any(marker in text for marker in SEMANTIC_CASE_GENERIC_TEXT_MARKERS)


def _validate_call_report_summary(
    *,
    evidence: ReportEvidence,
    errors: list[ReportEvidenceValidationIssue],
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    summary = evidence.call_report_summary
    if summary is None:
        return
    if summary.client_display_name is None and summary.client_name_confidence is not None:
        warnings.append(
            _issue(
                code="client_name_confidence_without_name",
                path="report_evidence.call_report_summary.client_name_confidence",
                message="client_name_confidence should be omitted or null when client_display_name is null.",
            )
        )

    phrase = _normalized_text(summary.suggested_manager_phrase)
    if phrase:
        client_quotes = _known_client_quote_texts(evidence)
        if phrase in client_quotes:
            errors.append(
                _issue(
                    code="suggested_manager_phrase_copies_client_quote",
                    path="report_evidence.call_report_summary.suggested_manager_phrase",
                    message="suggested_manager_phrase must be phrased as the manager and must not copy a client quote.",
                )
            )
        status = evidence.business_outcome.status if evidence.business_outcome else None
        has_follow_up = any(item.usable_in_report for item in evidence.follow_up_candidates)
        if status in {
            BusinessOutcomeStatus.REFUSAL,
            BusinessOutcomeStatus.TECH_SERVICE,
            BusinessOutcomeStatus.NOT_SUITABLE,
        } and not has_follow_up:
            warnings.append(
                _issue(
                    code="suggested_manager_phrase_on_non_follow_up_outcome",
                    path="report_evidence.call_report_summary.suggested_manager_phrase",
                    message="Refusal, tech/service, and not_suitable outcomes usually should not include a commercial suggested_manager_phrase.",
                )
            )


def _known_client_quote_texts(evidence: ReportEvidence) -> set[str]:
    quotes: set[str] = set()
    if (
        evidence.business_outcome
        and evidence.business_outcome.evidence_speaker == Speaker.CLIENT
        and evidence.business_outcome.evidence_quote
    ):
        quotes.add(_normalized_text(evidence.business_outcome.evidence_quote))
    for item in evidence.voice_of_customer:
        if item.speaker == Speaker.CLIENT:
            quotes.add(_normalized_text(item.quote))
    for item in evidence.quote_bank:
        if item.speaker == Speaker.CLIENT:
            quotes.add(_normalized_text(item.quote))
    return {quote for quote in quotes if quote}


def _validate_stage_code(
    stage_code: str,
    allowed_stage_codes: set[str],
    path: str,
    errors: list[ReportEvidenceValidationIssue],
) -> None:
    if stage_code not in allowed_stage_codes:
        errors.append(
            _issue(
                code="invalid_stage_code",
                path=path,
                message=f"Unknown stage_code: {stage_code}",
            )
        )


def _validate_insufficient_evidence(
    *,
    evidence_quality: EvidenceQuality,
    usable_in_report: bool,
    path: str,
    errors: list[ReportEvidenceValidationIssue],
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    if evidence_quality != EvidenceQuality.INSUFFICIENT:
        return
    issue = _issue(
        code="insufficient_evidence_marked_usable",
        path=path,
        message="Items with evidence_quality=insufficient must not be rendered as usable report proof.",
    )
    if usable_in_report:
        errors.append(issue)
    else:
        warnings.append(
            _issue(
                code="insufficient_evidence_not_usable",
                path=path,
                message="Item is marked insufficient and correctly disabled for report use.",
            )
        )


def _validate_grounded_text(
    *,
    text: str | None,
    transcript: str | None,
    path: str,
    evidence_quality: EvidenceQuality | None,
    usable_in_report: bool,
    errors: list[ReportEvidenceValidationIssue],
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    value = _normalized_text(text)
    if not value:
        return
    if _text_is_grounded(text, transcript):
        return
    if evidence_quality == EvidenceQuality.INSUFFICIENT and not usable_in_report:
        warnings.append(
            _issue(
                code="ungrounded_insufficient_evidence",
                path=path,
                message="Text is not found in transcript, but evidence is marked insufficient and not usable.",
            )
        )
        return
    errors.append(
        _issue(
            code="ungrounded_evidence_text",
            path=path,
            message="Evidence text is not grounded in the transcript.",
        )
    )


def _text_is_grounded(text: str | None, transcript: str | None) -> bool:
    value = _normalized_text(text)
    haystack = _normalized_text(transcript)
    if not value:
        return True
    if not haystack:
        return False
    return value in haystack


def _normalized_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


def _as_non_empty_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _format_pydantic_location(location: Any) -> str:
    if not location:
        return "report_evidence"
    return ".".join(str(part) for part in location)


def _issue(*, code: str, path: str, message: str) -> ReportEvidenceValidationIssue:
    return ReportEvidenceValidationIssue(code=code, path=path, message=message)
