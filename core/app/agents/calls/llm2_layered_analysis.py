"""Bounded adapter for future layered LLM-2 analysis artifacts.

This module intentionally does not wire the layered LLM-2 passes into the
production CallsAnalyzer runtime. It only assembles already-produced
LLM-2A/2B/2C/2D artifacts into the current scores_detail-compatible shape and
passes proof cards through the existing report_evidence validator.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.agents.calls.analyzer import (
    APPROVED_CHECKLIST_VERSION,
    APPROVED_SCHEMA_VERSION,
    CHECKLIST_DEFINITION,
)
from app.agents.calls.report_evidence import (
    SUPPORTED_REPORT_EVIDENCE_VERSION,
    ReportEvidenceValidationResult,
    validate_report_evidence,
)


LAYERED_ADAPTER_INSTRUCTION_VERSION = "llm2_layered_analysis_adapter_v1"

_ACCEPTED_PROOF_STATUSES = {"proven", "verified", "soften", "softened"}
_CURRENT_PROOF_STATUS_BY_LAYERED_STATUS = {
    "proven": "proven",
    "verified": "verified",
    "softened": "soften",
    "soften": "soften",
    "rejected": "reject",
    "reject": "reject",
    "insufficient": "retry",
    "retry": "retry",
    "downgrade": "downgrade",
    "warning": "warning",
}
_CURRENT_REJECT_REASON_BY_LAYERED_REASON = {
    "no_scene": "missing_scene",
    "missing_scene": "missing_scene",
    "no_evidence": "missing_evidence",
    "missing_evidence": "missing_evidence",
    "quote_not_exact": "ungrounded_quote",
    "ungrounded_quote": "ungrounded_quote",
    "counter_evidence_stronger": "counter_evidence_conflict",
    "counter_evidence_conflict": "counter_evidence_conflict",
    "claim_too_broad": "claim_too_broad",
    "unsupported_absence": "missing_evidence",
    "missing_recommendation_link": "missing_recommendation_link",
    "not_sales_coaching": "form_only_issue",
    "contradicts_transcript": "counter_evidence_conflict",
}
_VALID_STAGE_CODES = {
    str(stage.get("stage_code"))
    for stage in CHECKLIST_DEFINITION.get("stages", [])
    if stage.get("stage_code")
}
_STAGE_CODE_ALIASES = {
    "qualification_pain": "qualification_primary",
    "qualification": "qualification_primary",
    "need_discovery": "needs_discovery",
    "next_step": "completion_next_step",
    "closing": "completion_next_step",
    "sale": "sale_final",
}


@dataclass(frozen=True, slots=True)
class LayeredLLM2NormalizationResult:
    """Result of adapting layered LLM-2 artifacts into scores_detail."""

    scores_detail: dict[str, Any]
    report_evidence_validation: ReportEvidenceValidationResult | None

    @property
    def is_valid(self) -> bool:
        """Return whether the report_evidence admission gate passed."""

        if self.report_evidence_validation is None:
            return True
        return self.report_evidence_validation.is_valid


def normalize_llm2_layered_scores_detail(
    artifact: dict[str, Any],
    *,
    transcript: str | None = None,
    validate_evidence: bool = True,
) -> dict[str, Any]:
    """Return only the scores_detail-compatible payload for a layered artifact."""

    return normalize_llm2_layered_analysis(
        artifact,
        transcript=transcript,
        validate_evidence=validate_evidence,
    ).scores_detail


def normalize_llm2_layered_analysis(
    artifact: dict[str, Any],
    *,
    transcript: str | None = None,
    validate_evidence: bool = True,
) -> LayeredLLM2NormalizationResult:
    """Assemble LLM-2A/2B/2C/2D artifacts into a scores_detail-compatible dict."""

    root = _as_dict(artifact)
    llm2a = _extract_pass_artifact(root, "2a")
    llm2b = _extract_pass_artifact(root, "2b")
    llm2c = _extract_pass_artifact(root, "2c")
    llm2d = _extract_pass_artifact(root, "2d")

    final_from_2d = _as_dict(llm2d.get("final_normalized_analysis"))
    scores_detail = _scores_detail_base(
        root=root,
        llm2a=llm2a,
        llm2d=llm2d,
        final_from_2d=final_from_2d,
    )

    evidence_by_id = _evidence_ledger_by_id(llm2a)
    scenes_by_id = _scenes_by_id(llm2a)
    proof_cards = _normalized_proof_cards(
        proof_cards=_source_proof_cards(llm2c=llm2c, llm2d=llm2d),
        recommendations=_as_list(llm2d.get("recommendations")),
        evidence_by_id=evidence_by_id,
    )
    accepted_proof_cards = _accepted_proof_cards_by_id(proof_cards)

    criteria_results = _as_list(
        final_from_2d.get("criteria_results")
        or scores_detail.get("criteria_results")
        or llm2b.get("criteria_results")
    )
    scores_detail["criteria_results"] = _normalized_criteria_results(
        criteria_results=criteria_results,
        evidence_by_id=evidence_by_id,
    )
    scores_detail["score_by_stage"] = _score_by_stage_from_criteria(
        scores_detail["criteria_results"]
    )
    scores_detail["strengths"] = _normalized_strengths(
        _as_list(final_from_2d.get("strengths") or llm2b.get("strength_claims")),
        evidence_by_id=evidence_by_id,
    )
    scores_detail["gaps"] = _normalized_gaps(
        gap_claims=_as_list(final_from_2d.get("gaps") or llm2b.get("gap_claims")),
        proof_cards_by_claim_id=_accepted_proof_cards_by_claim_id(proof_cards),
        evidence_by_id=evidence_by_id,
    )
    scores_detail["recommendations"] = _normalized_recommendations(
        _as_list(final_from_2d.get("recommendations") or llm2d.get("recommendations")),
        accepted_proof_cards=accepted_proof_cards,
    )
    if not scores_detail.get("evidence_fragments"):
        scores_detail["evidence_fragments"] = _evidence_fragments_from_scenes(
            scenes_by_id=scenes_by_id,
            evidence_by_id=evidence_by_id,
        )
    _attach_report_evidence(
        scores_detail=scores_detail,
        llm2a=llm2a,
        final_from_2d=final_from_2d,
        proof_cards=proof_cards,
        evidence_by_id=evidence_by_id,
    )
    _attach_layered_analysis_metadata(
        scores_detail=scores_detail,
        llm2a=llm2a,
        llm2b=llm2b,
        llm2c=llm2c,
        llm2d=llm2d,
        proof_cards=proof_cards,
    )
    _populate_checklist_score(scores_detail)

    validation_result = (
        validate_report_evidence(scores_detail, transcript) if validate_evidence else None
    )
    if validation_result is not None and validation_result.normalized:
        scores_detail.update(validation_result.normalized)

    return LayeredLLM2NormalizationResult(
        scores_detail=scores_detail,
        report_evidence_validation=validation_result,
    )


def _scores_detail_base(
    *,
    root: dict[str, Any],
    llm2a: dict[str, Any],
    llm2d: dict[str, Any],
    final_from_2d: dict[str, Any],
) -> dict[str, Any]:
    scores_detail = deepcopy(final_from_2d)
    call_id = _first_non_empty_str(
        scores_detail.get("call_id"),
        _as_dict(scores_detail.get("call")).get("call_id"),
        _as_dict(scores_detail.get("call")).get("id"),
        llm2d.get("call_id"),
        llm2a.get("call_id"),
        root.get("call_id"),
    )
    scores_detail.setdefault("schema_version", APPROVED_SCHEMA_VERSION)
    scores_detail.setdefault("instruction_version", LAYERED_ADAPTER_INSTRUCTION_VERSION)
    scores_detail.setdefault("checklist_version", APPROVED_CHECKLIST_VERSION)
    scores_detail.setdefault("analysis_timestamp", datetime.now(UTC).isoformat())
    call = _as_dict(scores_detail.get("call"))
    if call_id:
        call.setdefault("id", call_id)
        call.setdefault("call_id", call_id)
    scores_detail["call"] = call
    classification = _as_dict(scores_detail.get("classification"))
    classification.setdefault(
        "analysis_eligibility",
        llm2a.get("analysis_eligibility") or "insufficient",
    )
    classification.setdefault("eligibility_reason", llm2a.get("eligibility_reason"))
    admission_gate = _as_dict(root.get("llm2_admission_gate") or root.get("llm2_admission"))
    if admission_gate.get("admitted") is True:
        eligibility = _lower_str(classification.get("analysis_eligibility"))
        if eligibility in {"not_eligible", "insufficient"}:
            original_reason = classification.get("eligibility_reason")
            classification["analysis_eligibility"] = "eligible"
            classification["eligibility_reason"] = "llm2_admission_gate_accepted"
            if original_reason:
                classification["eligibility_reason_before_admission_gate"] = original_reason
            classification["eligibility_overridden_by_admission_gate"] = True
    scores_detail["classification"] = classification
    if admission_gate:
        diagnostics = _as_dict(scores_detail.get("diagnostics"))
        diagnostics["llm2_admission_gate"] = admission_gate
        scores_detail["diagnostics"] = diagnostics
    scores_detail.setdefault("summary", {})
    scores_detail.setdefault("score", {"checklist_score": {}})
    scores_detail.setdefault("agreements", [])
    scores_detail.setdefault("follow_up", {})
    scores_detail.setdefault("product_signals", [])
    scores_detail.setdefault("analytics_tags", [])
    scores_detail.setdefault("data_quality", {})
    return scores_detail


def _extract_pass_artifact(root: dict[str, Any], pass_name: str) -> dict[str, Any]:
    normalized_pass = pass_name.lower().replace("-", "")
    direct_pass = str(root.get("pass") or "").lower().replace("-", "")
    if direct_pass in {f"llm{normalized_pass}", f"llm{normalized_pass.upper()}".lower()}:
        return root
    candidates = (
        f"llm{normalized_pass}_artifact",
        f"llm{normalized_pass}",
        f"LLM-{pass_name.upper()}",
        f"LLM{pass_name.upper()}",
        pass_name.upper(),
        pass_name.lower(),
    )
    for key in candidates:
        value = root.get(key)
        if isinstance(value, dict):
            return value
    nested = _as_dict(root.get("artifacts"))
    for key in candidates:
        value = nested.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _source_proof_cards(*, llm2c: dict[str, Any], llm2d: dict[str, Any]) -> list[dict[str, Any]]:
    universal_pack = _as_dict(llm2d.get("universal_evidence_pack"))
    proof_cards = _as_list(universal_pack.get("proof_cards"))
    if proof_cards:
        proof_cards_by_id = {
            str(card.get("proof_id")): card
            for card in _as_list(llm2c.get("proof_cards"))
            if isinstance(card, dict) and card.get("proof_id")
        }
        merged = []
        for card in proof_cards:
            if not isinstance(card, dict):
                continue
            source = dict(proof_cards_by_id.get(str(card.get("proof_id")) or "", {}))
            source.update(card)
            merged.append(source)
        return merged
    return _as_list(llm2c.get("proof_cards"))


def _normalized_proof_cards(
    *,
    proof_cards: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendation_by_proof_id = {
        str(item.get("proof_id")): item
        for item in recommendations
        if isinstance(item, dict) and item.get("proof_id")
    }
    normalized = []
    for raw_card in proof_cards:
        card = _as_dict(raw_card)
        proof_id = _str_or_none(card.get("proof_id"))
        if not proof_id:
            continue
        supporting_ids = _string_list(
            card.get("supporting_evidence_ids")
            or card.get("evidence_ids")
            or ([card.get("evidence_id")] if card.get("evidence_id") else [])
        )
        counter_ids = _string_list(card.get("counter_evidence_ids"))
        status = _proof_status(card)
        recommendation = recommendation_by_proof_id.get(proof_id, {})
        normalized_card = {
            "_claim_id": card.get("claim_id"),
            "proof_id": _clip(proof_id, 120),
            "claim": _clip(
                card.get("softened_claim")
                if status == "soften" and card.get("softened_claim")
                else card.get("claim"),
                420,
            ),
            "claim_scope": card.get("claim_scope") or "scene",
            "claim_type": card.get("claim_type") or "manager_gap",
            "proof_type": card.get("proof_type") or "sequence_inference",
            "status": status,
            "stage_code": _normalized_stage_code(
                card.get("stage_code") or recommendation.get("stage_code")
            ),
            "scene_id": card.get("scene_id"),
            "evidence_id": card.get("evidence_id")
            or (supporting_ids[0] if supporting_ids else None),
            "evidence_ids": supporting_ids,
            "evidence_quote": _clip(card.get("evidence_quote"), 700),
            "gap_proven": card.get("gap_proven"),
            "recommendation_id": card.get("recommendation_id")
            or recommendation.get("recommendation_id"),
            "supporting_evidence": _proof_card_evidence(
                explicit_items=_as_list(card.get("supporting_evidence")),
                evidence_ids=supporting_ids,
                evidence_by_id=evidence_by_id,
            ),
            "counter_evidence": _proof_card_evidence(
                explicit_items=_as_list(card.get("counter_evidence")),
                evidence_ids=counter_ids,
                evidence_by_id=evidence_by_id,
            ),
            "expected_absent_element": _clip(card.get("expected_absent_element"), 240),
            "reject_reason": _reject_reason(card),
            "outcome_reason": _clip(
                card.get("outcome_reason")
                or card.get("proof_explanation")
                or card.get("reject_reason"),
                360,
            ),
        }
        _fail_closed_on_missing_supporting_evidence(
            normalized_card,
            supporting_ids=supporting_ids,
            evidence_by_id=evidence_by_id,
        )
        if (
            normalized_card["proof_type"] == "absence_based"
            and not normalized_card["expected_absent_element"]
        ):
            normalized_card["expected_absent_element"] = _clip(card.get("claim"), 240)
        _enforce_proof_card_admission_contract(normalized_card)
        if normalized_card["status"] == "reject" and not normalized_card["reject_reason"]:
            normalized_card["reject_reason"] = "missing_evidence"
        if normalized_card["status"] in {"reject", "soften", "downgrade", "retry"}:
            normalized_card["outcome_reason"] = (
                normalized_card["outcome_reason"] or "Proof did not pass as verified."
            )
        normalized.append(
            {key: value for key, value in normalized_card.items() if value is not None}
        )
    return normalized


def _fail_closed_on_missing_supporting_evidence(
    card: dict[str, Any],
    *,
    supporting_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
) -> None:
    if _lower_str(card.get("status")) not in {"verified", "proven"}:
        return
    missing_ids = [
        evidence_id for evidence_id in supporting_ids if evidence_id not in evidence_by_id
    ]
    if not missing_ids:
        return
    card["status"] = "retry"
    card["gap_proven"] = False if card.get("gap_proven") is True else card.get("gap_proven")
    card["outcome_reason"] = (
        card.get("outcome_reason")
        or "Proof references supporting evidence ids that are missing from LLM-2A."
    )


def _enforce_proof_card_admission_contract(card: dict[str, Any]) -> None:
    status = _lower_str(card.get("status"))
    if status not in {"verified", "proven"}:
        return
    counter_evidence = _as_list(card.get("counter_evidence"))
    has_counter_evidence = any(
        _str_or_none(item.get("quote") if isinstance(item, dict) else item)
        or _str_or_none(item.get("evidence_id") if isinstance(item, dict) else None)
        for item in counter_evidence
    )
    if has_counter_evidence:
        card["status"] = "soften"
        card["gap_proven"] = False if card.get("gap_proven") is True else card.get("gap_proven")
        card["outcome_reason"] = (
            card.get("outcome_reason")
            or "Counter-evidence is present, so the claim cannot pass as proven."
        )
        return
    if _lower_str(card.get("proof_type")) != "sequence_inference":
        return
    supporting_evidence = _as_list(card.get("supporting_evidence"))
    evidence_count = sum(
        1
        for item in supporting_evidence
        if isinstance(item, dict)
        and (_str_or_none(item.get("evidence_id")) or _str_or_none(item.get("quote")))
    )
    if evidence_count < 2:
        card["status"] = "retry"
        card["gap_proven"] = False if card.get("gap_proven") is True else card.get("gap_proven")
        card["outcome_reason"] = (
            card.get("outcome_reason")
            or "Sequence inference needs at least two grounded evidence points."
        )


def _proof_card_evidence(
    *,
    explicit_items: list[Any],
    evidence_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_item in explicit_items:
        item = _as_dict(raw_item)
        quote = item.get("quote") or item.get("text")
        items.append(
            {
                "evidence_id": item.get("evidence_id"),
                "quote": _clip(quote, 700),
                "speaker": item.get("speaker") or "unknown",
            }
        )
    seen_ids = {_str_or_none(item.get("evidence_id")) for item in items}
    for evidence_id in evidence_ids:
        if evidence_id in seen_ids:
            continue
        evidence = evidence_by_id.get(evidence_id, {})
        items.append(
            {
                "evidence_id": evidence_id,
                "quote": _clip(evidence.get("text"), 700),
                "speaker": evidence.get("speaker") or "unknown",
            }
        )
    return [
        {key: value for key, value in item.items() if value is not None}
        for item in items
        if item.get("evidence_id") or item.get("quote")
    ]


def _proof_status(card: dict[str, Any]) -> str:
    raw_status = _lower_str(card.get("status") or card.get("proof_status"))
    if not raw_status:
        raw_status = "proven" if card.get("gap_proven") is True else "retry"
    return _CURRENT_PROOF_STATUS_BY_LAYERED_STATUS.get(raw_status, "retry")


def _reject_reason(card: dict[str, Any]) -> str | None:
    raw_reason = _lower_str(card.get("reject_reason"))
    if not raw_reason:
        return None
    return _CURRENT_REJECT_REASON_BY_LAYERED_REASON.get(raw_reason, "form_only_issue")


def _accepted_proof_cards_by_id(proof_cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(card.get("proof_id")): card
        for card in proof_cards
        if card.get("proof_id") and _lower_str(card.get("status")) in _ACCEPTED_PROOF_STATUSES
    }


def _accepted_proof_cards_by_claim_id(
    proof_cards: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(card.get("_claim_id")): card
        for card in proof_cards
        if card.get("_claim_id") and _lower_str(card.get("status")) in _ACCEPTED_PROOF_STATUSES
    }


def _normalized_criteria_results(
    *,
    criteria_results: list[Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for raw_item in criteria_results:
        item = _as_dict(raw_item)
        if not item:
            continue
        evidence_ids = _string_list(item.get("evidence_ids"))
        normalized.append(
            {
                "criterion_code": item.get("criterion_code"),
                "criterion_name": item.get("criterion_name"),
                "stage_code": _normalized_stage_code(item.get("stage_code")),
                "applicable": item.get("applicable", True),
                "score": _safe_int(item.get("score")),
                "max_score": _safe_int(item.get("max_score"), default=2),
                "comment": item.get("comment") or item.get("missing_evidence_reason") or "",
                "evidence": item.get("evidence")
                or _joined_evidence_text(evidence_ids, evidence_by_id),
                "scene_ids": _string_list(item.get("scene_ids")),
                "evidence_ids": evidence_ids,
                "missing_evidence_reason": item.get("missing_evidence_reason"),
            }
        )
    return normalized


def _score_by_stage_from_criteria(criteria_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stage_order = _checklist_stage_order()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for criterion in criteria_results:
        stage_code = _str_or_none(criterion.get("stage_code"))
        if not stage_code:
            continue
        grouped.setdefault(stage_code, []).append(criterion)
    stages = []
    for stage_code in sorted(grouped, key=lambda code: stage_order.get(code, 10_000)):
        criteria = grouped[stage_code]
        stage_score = sum(_safe_int(item.get("score")) for item in criteria)
        max_stage_score = sum(_safe_int(item.get("max_score")) for item in criteria)
        stages.append(
            {
                "stage_code": stage_code,
                "stage_name": _stage_name(stage_code),
                "stage_score": stage_score,
                "max_stage_score": max_stage_score,
                "criteria_results": criteria,
            }
        )
    return stages


def _normalized_strengths(
    strength_claims: list[Any],
    *,
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for raw_item in strength_claims:
        item = _as_dict(raw_item)
        if not item:
            continue
        evidence_ids = _string_list(item.get("evidence_ids"))
        normalized.append(
            {
                "claim_id": item.get("claim_id"),
                "stage_code": _normalized_stage_code(item.get("stage_code")),
                "title": item.get("claim"),
                "impact": item.get("comment") or item.get("claim"),
                "evidence": _joined_evidence_text(evidence_ids, evidence_by_id),
                "scene_ids": _string_list(item.get("scene_ids")),
                "evidence_ids": evidence_ids,
                "confidence": item.get("confidence"),
            }
        )
    return normalized


def _normalized_gaps(
    *,
    gap_claims: list[Any],
    proof_cards_by_claim_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for raw_item in gap_claims:
        item = _as_dict(raw_item)
        claim_id = _str_or_none(item.get("claim_id"))
        proof_card = proof_cards_by_claim_id.get(claim_id or "")
        if not proof_card:
            continue
        evidence_ids = _string_list(item.get("evidence_ids") or proof_card.get("evidence_ids"))
        normalized.append(
            {
                "claim_id": claim_id,
                "proof_id": proof_card.get("proof_id"),
                "stage_code": _normalized_stage_code(
                    item.get("stage_code") or proof_card.get("stage_code")
                ),
                "title": proof_card.get("claim") or item.get("claim"),
                "impact": item.get("expected_behavior")
                or item.get("observed_behavior")
                or item.get("claim"),
                "evidence": proof_card.get("evidence_quote")
                or _joined_evidence_text(evidence_ids, evidence_by_id),
                "scene_ids": _string_list(item.get("scene_ids") or [proof_card.get("scene_id")]),
                "evidence_ids": evidence_ids,
                "proof_status": proof_card.get("status"),
            }
        )
    return normalized


def _normalized_recommendations(
    recommendations: list[Any],
    *,
    accepted_proof_cards: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for raw_item in recommendations:
        item = _as_dict(raw_item)
        proof_id = _str_or_none(item.get("proof_id"))
        if proof_id not in accepted_proof_cards:
            continue
        proof_card = accepted_proof_cards[proof_id]
        normalized.append(
            {
                "recommendation_id": item.get("recommendation_id"),
                "proof_id": proof_id,
                "stage_code": _normalized_stage_code(
                    item.get("stage_code") or proof_card.get("stage_code")
                ),
                "priority": item.get("priority") or "medium",
                "problem": item.get("problem") or proof_card.get("claim"),
                "why_it_matters": item.get("why_it_matters"),
                "better_phrase": item.get("better_phrase"),
                "next_action": item.get("next_action"),
                "recommendation": item.get("next_action") or item.get("better_phrase"),
            }
        )
    return normalized


def _attach_report_evidence(
    *,
    scores_detail: dict[str, Any],
    llm2a: dict[str, Any],
    final_from_2d: dict[str, Any],
    proof_cards: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> None:
    report_evidence = _allowed_report_evidence_fields(
        final_from_2d.get("report_evidence") or scores_detail.get("report_evidence")
    )
    if report_evidence.get("quote_bank"):
        report_evidence["quote_bank"] = _normalized_quote_bank(
            report_evidence.get("quote_bank"),
            evidence_by_id=evidence_by_id,
        )
    report_evidence["proof_cards"] = [_public_proof_card(card) for card in proof_cards]
    business_outcome = _business_outcome(llm2a, evidence_by_id)
    if business_outcome:
        report_evidence["business_outcome"] = business_outcome
    if not _as_dict(report_evidence.get("call_essence")):
        call_essence = _call_essence(
            report_evidence=report_evidence,
            business_outcome=business_outcome,
            llm2a=llm2a,
            final_from_2d=scores_detail,
        )
        if call_essence:
            report_evidence["call_essence"] = call_essence
    scores_detail["report_evidence_version"] = SUPPORTED_REPORT_EVIDENCE_VERSION
    scores_detail["report_evidence"] = report_evidence


def _normalized_quote_bank(
    value: Any,
    *,
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in _as_list(value):
        raw = _as_dict(item)
        evidence_id = _first_non_empty_str(raw.get("evidence_id"), raw.get("id"))
        source = evidence_by_id.get(evidence_id or "", {})
        quote = _first_non_empty_str(raw.get("quote"), raw.get("text"), source.get("text"))
        if not quote:
            continue
        normalized.append(
            {
                "quote": quote,
                "speaker": _lower_str(raw.get("speaker") or source.get("speaker")) or "unknown",
                "topic": _first_non_empty_str(raw.get("topic"), evidence_id, "call evidence"),
                "stage_code": _first_non_empty_str(
                    raw.get("stage_code"),
                    source.get("stage_code"),
                    source.get("stage_hint"),
                    "cross_stage_transition",
                ),
                "evidence_quality": _lower_str(raw.get("evidence_quality")) or "direct",
                "usable_in_report": bool(raw.get("usable_in_report", True)),
            }
        )
    return normalized


def _attach_layered_analysis_metadata(
    *,
    scores_detail: dict[str, Any],
    llm2a: dict[str, Any],
    llm2b: dict[str, Any],
    llm2c: dict[str, Any],
    llm2d: dict[str, Any],
    proof_cards: list[dict[str, Any]],
) -> None:
    existing = _as_dict(scores_detail.get("layered_analysis"))
    existing.update(
        {
            "adapter_instruction_version": LAYERED_ADAPTER_INSTRUCTION_VERSION,
            "pass_artifacts": {
                "llm2a": _pass_artifact_metadata(
                    llm2a,
                    required_list_fields=("scenes", "evidence_ledger"),
                ),
                "llm2b": _pass_artifact_metadata(
                    llm2b,
                    required_list_fields=("criteria_results",),
                ),
                "llm2c": _pass_artifact_metadata(
                    llm2c,
                    required_list_fields=("proof_cards",),
                ),
                "llm2d": _pass_artifact_metadata(
                    llm2d,
                    required_any_fields=(
                        "recommendations",
                        "final_normalized_analysis",
                    ),
                ),
            },
            "proof_card_counts": _proof_card_counts(proof_cards),
        }
    )
    scores_detail["layered_analysis"] = existing


def _pass_artifact_metadata(
    artifact: dict[str, Any],
    *,
    required_list_fields: tuple[str, ...] = (),
    required_any_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    present = bool(artifact)
    has_required_lists = all(
        isinstance(artifact.get(field), list) for field in required_list_fields
    )
    has_any_required = (
        True
        if not required_any_fields
        else any(artifact.get(field) not in (None, "") for field in required_any_fields)
    )
    return {
        "present": present,
        "pass": artifact.get("pass"),
        "artifact_version": artifact.get("artifact_version"),
        "call_id": artifact.get("call_id"),
        "valid_shape": present and has_required_lists and has_any_required,
    }


def _proof_card_counts(proof_cards: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total": len(proof_cards),
        "accepted": 0,
        "verified": 0,
        "proven": 0,
        "soften": 0,
        "retry": 0,
        "reject": 0,
        "downgrade": 0,
        "warning": 0,
    }
    for card in proof_cards:
        status = _lower_str(card.get("status"))
        if status in counts:
            counts[status] += 1
        if status in _ACCEPTED_PROOF_STATUSES:
            counts["accepted"] += 1
    return counts


def _allowed_report_evidence_fields(value: Any) -> dict[str, Any]:
    allowed_keys = {
        "business_outcome",
        "call_essence",
        "call_report_summary",
        "semantic_case",
        "block_candidates",
        "situation_candidates",
        "manager_coaching_moments",
        "voice_of_customer",
        "additional_situations",
        "follow_up_candidates",
        "quote_bank",
    }
    return {
        key: item
        for key, item in _as_dict(value).items()
        if key in allowed_keys
    }


def _public_proof_card(card: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in card.items() if not key.startswith("_")}


def _business_outcome(
    llm2a: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    signal = _as_dict(llm2a.get("business_outcome_signal"))
    status = _lower_str(signal.get("status"))
    if status not in {
        "agreement",
        "rescheduled",
        "refusal",
        "open",
        "tech_service",
        "not_suitable",
    }:
        return None
    evidence_ids = _string_list(signal.get("evidence_ids"))
    first_evidence = evidence_by_id.get(evidence_ids[0], {}) if evidence_ids else {}
    return {
        "status": status,
        "confidence": _lower_str(signal.get("confidence")) or "low",
        "reason": signal.get("reason") or "",
        "evidence_quote": first_evidence.get("text"),
        "evidence_speaker": first_evidence.get("speaker") or "unknown",
    }


def _call_essence(
    *,
    report_evidence: dict[str, Any],
    business_outcome: dict[str, Any] | None,
    llm2a: dict[str, Any],
    final_from_2d: dict[str, Any],
) -> dict[str, Any] | None:
    summary = _as_dict(report_evidence.get("call_report_summary"))
    follow_up = _as_dict(final_from_2d.get("follow_up"))
    first_follow_up = _as_dict(_first_list_item(report_evidence.get("follow_up_candidates")))
    first_agreement = _first_list_item(final_from_2d.get("agreements"))
    first_recommendation = _as_dict(_first_list_item(final_from_2d.get("recommendations")))
    agreement_text = _first_non_empty_str(
        _agreement_text(first_agreement),
        first_follow_up.get("why_follow_up"),
        _scene_commitment_text(llm2a),
    )
    topic = _first_non_empty_str(
        summary.get("short_topic"),
        _as_dict(final_from_2d.get("summary")).get("short"),
        _scene_topic_text(llm2a),
    )
    outcome = _first_non_empty_str(
        _as_dict(business_outcome).get("status"),
        first_follow_up.get("status"),
    )
    outcome_reason = _first_non_empty_str(
        _as_dict(business_outcome).get("reason"),
        summary.get("hotness_reason"),
        first_follow_up.get("why_follow_up"),
        _scene_service_or_refusal_text(llm2a),
    )
    next_step = _first_non_empty_str(
        first_follow_up.get("next_step"),
        follow_up.get("next_step_text"),
        follow_up.get("next_step"),
        summary.get("manager_next_action"),
        _as_dict(first_agreement).get("next_step"),
        first_recommendation.get("next_action"),
        first_recommendation.get("recommendation"),
    )
    service_request = (
        _scene_service_or_refusal_text(llm2a)
        if outcome == "tech_service"
        else None
    )
    manager_visible_text = _first_non_empty_str(
        summary.get("manager_visible_summary"),
        summary.get("short_context"),
        _compose_call_essence_text(
            topic=topic,
            outcome=outcome,
            reason=outcome_reason,
            agreement=agreement_text,
            next_step=next_step,
            service_request=service_request,
        ),
    )
    if not any((topic, outcome, outcome_reason, agreement_text, next_step, service_request, manager_visible_text)):
        return None
    essence = {
        "topic": _clip(topic, 160),
        "outcome": outcome if outcome in {
            "agreement",
            "rescheduled",
            "refusal",
            "open",
            "tech_service",
            "not_suitable",
        } else None,
        "refusal_or_interest_reason": _clip(outcome_reason, 280),
        "outcome_reason": _clip(outcome_reason, 280),
        "agreement": _clip(agreement_text, 280),
        "next_step": _clip(next_step, 280),
        "deadline": _clip(first_follow_up.get("deadline"), 120),
        "service_request": _clip(service_request, 280),
        "manager_visible_text": _clip(manager_visible_text, 640),
        "source": "llm2_layered_analysis.derived_call_essence",
        "evidence_quote": _clip(_as_dict(business_outcome).get("evidence_quote"), 700),
        "evidence_speaker": _as_dict(business_outcome).get("evidence_speaker") or "unknown",
    }
    return {key: value for key, value in essence.items() if value is not None}


def _first_list_item(value: Any) -> Any:
    items = _as_list(value)
    return items[0] if items else {}


def _agreement_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    item = _as_dict(value)
    return _first_non_empty_str(
        item.get("agreement"),
        item.get("summary"),
        item.get("description"),
        item.get("what_agreed"),
        item.get("commitment"),
    )


def _scene_topic_text(llm2a: dict[str, Any]) -> str | None:
    scene = _as_dict(_first_list_item(llm2a.get("scenes")))
    return _first_non_empty_str(scene.get("what_happened"), scene.get("stage_hint"))


def _scene_commitment_text(llm2a: dict[str, Any]) -> str | None:
    for scene in _as_list(llm2a.get("scenes")):
        commitments = [
            _str_or_none(item)
            for item in _as_list(_as_dict(scene).get("observed_commitments"))
        ]
        text = "; ".join(item for item in commitments if item)
        if text:
            return text
    return None


def _scene_service_or_refusal_text(llm2a: dict[str, Any]) -> str | None:
    for scene in _as_list(llm2a.get("scenes")):
        signals = [
            _str_or_none(item)
            for item in _as_list(_as_dict(scene).get("service_or_refusal_signals"))
        ]
        text = "; ".join(item for item in signals if item)
        if text:
            return text
    return None


def _compose_call_essence_text(
    *,
    topic: str | None,
    outcome: str | None,
    reason: str | None,
    agreement: str | None,
    next_step: str | None,
    service_request: str | None,
) -> str | None:
    parts = [
        _str_or_none(topic),
        _str_or_none(service_request),
        _str_or_none(reason),
        _str_or_none(agreement),
        _str_or_none(next_step),
    ]
    text = ". ".join(part.rstrip(".") for part in parts if part)
    if outcome and text:
        return text
    return text or None


def _evidence_fragments_from_scenes(
    *,
    scenes_by_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    fragments = []
    for evidence_id, evidence in evidence_by_id.items():
        scene = scenes_by_id.get(str(evidence.get("scene_id") or ""), {})
        fragments.append(
            {
                "type": "llm2_scene_evidence",
                "stage_code": scene.get("stage_hint"),
                "scene_id": evidence.get("scene_id"),
                "evidence_id": evidence_id,
                "speaker": evidence.get("speaker") or "unknown",
                "quote": evidence.get("text"),
                "comment": scene.get("what_happened"),
            }
        )
    return fragments


def _populate_checklist_score(scores_detail: dict[str, Any]) -> None:
    total_points = 0
    max_points = 0
    for stage in _as_list(scores_detail.get("score_by_stage")):
        item = _as_dict(stage)
        total_points += _safe_int(item.get("stage_score"))
        max_points += _safe_int(item.get("max_stage_score"))
    percent = round((total_points / max_points) * 100, 2) if max_points else 0.0
    checklist_score = _as_dict(_as_dict(scores_detail.get("score")).get("checklist_score"))
    checklist_score.update(
        {
            "total_points": total_points,
            "max_points": max_points,
            "score_percent": percent,
            "level": _score_level(percent),
        }
    )
    scores_detail["score"] = {"checklist_score": checklist_score}


def _score_level(percent: float) -> str:
    if percent >= 85:
        return "excellent"
    if percent >= 70:
        return "strong"
    if percent >= 50:
        return "basic"
    return "problematic"


def _evidence_ledger_by_id(llm2a: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("evidence_id")): item
        for item in _as_list(llm2a.get("evidence_ledger"))
        if isinstance(item, dict) and item.get("evidence_id")
    }


def _scenes_by_id(llm2a: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("scene_id")): item
        for item in _as_list(llm2a.get("scenes"))
        if isinstance(item, dict) and item.get("scene_id")
    }


def _joined_evidence_text(
    evidence_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
) -> str:
    return " / ".join(
        str(evidence_by_id[evidence_id].get("text") or "").strip()
        for evidence_id in evidence_ids
        if evidence_id in evidence_by_id
        and str(evidence_by_id[evidence_id].get("text") or "").strip()
    )


def _stage_name(stage_code: str) -> str:
    for stage in CHECKLIST_DEFINITION.get("stages", []):
        if stage.get("stage_code") == stage_code:
            return str(stage.get("stage_name") or stage_code)
    return stage_code


def _normalized_stage_code(value: Any) -> str:
    stage_code = _lower_str(value)
    if not stage_code:
        return ""
    stage_code = _STAGE_CODE_ALIASES.get(stage_code, stage_code)
    return stage_code if stage_code in _VALID_STAGE_CODES else stage_code


def _checklist_stage_order() -> dict[str, int]:
    return {
        str(stage.get("stage_code")): index
        for index, stage in enumerate(CHECKLIST_DEFINITION.get("stages", []))
        if stage.get("stage_code")
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _first_non_empty_str(*values: Any) -> str | None:
    for value in values:
        text = _str_or_none(value)
        if text:
            return text
    return None


def _lower_str(value: Any) -> str:
    return str(value or "").strip().lower()


def _clip(value: Any, max_length: int) -> str | None:
    text = _str_or_none(value)
    if text is None:
        return None
    return text[:max_length]


__all__ = [
    "LAYERED_ADAPTER_INSTRUCTION_VERSION",
    "LayeredLLM2NormalizationResult",
    "normalize_llm2_layered_analysis",
    "normalize_llm2_layered_scores_detail",
]
