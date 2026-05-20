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


class CoachingMomentProofType(StrEnum):
    DIRECT_GAP = "direct_gap"
    ABSENCE_IN_CONTEXT = "absence_in_context"
    SEQUENCE_INFERENCE = "sequence_inference"
    CONTEXT_SUPPORT = "context_support"


class CoachingMomentQuoteRole(StrEnum):
    PROVES_GAP = "proves_gap"
    SUPPORTS_CONTEXT = "supports_context"
    COUNTER_EVIDENCE = "counter_evidence"
    NOT_APPLICABLE = "not_applicable"


class ReportBlockRole(StrEnum):
    COACHING_PROBLEM = "coaching_problem"
    CUSTOMER_SIGNAL = "customer_signal"
    FOLLOW_UP_ACTION = "follow_up_action"
    NEUTRAL_SUMMARY = "neutral_summary"
    STRONG_PRACTICE = "strong_practice"


class BlockCandidateRole(StrEnum):
    COACHING_PROBLEM = "coaching_problem"
    CUSTOMER_SIGNAL = "customer_signal"
    FOLLOW_UP_ACTION = "follow_up_action"
    NEUTRAL_SUMMARY = "neutral_summary"
    STRONG_PRACTICE = "strong_practice"
    COMMERCIAL_OPPORTUNITY = "commercial_opportunity"
    SKILL_CHALLENGE = "skill_challenge"
    CALL_LIST_CONTEXT = "call_list_context"


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
    manager_visible_summary: str | None = Field(default=None, max_length=640)
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
    gap_claim: str | None = Field(default=None, max_length=280)
    proof_type: CoachingMomentProofType | None = None
    proof_explanation: str | None = Field(default=None, max_length=420)
    quote_role: CoachingMomentQuoteRole | None = None
    counter_evidence: list[str] = Field(default_factory=list, max_length=3)


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


class BlockCandidateBase(_ReportEvidenceModel):
    fit: bool
    score: int = Field(ge=0, le=100)
    role: BlockCandidateRole | None = None
    title_mode: ReportBlockTitleMode | None = None
    stage_code: str | None = None
    main_thesis: str | None = Field(default=None, max_length=360)
    why_it_matters: str | None = Field(default=None, max_length=420)
    proof_type: CoachingMomentProofType | None = None
    proof_explanation: str | None = Field(default=None, max_length=520)
    supporting_quote: str | None = None
    quote_role: CoachingMomentQuoteRole | None = None
    counter_evidence: list[str] = Field(default_factory=list, max_length=3)
    insufficiency_reason: str | None = Field(default=None, max_length=360)


class SituationDayBlockCandidate(BlockCandidateBase):
    what_happened: str | None = Field(default=None, max_length=520)
    what_was_missing: str | None = Field(default=None, max_length=420)
    better_next_action: str | None = Field(default=None, max_length=420)


class CallBreakdownMoment(_ReportEvidenceModel):
    situation: str | None = Field(default=None, max_length=360)
    essence: str | None = Field(default=None, max_length=420)
    proof: str | None = Field(default=None, max_length=420)
    proof_explanation: str | None = Field(default=None, max_length=420)
    what_was_missing: str | None = Field(default=None, max_length=360)
    better_next_action: str | None = Field(default=None, max_length=360)
    better_action: str | None = Field(default=None, max_length=360)


class CallBreakdownBlockCandidate(BlockCandidateBase):
    moments: list[CallBreakdownMoment] = Field(default_factory=list, max_length=3)


class VoiceOfCustomerBlockCandidate(BlockCandidateBase):
    customer_signal: str | None = Field(default=None, max_length=420)
    customer_need_or_objection: str | None = Field(default=None, max_length=420)
    what_it_means: str | None = Field(default=None, max_length=420)
    manager_should_do: str | None = Field(default=None, max_length=420)
    manager_action: str | None = Field(default=None, max_length=420)


class MoneyOnTableBlockCandidate(BlockCandidateBase):
    commercial_opportunity: str | None = Field(default=None, max_length=420)
    signal_strength: BusinessSignal | None = None
    monetizable_signal: str | None = Field(default=None, max_length=420)
    what_was_monetizable: str | None = Field(default=None, max_length=420)
    manager_action_or_gap: str | None = Field(default=None, max_length=420)
    manager_action: str | None = Field(default=None, max_length=420)
    next_commercial_action: str | None = Field(default=None, max_length=420)


