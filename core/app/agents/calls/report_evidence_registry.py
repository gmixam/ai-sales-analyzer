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
    "call_essence",
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

VERIFIED_PROOF_STATUS = "verified_proof_card"
SOFTENED_PROOF_STATUS = "softened_proof_card"
_SOFTENED_CARD_STATUSES = {"soften", "softened", "downgrade"}


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
    call_essence: dict[str, Any] = field(default_factory=dict)


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

        call_essence = _as_mapping(evidence.get("call_essence"))
        if call_essence:
            items.append(
                _build_call_essence_item(
                    call_id=call_id,
                    essence=call_essence,
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

        for situation_index, situation in enumerate(_as_list(evidence.get("additional_situations"))):
            situation_dict = _as_mapping(situation)
            if situation_dict:
                items.append(
                    _build_additional_situation_item(
                        call_id=call_id,
                        situation=situation_dict,
                        artifact_index=artifact_index,
                        source_index=situation_index,
                    )
                )

        for candidate_index, candidate in enumerate(_as_list(evidence.get("follow_up_candidates"))):
            candidate_dict = _as_mapping(candidate)
            if candidate_dict:
                items.append(
                    _build_follow_up_candidate_item(
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

        for quote_index, quote in enumerate(_as_list(evidence.get("quote_bank"))):
            quote_item = _as_mapping(quote)
            if quote_item:
                items.append(
                    _build_quote_bank_item(
                        call_id=call_id,
                        item=quote_item,
                        artifact_index=artifact_index,
                        source_index=quote_index,
                    )
                )

        for proof_index, proof_card in enumerate(_as_list(evidence.get("proof_cards"))):
            proof_card_dict = _as_mapping(proof_card)
            if proof_card_dict:
                items.append(
                    _build_proof_card_item(
                        call_id=call_id,
                        proof_card=proof_card_dict,
                        artifact_index=artifact_index,
                        source_index=proof_index,
                    )
                )

        for fragment_index, fragment in enumerate(_as_list(evidence.get("evidence_fragments"))):
            fragment_item = _as_mapping(fragment)
            if fragment_item:
                items.append(
                    _build_evidence_fragment_item(
                        call_id=call_id,
                        fragment=fragment_item,
                        artifact_index=artifact_index,
                        source_index=fragment_index,
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
        diagnostics=_with_proof_diagnostics(
            candidate,
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "fit": _as_bool(candidate.get("fit")),
                "score": _as_int(candidate.get("score")),
                "role": _text_or_none(candidate.get("role")),
                "title_mode": _text_or_none(candidate.get("title_mode")),
                "source_evidence_type": _text_or_none(candidate.get("evidence_type")),
                "insufficiency_reason": _text_or_none(candidate.get("insufficiency_reason")),
            },
        ),
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
        diagnostics=_with_proof_diagnostics(
            semantic_case,
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "case_type": _text_or_none(semantic_case.get("case_type")),
                "priority": _text_or_none(semantic_case.get("priority")),
                "evidence_quality": _text_or_none(semantic_case.get("evidence_quality")),
            },
        ),
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
        diagnostics=_with_proof_diagnostics(
            moment,
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "moment_type": _text_or_none(moment.get("moment_type")),
                "priority": _text_or_none(moment.get("priority")),
                "evidence_quality": _text_or_none(moment.get("evidence_quality")),
                "what_better": _text_or_none(moment.get("what_better")),
            },
        ),
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
        diagnostics=_with_proof_diagnostics(
            candidate,
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "problem_type": _text_or_none(candidate.get("problem_type")),
                "priority": _text_or_none(candidate.get("priority")),
                "evidence_quality": _text_or_none(candidate.get("evidence_quality")),
            },
        ),
    )


def _build_additional_situation_item(
    *,
    call_id: str | None,
    situation: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.additional_situations"
    evidence_type = _classify_additional_situation(situation)
    proof_strength = _proof_strength(situation)
    rejection_reasons = _base_rejection_reasons(situation, proof_strength)
    dialogue_scene = _dialogue_scene(
        situation.get("dialogue_fragment") or situation.get("best_dialogue_fragment")
    )
    supporting_quote = _first_text(
        situation.get("supporting_quote"),
        situation.get("quote"),
        situation.get("client_quote"),
        situation.get("customer_quote"),
        situation.get("manager_quote"),
    ) or _supporting_quote_from_scene(dialogue_scene)
    if supporting_quote and not dialogue_scene:
        dialogue_scene = [_quote_turn(situation, supporting_quote)]
    if not (dialogue_scene or supporting_quote):
        rejection_reasons.append("missing_dialogue_evidence")

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type=evidence_type,
        proof_type=_proof_type(situation, evidence_type, proof_strength, dialogue_scene, supporting_quote),
        proof_strength=proof_strength,
        stage_code=_text_or_none(situation.get("stage_code")),
        problem_title=_first_text(situation.get("title"), situation.get("case_title")),
        manager_gap=_first_text(
            situation.get("what_was_missing"),
            situation.get("manager_gap"),
            situation.get("recommended_action"),
            situation.get("recommended_next_action"),
            situation.get("what_better"),
        )
        if evidence_type == "manager_gap"
        else None,
        customer_context=_first_text(
            situation.get("what_happened"),
            situation.get("why_it_matters"),
            situation.get("customer_signal"),
            situation.get("core_meaning"),
        ),
        dialogue_scene=dialogue_scene,
        supporting_quote=supporting_quote,
        counter_evidence=_string_list(situation.get("counter_evidence")),
        block_suitability={
            "additional_situations": _block_suitability(
                block_name="additional_situations",
                source=source,
                evidence_type=evidence_type,
                proof_strength=proof_strength,
                fit=True,
                score=_as_int(situation.get("score")),
                base_reasons=rejection_reasons,
            )
        },
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics=_with_proof_diagnostics(
            situation,
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "type": _text_or_none(situation.get("type") or situation.get("case_type")),
                "priority": _text_or_none(situation.get("priority")),
                "evidence_quality": _text_or_none(situation.get("evidence_quality")),
            },
        ),
    )


