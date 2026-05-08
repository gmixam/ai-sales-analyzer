"""Schema and validation helpers for additive LLM2 report evidence."""

from __future__ import annotations

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


class ReportEvidence(_ReportEvidenceModel):
    business_outcome: BusinessOutcomeEvidence | None = None
    call_report_summary: CallReportSummary | None = None
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

    package_payload = {
        "report_evidence_version": version or SUPPORTED_REPORT_EVIDENCE_VERSION,
        "report_evidence": raw_report_evidence,
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