class TomorrowFollowUpBlockCandidate(BlockCandidateBase):
    client_label: str | None = Field(default=None, max_length=120)
    next_action: str | None = Field(default=None, max_length=420)
    client_next_action: str | None = Field(default=None, max_length=420)
    why_follow_up: str | None = Field(default=None, max_length=420)
    opening_phrase: str | None = Field(default=None, max_length=280)
    risk_if_not_followed_up: str | None = Field(default=None, max_length=420)
    risk_if_no_follow_up: str | None = Field(default=None, max_length=420)


class TomorrowChallengeBlockCandidate(BlockCandidateBase):
    skill: str | None = Field(default=None, max_length=240)
    skill_signal: str | None = Field(default=None, max_length=240)
    practice_action: str | None = Field(default=None, max_length=420)
    practice_focus: str | None = Field(default=None, max_length=420)
    behavior_standard: str | None = Field(default=None, max_length=420)
    example_phrase: str | None = Field(default=None, max_length=280)


class CallListContextBlockCandidate(BlockCandidateBase):
    short_topic: str | None = Field(default=None, max_length=120)
    short_context: str | None = Field(default=None, max_length=280)
    manager_visible_summary: str | None = Field(default=None, max_length=640)
    call_list_context_rich: str | None = Field(default=None, max_length=640)
    action_hint: str | None = Field(default=None, max_length=280)
    final_action_hint: str | None = Field(default=None, max_length=280)


class ReportBlockCandidates(_ReportEvidenceModel):
    situation_day: SituationDayBlockCandidate | None = None
    call_breakdown: CallBreakdownBlockCandidate | None = None
    voice_of_customer: VoiceOfCustomerBlockCandidate | None = None
    money_on_table: MoneyOnTableBlockCandidate | None = None
    tomorrow_follow_up: TomorrowFollowUpBlockCandidate | None = None
    tomorrow_challenge: TomorrowChallengeBlockCandidate | None = None
    call_list_context: CallListContextBlockCandidate | None = None