def _build_call_essence_item(
    *,
    call_id: str | None,
    essence: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.call_essence"
    outcome = _text_or_none(essence.get("outcome") or essence.get("status"))
    topic = _text_or_none(essence.get("topic"))
    agreement = _text_or_none(essence.get("agreement"))
    next_step = _text_or_none(essence.get("next_step"))
    manager_visible_text = _first_text(
        essence.get("manager_visible_text"),
        essence.get("manager_visible_summary"),
        essence.get("short_context"),
    )
    reason = _first_text(
        essence.get("refusal_or_interest_reason"),
        essence.get("outcome_reason"),
        essence.get("reason"),
    )
    service_request = _text_or_none(essence.get("service_request"))
    deadline = _text_or_none(essence.get("deadline"))
    evidence_quote = _text_or_none(essence.get("evidence_quote"))
    proof_strength = _call_essence_proof_strength(essence)
    rejection_reasons = _call_essence_rejection_reasons(
        outcome=outcome,
        topic=topic,
        agreement=agreement,
        next_step=next_step,
        reason=reason,
        service_request=service_request,
        manager_visible_text=manager_visible_text,
        proof_strength=proof_strength,
    )
    is_follow_up = (outcome or "").strip().lower() in {"agreement", "rescheduled", "open"}
    fit_call_list = bool(topic or manager_visible_text or agreement or reason or service_request)
    fit_follow_up = is_follow_up and bool(next_step)

    normalized_essence = {
        "topic": topic,
        "outcome": outcome,
        "refusal_or_interest_reason": _text_or_none(essence.get("refusal_or_interest_reason")),
        "outcome_reason": _text_or_none(essence.get("outcome_reason")) or reason,
        "agreement": agreement,
        "next_step": next_step,
        "deadline": deadline,
        "service_request": service_request,
        "manager_visible_text": manager_visible_text,
        "source": _text_or_none(essence.get("source")) or source,
    }
    normalized_essence = {
        key: value for key, value in normalized_essence.items() if value not in (None, "")
    }

    block_suitability = {
        "call_list": _block_suitability(
            block_name="call_list",
            source=source,
            evidence_type="call_essence",
            proof_strength=proof_strength,
            fit=fit_call_list,
            score=_as_int(essence.get("score")) or 85,
            base_reasons=rejection_reasons if not fit_call_list else [],
        )
    }
    if is_follow_up:
        block_suitability["follow_up"] = _block_suitability(
            block_name="follow_up",
            source=source,
            evidence_type="follow_up_opportunity",
            proof_strength=proof_strength,
            fit=fit_follow_up,
            score=_as_int(essence.get("score")) or 85,
            base_reasons=rejection_reasons if not fit_follow_up else [],
        )

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type="call_essence",
        proof_type="sequence_inference",
        proof_strength=proof_strength,
        stage_code=_text_or_none(essence.get("stage_code")),
        problem_title=topic,
        manager_gap=None,
        customer_context=_first_text(manager_visible_text, agreement, reason, service_request),
        dialogue_scene=[_quote_turn(essence, evidence_quote)] if evidence_quote else [],
        supporting_quote=evidence_quote,
        counter_evidence=_string_list(essence.get("counter_evidence")),
        block_suitability=block_suitability,
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics={
            "artifact_index": artifact_index,
            "source_index": source_index,
            "source_contract": "call_essence",
            "outcome": outcome,
            "deadline": deadline,
            "quality_flags": _call_essence_quality_flags(
                outcome=outcome,
                topic=topic,
                agreement=agreement,
                next_step=next_step,
                reason=reason,
                service_request=service_request,
                manager_visible_text=manager_visible_text,
            ),
            "proof_status": "diagnostics_only_call_essence",
            "verified_source": False,
        },
        call_essence=normalized_essence,
    )


