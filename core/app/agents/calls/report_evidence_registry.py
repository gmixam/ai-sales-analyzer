"""First-pass normalized evidence registry for manager_daily report routing.

The registry is intentionally read-only and deterministic.  It accepts the
same loose ReportArtifact-like surfaces that composers use, but it does not
decide final block rendering; it only preserves candidate evidence with enough
classification and suitability metadata for a later router to explain choices.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal


EvidenceType = Literal[
    "manager_gap",
    "customer_signal",
    "service_issue",
    "follow_up_opportunity",
    "neutral_summary",
    "positive_case",
]
ProofType = Literal[
    "direct_gap",
    "sequence_inference",
    "absence_in_context",
    "customer_signal",
    "service_issue",
    "positive_case",
]
ProofStrength = Literal["strong", "medium", "weak", "insufficient"]


@dataclass(frozen=True, slots=True)
class ReportEvidenceItem:
    evidence_id: str
    call_id: str | None
    source: str
    evidence_type: EvidenceType
    proof_type: ProofType
    proof_strength: ProofStrength
    stage_code: str | None
    problem_title: str | None
    manager_gap: str | None
    customer_context: str | None
    dialogue_scene: list[dict[str, Any]] = field(default_factory=list)
    supporting_quote: str | None = None
    counter_evidence: list[str] = field(default_factory=list)
    block_suitability: dict[str, dict[str, Any]] = field(default_factory=dict)
    rejection_reasons: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def build_report_evidence_registry(artifacts: Any | Iterable[Any]) -> list[ReportEvidenceItem]:
    """Build normalized evidence items from ReportArtifact-like objects or dicts."""

    items: list[ReportEvidenceItem] = []
    for artifact_index, artifact in enumerate(_as_artifact_list(artifacts)):
        evidence = _extract_report_evidence(artifact)
        if not evidence:
            continue
        call_id = _extract_call_id(artifact, evidence)

        block_candidates = _as_mapping(evidence.get("block_candidates"))
        for block_name in ("situation_day", "call_breakdown"):
            candidate = _as_mapping(block_candidates.get(block_name))
            if candidate:
                items.append(
                    _build_block_candidate_item(
                        call_id=call_id,
                        block_name=block_name,
                        candidate=candidate,
                        artifact_index=artifact_index,
                        source_index=len(items),
                    )
                )

        semantic_case = _as_mapping(evidence.get("semantic_case"))
        if semantic_case:
            items.append(
                _build_semantic_case_item(
                    call_id=call_id,
                    semantic_case=semantic_case,
                    artifact_index=artifact_index,
                    source_index=len(items),
                )
            )

        for moment_index, moment in enumerate(_as_list(evidence.get("manager_coaching_moments"))):
            moment_dict = _as_mapping(moment)
            if moment_dict:
                items.append(
                    _build_manager_coaching_item(
                        call_id=call_id,
                        moment=moment_dict,
                        artifact_index=artifact_index,
                        source_index=moment_index,
                    )
                )

        for candidate_index, candidate in enumerate(_as_list(evidence.get("situation_candidates"))):
            candidate_dict = _as_mapping(candidate)
            if candidate_dict:
                items.append(
                    _build_situation_candidate_item(
                        call_id=call_id,
                        candidate=candidate_dict,
                        artifact_index=artifact_index,
                        source_index=candidate_index,
                    )
                )

        for voc_index, item in enumerate(_as_list(evidence.get("voice_of_customer"))):
            voc_item = _as_mapping(item)
            if voc_item:
                items.append(
                    _build_voice_of_customer_item(
                        call_id=call_id,
                        item=voc_item,
                        artifact_index=artifact_index,
                        source_index=voc_index,
                    )
                )

        summary = _as_mapping(evidence.get("call_report_summary"))
        if summary:
            items.append(
                _build_call_report_summary_item(
                    call_id=call_id,
                    summary=summary,
                    artifact_index=artifact_index,
                    source_index=len(items),
                )
            )

    return items


def report_evidence_registry_as_dicts(items: Iterable[ReportEvidenceItem]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]


def _build_block_candidate_item(
    *,
    call_id: str | None,
    block_name: str,
    candidate: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = f"report_evidence.block_candidates.{block_name}"
    evidence_type = _classify_block_candidate(candidate)
    proof_strength = _proof_strength(candidate)
    rejection_reasons = _base_rejection_reasons(candidate, proof_strength)
    if candidate.get("fit") is False:
        rejection_reasons.append("fit_false")

    dialogue_scene = _dialogue_scene(candidate.get("dialogue_fragment"))
    supporting_quote = _text_or_none(candidate.get("supporting_quote")) or _supporting_quote_from_scene(
        dialogue_scene
    )
    if evidence_type == "manager_gap" and not (dialogue_scene or supporting_quote):
        rejection_reasons.append("missing_dialogue_evidence")

    block_suitability = {
        block_name: _block_suitability(
            block_name=block_name,
            source=source,
            evidence_type=evidence_type,
            proof_strength=proof_strength,
            fit=_as_bool(candidate.get("fit")),
            score=_as_int(candidate.get("score")),
            base_reasons=rejection_reasons,
        )
    }

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type=evidence_type,
        proof_type=_proof_type(candidate, evidence_type, proof_strength, dialogue_scene, supporting_quote),
        proof_strength=proof_strength,
        stage_code=_text_or_none(candidate.get("stage_code")),
        problem_title=_first_text(
            candidate.get("main_thesis"),
            candidate.get("situation_title"),
            candidate.get("situation"),
        ),
        manager_gap=_first_text(
            candidate.get("what_was_missing"),
            candidate.get("manager_action_or_gap"),
            candidate.get("manager_gap"),
            candidate.get("better_next_action"),
        ),
        customer_context=_first_text(
            candidate.get("client_context"),
            candidate.get("customer_signal"),
            candidate.get("customer_need_or_objection"),
            candidate.get("what_it_means"),
            candidate.get("why_it_matters"),
        ),
        dialogue_scene=dialogue_scene,
        supporting_quote=supporting_quote,
        counter_evidence=_string_list(candidate.get("counter_evidence")),
        block_suitability=block_suitability,
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics={
            "artifact_index": artifact_index,
            "source_index": source_index,
            "fit": _as_bool(candidate.get("fit")),
            "score": _as_int(candidate.get("score")),
            "role": _text_or_none(candidate.get("role")),
            "title_mode": _text_or_none(candidate.get("title_mode")),
            "source_evidence_type": _text_or_none(candidate.get("evidence_type")),
            "insufficiency_reason": _text_or_none(candidate.get("insufficiency_reason")),
        },
    )


def _build_semantic_case_item(
    *,
    call_id: str | None,
    semantic_case: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.semantic_case"
    evidence_type = _classify_semantic_case(semantic_case)
    proof_strength = _proof_strength(semantic_case)
    rejection_reasons = _base_rejection_reasons(semantic_case, proof_strength)
    dialogue_scene = _dialogue_scene(semantic_case.get("best_dialogue_fragment"))
    supporting_quote = _semantic_supporting_quote(semantic_case, dialogue_scene)
    if evidence_type == "manager_gap" and not (dialogue_scene or supporting_quote):
        rejection_reasons.append("missing_dialogue_evidence")

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type=evidence_type,
        proof_type=_proof_type(semantic_case, evidence_type, proof_strength, dialogue_scene, supporting_quote),
        proof_strength=proof_strength,
        stage_code=_text_or_none(semantic_case.get("stage_code")),
        problem_title=_text_or_none(semantic_case.get("case_title")),
        manager_gap=_first_text(
            semantic_case.get("manager_behavior"),
            semantic_case.get("coaching_diagnosis"),
            semantic_case.get("recommended_next_action"),
        )
        if evidence_type == "manager_gap"
        else None,
        customer_context=_first_text(
            semantic_case.get("customer_signal"),
            semantic_case.get("core_meaning"),
            semantic_case.get("why_this_call_matters"),
        ),
        dialogue_scene=dialogue_scene,
        supporting_quote=supporting_quote,
        counter_evidence=_semantic_counter_evidence(semantic_case),
        block_suitability=_semantic_block_suitability(
            source=source,
            semantic_case=semantic_case,
            evidence_type=evidence_type,
            proof_strength=proof_strength,
            base_reasons=rejection_reasons,
        ),
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics={
            "artifact_index": artifact_index,
            "source_index": source_index,
            "case_type": _text_or_none(semantic_case.get("case_type")),
            "priority": _text_or_none(semantic_case.get("priority")),
            "evidence_quality": _text_or_none(semantic_case.get("evidence_quality")),
        },
    )


def _build_manager_coaching_item(
    *,
    call_id: str | None,
    moment: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.manager_coaching_moments"
    evidence_type = _classify_manager_coaching_moment(moment)
    proof_strength = _proof_strength(moment)
    rejection_reasons = _base_rejection_reasons(moment, proof_strength)
    dialogue_scene = _dialogue_scene(moment.get("dialogue_fragment"))
    supporting_quote = _supporting_quote_from_scene(dialogue_scene)
    if evidence_type == "manager_gap" and not dialogue_scene:
        rejection_reasons.append("missing_dialogue_scene")

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type=evidence_type,
        proof_type=_proof_type(moment, evidence_type, proof_strength, dialogue_scene, supporting_quote),
        proof_strength=proof_strength,
        stage_code=_text_or_none(moment.get("stage_code")),
        problem_title=_first_text(moment.get("what_happened"), moment.get("what_better")),
        manager_gap=_first_text(moment.get("what_happened"), moment.get("what_better"))
        if evidence_type == "manager_gap"
        else None,
        customer_context=_customer_context_from_scene(dialogue_scene),
        dialogue_scene=dialogue_scene,
        supporting_quote=supporting_quote,
        counter_evidence=_string_list(moment.get("counter_evidence")),
        block_suitability={
            "call_breakdown": _block_suitability(
                block_name="call_breakdown",
                source=source,
                evidence_type=evidence_type,
                proof_strength=proof_strength,
                fit=True,
                score=None,
                base_reasons=rejection_reasons,
            )
        },
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics={
            "artifact_index": artifact_index,
            "source_index": source_index,
            "moment_type": _text_or_none(moment.get("moment_type")),
            "priority": _text_or_none(moment.get("priority")),
            "evidence_quality": _text_or_none(moment.get("evidence_quality")),
            "what_better": _text_or_none(moment.get("what_better")),
        },
    )


def _build_situation_candidate_item(
    *,
    call_id: str | None,
    candidate: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.situation_candidates"
    evidence_type: EvidenceType = "manager_gap"
    proof_strength = _proof_strength(candidate)
    rejection_reasons = _base_rejection_reasons(candidate, proof_strength)
    dialogue_scene = _dialogue_scene(candidate.get("dialogue_fragment"))
    supporting_quote = _supporting_quote_from_scene(dialogue_scene)
    if not (dialogue_scene or supporting_quote):
        rejection_reasons.append("missing_dialogue_evidence")

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type=evidence_type,
        proof_type=_proof_type(candidate, evidence_type, proof_strength, dialogue_scene, supporting_quote),
        proof_strength=proof_strength,
        stage_code=_text_or_none(candidate.get("stage_code")),
        problem_title=_text_or_none(candidate.get("situation_title")),
        manager_gap=_first_text(
            candidate.get("what_was_missing"),
            candidate.get("what_happened"),
            candidate.get("next_time_action"),
        ),
        customer_context=_first_text(candidate.get("what_it_means"), candidate.get("what_happened")),
        dialogue_scene=dialogue_scene,
        supporting_quote=supporting_quote,
        counter_evidence=_string_list(candidate.get("counter_evidence")),
        block_suitability={
            "situation_day": _block_suitability(
                block_name="situation_day",
                source=source,
                evidence_type=evidence_type,
                proof_strength=proof_strength,
                fit=True,
                score=None,
                base_reasons=rejection_reasons,
            )
        },
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics={
            "artifact_index": artifact_index,
            "source_index": source_index,
            "problem_type": _text_or_none(candidate.get("problem_type")),
            "priority": _text_or_none(candidate.get("priority")),
            "evidence_quality": _text_or_none(candidate.get("evidence_quality")),
        },
    )


def _build_voice_of_customer_item(
    *,
    call_id: str | None,
    item: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.voice_of_customer"
    evidence_type = _classify_voice_of_customer(item)
    proof_strength = _proof_strength(item)
    rejection_reasons = _base_rejection_reasons(item, proof_strength)
    quote = _text_or_none(item.get("quote"))
    if not quote:
        rejection_reasons.append("missing_customer_quote")

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type=evidence_type,
        proof_type="service_issue" if evidence_type == "service_issue" else "customer_signal",
        proof_strength=proof_strength,
        stage_code=_text_or_none(item.get("stage_code")),
        problem_title=_text_or_none(item.get("topic")),
        manager_gap=None,
        customer_context=_first_text(item.get("meaning"), item.get("topic")),
        dialogue_scene=[{"speaker": _text_or_none(item.get("speaker")) or "client", "text": quote}]
        if quote
        else [],
        supporting_quote=quote,
        counter_evidence=_string_list(item.get("counter_evidence")),
        block_suitability={
            "voice_of_customer": _block_suitability(
                block_name="voice_of_customer",
                source=source,
                evidence_type=evidence_type,
                proof_strength=proof_strength,
                fit=True,
                score=None,
                base_reasons=rejection_reasons,
            ),
            "call_breakdown": _block_suitability(
                block_name="call_breakdown",
                source=source,
                evidence_type=evidence_type,
                proof_strength=proof_strength,
                fit=False,
                score=None,
                base_reasons=["customer_signal_not_manager_gap"]
                if evidence_type == "customer_signal"
                else ["service_issue_not_manager_gap"],
            ),
        },
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics={
            "artifact_index": artifact_index,
            "source_index": source_index,
            "topic": _text_or_none(item.get("topic")),
            "business_signal": _text_or_none(item.get("business_signal")),
            "evidence_quality": _text_or_none(item.get("evidence_quality")),
        },
    )


def _build_call_report_summary_item(
    *,
    call_id: str | None,
    summary: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.call_report_summary"
    evidence_type: EvidenceType = (
        "follow_up_opportunity" if _text_or_none(summary.get("manager_next_action")) else "neutral_summary"
    )
    proof_strength: ProofStrength = "medium" if evidence_type == "follow_up_opportunity" else "weak"
    rejection_reasons: list[str] = []
    if evidence_type == "neutral_summary":
        rejection_reasons.append("neutral_summary")

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type=evidence_type,
        proof_type="sequence_inference",
        proof_strength=proof_strength,
        stage_code=None,
        problem_title=_text_or_none(summary.get("short_topic")),
        manager_gap=None,
        customer_context=_first_text(summary.get("short_context"), summary.get("hotness_reason")),
        dialogue_scene=[],
        supporting_quote=None,
        counter_evidence=[],
        block_suitability={
            "call_tomorrow": _block_suitability(
                block_name="call_tomorrow",
                source=source,
                evidence_type=evidence_type,
                proof_strength=proof_strength,
                fit=evidence_type == "follow_up_opportunity",
                score=None,
                base_reasons=rejection_reasons,
            )
        },
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics={
            "artifact_index": artifact_index,
            "source_index": source_index,
            "client_display_name": _text_or_none(summary.get("client_display_name")),
            "hotness": _text_or_none(summary.get("hotness")),
            "manager_next_action": _text_or_none(summary.get("manager_next_action")),
        },
    )


def _extract_report_evidence(artifact: Any) -> dict[str, Any]:
    raw = _as_mapping(artifact)
    detail = _as_mapping(raw.get("scores_detail")) or _as_mapping(_path_get(artifact, "analysis.scores_detail"))
    llm2_facts = _as_mapping(raw.get("llm2_facts")) or _as_mapping(detail.get("llm2_facts"))

    evidence = _as_mapping(raw.get("report_evidence")) or _as_mapping(detail.get("report_evidence"))
    if evidence.get("report_evidence"):
        evidence = _as_mapping(evidence.get("report_evidence"))
    if not evidence:
        evidence = _as_mapping(llm2_facts.get("report_evidence"))

    merged = dict(evidence)
    for container in (llm2_facts, detail, raw):
        for key in (
            "block_candidates",
            "semantic_case",
            "manager_coaching_moments",
            "situation_candidates",
            "voice_of_customer",
            "call_report_summary",
        ):
            if key in container and key not in merged:
                merged[key] = container[key]
    return merged


def _extract_call_id(artifact: Any, evidence: dict[str, Any]) -> str | None:
    candidates = (
        _path_get(artifact, "call_id"),
        _path_get(artifact, "interaction_id"),
        _path_get(artifact, "selected_call.call_id"),
        _path_get(artifact, "interaction.id"),
        _path_get(artifact, "llm2_facts.call_id"),
        evidence.get("call_id"),
    )
    return _first_text(*candidates)


def _classify_block_candidate(candidate: dict[str, Any]) -> EvidenceType:
    raw_type = str(candidate.get("evidence_type") or "").strip().lower()
    if raw_type == "manager_gap":
        return "manager_gap"
    if raw_type == "customer_signal":
        return "customer_signal"
    if raw_type == "service_issue":
        return "service_issue"
    if raw_type == "follow_up":
        return "follow_up_opportunity"
    if raw_type == "strong_practice":
        return "positive_case"

    role = str(candidate.get("role") or candidate.get("block_role") or "").strip().lower()
    title_mode = str(candidate.get("title_mode") or "").strip().lower()
    if role in {"coaching_problem", "skill_challenge"} or title_mode == "problem":
        return "manager_gap"
    if role == "customer_signal":
        return "customer_signal"
    if role == "follow_up_action":
        return "follow_up_opportunity"
    if role == "strong_practice" or title_mode == "positive":
        return "positive_case"
    return "neutral_summary"


def _classify_semantic_case(semantic_case: dict[str, Any]) -> EvidenceType:
    case_type = str(semantic_case.get("case_type") or "").strip().lower()
    if case_type in {"growth_zone", "missed_opportunity"}:
        return "manager_gap"
    if case_type == "customer_signal":
        return "customer_signal"
    if case_type == "service_issue":
        return "service_issue"
    if case_type == "strong_practice":
        return "positive_case"

    fit = _as_mapping(semantic_case.get("report_block_fit"))
    for block_name in ("situation_day", "call_breakdown"):
        block_fit = _as_mapping(fit.get(block_name))
        if _classify_block_candidate(block_fit) == "manager_gap" and block_fit.get("fit") is True:
            return "manager_gap"
    return "neutral_summary"


def _classify_manager_coaching_moment(moment: dict[str, Any]) -> EvidenceType:
    moment_type = str(moment.get("moment_type") or "").strip().lower()
    if moment_type == "worked":
        return "positive_case"
    return "manager_gap"


def _classify_voice_of_customer(item: dict[str, Any]) -> EvidenceType:
    topic = str(item.get("topic") or "").strip().lower()
    if topic == "service_issue":
        return "service_issue"
    return "customer_signal"


def _proof_type(
    payload: dict[str, Any],
    evidence_type: EvidenceType,
    proof_strength: ProofStrength,
    dialogue_scene: list[dict[str, Any]],
    supporting_quote: str | None,
) -> ProofType:
    if evidence_type == "customer_signal":
        return "customer_signal"
    if evidence_type == "service_issue":
        return "service_issue"
    if evidence_type == "positive_case":
        return "positive_case"

    raw = str(payload.get("proof_type") or "").strip().lower()
    if raw in {"direct_gap", "sequence_inference", "absence_in_context"}:
        return raw  # type: ignore[return-value]
    if raw in {"inferred_from_dialogue", "context_support"}:
        return "sequence_inference"

    if evidence_type == "manager_gap":
        quality = str(payload.get("evidence_quality") or "").strip().lower()
        if quality == "direct" and supporting_quote:
            return "direct_gap"
        if dialogue_scene or supporting_quote:
            return "sequence_inference"
        return "absence_in_context"

    if proof_strength == "insufficient":
        return "absence_in_context"
    return "sequence_inference"


def _proof_strength(payload: dict[str, Any]) -> ProofStrength:
    explicit = str(payload.get("proof_strength") or "").strip().lower()
    if explicit in {"strong", "medium", "weak", "insufficient"}:
        return explicit  # type: ignore[return-value]

    quality = str(payload.get("evidence_quality") or "").strip().lower()
    if quality == "direct":
        return "strong"
    if quality == "indirect":
        return "medium"
    if quality == "weak":
        return "weak"
    if quality == "insufficient":
        return "insufficient"

    score = _as_int(payload.get("score"))
    if score is not None:
        if score >= 80:
            return "strong"
        if score >= 60:
            return "medium"
        if score >= 35:
            return "weak"
        return "insufficient"
    return "weak"


def _block_suitability(
    *,
    block_name: str,
    source: str,
    evidence_type: EvidenceType,
    proof_strength: ProofStrength,
    fit: bool | None,
    score: int | None,
    base_reasons: list[str],
) -> dict[str, Any]:
    reasons = list(base_reasons)
    if fit is False:
        reasons.append("fit_false")
    if evidence_type == "neutral_summary":
        reasons.append("not_actionable_evidence_type")
    if block_name in {"situation_day", "call_breakdown"} and evidence_type == "customer_signal":
        reasons.append("customer_signal_not_manager_gap")
    if block_name in {"situation_day", "call_breakdown"} and evidence_type == "service_issue":
        reasons.append("service_issue_not_manager_gap")

    eligible = fit is not False and evidence_type != "neutral_summary"
    if block_name in {"situation_day", "call_breakdown"}:
        eligible = eligible and evidence_type in {"manager_gap", "positive_case"}
    if block_name == "voice_of_customer":
        eligible = eligible and evidence_type in {"customer_signal", "service_issue"}
    if block_name == "call_tomorrow":
        eligible = eligible and evidence_type == "follow_up_opportunity"

    return {
        "eligible": eligible,
        "strength": proof_strength,
        "fit": fit,
        "score": score,
        "source": source,
        "reasons": _dedupe(reasons),
    }


def _semantic_block_suitability(
    *,
    source: str,
    semantic_case: dict[str, Any],
    evidence_type: EvidenceType,
    proof_strength: ProofStrength,
    base_reasons: list[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    report_block_fit = _as_mapping(semantic_case.get("report_block_fit"))
    for block_name in ("situation_day", "call_breakdown", "voice_of_customer"):
        fit_item = _as_mapping(report_block_fit.get(block_name))
        if not fit_item:
            continue
        fit_evidence_type = _classify_block_candidate(fit_item)
        result[block_name] = _block_suitability(
            block_name=block_name,
            source=source,
            evidence_type=fit_evidence_type if fit_evidence_type != "neutral_summary" else evidence_type,
            proof_strength=proof_strength,
            fit=_as_bool(fit_item.get("fit")),
            score=_as_int(fit_item.get("score")),
            base_reasons=base_reasons,
        )
    if not result and evidence_type == "manager_gap":
        result["call_breakdown"] = _block_suitability(
            block_name="call_breakdown",
            source=source,
            evidence_type=evidence_type,
            proof_strength=proof_strength,
            fit=True,
            score=None,
            base_reasons=base_reasons,
        )
    return result


def _base_rejection_reasons(payload: dict[str, Any], proof_strength: ProofStrength) -> list[str]:
    reasons: list[str] = []
    if payload.get("usable_in_report") is False:
        reasons.append("not_usable_in_report")
    if proof_strength == "weak":
        reasons.append("weak_evidence_quality")
    elif proof_strength == "insufficient":
        reasons.append("insufficient_evidence")
    if not _text_or_none(payload.get("stage_code")) and (
        "stage_code" in payload or payload.get("fit") is True
    ):
        reasons.append("missing_stage_code")
    insufficiency = _text_or_none(payload.get("insufficiency_reason"))
    if insufficiency:
        reasons.append("has_insufficiency_reason")
    return reasons


def _semantic_supporting_quote(
    semantic_case: dict[str, Any],
    dialogue_scene: list[dict[str, Any]],
) -> str | None:
    fit = _as_mapping(semantic_case.get("report_block_fit"))
    for block_name in ("call_breakdown", "situation_day", "voice_of_customer"):
        block_fit = _as_mapping(fit.get(block_name))
        coaching_moment = _as_mapping(block_fit.get("coaching_moment"))
        quote = _text_or_none(coaching_moment.get("supporting_quote")) or _text_or_none(
            block_fit.get("supporting_quote")
        )
        if quote:
            return quote
    return _supporting_quote_from_scene(dialogue_scene)


def _semantic_counter_evidence(semantic_case: dict[str, Any]) -> list[str]:
    fit = _as_mapping(semantic_case.get("report_block_fit"))
    result: list[str] = []
    for block_name in ("call_breakdown", "situation_day", "voice_of_customer"):
        block_fit = _as_mapping(fit.get(block_name))
        result.extend(_string_list(block_fit.get("counter_evidence")))
        result.extend(_string_list(_as_mapping(block_fit.get("coaching_moment")).get("counter_evidence")))
    return _dedupe(result)


def _dialogue_scene(raw_turns: Any) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for raw_turn in _as_list(raw_turns):
        turn = _as_mapping(raw_turn)
        text = _text_or_none(turn.get("text") or turn.get("quote"))
        if not text:
            continue
        normalized = {
            "speaker": _text_or_none(turn.get("speaker")) or "unknown",
            "text": text,
        }
        start = turn.get("timestamp_start", turn.get("start_sec"))
        end = turn.get("timestamp_end", turn.get("end_sec"))
        if start is not None:
            normalized["timestamp_start"] = start
        if end is not None:
            normalized["timestamp_end"] = end
        turns.append(normalized)
    return turns


def _supporting_quote_from_scene(dialogue_scene: list[dict[str, Any]]) -> str | None:
    for preferred_speaker in ("manager", "client", "unknown"):
        for turn in dialogue_scene:
            if str(turn.get("speaker") or "").strip().lower() == preferred_speaker:
                return _text_or_none(turn.get("text"))
    return None


def _customer_context_from_scene(dialogue_scene: list[dict[str, Any]]) -> str | None:
    for turn in dialogue_scene:
        if str(turn.get("speaker") or "").strip().lower() in {"client", "customer"}:
            return _text_or_none(turn.get("text"))
    return None


def _evidence_id(call_id: str | None, source: str, index: int) -> str:
    safe_call_id = call_id or "unknown_call"
    return f"{safe_call_id}:{source}:{index}"


def _as_artifact_list(artifacts: Any | Iterable[Any]) -> list[Any]:
    if artifacts is None:
        return []
    if isinstance(artifacts, (str, bytes)) or isinstance(artifacts, dict):
        return [artifacts]
    try:
        return list(artifacts)
    except TypeError:
        return [artifacts]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return {}
    result: dict[str, Any] = {}
    for name in getattr(value, "__dataclass_fields__", {}):
        result[name] = getattr(value, name, None)
    if result:
        return result
    namespace = getattr(value, "__dict__", None)
    if isinstance(namespace, dict):
        return dict(namespace)
    return {}


def _path_get(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text_or_none(value)
        if text:
            return text
    return None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [
        str(item).strip()
        for item in _as_list(value)
        if str(item).strip()
    ]


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


__all__ = [
    "EvidenceType",
    "ProofStrength",
    "ProofType",
    "ReportEvidenceItem",
    "build_report_evidence_registry",
    "report_evidence_registry_as_dicts",
]