class ReportEvidence(_ReportEvidenceModel):
    business_outcome: BusinessOutcomeEvidence | None = None
    call_report_summary: CallReportSummary | None = None
    semantic_case: SemanticCase | None = None
    block_candidates: ReportBlockCandidates | None = None
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

    if evidence.block_candidates is not None:
        _validate_block_candidates(
            block_candidates=evidence.block_candidates,
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


BLOCK_CANDIDATE_NAMES = (
    "situation_day",
    "call_breakdown",
    "voice_of_customer",
    "money_on_table",
    "tomorrow_follow_up",
    "tomorrow_challenge",
    "call_list_context",
)

BLOCK_CANDIDATE_REQUIRED_FIELDS = {
    "situation_day": (
        "main_thesis",
        "what_happened",
        "why_it_matters",
        "what_was_missing",
        "better_next_action",
    ),
    "call_breakdown": ("main_thesis", "why_it_matters"),
    "voice_of_customer": (
        "customer_signal",
        "customer_need_or_objection",
        "manager_should_do",
    ),
    "money_on_table": (
        "commercial_opportunity",
        "signal_strength",
        "monetizable_signal",
        "manager_action_or_gap",
        "next_commercial_action",
    ),
    "tomorrow_follow_up": (
        "client_label",
        "next_action",
        "why_follow_up",
        "opening_phrase",
        "risk_if_not_followed_up",
    ),
    "tomorrow_challenge": ("skill", "practice_action", "behavior_standard"),
    "call_list_context": ("short_topic", "short_context"),
}

BLOCK_CANDIDATE_TEXT_FIELDS = {
    "situation_day": (
        "main_thesis",
        "what_happened",
        "why_it_matters",
        "what_was_missing",
        "better_next_action",
    ),
    "call_breakdown": ("main_thesis", "why_it_matters"),
    "voice_of_customer": (
        "customer_signal",
        "customer_need_or_objection",
        "manager_should_do",
    ),
    "money_on_table": (
        "commercial_opportunity",
        "monetizable_signal",
        "manager_action_or_gap",
        "next_commercial_action",
    ),
    "tomorrow_follow_up": (
        "next_action",
        "why_follow_up",
        "opening_phrase",
        "risk_if_not_followed_up",
    ),
    "tomorrow_challenge": ("practice_action", "behavior_standard", "example_phrase"),
    "call_list_context": (
        "short_topic",
        "short_context",
        "manager_visible_summary",
        "call_list_context_rich",
        "action_hint",
    ),
}

BLOCK_CANDIDATE_FIELD_ALIASES = {
    "voice_of_customer": {
        "customer_need_or_objection": ("customer_need_or_objection", "what_it_means"),
        "manager_should_do": ("manager_should_do", "manager_action"),
    },
    "money_on_table": {
        "monetizable_signal": ("monetizable_signal", "what_was_monetizable"),
        "manager_action_or_gap": ("manager_action_or_gap", "manager_action"),
    },
    "tomorrow_follow_up": {
        "next_action": ("next_action", "client_next_action"),
        "risk_if_not_followed_up": (
            "risk_if_not_followed_up",
            "risk_if_no_follow_up",
        ),
    },
    "tomorrow_challenge": {
        "skill": ("skill", "skill_signal"),
        "practice_action": ("practice_action", "practice_focus"),
    },
    "call_list_context": {
        "action_hint": ("action_hint", "final_action_hint"),
    },
}

CALL_BREAKDOWN_MOMENT_FIELD_ALIASES = {
    "proof": ("proof", "proof_explanation"),
    "better_next_action": ("better_next_action", "better_action"),
}


def _block_candidate_field_value(
    *,
    block_name: str,
    candidate: BlockCandidateBase,
    field: str,
) -> Any:
    aliases = BLOCK_CANDIDATE_FIELD_ALIASES.get(block_name, {}).get(field, (field,))
    for alias in aliases:
        value = getattr(candidate, alias, None)
        if isinstance(value, StrEnum):
            return value
        if _normalized_text(value):
            return value
    return getattr(candidate, field, None)


def _call_breakdown_moment_field_value(
    *,
    moment: CallBreakdownMoment,
    field: str,
) -> Any:
    aliases = CALL_BREAKDOWN_MOMENT_FIELD_ALIASES.get(field, (field,))
    for alias in aliases:
        value = getattr(moment, alias, None)
        if _normalized_text(value):
            return value
    return getattr(moment, field, None)

BLOCK_CANDIDATE_ALLOWED_ROLES = {
    "situation_day": {
        BlockCandidateRole.COACHING_PROBLEM,
        BlockCandidateRole.STRONG_PRACTICE,
    },
    "call_breakdown": {
        BlockCandidateRole.COACHING_PROBLEM,
        BlockCandidateRole.STRONG_PRACTICE,
    },
    "voice_of_customer": {BlockCandidateRole.CUSTOMER_SIGNAL},
    "money_on_table": {BlockCandidateRole.COMMERCIAL_OPPORTUNITY},
    "tomorrow_follow_up": {BlockCandidateRole.FOLLOW_UP_ACTION},
    "tomorrow_challenge": {
        BlockCandidateRole.COACHING_PROBLEM,
        BlockCandidateRole.SKILL_CHALLENGE,
    },
    "call_list_context": {
        BlockCandidateRole.NEUTRAL_SUMMARY,
        BlockCandidateRole.CALL_LIST_CONTEXT,
    },
}

BLOCK_CANDIDATE_EXPECTED_TITLE_MODE = {
    "voice_of_customer": {ReportBlockTitleMode.NEUTRAL},
    "money_on_table": {ReportBlockTitleMode.NEUTRAL, ReportBlockTitleMode.PROBLEM},
    "tomorrow_follow_up": {ReportBlockTitleMode.NEUTRAL},
    "call_list_context": {ReportBlockTitleMode.NEUTRAL},
}

BLOCK_CANDIDATE_PROBLEM_BLOCKS = {
    "situation_day",
    "call_breakdown",
    "tomorrow_challenge",
}


def _validate_block_candidates(
    *,
    block_candidates: ReportBlockCandidates,
    stage_codes: set[str],
    transcript: str | None,
    errors: list[ReportEvidenceValidationIssue],
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    for block_name in BLOCK_CANDIDATE_NAMES:
        candidate = getattr(block_candidates, block_name)
        if candidate is None:
            continue
        path = f"report_evidence.block_candidates.{block_name}"
        _validate_block_candidate(
            block_name=block_name,
            candidate=candidate,
            stage_codes=stage_codes,
            transcript=transcript,
            path=path,
            errors=errors,
            warnings=warnings,
        )


def _validate_block_candidate(
    *,
    block_name: str,
    candidate: BlockCandidateBase,
    stage_codes: set[str],
    transcript: str | None,
    path: str,
    errors: list[ReportEvidenceValidationIssue],
    warnings: list[ReportEvidenceValidationIssue],
) -> None:
    stage_code = _as_non_empty_str(candidate.stage_code)
    if candidate.fit and not stage_code:
        errors.append(
            _issue(
                code="block_candidate_missing_stage_code",
                path=f"{path}.stage_code",
                message="fit=true block candidate must include canonical stage_code.",
            )
        )
    elif stage_code:
        _validate_stage_code(stage_code, stage_codes, f"{path}.stage_code", errors)

    if candidate.fit and candidate.score < 50:
        errors.append(
            _issue(
                code="block_candidate_low_fit_score",
                path=f"{path}.score",
                message="block_candidates item has fit=true but score is below 50.",
            )
        )
    elif not candidate.fit and candidate.score > 60:
        warnings.append(
            _issue(
                code="block_candidate_high_nonfit_score",
                path=f"{path}.score",
                message="block_candidates item has fit=false but score is above 60.",
            )
        )

    if candidate.supporting_quote:
        _validate_grounded_text(
            text=candidate.supporting_quote,
            transcript=transcript,
            path=f"{path}.supporting_quote",
            evidence_quality=EvidenceQuality.INSUFFICIENT if not candidate.fit else None,
            usable_in_report=candidate.fit,
            errors=errors,
            warnings=warnings,
        )

    if not candidate.fit:
        return

    _validate_block_candidate_required_fields(
        block_name=block_name,
        candidate=candidate,
        path=path,
        errors=errors,
    )
    _validate_block_candidate_role(
        block_name=block_name,
        candidate=candidate,
        path=path,
        errors=errors,
    )
    _validate_block_candidate_text_quality(
        block_name=block_name,
        candidate=candidate,
        path=path,
        errors=errors,
    )
    _validate_block_candidate_duplicates(
        block_name=block_name,
        candidate=candidate,
        path=path,
        errors=errors,
    )
    _validate_block_candidate_proof(
        block_name=block_name,
        candidate=candidate,
        path=path,
        errors=errors,
    )


def _validate_block_candidate_required_fields(
    *,
    block_name: str,
    candidate: BlockCandidateBase,
    path: str,
    errors: list[ReportEvidenceValidationIssue],
) -> None:
    common_fields = (
        "role",
        "title_mode",
        "proof_type",
        "proof_explanation",
        "quote_role",
    )
    for field in common_fields + BLOCK_CANDIDATE_REQUIRED_FIELDS[block_name]:
        value = _block_candidate_field_value(
            block_name=block_name,
            candidate=candidate,
            field=field,
        )
        if isinstance(value, list):
            missing = not value
        elif isinstance(value, StrEnum):
            missing = False
        else:
            missing = not _normalized_text(value)
        if missing:
            errors.append(
                _issue(
                    code="block_candidate_missing_required_field",
                    path=f"{path}.{field}",
                    message=f"fit=true block candidate must include {field}.",
                )
            )

    if block_name == "call_breakdown":
        _validate_call_breakdown_candidate_moments(
            candidate=candidate,
            path=path,
            errors=errors,
        )


def _validate_call_breakdown_candidate_moments(
    *,
    candidate: BlockCandidateBase,
    path: str,
    errors: list[ReportEvidenceValidationIssue],
) -> None:
    if not isinstance(candidate, CallBreakdownBlockCandidate):
        return
    if not candidate.moments:
        errors.append(
            _issue(
                code="block_candidate_missing_required_field",
                path=f"{path}.moments",
                message="call_breakdown block candidate must include one to three moments.",
            )
        )
        return
    for index, moment in enumerate(candidate.moments):
        moment_path = f"{path}.moments[{index}]"
        for field in ("situation", "essence", "proof", "better_next_action"):
            if not _normalized_text(
                _call_breakdown_moment_field_value(moment=moment, field=field)
            ):
                errors.append(
                    _issue(
                        code="block_candidate_missing_required_field",
                        path=f"{moment_path}.{field}",
                        message=f"call_breakdown moment must include {field}.",
                    )
                )
        if (
            _normalized_text(moment.what_was_missing)
            and _normalized_text(moment.what_was_missing)
            == _normalized_text(
                _call_breakdown_moment_field_value(
                    moment=moment,
                    field="better_next_action",
                )
            )
        ):
            errors.append(
                _issue(
                    code="block_candidate_duplicate_missing_action",
                    path=moment_path,
                    message=(
                        "what_was_missing and better_next_action must not repeat "
                        "identical text."
                    ),
                )
            )


def _validate_block_candidate_role(
    *,
    block_name: str,
    candidate: BlockCandidateBase,
    path: str,
    errors: list[ReportEvidenceValidationIssue],
) -> None:
    if candidate.role is None:
        return
    allowed_roles = BLOCK_CANDIDATE_ALLOWED_ROLES[block_name]
    if candidate.role not in allowed_roles:
        errors.append(
            _issue(
                code="block_candidate_role_mismatch",
                path=f"{path}.role",
                message=(
                    f"{block_name} block candidate uses role={candidate.role}, "
                    "which is not valid for this block."
                ),
            )
        )

    if candidate.title_mode is None:
        return
    expected_title_modes = BLOCK_CANDIDATE_EXPECTED_TITLE_MODE.get(block_name)
    if candidate.role == BlockCandidateRole.COACHING_PROBLEM:
        expected_title_modes = {ReportBlockTitleMode.PROBLEM}
    elif candidate.role == BlockCandidateRole.STRONG_PRACTICE:
        expected_title_modes = {ReportBlockTitleMode.POSITIVE}
    elif candidate.role == BlockCandidateRole.SKILL_CHALLENGE:
        expected_title_modes = {ReportBlockTitleMode.PROBLEM, ReportBlockTitleMode.NEUTRAL}
    if expected_title_modes is not None and candidate.title_mode not in expected_title_modes:
        errors.append(
            _issue(
                code="block_candidate_title_mode_mismatch",
                path=f"{path}.title_mode",
                message=f"{block_name} block candidate title_mode does not match its role.",
            )
        )


def _validate_block_candidate_text_quality(
    *,
    block_name: str,
    candidate: BlockCandidateBase,
    path: str,
    errors: list[ReportEvidenceValidationIssue],
) -> None:
    for field in BLOCK_CANDIDATE_TEXT_FIELDS[block_name]:
        value = _block_candidate_field_value(
            block_name=block_name,
            candidate=candidate,
            field=field,
        )
        if not _normalized_text(value):
            continue
        allow_short = block_name == "call_list_context" and field == "short_topic"
        if _semantic_case_text_is_generic(value, allow_short=allow_short):
            errors.append(
                _issue(
                    code="block_candidate_generic_field",
                    path=f"{path}.{field}",
                    message=(
                        f"block_candidates.{block_name}.{field} must be concrete "
                        "and block-ready."
                    ),
                )
            )

    if isinstance(candidate, CallBreakdownBlockCandidate):
        for index, moment in enumerate(candidate.moments):
            for field in ("situation", "essence", "proof", "better_next_action"):
                value = _call_breakdown_moment_field_value(
                    moment=moment,
                    field=field,
                )
                if _normalized_text(value) and _semantic_case_text_is_generic(
                    value,
                    allow_short=False,
                ):
                    errors.append(
                        _issue(
                            code="block_candidate_generic_field",
                            path=f"{path}.moments[{index}].{field}",
                            message=(
                                f"call_breakdown moment {field} must be concrete "
                                "and block-ready."
                            ),
                        )
                    )


def _validate_block_candidate_duplicates(
    *,
    block_name: str,
    candidate: BlockCandidateBase,
    path: str,
    errors: list[ReportEvidenceValidationIssue],
) -> None:
    if isinstance(candidate, SituationDayBlockCandidate):
        missing = _normalized_text(candidate.what_was_missing)
        action = _normalized_text(candidate.better_next_action)
        if missing and missing == action:
            errors.append(
                _issue(
                    code="block_candidate_duplicate_missing_action",
                    path=path,
                    message=(
                        "what_was_missing and better_next_action must not repeat "
                        "identical text."
                    ),
                )
            )

    if block_name == "situation_day":
        return


def _validate_block_candidate_proof(
    *,
    block_name: str,
    candidate: BlockCandidateBase,
    path: str,
    errors: list[ReportEvidenceValidationIssue],
) -> None:
    if candidate.proof_type is None or candidate.quote_role is None:
        return

    if (
        candidate.supporting_quote
        and candidate.quote_role == CoachingMomentQuoteRole.NOT_APPLICABLE
    ):
        errors.append(
            _issue(
                code="block_candidate_quote_role_conflict",
                path=f"{path}.quote_role",
                message=(
                    "quote_role=not_applicable cannot be used when "
                    "supporting_quote is present."
                ),
            )
        )

    if candidate.quote_role == CoachingMomentQuoteRole.COUNTER_EVIDENCE:
        errors.append(
            _issue(
                code="block_candidate_proof_conflict",
                path=f"{path}.quote_role",
                message=(
                    "fit=true block candidate cannot use a counter-evidence quote "
                    "as report proof."
                ),
            )
        )

    counter_evidence = [
        item for item in candidate.counter_evidence if _normalized_text(item)
    ]
    if counter_evidence and candidate.role == BlockCandidateRole.COACHING_PROBLEM:
        errors.append(
            _issue(
                code="block_candidate_proof_conflict",
                path=f"{path}.counter_evidence",
                message=(
                    "Problem-oriented block candidate contains counter_evidence "
                    "and must not be used as a proven manager gap."
                ),
            )
        )

    if candidate.proof_type == CoachingMomentProofType.DIRECT_GAP:
        if candidate.role != BlockCandidateRole.COACHING_PROBLEM:
            errors.append(
                _issue(
                    code="block_candidate_direct_gap_wrong_role",
                    path=f"{path}.proof_type",
                    message=(
                        "proof_type=direct_gap is only valid for coaching_problem "
                        "block candidates."
                    ),
                )
            )
        if candidate.quote_role != CoachingMomentQuoteRole.PROVES_GAP:
            errors.append(
                _issue(
                    code="block_candidate_quote_role_conflict",
                    path=f"{path}.quote_role",
                    message="proof_type=direct_gap requires quote_role=proves_gap.",
                )
            )
        if not _normalized_text(candidate.supporting_quote):
            errors.append(
                _issue(
                    code="block_candidate_direct_gap_without_quote",
                    path=f"{path}.supporting_quote",
                    message="proof_type=direct_gap requires a grounded supporting_quote.",
                )
            )
        elif _block_candidate_direct_gap_overclaimed(candidate):
            errors.append(
                _issue(
                    code="block_candidate_direct_gap_overclaim",
                    path=f"{path}.supporting_quote",
                    message=(
                        "supporting_quote is context or counter-evidence, not "
                        "direct proof of the claimed manager gap."
                    ),
                )
            )

    if (
        candidate.quote_role == CoachingMomentQuoteRole.PROVES_GAP
        and candidate.proof_type != CoachingMomentProofType.DIRECT_GAP
    ):
        errors.append(
            _issue(
                code="block_candidate_quote_role_conflict",
                path=f"{path}.quote_role",
                message="quote_role=proves_gap requires proof_type=direct_gap.",
            )
        )

    if (
        candidate.quote_role == CoachingMomentQuoteRole.SUPPORTS_CONTEXT
        and candidate.proof_type == CoachingMomentProofType.DIRECT_GAP
    ):
        errors.append(
            _issue(
                code="block_candidate_quote_role_conflict",
                path=f"{path}.quote_role",
                message="quote_role=supports_context cannot be used with proof_type=direct_gap.",
            )
        )

    if (
        block_name in BLOCK_CANDIDATE_PROBLEM_BLOCKS
        and candidate.role == BlockCandidateRole.COACHING_PROBLEM
        and candidate.proof_type == CoachingMomentProofType.CONTEXT_SUPPORT
    ):
        errors.append(
            _issue(
                code="block_candidate_context_support_problem_claim",
                path=f"{path}.proof_type",
                message=(
                    "proof_type=context_support is not enough for a "
                    "problem-oriented block candidate."
                ),
            )
        )


def _block_candidate_direct_gap_overclaimed(candidate: BlockCandidateBase) -> bool:
    claim_text = _block_candidate_gap_claim_text(candidate)
    return (
        _quote_looks_like_counter_evidence_for_gap_text(
            supporting_quote=candidate.supporting_quote,
            gap_claim_text=claim_text,
        )
        or _quote_looks_like_context_only_for_gap_text(
            supporting_quote=candidate.supporting_quote,
            gap_claim_text=claim_text,
        )
    )


def _block_candidate_gap_claim_text(candidate: BlockCandidateBase) -> str:
    parts: list[str | None] = [
        candidate.main_thesis,
        candidate.why_it_matters,
        candidate.proof_explanation,
    ]
    if isinstance(candidate, SituationDayBlockCandidate):
        parts.extend(
            [
                candidate.what_happened,
                candidate.what_was_missing,
                candidate.better_next_action,
            ]
        )
    elif isinstance(candidate, CallBreakdownBlockCandidate):
        for moment in candidate.moments:
            parts.extend(
                [
                    moment.situation,
                    moment.essence,
                    _call_breakdown_moment_field_value(
                        moment=moment,
                        field="proof",
                    ),
                    moment.what_was_missing,
                    _call_breakdown_moment_field_value(
                        moment=moment,
                        field="better_next_action",
                    ),
                ]
            )
    elif isinstance(candidate, VoiceOfCustomerBlockCandidate):
        parts.extend(
            [
                candidate.customer_signal,
                _block_candidate_field_value(
                    block_name="voice_of_customer",
                    candidate=candidate,
                    field="customer_need_or_objection",
                ),
                _block_candidate_field_value(
                    block_name="voice_of_customer",
                    candidate=candidate,
                    field="manager_should_do",
                ),
            ]
        )
    elif isinstance(candidate, MoneyOnTableBlockCandidate):
        parts.extend(
            [
                candidate.commercial_opportunity,
                _block_candidate_field_value(
                    block_name="money_on_table",
                    candidate=candidate,
                    field="monetizable_signal",
                ),
                _block_candidate_field_value(
                    block_name="money_on_table",
                    candidate=candidate,
                    field="manager_action_or_gap",
                ),
                candidate.next_commercial_action,
            ]
        )
    elif isinstance(candidate, TomorrowFollowUpBlockCandidate):
        parts.extend(
            [
                _block_candidate_field_value(
                    block_name="tomorrow_follow_up",
                    candidate=candidate,
                    field="next_action",
                ),
                candidate.why_follow_up,
                _block_candidate_field_value(
                    block_name="tomorrow_follow_up",
                    candidate=candidate,
                    field="risk_if_not_followed_up",
                ),
            ]
        )
    elif isinstance(candidate, TomorrowChallengeBlockCandidate):
        parts.extend(
            [
                _block_candidate_field_value(
                    block_name="tomorrow_challenge",
                    candidate=candidate,
                    field="skill",
                ),
                _block_candidate_field_value(
                    block_name="tomorrow_challenge",
                    candidate=candidate,
                    field="practice_action",
                ),
                candidate.behavior_standard,
            ]
        )
    return " ".join(str(part or "") for part in parts)


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
                block_name=block_name,
                block_fit_item=item,
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
    block_name: str,
    block_fit_item: ReportBlockFitItem,
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
    proof_conflict = _coaching_moment_problem_proof_conflict(
        coaching_moment=coaching_moment,
        block_name=block_name,
        block_fit_item=block_fit_item,
    )
    if proof_conflict is not None:
        errors.append(
            _issue(
                code="coaching_moment_proof_conflict",
                path=path,
                message=proof_conflict,
            )
        )


def _coaching_moment_problem_proof_conflict(
    *,
    coaching_moment: CoachingMoment,
    block_name: str,
    block_fit_item: ReportBlockFitItem,
) -> str | None:
    if block_name not in {"situation_day", "call_breakdown"}:
        return None
    if block_fit_item.fit is not True:
        return None
    if block_fit_item.evidence_type != ReportBlockEvidenceType.MANAGER_GAP:
        return None
    if block_fit_item.block_role not in {None, ReportBlockRole.COACHING_PROBLEM}:
        return None
    counter_evidence = [
        item for item in coaching_moment.counter_evidence if _normalized_text(item)
    ]
    if counter_evidence:
        return (
            "Problem-oriented coaching_moment contains counter_evidence and must "
            "not be used as proven manager gap."
        )
    if coaching_moment.quote_role == CoachingMomentQuoteRole.COUNTER_EVIDENCE:
        return "supporting_quote is marked as counter_evidence, not proof of the manager gap."
    if (
        coaching_moment.quote_role == CoachingMomentQuoteRole.SUPPORTS_CONTEXT
        and coaching_moment.proof_type
        not in {
            CoachingMomentProofType.ABSENCE_IN_CONTEXT,
            CoachingMomentProofType.SEQUENCE_INFERENCE,
        }
    ):
        return "supporting_quote only supports context and does not prove the manager gap."
    if coaching_moment.proof_type == CoachingMomentProofType.CONTEXT_SUPPORT:
        return "proof_type=context_support is not enough for a problem block."
    if (
        coaching_moment.evidence_type == CoachingMomentEvidenceType.DIRECT_QUOTE
        and coaching_moment.supporting_quote
        and _quote_looks_like_counter_evidence_for_gap(coaching_moment)
    ):
        return (
            "supporting_quote appears to show the allegedly missing manager action, "
            "so it is counter-evidence rather than proof."
        )
    if (
        coaching_moment.proof_type == CoachingMomentProofType.DIRECT_GAP
        and coaching_moment.supporting_quote
        and _quote_looks_like_context_only_for_gap_text(
            supporting_quote=coaching_moment.supporting_quote,
            gap_claim_text=" ".join(
                str(value or "")
                for value in (
                    coaching_moment.gap_claim,
                    coaching_moment.summary,
                    coaching_moment.missing_action,
                    coaching_moment.proof_explanation,
                )
            ),
        )
    ):
        return "supporting_quote is context, not direct proof of the claimed manager gap."
    return None


def _quote_looks_like_counter_evidence_for_gap(coaching_moment: CoachingMoment) -> bool:
    return _quote_looks_like_counter_evidence_for_gap_text(
        supporting_quote=coaching_moment.supporting_quote,
        gap_claim_text=" ".join(
            str(value or "")
            for value in (
                coaching_moment.gap_claim,
                coaching_moment.summary,
                coaching_moment.missing_action,
                coaching_moment.proof_explanation,
            )
        ),
    )


def _quote_looks_like_counter_evidence_for_gap_text(
    *,
    supporting_quote: str | None,
    gap_claim_text: str | None,
) -> bool:
    quote = _normalized_text(supporting_quote)
    if not quote:
        return False
    claim = _normalized_text(gap_claim_text)
    if not claim:
        return False
    checks = (
        (
            ("роль", "лпр", "решени", "кем", "руковод", "должност"),
            (
                "кем являет",
                "кем вы",
                "какая роль",
                "роль",
                "принимаете решение",
                "руковод",
                "являетесь",
            ),
        ),
        (
            ("удоб", "уместн", "не провер"),
            ("удобно", "можете говорить", "сейчас говорить", "вам удобно"),
        ),
        (
            ("срок", "дат", "время", "следующ", "ответствен", "когда", "созвон", "перезвон"),
            (
                "когда",
                "срок",
                "дат",
                "время",
                "завтра",
                "понедельник",
                "вторник",
                "сред",
                "четверг",
                "пятниц",
                "перезвон",
                "созвон",
            ),
        ),
        (
            ("процесс", "как сейчас", "документ", "потребност", "задач"),
            ("как сейчас", "как у вас", "какой процесс", "документ", "задач", "потребност"),
        ),
    )
    for claim_markers, quote_markers in checks:
        if any(marker in claim for marker in claim_markers) and any(
            marker in quote for marker in quote_markers
        ):
            return True
    return False


def _quote_looks_like_context_only_for_gap_text(
    *,
    supporting_quote: str | None,
    gap_claim_text: str | None,
) -> bool:
    quote = _normalized_text(supporting_quote)
    claim = _normalized_text(gap_claim_text)
    if not quote or not claim:
        return False

    missing_qualification_claim = (
        any(
            marker in claim
            for marker in (
                "не уточн",
                "не выясн",
                "не выяв",
                "не спрос",
                "без квалификац",
                "до выяснен",
                "до выявлен",
                "перед выяснен",
                "перед выявлен",
            )
        )
        and any(
            marker in claim
            for marker in (
                "роль",
                "лпр",
                "решени",
                "процесс",
                "потребност",
                "задач",
                "контекст",
                "квалификац",
            )
        )
    )
    product_or_presentation_quote = any(
        marker in quote
        for marker in (
            "скину информац",
            "скинуть информац",
            "отправлю информац",
            "отправить информац",
            "пришлю информац",
            "информацию о продукт",
            "о нашем продукт",
            "расскажу про",
            "расскажу о",
            "предлож",
            "тариф",
            "коммерческ",
            "кп",
        )
    )
    if missing_qualification_claim and product_or_presentation_quote:
        return True

    missing_next_step_claim = any(
        marker in claim
        for marker in (
            "не закреп",
            "не зафикс",
            "не соглас",
            "без срока",
            "без даты",
        )
    ) and any(
        marker in claim
        for marker in ("срок", "дат", "следующ", "возврат", "перезвон", "созвон")
    )
    dispatch_quote = any(
        marker in quote
        for marker in (
            "скину",
            "отправлю",
            "пришлю",
            "направлю",
            "отправить",
            "скинуть",
            "выслать",
        )
    )
    quote_has_timing = any(
        marker in quote
        for marker in (
            "когда",
            "срок",
            "дата",
            "дату",
            "завтра",
            "сегодня",
            "понедельник",
            "вторник",
            "сред",
            "четверг",
            "пятниц",
            "созвон",
            "перезвон",
        )
    )
    return missing_next_step_claim and dispatch_quote and not quote_has_timing


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