def _build_follow_up_candidate_item(
    *,
    call_id: str | None,
    candidate: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.follow_up_candidates"
    evidence_type: EvidenceType = "follow_up_opportunity"
    proof_strength = _follow_up_proof_strength(candidate)
    rejection_reasons = _base_rejection_reasons(candidate, proof_strength)
    next_action = _first_text(
        candidate.get("next_step"),
        candidate.get("manager_next_action"),
        candidate.get("suggested_manager_phrase"),
        candidate.get("first_phrase"),
    )
    if not next_action:
        rejection_reasons.append("missing_next_action")

    suitability = _block_suitability(
        block_name="call_tomorrow",
        source=source,
        evidence_type=evidence_type,
        proof_strength=proof_strength,
        fit=True,
        score=_as_int(candidate.get("score")),
        base_reasons=rejection_reasons,
    )

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type=evidence_type,
        proof_type="sequence_inference",
        proof_strength=proof_strength,
        stage_code=_text_or_none(candidate.get("stage_code")),
        problem_title=_first_text(candidate.get("client_label"), candidate.get("topic"), next_action),
        manager_gap=None,
        customer_context=_first_text(
            candidate.get("why_follow_up"),
            candidate.get("client_context"),
            candidate.get("deadline"),
            candidate.get("status"),
        ),
        dialogue_scene=[],
        supporting_quote=_text_or_none(candidate.get("first_phrase")),
        counter_evidence=_string_list(candidate.get("counter_evidence")),
        block_suitability={
            "follow_up": dict(suitability),
            "call_tomorrow": suitability,
        },
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics=_with_proof_diagnostics(
            candidate,
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "status": _text_or_none(candidate.get("status")),
                "priority": _text_or_none(candidate.get("priority")),
                "deadline": _text_or_none(candidate.get("deadline")),
            },
        ),
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
    proof_strength = _proof_strength_with_business_signal(item)
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
        diagnostics=_with_proof_diagnostics(
            item,
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "topic": _text_or_none(item.get("topic")),
                "business_signal": _text_or_none(item.get("business_signal")),
                "evidence_quality": _text_or_none(item.get("evidence_quality")),
            },
        ),
    )


def _build_quote_bank_item(
    *,
    call_id: str | None,
    item: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.quote_bank"
    evidence_type = _classify_quote_bank_item(item)
    proof_strength = _proof_strength_with_business_signal(item)
    rejection_reasons = _base_rejection_reasons(item, proof_strength)
    quote = _text_or_none(item.get("quote") or item.get("text"))
    speaker = _text_or_none(item.get("speaker"))
    if not quote:
        rejection_reasons.append("missing_customer_quote")
    if not speaker:
        rejection_reasons.append("missing_speaker")

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
        customer_context=_first_text(item.get("meaning"), item.get("topic"), item.get("business_signal")),
        dialogue_scene=[{"speaker": speaker or "unknown", "text": quote}] if quote else [],
        supporting_quote=quote,
        counter_evidence=_string_list(item.get("counter_evidence")),
        block_suitability={
            "voice_of_customer": _block_suitability(
                block_name="voice_of_customer",
                source=source,
                evidence_type=evidence_type,
                proof_strength=proof_strength,
                fit=bool(quote and speaker),
                score=_as_int(item.get("score")),
                base_reasons=rejection_reasons,
            )
        },
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics=_with_proof_diagnostics(
            item,
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "topic": _text_or_none(item.get("topic")),
                "speaker": speaker,
                "business_signal": _text_or_none(item.get("business_signal")),
                "evidence_quality": _text_or_none(item.get("evidence_quality")),
            },
        ),
    )


def _build_proof_card_item(
    *,
    call_id: str | None,
    proof_card: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "report_evidence.proof_cards"
    evidence_type = _proof_card_evidence_type(proof_card)
    proof_strength = _proof_card_strength(proof_card)
    status = (_text_or_none(proof_card.get("status")) or "").strip().lower()
    dialogue_scene, supporting_quote = _proof_card_dialogue_scene(proof_card)
    counter_evidence = [
        quote
        for quote in (
            _text_or_none(item.get("quote"))
            for item in _as_list(proof_card.get("counter_evidence"))
            if isinstance(item, dict)
        )
        if quote
    ]
    rejection_reasons: list[str] = []
    if status in {"reject", "rejected", "retry", "warning"}:
        rejection_reasons.append(f"proof_card_{status}")
    if proof_strength in {"weak", "insufficient"}:
        rejection_reasons.append("insufficient_evidence")
    if not dialogue_scene and not supporting_quote:
        rejection_reasons.append("missing_dialogue_evidence")
    if _text_or_none(proof_card.get("reject_reason")):
        rejection_reasons.append("proof_card_rejected")

    primary_block = _proof_card_primary_block(evidence_type)
    block_suitability: dict[str, dict[str, Any]] = {}
    if primary_block:
        block_suitability[primary_block] = _block_suitability(
            block_name=primary_block,
            source=source,
            evidence_type=evidence_type,
            proof_strength=proof_strength,
            fit=not rejection_reasons,
            score=None,
            base_reasons=rejection_reasons,
        )
    if evidence_type == "manager_gap":
        block_suitability["call_breakdown"] = _block_suitability(
            block_name="call_breakdown",
            source=source,
            evidence_type=evidence_type,
            proof_strength=proof_strength,
            fit=not rejection_reasons,
            score=None,
            base_reasons=rejection_reasons,
        )

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id or _text_or_none(proof_card.get("call_id")),
        source=source,
        evidence_type=evidence_type,
        proof_type=_proof_card_proof_type(proof_card),
        proof_strength=proof_strength,
        stage_code=_text_or_none(proof_card.get("stage_code")),
        problem_title=_text_or_none(proof_card.get("claim")),
        manager_gap=_text_or_none(proof_card.get("claim")) if evidence_type == "manager_gap" else None,
        customer_context=_text_or_none(proof_card.get("claim"))
        if evidence_type == "customer_signal"
        else None,
        dialogue_scene=dialogue_scene,
        supporting_quote=supporting_quote,
        counter_evidence=counter_evidence,
        block_suitability=block_suitability,
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics=_with_proof_diagnostics(
            {"proof_card": proof_card},
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "proof_source": "top_level_proof_cards",
            },
        ),
    )


def _build_evidence_fragment_item(
    *,
    call_id: str | None,
    fragment: dict[str, Any],
    artifact_index: int,
    source_index: int,
) -> ReportEvidenceItem:
    source = "evidence_fragments"
    evidence_type = _classify_evidence_fragment(fragment)
    proof_strength = _proof_strength(fragment)
    rejection_reasons = _base_rejection_reasons(fragment, proof_strength)
    quote, speaker = _fragment_quote_and_speaker(fragment)
    dialogue_scene = [{"speaker": speaker or "unknown", "text": quote}] if quote else []
    if not quote:
        rejection_reasons.append("missing_dialogue_evidence")

    target_block = "voice_of_customer" if evidence_type == "customer_signal" else "call_breakdown"
    block_suitability = {
        target_block: _block_suitability(
            block_name=target_block,
            source=source,
            evidence_type=evidence_type,
            proof_strength=proof_strength,
            fit=bool(quote),
            score=_as_int(fragment.get("score")),
            base_reasons=rejection_reasons,
        )
    }
    if evidence_type == "manager_gap":
        block_suitability["situation_day"] = _block_suitability(
            block_name="situation_day",
            source=source,
            evidence_type=evidence_type,
            proof_strength=proof_strength,
            fit=bool(quote),
            score=_as_int(fragment.get("score")),
            base_reasons=rejection_reasons,
        )

    return ReportEvidenceItem(
        evidence_id=_evidence_id(call_id, source, source_index),
        call_id=call_id,
        source=source,
        evidence_type=evidence_type,
        proof_type=_proof_type(fragment, evidence_type, proof_strength, dialogue_scene, quote),
        proof_strength=proof_strength,
        stage_code=_first_text(fragment.get("stage_code"), fragment.get("stage")),
        problem_title=_first_text(
            fragment.get("title"),
            fragment.get("criterion_name"),
            fragment.get("criterion_code"),
        ),
        manager_gap=_first_text(
            fragment.get("manager_gap"),
            fragment.get("what_was_missing"),
            fragment.get("gap"),
            fragment.get("comment"),
        )
        if evidence_type == "manager_gap"
        else None,
        customer_context=_first_text(
            fragment.get("customer_signal"),
            fragment.get("client_text"),
            fragment.get("customer_text"),
            fragment.get("quote"),
            fragment.get("text"),
        ),
        dialogue_scene=dialogue_scene,
        supporting_quote=quote,
        counter_evidence=_string_list(fragment.get("counter_evidence")),
        block_suitability=block_suitability,
        rejection_reasons=_dedupe(rejection_reasons),
        diagnostics=_with_proof_diagnostics(
            fragment,
            evidence_type,
            {
                "artifact_index": artifact_index,
                "source_index": source_index,
                "criterion_code": _text_or_none(fragment.get("criterion_code")),
                "speaker": speaker,
                "source_evidence_type": _text_or_none(fragment.get("evidence_type")),
            },
        ),
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
            "call_list": _block_suitability(
                block_name="call_list",
                source=source,
                evidence_type=evidence_type,
                proof_strength=proof_strength,
                fit=bool(
                    _text_or_none(summary.get("manager_visible_summary"))
                    or _text_or_none(summary.get("short_context"))
                    or _text_or_none(summary.get("short_topic"))
                ),
                score=None,
                base_reasons=rejection_reasons,
            ),
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
            "call_list_source_priority": 40,
            "call_list_quality": "medium" if not rejection_reasons else "warning",
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
            "additional_situations",
            "follow_up_candidates",
            "quote_bank",
            "evidence_fragments",
            "call_essence",
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


def _classify_additional_situation(situation: dict[str, Any]) -> EvidenceType:
    raw_type = str(
        situation.get("evidence_type") or situation.get("type") or situation.get("case_type") or ""
    ).strip().lower()
    if raw_type in {"strong_practice", "positive_case", "worked"}:
        return "positive_case"
    return "manager_gap"


def _classify_quote_bank_item(item: dict[str, Any]) -> EvidenceType:
    raw_type = str(item.get("evidence_type") or item.get("type") or item.get("case_type") or "").strip().lower()
    topic = str(item.get("topic") or "").strip().lower()
    if raw_type in {"service_issue", "tech_service", "support_issue"} or topic in {
        "service_issue",
        "tech_service",
        "support_issue",
    }:
        return "service_issue"
    return "customer_signal"


def _classify_evidence_fragment(fragment: dict[str, Any]) -> EvidenceType:
    raw_type = str(
        fragment.get("evidence_type") or fragment.get("type") or fragment.get("case_type") or ""
    ).strip().lower()
    if raw_type in {"manager_gap", "manager_coaching_moment", "stage_gap", "growth_zone", "missed_opportunity"}:
        return "manager_gap"
    if raw_type in {"customer_signal", "voice_of_customer"}:
        return "customer_signal"
    if _first_text(
        fragment.get("manager_gap"),
        fragment.get("what_was_missing"),
        fragment.get("gap"),
        fragment.get("manager_text"),
        fragment.get("operator_text"),
    ):
        return "manager_gap"
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


def _proof_strength_with_business_signal(payload: dict[str, Any]) -> ProofStrength:
    if _has_proof_strength_hint(payload):
        return _proof_strength(payload)
    signal = str(payload.get("business_signal") or "").strip().lower()
    if signal in {"high", "hot", "strong"}:
        return "strong"
    if signal in {"medium", "warm"}:
        return "medium"
    if signal in {"low", "cold", "weak"}:
        return "weak"
    if signal in {"insufficient", "none", "no_signal"}:
        return "insufficient"
    return _proof_strength(payload)


def _follow_up_proof_strength(payload: dict[str, Any]) -> ProofStrength:
    if _has_proof_strength_hint(payload):
        return _proof_strength(payload)
    priority = str(payload.get("priority") or "").strip().lower()
    status = str(payload.get("status") or payload.get("follow_up_status") or "").strip().lower()
    if priority in {"high", "urgent", "hot"}:
        return "strong"
    if priority in {"medium", "open", "warm"} or status in {"open", "agreement", "rescheduled"}:
        return "medium"
    if priority in {"low", "cold", "weak"}:
        return "weak"
    if _first_text(payload.get("next_step"), payload.get("manager_next_action"), payload.get("first_phrase")):
        return "medium"
    return "weak"


CALL_ESSENCE_GENERIC_TEXT_MARKERS = (
    "есть договоренность",
    "есть договорённость",
    "контакт в работу",
    "нужно продолжить работу",
    "продолжить работу",
    "обсудили вопрос",
    "обсудили сотрудничество",
    "разговор с клиентом",
)


def _call_essence_proof_strength(payload: dict[str, Any]) -> ProofStrength:
    if _has_proof_strength_hint(payload):
        return _proof_strength(payload)
    outcome = str(payload.get("outcome") or payload.get("status") or "").strip().lower()
    has_topic = bool(_text_or_none(payload.get("topic")))
    has_next_step = bool(_text_or_none(payload.get("next_step")))
    has_agreement = bool(_text_or_none(payload.get("agreement")))
    has_reason = bool(
        _first_text(
            payload.get("refusal_or_interest_reason"),
            payload.get("outcome_reason"),
            payload.get("reason"),
        )
    )
    has_service_request = bool(_text_or_none(payload.get("service_request")))
    if outcome in {"agreement", "rescheduled", "open"}:
        return "medium" if has_topic and has_agreement and has_next_step else "weak"
    if outcome == "refusal":
        return "medium" if has_topic and has_reason else "weak"
    if outcome == "tech_service":
        return "medium" if has_service_request or has_topic else "weak"
    if any((has_topic, has_reason, has_service_request)):
        return "medium"
    return "weak"


def _call_essence_rejection_reasons(
    *,
    outcome: str | None,
    topic: str | None,
    agreement: str | None,
    next_step: str | None,
    reason: str | None,
    service_request: str | None,
    manager_visible_text: str | None,
    proof_strength: ProofStrength,
) -> list[str]:
    reasons = _call_essence_quality_flags(
        outcome=outcome,
        topic=topic,
        agreement=agreement,
        next_step=next_step,
        reason=reason,
        service_request=service_request,
        manager_visible_text=manager_visible_text,
    )
    if proof_strength in {"weak", "insufficient"}:
        reasons.append("weak_call_essence")
    return _dedupe(reasons)


def _call_essence_quality_flags(
    *,
    outcome: str | None,
    topic: str | None,
    agreement: str | None,
    next_step: str | None,
    reason: str | None,
    service_request: str | None,
    manager_visible_text: str | None,
) -> list[str]:
    flags: list[str] = []
    normalized_outcome = str(outcome or "").strip().lower()
    if not (topic or manager_visible_text):
        flags.append("missing_topic")
    if normalized_outcome in {"agreement", "rescheduled", "open"}:
        if not topic:
            flags.append("missing_agreement_topic")
        if not agreement:
            flags.append("missing_agreement")
        if not next_step:
            flags.append("missing_next_step")
    if normalized_outcome == "refusal" and not reason:
        flags.append("missing_refusal_reason")
    if normalized_outcome == "tech_service" and not (service_request or topic or manager_visible_text):
        flags.append("missing_service_request")
    for field, value in {
        "topic": topic,
        "agreement": agreement,
        "next_step": next_step,
        "reason": reason,
        "service_request": service_request,
        "manager_visible_text": manager_visible_text,
    }.items():
        if _call_essence_text_is_generic(value):
            flags.append(f"generic_{field}")
    return _dedupe(flags)


def _call_essence_text_is_generic(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if len(text) < 10:
        return True
    return any(marker in text for marker in CALL_ESSENCE_GENERIC_TEXT_MARKERS)


def _has_proof_strength_hint(payload: dict[str, Any]) -> bool:
    return bool(
        _text_or_none(payload.get("proof_strength"))
        or _text_or_none(payload.get("evidence_quality"))
        or _as_int(payload.get("score")) is not None
    )


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
    proof_card = _proof_card(payload)
    if not proof_card:
        reasons.append("missing_proof_card")
    elif _proof_card_reject_reason(proof_card):
        reasons.append("proof_card_rejected")
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


def _with_proof_diagnostics(
    payload: dict[str, Any],
    evidence_type: EvidenceType,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    proof_card = _proof_card(payload)
    if not proof_card:
        return {
            **diagnostics,
            "proof_status": "legacy_hint_only",
            "verified_source": False,
            "proof_missing_reason": "missing_proof_card",
        }

    reject_reason = _proof_card_reject_reason(proof_card)
    gap_proven = proof_card.get("gap_proven")
    status = (_text_or_none(proof_card.get("status")) or "").strip().lower()
    if reject_reason:
        proof_status = "rejected_proof_card"
        verified_source = False
    elif evidence_type == "manager_gap" and gap_proven is False:
        proof_status = "unverified_proof_card"
        verified_source = False
    elif status in _SOFTENED_CARD_STATUSES:
        proof_status = SOFTENED_PROOF_STATUS
        verified_source = False
    elif status and status not in {"verified", "proven"}:
        proof_status = "unverified_proof_card"
        verified_source = False
    else:
        proof_status = VERIFIED_PROOF_STATUS
        verified_source = True

    return {
        **diagnostics,
        "proof_status": proof_status,
        "verified_source": verified_source,
        "proof_id": _text_or_none(proof_card.get("proof_id")),
        "proof_scene_id": _text_or_none(proof_card.get("scene_id")),
        "proof_evidence_ids": _string_list(proof_card.get("evidence_ids")),
        "proof_claim_scope": _text_or_none(proof_card.get("claim_scope")),
        "proof_reject_reason": reject_reason,
    }


def _proof_card(payload: dict[str, Any]) -> dict[str, Any]:
    return _as_mapping(payload.get("proof_card"))


def _proof_card_reject_reason(proof_card: dict[str, Any]) -> str | None:
    return _text_or_none(proof_card.get("reject_reason"))


def _proof_card_evidence_type(proof_card: dict[str, Any]) -> EvidenceType:
    claim_type = (_text_or_none(proof_card.get("claim_type")) or "").strip().lower()
    if claim_type == "customer_signal":
        return "customer_signal"
    if claim_type == "follow_up":
        return "follow_up_opportunity"
    if claim_type == "strong_practice":
        return "positive_case"
    if claim_type == "business_outcome":
        return "follow_up_opportunity"
    return "manager_gap"


def _proof_card_proof_type(proof_card: dict[str, Any]) -> ProofType:
    proof_type = (_text_or_none(proof_card.get("proof_type")) or "").strip().lower()
    if proof_type == "direct_quote" and _proof_card_evidence_type(proof_card) == "customer_signal":
        return "customer_signal"
    if proof_type == "direct_quote":
        return "direct_gap"
    if proof_type == "absence_based":
        return "absence_in_context"
    return "sequence_inference"


def _proof_card_strength(proof_card: dict[str, Any]) -> ProofStrength:
    status = (_text_or_none(proof_card.get("status")) or "").strip().lower()
    if status in {"verified", "proven"}:
        return "strong" if proof_card.get("proof_type") == "direct_quote" else "medium"
    if status in {"soften", "softened", "downgrade"}:
        return "medium"
    return "insufficient"


def _proof_card_primary_block(evidence_type: EvidenceType) -> str | None:
    if evidence_type == "manager_gap":
        return "situation_day"
    if evidence_type == "customer_signal":
        return "voice_of_customer"
    if evidence_type == "follow_up_opportunity":
        return "follow_up"
    if evidence_type == "positive_case":
        return "additional_situations"
    return None


def _proof_card_dialogue_scene(proof_card: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    evidence_items = _as_list(proof_card.get("supporting_evidence"))
    dialogue_scene: list[dict[str, Any]] = []
    for item in evidence_items:
        evidence = _as_mapping(item)
        quote = _text_or_none(evidence.get("quote"))
        if not quote:
            continue
        dialogue_scene.append(
            {
                "speaker": _text_or_none(evidence.get("speaker")) or "unknown",
                "text": quote,
            }
        )
    if not dialogue_scene:
        quote = _text_or_none(proof_card.get("evidence_quote"))
        if quote:
            dialogue_scene.append({"speaker": "unknown", "text": quote})
    supporting_quote = _text_or_none(proof_card.get("evidence_quote"))
    if not supporting_quote and dialogue_scene:
        supporting_quote = _text_or_none(dialogue_scene[0].get("text"))
    return dialogue_scene, supporting_quote


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


def _quote_turn(payload: dict[str, Any], quote: str) -> dict[str, Any]:
    return {
        "speaker": _text_or_none(payload.get("speaker")) or "unknown",
        "text": quote,
    }


def _fragment_quote_and_speaker(fragment: dict[str, Any]) -> tuple[str | None, str | None]:
    for field, speaker in (
        ("client_text", "client"),
        ("customer_text", "client"),
        ("manager_text", "manager"),
        ("operator_text", "manager"),
        ("quote", _text_or_none(fragment.get("speaker")) or "unknown"),
        ("text", _text_or_none(fragment.get("speaker")) or "unknown"),
        ("transcript_excerpt", _text_or_none(fragment.get("speaker")) or "unknown"),
    ):
        quote = _text_or_none(fragment.get(field))
        if quote:
            return quote, speaker
    return None, _text_or_none(fragment.get("speaker"))


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
