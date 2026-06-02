"""Pilot Situation Day composer for manager daily reports.

The module is intentionally isolated from ``reporting.py``.  It accepts already
prepared call artifacts / LLM2 analysis facts, builds a day-level candidate
pool, ranks business-significant coaching episodes, and returns a structure
that can be adapted directly into the current Report Layer payload.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Literal

from app.agents.calls.openai_chat_compat import build_chat_completion_kwargs

SITUATION_DAY_COMPOSER_VERSION = "situation_day_composer_v1"
SITUATION_DAY_PROMPT_VERSION = "situation_day_composer_v1"

SituationStatus = Literal["verified", "insufficient", "no_data"]
ProofType = Literal["direct_gap", "sequence_inference", "business_context_inference"]
ProofStrength = Literal["strong", "medium", "weak"]

SUPPORTED_PROOF_TYPES: set[str] = {
    "direct_gap",
    "sequence_inference",
    "business_context_inference",
}

REPORT_LAYER_SOURCE = "report_evidence.situation_day_composer.v1"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "situation_day_composer_v1.md"

_B2B_TERMS = (
    "авр",
    "архив",
    "головной офис",
    "доступ",
    "интеграц",
    "кабинет",
    "пользовател",
    "регион",
    "роль",
    "руковод",
    "согласован",
    "школ",
    "эцп",
    "эдо",
    "юрлиц",
    "юрид",
)
_SCALE_TERMS = (
    "в месяц",
    "документ",
    "договор",
    "контрагент",
    "пользовател",
    "сотрудник",
    "филиал",
    "школ",
    "регион",
)
_VAGUE_NEXT_STEP_TERMS = (
    "перезвоню",
    "перезвон",
    "уточню",
    "посмотрю",
    "узнаю",
    "отпишусь",
    "скину",
    "отправлю",
)
_CONTROLLED_NEXT_STEP_TERMS = (
    "демо",
    "демонстрац",
    "встреч",
    "созвон",
    "завтра",
    "сегодня",
    "дат",
    "время",
    "кто будет",
    "кто принимает",
    "лпр",
    "юрист",
    "it",
    "айти",
    "повестк",
)
_NEXT_STEP_ACTION_TERMS = (
    "демо",
    "демонстрац",
    "встреч",
    "созвон",
    "презентац",
    "показ",
    "назнач",
    "зафикс",
    "соглас",
    "завтра",
    "сегодня",
    "время",
    "удобно",
)
_QUALIFICATION_TERMS = (
    "сколько",
    "объем",
    "объём",
    "в месяц",
    "пользовател",
    "сотрудник",
    "кто принимает",
    "кто будет",
    "роль",
    "срок",
    "когда",
    "критер",
    "решени",
    "лпр",
)
_PROPOSAL_TERMS = (
    "коммерческое предложение",
    "коммерческим предложением",
    "кп",
    "прайс",
    "тариф",
)
_INTEREST_TERMS = (
    "интересно",
    "интересует",
    "расскажите",
    "хотели бы",
    "актуально",
    "рассматриваем",
)


@dataclass(slots=True, frozen=True)
class SituationDayCallInput:
    """Normalized single-call input for the composer.

    ``analysis`` and ``report_evidence`` must be persisted facts produced by
    previous layers.  The composer treats them as source data and does not
    infer customer facts that are absent from these fields or the transcript.
    """

    call_id: str
    transcript: str = ""
    analysis: dict[str, Any] = field(default_factory=dict)
    report_evidence: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    call_started_at: datetime | None = None
    duration_sec: int | None = None
    client_label: str | None = None
    client_phone: str | None = None


@dataclass(slots=True, frozen=True)
class SituationDayCandidate:
    """One business-significant coaching episode candidate."""

    candidate_id: str
    call_id: str
    pattern_code: str
    source: str
    score: float
    problem_title: str
    client_context: str
    evidence_scene: str
    manager_gap: str
    why_it_matters: str
    next_time_action: str
    suggested_phrase: str
    proof_type: ProofType
    proof_strength: ProofStrength
    stage_code: str | None = None
    stage_label: str | None = None
    supporting_quote: str | None = None
    manager_text: str | None = None
    dialogue_turns: list[dict[str, str]] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    ranking_features: dict[str, Any] = field(default_factory=dict)

    def to_diagnostic(self, rejection_reason: str | None = None) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "call_id": self.call_id,
            "pattern_code": self.pattern_code,
            "source": self.source,
            "score": round(self.score, 2),
            "problem_title": self.problem_title,
            "proof_type": self.proof_type,
            "proof_strength": self.proof_strength,
            "stage_code": self.stage_code,
            "rejection_reason": rejection_reason,
            "ranking_features": dict(self.ranking_features),
        }


@dataclass(slots=True, frozen=True)
class SituationDayComposerResult:
    """Output contract returned by ``SituationDayComposer.compose``."""

    status: SituationStatus
    selected_call_id: str | None = None
    problem_title: str | None = None
    client_context: str | None = None
    evidence_scene: str | None = None
    manager_gap: str | None = None
    why_it_matters: str | None = None
    next_time_action: str | None = None
    suggested_phrase: str | None = None
    proof_type: ProofType | None = None
    proof_strength: ProofStrength | None = None
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)
    quality_diagnostics: dict[str, Any] = field(default_factory=dict)
    report_layer_block: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "selected_call_id": self.selected_call_id,
            "problem_title": self.problem_title,
            "client_context": self.client_context,
            "evidence_scene": self.evidence_scene,
            "manager_gap": self.manager_gap,
            "why_it_matters": self.why_it_matters,
            "next_time_action": self.next_time_action,
            "suggested_phrase": self.suggested_phrase,
            "proof_type": self.proof_type,
            "proof_strength": self.proof_strength,
            "rejected_candidates": list(self.rejected_candidates),
            "quality_diagnostics": dict(self.quality_diagnostics),
        }
        payload.update(self.report_layer_block)
        return payload


class SituationDayInputAdapter:
    """Convert ReportArtifact-like objects or plain dictionaries into calls."""

    def normalize_calls(
        self,
        artifacts: Iterable[Any],
        *,
        report_evidence_index: dict[str, dict[str, Any]] | None = None,
    ) -> list[SituationDayCallInput]:
        calls: list[SituationDayCallInput] = []
        for artifact in artifacts:
            call = self._normalize_one(
                artifact,
                report_evidence_index=report_evidence_index or {},
            )
            if call is not None:
                calls.append(call)
        return calls

    def _normalize_one(
        self,
        artifact: Any,
        *,
        report_evidence_index: dict[str, dict[str, Any]],
    ) -> SituationDayCallInput | None:
        interaction = _obj_get(artifact, "interaction") or {}
        analysis_obj = _obj_get(artifact, "analysis") or _obj_get(artifact, "original_analysis")
        call_id = _first_text(
            _obj_get(interaction, "id"),
            _dict_get(artifact, "call_id"),
            _dict_get(artifact, "interaction_id"),
            _dict_get(interaction, "interaction_id"),
        )
        if not call_id:
            return None

        metadata = _as_dict(_obj_get(interaction, "metadata_") or _obj_get(interaction, "metadata"))
        metadata.update(_as_dict(_dict_get(artifact, "metadata")))
        transcript = _first_text(
            _obj_get(interaction, "text"),
            _dict_get(artifact, "transcript"),
            _dict_get(artifact, "text"),
        )
        analysis = _as_dict(_obj_get(analysis_obj, "scores_detail") or _dict_get(artifact, "analysis"))
        indexed = _as_dict(report_evidence_index.get(call_id))
        report_evidence = _as_dict(indexed.get("report_evidence") or analysis.get("report_evidence"))
        call_started_at = _coerce_datetime(
            _obj_get(artifact, "call_started_at")
            or metadata.get("call_date")
            or metadata.get("started_at")
        )
        return SituationDayCallInput(
            call_id=call_id,
            transcript=transcript or "",
            analysis=analysis,
            report_evidence=report_evidence,
            metadata=metadata,
            call_started_at=call_started_at,
            duration_sec=_coerce_int(
                _obj_get(interaction, "duration_sec")
                or _dict_get(artifact, "duration_sec")
                or metadata.get("duration_sec")
            ),
            client_label=_first_text(
                metadata.get("contact_name"),
                metadata.get("client_name"),
                metadata.get("contact_label"),
            ),
            client_phone=_first_text(
                metadata.get("contact_phone"),
                metadata.get("phone"),
                _nested_text(analysis, ("call", "contact_phone")),
            ),
        )


class SituationDayCandidatePoolBuilder:
    """Build candidates from LLM2 report evidence, analysis facts and transcript."""

    def build(self, calls: list[SituationDayCallInput]) -> list[SituationDayCandidate]:
        candidates: list[SituationDayCandidate] = []
        for call in calls:
            candidates.extend(self._from_block_candidates(call))
            candidates.extend(self._from_semantic_case(call))
            candidates.extend(self._from_legacy_candidates(call))
            candidates.extend(self._from_transcript_patterns(call))
        return _dedupe_candidates(candidates)

    def _from_block_candidates(self, call: SituationDayCallInput) -> list[SituationDayCandidate]:
        block_candidates = _as_dict(call.report_evidence.get("block_candidates"))
        raw = _as_dict(block_candidates.get("situation_day"))
        if not raw or not _truthy(raw.get("fit")):
            return []
        pattern_code = _pattern_from_text(
            " ".join(str(raw.get(key) or "") for key in raw),
            default="report_evidence_block_candidate",
        )
        turns = _turns_from_candidate(raw)
        source_text = _candidate_source_text(raw, turns=turns, transcript=call.transcript)
        return [
            self._candidate_from_parts(
                call=call,
                pattern_code=pattern_code,
                source="report_evidence.block_candidates.situation_day",
                base_score=float(_coerce_int(raw.get("score")) or 65),
                problem_title=_first_text(raw.get("main_thesis"), raw.get("title"), raw.get("situation_title"))
                or _problem_title_for_pattern(pattern_code),
                client_context=_first_text(
                    raw.get("client_context"),
                    raw.get("business_context"),
                    _nested_text(call.report_evidence, ("call_report_summary", "business_context")),
                    source_text,
                ),
                evidence_scene=source_text,
                manager_gap=_first_text(raw.get("what_was_missing"), raw.get("missing_action"))
                or _manager_gap_for_pattern(pattern_code),
                why_it_matters=_first_text(raw.get("why_it_matters"), raw.get("meaning"))
                or _why_it_matters_for_pattern(pattern_code),
                next_time_action=_first_text(raw.get("better_next_action"), raw.get("next_time_action"))
                or _next_action_for_pattern(pattern_code),
                suggested_phrase=_first_script(raw) or _suggested_phrase_for_pattern(pattern_code),
                proof_type=_proof_type_from_raw(raw, pattern_code),
                proof_strength=_proof_strength_from_source(raw, source_text),
                stage_code=_first_text(raw.get("stage_code"), raw.get("stage")),
                supporting_quote=_first_text(raw.get("supporting_quote"), raw.get("quote")),
                dialogue_turns=turns,
                raw_features={"fit_score": raw.get("score")},
            )
        ]

    def _from_semantic_case(self, call: SituationDayCallInput) -> list[SituationDayCandidate]:
        case = _as_dict(call.report_evidence.get("semantic_case"))
        if not case or case.get("usable_in_report") is False:
            return []
        fit = _as_dict(_as_dict(case.get("report_block_fit")).get("situation_day"))
        if fit and fit.get("fit") is False:
            return []
        text = " ".join(str(case.get(key) or "") for key in case)
        pattern_code = _pattern_from_text(text, default="semantic_case")
        turns = _turns_from_candidate(case)
        source_text = _candidate_source_text(case, turns=turns, transcript=call.transcript)
        moment = _as_dict(fit.get("coaching_moment")) or _as_dict(case.get("coaching_moment"))
        return [
            self._candidate_from_parts(
                call=call,
                pattern_code=pattern_code,
                source="report_evidence.semantic_case",
                base_score=float(_coerce_int(fit.get("score")) or 62),
                problem_title=_first_text(case.get("case_title"), fit.get("title"))
                or _problem_title_for_pattern(pattern_code),
                client_context=_first_text(
                    case.get("customer_context"),
                    case.get("client_context"),
                    case.get("why_this_call_matters"),
                    _nested_text(call.report_evidence, ("call_report_summary", "business_context")),
                    source_text,
                ),
                evidence_scene=source_text,
                manager_gap=_first_text(
                    moment.get("missing_action"),
                    moment.get("gap_claim"),
                    case.get("coaching_diagnosis"),
                )
                or _manager_gap_for_pattern(pattern_code),
                why_it_matters=_first_text(
                    moment.get("why_it_matters"),
                    case.get("core_meaning"),
                    case.get("why_this_call_matters"),
                )
                or _why_it_matters_for_pattern(pattern_code),
                next_time_action=_first_text(case.get("recommended_next_action"), moment.get("better_action"))
                or _next_action_for_pattern(pattern_code),
                suggested_phrase=_first_script(case) or _suggested_phrase_for_pattern(pattern_code),
                proof_type=_proof_type_from_raw(moment or case, pattern_code),
                proof_strength=_proof_strength_from_source(case, source_text),
                stage_code=_first_text(
                    fit.get("stage_code"),
                    case.get("stage_code"),
                    moment.get("stage_code"),
                ),
                supporting_quote=_first_text(moment.get("supporting_quote"), case.get("supporting_quote")),
                dialogue_turns=turns,
                raw_features={"fit_score": fit.get("score"), "case_type": case.get("case_type")},
            )
        ]

    def _from_legacy_candidates(self, call: SituationDayCallInput) -> list[SituationDayCandidate]:
        result: list[SituationDayCandidate] = []
        for index, raw_item in enumerate(call.report_evidence.get("situation_candidates") or []):
            raw = _as_dict(raw_item)
            if not raw or raw.get("usable_in_report") is False:
                continue
            turns = _turns_from_candidate(raw)
            source_text = _candidate_source_text(raw, turns=turns, transcript=call.transcript)
            pattern_code = _pattern_from_text(
                " ".join(str(raw.get(key) or "") for key in raw),
                default="legacy_situation_candidate",
            )
            result.append(
                self._candidate_from_parts(
                    call=call,
                    pattern_code=pattern_code,
                    source=f"report_evidence.situation_candidates[{index}]",
                    base_score=58.0,
                    problem_title=_first_text(raw.get("situation_title"), raw.get("title"))
                    or _problem_title_for_pattern(pattern_code),
                    client_context=_first_text(raw.get("client_context"), source_text),
                    evidence_scene=source_text,
                    manager_gap=_first_text(raw.get("what_was_missing"), raw.get("manager_gap"))
                    or _manager_gap_for_pattern(pattern_code),
                    why_it_matters=_first_text(raw.get("what_it_means"), raw.get("why_it_matters"))
                    or _why_it_matters_for_pattern(pattern_code),
                    next_time_action=_first_text(raw.get("next_time_action"), raw.get("better_next_action"))
                    or _next_action_for_pattern(pattern_code),
                    suggested_phrase=_first_script(raw) or _suggested_phrase_for_pattern(pattern_code),
                    proof_type=_proof_type_from_raw(raw, pattern_code),
                    proof_strength=_proof_strength_from_source(raw, source_text),
                    stage_code=_first_text(raw.get("stage_code"), raw.get("stage")),
                    supporting_quote=_first_text(raw.get("supporting_quote"), raw.get("quote")),
                    dialogue_turns=turns,
                    raw_features={"legacy_index": index},
                )
            )
        return result

    def _from_transcript_patterns(self, call: SituationDayCallInput) -> list[SituationDayCandidate]:
        transcript = _clean_text(call.transcript)
        if not transcript:
            return []

        facts = _transcript_features(transcript)
        patterns: list[str] = []
        if _detect_proposal_without_microqualification(transcript, facts):
            patterns.append("proposal_without_microqualification")
        if _detect_complex_b2b_without_next_step(transcript, facts):
            patterns.append("complex_b2b_without_controlled_next_step")
        if _detect_interest_without_decision(transcript, facts):
            patterns.append("interest_without_decision")

        result: list[SituationDayCandidate] = []
        for pattern_code in patterns:
            scene = _scene_for_pattern(transcript, pattern_code)
            context = _context_for_pattern(call, transcript, pattern_code, scene)
            result.append(
                self._candidate_from_parts(
                    call=call,
                    pattern_code=pattern_code,
                    source="transcript.pattern_inference",
                    base_score=_pattern_base_score(pattern_code),
                    problem_title=_problem_title_for_pattern(pattern_code),
                    client_context=context,
                    evidence_scene=scene,
                    manager_gap=_manager_gap_for_pattern(pattern_code),
                    why_it_matters=_why_it_matters_for_pattern(pattern_code),
                    next_time_action=_next_action_for_pattern(pattern_code),
                    suggested_phrase=_suggested_phrase_for_pattern(pattern_code),
                    proof_type="sequence_inference",
                    proof_strength="strong" if len(scene) >= 220 else "medium",
                    stage_code=_stage_for_pattern(pattern_code),
                    supporting_quote=_supporting_quote_for_pattern(transcript, pattern_code),
                    dialogue_turns=[{"speaker": "context", "text": scene}],
                    raw_features=facts,
                )
            )
        return result

    def _candidate_from_parts(
        self,
        *,
        call: SituationDayCallInput,
        pattern_code: str,
        source: str,
        base_score: float,
        problem_title: str,
        client_context: str,
        evidence_scene: str,
        manager_gap: str,
        why_it_matters: str,
        next_time_action: str,
        suggested_phrase: str,
        proof_type: ProofType,
        proof_strength: ProofStrength,
        stage_code: str | None,
        supporting_quote: str | None,
        dialogue_turns: list[dict[str, str]],
        raw_features: dict[str, Any],
    ) -> SituationDayCandidate:
        features = {
            **raw_features,
            "business_signal_count": _business_signal_count(
                " ".join((client_context, evidence_scene, call.transcript))
            ),
            "has_transcript": bool(call.transcript.strip()),
            "has_dialogue_turns": bool(dialogue_turns),
        }
        score = _score_candidate(
            base_score=base_score,
            pattern_code=pattern_code,
            client_context=client_context,
            evidence_scene=evidence_scene,
            features=features,
        )
        return SituationDayCandidate(
            candidate_id=f"{call.call_id}:{source}:{pattern_code}",
            call_id=call.call_id,
            pattern_code=pattern_code,
            source=source,
            score=score,
            problem_title=_first_sentence(problem_title, limit=220),
            client_context=_bounded_text(client_context, limit=900),
            evidence_scene=_bounded_text(evidence_scene, limit=1100),
            manager_gap=_bounded_text(manager_gap, limit=650),
            why_it_matters=_bounded_text(why_it_matters, limit=650),
            next_time_action=_bounded_text(next_time_action, limit=650),
            suggested_phrase=_bounded_text(suggested_phrase, limit=650),
            proof_type=proof_type,
            proof_strength=proof_strength,
            stage_code=stage_code,
            stage_label=_stage_label_for_code(stage_code),
            supporting_quote=_bounded_text(supporting_quote or "", limit=260) or None,
            manager_text=None,
            dialogue_turns=dialogue_turns[:5],
            evidence_refs=[
                {
                    "call_id": call.call_id,
                    "source": source,
                    "pattern_code": pattern_code,
                    "uses_transcript": bool(call.transcript.strip()),
                }
            ],
            ranking_features=features,
        )


class SituationDayRanker:
    """Rank day candidates by coaching value and evidence quality."""

    def rank(self, candidates: list[SituationDayCandidate]) -> list[SituationDayCandidate]:
        return sorted(
            candidates,
            key=lambda item: (
                -item.score,
                _proof_strength_rank(item.proof_strength),
                _source_rank(item.source),
                item.call_id,
            ),
        )


class SituationDayQualityGate:
    """Fail-closed quality gate for manager-facing Situation Day blocks."""

    def validate(self, candidate: SituationDayCandidate) -> tuple[bool, dict[str, Any]]:
        checks = {
            "selected_call_id": bool(candidate.call_id),
            "client_context": _meaningful_text(candidate.client_context, min_chars=70),
            "evidence_scene": _meaningful_text(candidate.evidence_scene, min_chars=90),
            "manager_gap": _meaningful_text(candidate.manager_gap, min_chars=45),
            "why_it_matters": _meaningful_text(candidate.why_it_matters, min_chars=45),
            "next_time_action": _meaningful_text(candidate.next_time_action, min_chars=45),
            "suggested_phrase": _meaningful_text(candidate.suggested_phrase, min_chars=25),
            "proof_type": candidate.proof_type in SUPPORTED_PROOF_TYPES,
            "proof_strength": candidate.proof_strength in {"strong", "medium"},
            "not_quote_only": _word_count(candidate.evidence_scene) >= 14,
            "concrete_action": _has_any(candidate.next_time_action, _CONTROLLED_NEXT_STEP_TERMS)
            or _has_any(candidate.next_time_action, ("уточнить", "зафиксировать", "резюмировать")),
            "manager_gap_specific": not _is_generic_gap(candidate.manager_gap),
            "client_context_specific": not _is_generic_context(candidate.client_context),
            "next_time_action_specific": not _is_generic_next_action(candidate.next_time_action),
        }
        failed = [name for name, passed in checks.items() if not passed]
        return not failed, {
            "status": "passed" if not failed else "failed",
            "failed_checks": failed,
            "checks": checks,
            "composer_version": SITUATION_DAY_COMPOSER_VERSION,
        }


class DeterministicSituationDayWriter:
    """Build final output without calling LLM3."""

    def build(
        self,
        *,
        candidate: SituationDayCandidate,
        rejected: list[dict[str, Any]],
        quality_diagnostics: dict[str, Any],
    ) -> SituationDayComposerResult:
        block = self._report_layer_block(
            candidate=candidate,
            rejected=rejected,
            quality_diagnostics=quality_diagnostics,
        )
        return SituationDayComposerResult(
            status="verified",
            selected_call_id=candidate.call_id,
            problem_title=candidate.problem_title,
            client_context=candidate.client_context,
            evidence_scene=candidate.evidence_scene,
            manager_gap=candidate.manager_gap,
            why_it_matters=candidate.why_it_matters,
            next_time_action=candidate.next_time_action,
            suggested_phrase=candidate.suggested_phrase,
            proof_type=candidate.proof_type,
            proof_strength=candidate.proof_strength,
            rejected_candidates=rejected,
            quality_diagnostics=quality_diagnostics,
            report_layer_block=block,
        )

    def insufficient(
        self,
        *,
        status: SituationStatus,
        reason: str,
        rejected: list[dict[str, Any]],
        candidates_count: int,
    ) -> SituationDayComposerResult:
        diagnostics = {
            "status": "failed",
            "reason": reason,
            "candidate_count": candidates_count,
            "composer_version": SITUATION_DAY_COMPOSER_VERSION,
        }
        block = {
            "situation_title": "Нет надежной ситуации дня",
            "no_verified_situation_day": True,
            "selection_diagnostics": {
                "candidate_source": "situation_day_composer",
                "selection_mode": "fail_closed",
                "selected": None,
                "rejected": rejected,
                "reason": reason,
            },
            "coaching_view": {
                "pattern_title": "Нет надежной ситуации дня",
                "what_happened": "Недостаточно доказательного материала для честного блока.",
                "meaning": "Лучше скрыть блок, чем показывать менеджеру неподтвержденный вывод.",
                "source": REPORT_LAYER_SOURCE,
                "situation_day_evidence_status": status,
                "insufficiency_reason": reason,
                "proof_strength": "insufficient",
            },
        }
        return SituationDayComposerResult(
            status=status,
            rejected_candidates=rejected,
            quality_diagnostics=diagnostics,
            report_layer_block=block,
        )

    def _report_layer_block(
        self,
        *,
        candidate: SituationDayCandidate,
        rejected: list[dict[str, Any]],
        quality_diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        ref = {
            "call_id": candidate.call_id,
            "client_label": None,
            "client_phone": None,
            "date_label": None,
            "time_label": None,
            "client_call_reference": candidate.call_id,
        }
        turns = candidate.dialogue_turns or [{"speaker": "context", "text": candidate.evidence_scene}]
        quote_is_manager_action = bool(
            candidate.supporting_quote
            and candidate.pattern_code == "complex_b2b_without_controlled_next_step"
            and _has_any(candidate.supporting_quote, _VAGUE_NEXT_STEP_TERMS)
        )
        return {
            "situation_title": candidate.problem_title,
            "evidence_quote": {
                **ref,
                "client_text": None if quote_is_manager_action else candidate.supporting_quote or candidate.evidence_scene,
                "manager_text": candidate.supporting_quote if quote_is_manager_action else candidate.manager_text,
                "criterion_code": None,
                "stage_code": candidate.stage_code,
                "source": REPORT_LAYER_SOURCE,
                "evidence_quality": "direct"
                if candidate.proof_type == "direct_gap"
                else "indirect",
                "client_grounded": candidate.proof_type != "business_context_inference" and not quote_is_manager_action,
                "proof_type": candidate.proof_type,
                "quote_role": "supports_context"
                if candidate.proof_type != "direct_gap"
                else "proves_gap",
            },
            "dialogue_excerpt": {
                **ref,
                "source": REPORT_LAYER_SOURCE,
                "is_partial": True,
                "partial_reason": "composer_bounded_day_scene",
                "turns": turns,
            },
            "coaching_view": {
                "pattern_title": candidate.problem_title,
                "stage_code": candidate.stage_code,
                "stage_label": candidate.stage_label,
                "what_happened": candidate.evidence_scene,
                "meaning": candidate.why_it_matters,
                "what_was_missing": candidate.manager_gap,
                "next_time_action": candidate.next_time_action,
                "scripts": [candidate.suggested_phrase],
                "moment_summary": candidate.problem_title,
                "missing_action": candidate.manager_gap,
                "why_it_matters": candidate.why_it_matters,
                "supporting_quote": candidate.supporting_quote,
                "evidence_type": candidate.proof_type,
                "proof_type": candidate.proof_type,
                "proof_strength": candidate.proof_strength,
                "source": REPORT_LAYER_SOURCE,
                "situation_day_evidence_status": "verified",
                "client_context": candidate.client_context,
                "evidence_scene": candidate.evidence_scene,
                "suggested_phrase": candidate.suggested_phrase,
                "selection_diagnostics": {
                    "candidate_source": "situation_day_composer",
                    "selection_mode": "ranked_quality_gate",
                    "selected": candidate.to_diagnostic(),
                    "rejected": rejected,
                    "quality_gate": quality_diagnostics,
                },
            },
            "selection_diagnostics": {
                "candidate_source": "situation_day_composer",
                "selection_mode": "ranked_quality_gate",
                "selected": candidate.to_diagnostic(),
                "rejected": rejected,
                "quality_gate": quality_diagnostics,
            },
        }


class LLM3SituationDayWriter:
    """Optional OpenAI-compatible LLM3 selector/composer for valid candidates."""

    def enabled(self) -> bool:
        try:
            from app.core_shared.config.settings import settings
        except Exception:
            return False
        return bool(settings.llm3_enabled)

    def compose_candidate(
        self,
        *,
        candidates: list[SituationDayCandidate],
        rejected: list[dict[str, Any]],
    ) -> tuple[SituationDayCandidate | None, dict[str, Any]]:
        diagnostics: dict[str, Any] = {
            "llm3_enabled": self.enabled(),
            "llm3_used": False,
            "llm3_prompt_version": SITUATION_DAY_PROMPT_VERSION,
        }
        if not candidates or not diagnostics["llm3_enabled"]:
            return None, diagnostics

        try:
            raw = self._request(candidates=candidates)
            diagnostics["llm3_raw_status"] = raw.get("status")
            if isinstance(raw.get("_routing"), dict):
                diagnostics["llm3_routing"] = raw.get("_routing")
            selected = self._candidate_from_response(raw=raw, candidates=candidates)
            if selected is None:
                diagnostics["llm3_rejection_reason"] = "no_matching_verified_candidate"
                diagnostics["llm3_response"] = _json_safe(raw)
                return None, diagnostics
            rewritten = self._rewrite_candidate_from_response(candidate=selected, raw=raw)
            diagnostics.update(
                {
                    "llm3_used": True,
                    "llm3_selected_candidate_id": selected.candidate_id,
                    "llm3_selected_call_id": selected.call_id,
                    "llm3_rejected_candidates_count": len(rejected),
                }
            )
            return rewritten, diagnostics
        except Exception as exc:
            diagnostics["llm3_error"] = str(exc)
            return None, diagnostics

    def _request(self, *, candidates: list[SituationDayCandidate]) -> dict[str, Any]:
        from openai import OpenAI
        from app.core_shared.ai_routing import AIProviderRouter
        from app.core_shared.config.settings import settings

        payload = build_llm3_contract_payload(candidates)
        prompt = _read_llm3_prompt()
        route_plan = AIProviderRouter().build_route_plan(
            layer="llm3",
            subject_key="|".join(candidate.candidate_id for candidate in candidates[:8]),
        )
        candidate = route_plan.current_candidate()
        compatibility_candidate = candidate
        if (candidate.endpoint or "").rstrip("/") == "/chat/completions":
            compatibility_candidate = replace(candidate, endpoint=None)
        AIProviderRouter.ensure_execution_compatibility(
            compatibility_candidate,
            executor_label="LLM-3 OpenAI-compatible executor",
            required_execution_mode="openai_compatible",
        )
        client = OpenAI(
            api_key=candidate.resolved_api_key(),
            base_url=candidate.api_base,
        )
        last_error: Exception | None = None
        response = None
        attempts_total = max(1, candidate.max_retries_for_this_provider + 1)
        for _ in range(attempts_total):
            try:
                response = client.chat.completions.create(
                    **build_chat_completion_kwargs(
                        model=candidate.model,
                        response_format={"type": "json_object"},
                        temperature=0.1,
                        timeout=candidate.timeout_sec or settings.openai_timeout_sec,
                        messages=[
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                    )
                )
                break
            except Exception as exc:
                last_error = exc
        if response is None:
            route_plan.mark_attempt_failure(str(last_error or "unknown_llm3_error"))
            raise last_error or RuntimeError("Unknown LLM3 request failure")
        route_plan.mark_attempt_success()
        content = _extract_openai_message_content(response)
        parsed = json.loads(content)
        result = _as_dict(parsed)
        result["_routing"] = route_plan.to_metadata(
            request_kind="situation_day_composer",
            notes="LLM-3 Situation Day composer completed.",
        )
        return result

    @staticmethod
    def _candidate_from_response(
        *,
        raw: dict[str, Any],
        candidates: list[SituationDayCandidate],
    ) -> SituationDayCandidate | None:
        if str(raw.get("status") or "").strip() != "verified":
            return None
        selected_candidate_id = str(raw.get("selected_candidate_id") or "").strip()
        selected_call_id = str(raw.get("selected_call_id") or "").strip()
        if selected_candidate_id:
            for candidate in candidates:
                if candidate.candidate_id == selected_candidate_id:
                    return candidate
        if selected_call_id:
            for candidate in candidates:
                if candidate.call_id == selected_call_id:
                    return candidate
        return None

    @staticmethod
    def _rewrite_candidate_from_response(
        *,
        candidate: SituationDayCandidate,
        raw: dict[str, Any],
    ) -> SituationDayCandidate:
        proof_type = str(raw.get("proof_type") or "").strip()
        proof_strength = str(raw.get("proof_strength") or "").strip()
        return replace(
            candidate,
            problem_title=_llm3_text_or_original(
                raw.get("problem_title"),
                candidate.problem_title,
                limit=220,
            ),
            client_context=_llm3_text_or_original(
                raw.get("client_context"),
                candidate.client_context,
                limit=900,
            ),
            evidence_scene=_llm3_text_or_original(
                raw.get("evidence_scene"),
                candidate.evidence_scene,
                limit=1100,
            ),
            manager_gap=_llm3_text_or_original(
                raw.get("manager_gap"),
                candidate.manager_gap,
                limit=650,
            ),
            why_it_matters=_llm3_text_or_original(
                raw.get("why_it_matters"),
                candidate.why_it_matters,
                limit=650,
            ),
            next_time_action=_llm3_text_or_original(
                raw.get("next_time_action"),
                candidate.next_time_action,
                limit=650,
            ),
            suggested_phrase=_llm3_text_or_original(
                raw.get("suggested_phrase"),
                candidate.suggested_phrase,
                limit=650,
            ),
            proof_type=candidate.proof_type if proof_type not in SUPPORTED_PROOF_TYPES else proof_type,
            proof_strength=candidate.proof_strength
            if proof_strength not in {"strong", "medium", "weak"}
            else proof_strength,
            ranking_features={
                **candidate.ranking_features,
                "llm3_composed": True,
            },
        )


class SituationDayComposer:
    """Pilot deterministic composer with LLM3-ready internal seams."""

    def __init__(
        self,
        *,
        input_adapter: SituationDayInputAdapter | None = None,
        candidate_pool_builder: SituationDayCandidatePoolBuilder | None = None,
        ranker: SituationDayRanker | None = None,
        quality_gate: SituationDayQualityGate | None = None,
        writer: DeterministicSituationDayWriter | None = None,
        llm3_writer: LLM3SituationDayWriter | None = None,
    ) -> None:
        self.input_adapter = input_adapter or SituationDayInputAdapter()
        self.candidate_pool_builder = candidate_pool_builder or SituationDayCandidatePoolBuilder()
        self.ranker = ranker or SituationDayRanker()
        self.quality_gate = quality_gate or SituationDayQualityGate()
        self.writer = writer or DeterministicSituationDayWriter()
        self.llm3_writer = llm3_writer or LLM3SituationDayWriter()

    def compose(
        self,
        artifacts: Iterable[Any],
        *,
        report_evidence_index: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        calls = self.input_adapter.normalize_calls(
            artifacts,
            report_evidence_index=report_evidence_index,
        )
        if not calls:
            return self.writer.insufficient(
                status="no_data",
                reason="no_calls",
                rejected=[],
                candidates_count=0,
            ).to_dict()

        candidates = self.candidate_pool_builder.build(calls)
        if not candidates:
            reason = "no_candidate_with_business_context"
            if not any(call.transcript.strip() for call in calls):
                reason = "no_transcript_or_analysis_facts"
            return self.writer.insufficient(
                status="no_data" if reason == "no_transcript_or_analysis_facts" else "insufficient",
                reason=reason,
                rejected=[],
                candidates_count=0,
            ).to_dict()

        rejected: list[dict[str, Any]] = []
        valid: list[tuple[SituationDayCandidate, dict[str, Any]]] = []
        for candidate in self.ranker.rank(candidates):
            passed, diagnostics = self.quality_gate.validate(candidate)
            if passed:
                valid.append((candidate, diagnostics))
                continue
            rejected.append(candidate.to_diagnostic(";".join(diagnostics["failed_checks"])))

        if valid:
            valid_candidates = [candidate for candidate, _diagnostics in valid]
            diagnostics_by_id = {
                candidate.candidate_id: diagnostics for candidate, diagnostics in valid
            }
            llm3_candidate, llm3_diagnostics = self.llm3_writer.compose_candidate(
                candidates=valid_candidates,
                rejected=rejected,
            )
            if llm3_candidate is not None:
                passed, rewritten_diagnostics = self.quality_gate.validate(llm3_candidate)
                if passed:
                    return self.writer.build(
                        candidate=llm3_candidate,
                        rejected=rejected,
                        quality_diagnostics={
                            **rewritten_diagnostics,
                            "llm3": llm3_diagnostics,
                        },
                    ).to_dict()
                llm3_diagnostics["llm3_rewrite_rejection_reason"] = ";".join(
                    rewritten_diagnostics["failed_checks"]
                )

            candidate, diagnostics = valid[0]
            return self.writer.build(
                candidate=candidate,
                rejected=rejected,
                quality_diagnostics={
                    **diagnostics_by_id.get(candidate.candidate_id, diagnostics),
                    "llm3": llm3_diagnostics,
                },
            ).to_dict()

        return self.writer.insufficient(
            status="insufficient",
            reason="quality_gate_no_valid_candidates",
            rejected=rejected,
            candidates_count=len(candidates),
        ).to_dict()

    def build_candidate_pool(
        self,
        artifacts: Iterable[Any],
        *,
        report_evidence_index: dict[str, dict[str, Any]] | None = None,
    ) -> list[SituationDayCandidate]:
        calls = self.input_adapter.normalize_calls(
            artifacts,
            report_evidence_index=report_evidence_index,
        )
        return self.candidate_pool_builder.build(calls)


def compose_situation_day(
    artifacts: Iterable[Any],
    *,
    report_evidence_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose Situation Day from day artifacts using the pilot deterministic path."""

    return SituationDayComposer().compose(
        artifacts,
        report_evidence_index=report_evidence_index,
    )


def build_situation_day_candidate_pool(
    artifacts: Iterable[Any],
    *,
    report_evidence_index: dict[str, dict[str, Any]] | None = None,
) -> list[SituationDayCandidate]:
    """Return candidate pool for debugging, A/B tests or a future LLM3 call."""

    return SituationDayComposer().build_candidate_pool(
        artifacts,
        report_evidence_index=report_evidence_index,
    )


def build_llm3_contract_payload(
    candidates: list[SituationDayCandidate],
    *,
    max_candidates: int = 8,
) -> dict[str, Any]:
    """Build the bounded payload a future LLM3 report-composer call should receive."""

    ranked = SituationDayRanker().rank(candidates)[:max_candidates]
    return {
        "contract_version": SITUATION_DAY_PROMPT_VERSION,
        "instruction": (
            "Choose one Situation Day candidate or return insufficient. Use only "
            "candidate fields and evidence_refs; do not add transcript facts."
        ),
        "candidates": [
            {
                "candidate_id": item.candidate_id,
                "call_id": item.call_id,
                "pattern_code": item.pattern_code,
                "source": item.source,
                "score": item.score,
                "problem_title": item.problem_title,
                "client_context": item.client_context,
                "evidence_scene": item.evidence_scene,
                "manager_gap": item.manager_gap,
                "why_it_matters": item.why_it_matters,
                "next_time_action": item.next_time_action,
                "suggested_phrase": item.suggested_phrase,
                "proof_type": item.proof_type,
                "proof_strength": item.proof_strength,
                "evidence_refs": item.evidence_refs,
            }
            for item in ranked
        ],
        "required_output_keys": [
            "status",
            "selected_candidate_id",
            "selected_call_id",
            "problem_title",
            "client_context",
            "evidence_scene",
            "manager_gap",
            "why_it_matters",
            "next_time_action",
            "suggested_phrase",
            "proof_type",
            "proof_strength",
            "rejected_candidates",
            "quality_diagnostics",
        ],
    }


def _read_llm3_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "Return one JSON object for Situation Day. Use only provided candidates. "
            "If no candidate is strong enough, return status='insufficient'."
        )


def _extract_openai_message_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return str(content or "").strip()


def _llm3_text_or_original(value: Any, original: str, *, limit: int) -> str:
    text = _bounded_text(_first_text(value) or "", limit=limit)
    if _word_count(text) < 4:
        return original
    return text


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _dedupe_candidates(candidates: list[SituationDayCandidate]) -> list[SituationDayCandidate]:
    best_by_key: dict[tuple[str, str], SituationDayCandidate] = {}
    for candidate in candidates:
        key = (candidate.call_id, candidate.pattern_code)
        previous = best_by_key.get(key)
        if previous is None or candidate.score > previous.score:
            best_by_key[key] = candidate
    return list(best_by_key.values())


def _score_candidate(
    *,
    base_score: float,
    pattern_code: str,
    client_context: str,
    evidence_scene: str,
    features: dict[str, Any],
) -> float:
    score = base_score
    score += min(int(features.get("business_signal_count") or 0), 8) * 3
    score += min(_word_count(client_context), 80) / 10
    score += min(_word_count(evidence_scene), 100) / 8
    if features.get("has_transcript"):
        score += 8
    if pattern_code == "complex_b2b_without_controlled_next_step":
        score += 12
    elif pattern_code == "proposal_without_microqualification":
        score += 9
    elif pattern_code == "interest_without_decision":
        score += 5
    return score


def _transcript_features(transcript: str) -> dict[str, Any]:
    normalized = _norm(transcript)
    return {
        "b2b_signal_count": _count_terms(normalized, _B2B_TERMS),
        "scale_signal_count": _count_terms(normalized, _SCALE_TERMS),
        "qualification_signal_count": _count_terms(normalized, _QUALIFICATION_TERMS),
        "proposal_signal": _has_any(normalized, _PROPOSAL_TERMS),
        "interest_signal": _has_any(normalized, _INTEREST_TERMS),
        "vague_next_step_signal": _has_any(normalized, _VAGUE_NEXT_STEP_TERMS),
        "controlled_next_step_signal": _has_controlled_next_step(transcript),
        "number_signal_count": len(re.findall(r"\b\d+\b", normalized)),
    }


def _detect_proposal_without_microqualification(
    transcript: str,
    features: dict[str, Any],
) -> bool:
    text = _norm(transcript)
    return (
        bool(features["proposal_signal"])
        and ("отправ" in text or "скин" in text or "whatsapp" in text or "ватсап" in text)
        and int(features["qualification_signal_count"]) <= 2
    )


def _detect_complex_b2b_without_next_step(
    transcript: str,
    features: dict[str, Any],
) -> bool:
    return (
        int(features["b2b_signal_count"]) >= 4
        and (int(features["scale_signal_count"]) >= 2 or int(features["number_signal_count"]) >= 1)
        and bool(features["vague_next_step_signal"])
        and not bool(features["controlled_next_step_signal"])
    )


def _has_controlled_next_step(transcript: str) -> bool:
    """Return true only for an explicit next action, not for qualification terms."""
    for sentence in _sentences(transcript):
        text = _norm(sentence)
        if not _has_any(text, _NEXT_STEP_ACTION_TERMS):
            continue
        if _has_any(text, ("кто будет доступ", "кто будет отправлять", "кто будет составлять")):
            continue
        if _has_any(text, ("давайте", "предлагаю", "назнач", "соглас", "удобно", "встреч", "демо", "созвон")):
            return True
    return False


def _detect_interest_without_decision(
    transcript: str,
    features: dict[str, Any],
) -> bool:
    return (
        bool(features["interest_signal"])
        and bool(features["vague_next_step_signal"])
        and not bool(features["controlled_next_step_signal"])
        and int(features["qualification_signal_count"]) <= 3
    )


def _scene_for_pattern(transcript: str, pattern_code: str) -> str:
    anchors_by_pattern = {
        "proposal_without_microqualification": _PROPOSAL_TERMS + ("отправ", "скин"),
        "complex_b2b_without_controlled_next_step": _B2B_TERMS + _VAGUE_NEXT_STEP_TERMS,
        "interest_without_decision": _INTEREST_TERMS + _VAGUE_NEXT_STEP_TERMS,
    }
    anchors = anchors_by_pattern.get(pattern_code, ())
    return _excerpt_around_terms(transcript, anchors, limit=900)


def _context_for_pattern(
    call: SituationDayCallInput,
    transcript: str,
    pattern_code: str,
    scene: str,
) -> str:
    summary_context = _first_text(
        _nested_text(call.report_evidence, ("call_report_summary", "business_context")),
        _nested_text(call.report_evidence, ("call_report_summary", "customer_need")),
        _nested_text(call.report_evidence, ("semantic_case", "customer_context")),
        _nested_text(call.report_evidence, ("semantic_case", "why_this_call_matters")),
    )
    if summary_context and _business_signal_count(summary_context) >= 2 and _word_count(summary_context) >= 12:
        return summary_context
    if pattern_code == "complex_b2b_without_controlled_next_step":
        complex_terms = tuple(
            term
            for term in (_B2B_TERMS + _SCALE_TERMS)
            if term not in {"договор", "документ"}
        )
        return _excerpt_around_terms(transcript, complex_terms, limit=650)
    return _bounded_text(scene, limit=650)


def _supporting_quote_for_pattern(transcript: str, pattern_code: str) -> str | None:
    anchors_by_pattern = {
        "proposal_without_microqualification": _PROPOSAL_TERMS,
        "complex_b2b_without_controlled_next_step": _VAGUE_NEXT_STEP_TERMS,
        "interest_without_decision": _INTEREST_TERMS,
    }
    return _sentence_with_terms(transcript, anchors_by_pattern.get(pattern_code, ()))


def _pattern_from_text(text: str, *, default: str) -> str:
    normalized = _norm(text)
    if _count_terms(normalized, _B2B_TERMS) >= 3:
        return "complex_b2b_without_controlled_next_step"
    if _has_any(normalized, _PROPOSAL_TERMS):
        return "proposal_without_microqualification"
    if _has_any(normalized, _INTEREST_TERMS):
        return "interest_without_decision"
    if "последователь" in normalized or "sequence" in normalized:
        return "sequence_gap"
    return default


def _pattern_base_score(pattern_code: str) -> float:
    return {
        "complex_b2b_without_controlled_next_step": 72.0,
        "proposal_without_microqualification": 68.0,
        "interest_without_decision": 58.0,
    }.get(pattern_code, 54.0)


def _problem_title_for_pattern(pattern_code: str) -> str:
    return {
        "proposal_without_microqualification": (
            "КП согласовали без минимальной квалификации"
        ),
        "complex_b2b_without_controlled_next_step": (
            "Сложный B2B-запрос не переведен в управляемый следующий шаг"
        ),
        "interest_without_decision": (
            "Интерес клиента не закреплен решением о следующем контакте"
        ),
        "sequence_gap": "Ошибка последовательности в развитии разговора",
    }.get(pattern_code, "Бизнес-значимая ситуация требует управляемого следующего шага")


def _manager_gap_for_pattern(pattern_code: str) -> str:
    return {
        "proposal_without_microqualification": (
            "Менеджер согласился отправить КП, но перед этим не собрал минимум: "
            "объем, пользователей, роль собеседника, критерии выбора и срок решения."
        ),
        "complex_b2b_without_controlled_next_step": (
            "Менеджер отвечал на вопросы и обещал уточнить детали, но не собрал "
            "требования в короткое резюме и не назначил управляемый следующий шаг."
        ),
        "interest_without_decision": (
            "Менеджер увидел интерес клиента, но не закрепил цель следующего контакта, "
            "участников, срок и ожидаемый результат."
        ),
        "sequence_gap": (
            "Проблема возникла в последовательности: после клиентского сигнала "
            "менеджер не сделал следующий управляемый продажный шаг."
        ),
    }.get(pattern_code, "Менеджер не зафиксировал конкретный следующий шаг.")


def _why_it_matters_for_pattern(pattern_code: str) -> str:
    return {
        "proposal_without_microqualification": (
            "КП без контекста превращается в общий прайс: клиенту сложнее увидеть "
            "ценность, а менеджеру сложнее вернуться к предметному обсуждению."
        ),
        "complex_b2b_without_controlled_next_step": (
            "В сложном B2B-запросе ценность появляется через управление процессом: "
            "роли, критерии, демонстрацию и дату решения. Без этого сделка остается "
            "в режиме разрозненных уточнений."
        ),
        "interest_without_decision": (
            "Интерес быстро остывает, если его не перевести в понятное действие: "
            "созвон, демо, участников и срок возврата к обсуждению."
        ),
        "sequence_gap": (
            "Когда менеджер пропускает следующий шаг после клиентского сигнала, "
            "разговор теряет управляемость и становится труднее продолжать сделку."
        ),
    }.get(pattern_code, "Без конкретного действия следующий контакт становится менее управляемым.")


def _next_action_for_pattern(pattern_code: str) -> str:
    return {
        "proposal_without_microqualification": (
            "Перед отправкой КП задать 2-3 микровопроса, зафиксировать цель КП и "
            "сразу договориться, когда вместе обсудить отправленный вариант."
        ),
        "complex_b2b_without_controlled_next_step": (
            "Сначала резюмировать требования клиента в 3-4 пунктах, затем предложить "
            "демо или созвон с нужными участниками и согласовать конкретное время."
        ),
        "interest_without_decision": (
            "После явного интереса зафиксировать следующий контакт: цель, участники, "
            "срок и что клиент должен получить по итогам."
        ),
        "sequence_gap": (
            "После клиентского сигнала остановиться, подытожить услышанное и "
            "перевести разговор в один конкретный следующий шаг."
        ),
    }.get(pattern_code, "Зафиксировать следующий шаг, владельца и срок.")


def _suggested_phrase_for_pattern(pattern_code: str) -> str:
    return {
        "proposal_without_microqualification": (
            "Да, отправлю КП. Чтобы оно было не общим, уточню три момента: сколько "
            "документов в месяц, сколько сотрудников будет работать и кто сравнивает "
            "предложения? После этого пришлю вариант и предложу коротко пройтись по цифрам."
        ),
        "complex_b2b_without_controlled_next_step": (
            "Правильно понял: у вас несколько ролей, пользователей и требований к "
            "доступу. Я уточню детали, но предлагаю сразу назначить короткую встречу "
            "и показать ваш сценарий в системе. Кто еще должен быть на этой встрече?"
        ),
        "interest_without_decision": (
            "Вижу, что тема вам интересна. Давайте закрепим следующий шаг: я покажу "
            "решение на вашем сценарии, а вы подключите коллегу, который влияет на "
            "решение. Когда удобно обсудить?"
        ),
        "sequence_gap": (
            "Давайте я коротко подытожу, что услышал, и предложу следующий шаг, чтобы "
            "мы не потеряли договоренность."
        ),
    }.get(pattern_code, "Давайте зафиксируем следующий шаг: что делаем, кто участвует и когда вернемся.")


def _stage_for_pattern(pattern_code: str) -> str:
    return {
        "proposal_without_microqualification": "qualification_primary",
        "complex_b2b_without_controlled_next_step": "completion_next_step",
        "interest_without_decision": "completion_next_step",
        "sequence_gap": "completion_next_step",
    }.get(pattern_code, "completion_next_step")


def _stage_label_for_code(stage_code: str | None) -> str | None:
    return {
        "qualification_primary": "Квалификация",
        "needs_discovery": "Выявление потребности",
        "presentation": "Презентация решения",
        "completion_next_step": "Завершение и следующий шаг",
    }.get(str(stage_code or ""), stage_code)


def _proof_type_from_raw(raw: dict[str, Any], pattern_code: str) -> ProofType:
    value = str(raw.get("proof_type") or raw.get("evidence_type") or "").strip().lower()
    if value in SUPPORTED_PROOF_TYPES:
        return value  # type: ignore[return-value]
    if value in {"absence_in_context", "inferred_from_dialogue"}:
        return "sequence_inference"
    if pattern_code == "complex_b2b_without_controlled_next_step":
        return "business_context_inference"
    return "sequence_inference"


def _proof_strength_from_source(raw: dict[str, Any], source_text: str) -> ProofStrength:
    quality = str(raw.get("evidence_quality") or raw.get("confidence") or "").lower()
    if quality in {"strong", "direct", "high"} and _word_count(source_text) >= 20:
        return "strong"
    if _word_count(source_text) >= 24:
        return "strong"
    if _word_count(source_text) >= 12:
        return "medium"
    return "weak"


def _candidate_source_text(
    raw: dict[str, Any],
    *,
    turns: list[dict[str, str]],
    transcript: str,
) -> str:
    direct = _first_text(
        raw.get("evidence_scene"),
        raw.get("dialogue_summary"),
        raw.get("what_happened"),
        raw.get("proof_explanation"),
        raw.get("supporting_quote"),
    )
    if turns:
        return _bounded_text(" ".join(turn["text"] for turn in turns), limit=900)
    if direct:
        quote = _first_text(raw.get("supporting_quote"), raw.get("quote"))
        if quote and transcript:
            return _excerpt_around_terms(transcript, (quote,), limit=900)
        return direct
    return _bounded_text(transcript, limit=900)


def _turns_from_candidate(raw: dict[str, Any]) -> list[dict[str, str]]:
    raw_turns: Any = None
    for key in ("dialogue_fragment", "best_dialogue_fragment"):
        if isinstance(raw.get(key), list):
            raw_turns = raw.get(key)
            break
    if raw_turns is None and isinstance(raw.get("dialogue_excerpt"), dict):
        raw_turns = raw["dialogue_excerpt"].get("turns")
    turns: list[dict[str, str]] = []
    for item in raw_turns or []:
        turn = _as_dict(item)
        text = _bounded_text(_first_text(turn.get("text"), turn.get("quote")) or "", limit=320)
        if not text:
            continue
        speaker = str(turn.get("speaker") or "unknown").strip().lower()
        if speaker not in {"manager", "client", "customer", "context", "evidence", "unknown"}:
            speaker = "unknown"
        if speaker == "customer":
            speaker = "client"
        turns.append({"speaker": speaker, "text": text})
    quote = _first_text(raw.get("supporting_quote"), raw.get("quote"), raw.get("evidence_quote"))
    if not turns and quote:
        turns.append({"speaker": "evidence", "text": _bounded_text(quote, limit=320)})
    return turns[:5]


def _first_script(raw: dict[str, Any]) -> str | None:
    scripts = raw.get("scripts") or raw.get("phrases") or raw.get("suggested_phrases")
    if isinstance(scripts, list):
        for item in scripts:
            text = _first_text(item)
            if text:
                return text
    return _first_text(raw.get("suggested_phrase"), raw.get("script"), raw.get("better_phrase"))


def _excerpt_around_terms(transcript: str, terms: Iterable[str], *, limit: int) -> str:
    chunks = _sentences(transcript)
    if not chunks:
        return _bounded_text(transcript, limit=limit)
    norm_terms = [_norm(term) for term in terms if _norm(term)]
    matched = [
        index
        for index, chunk in enumerate(chunks)
        if any(term in _norm(chunk) for term in norm_terms)
    ]
    if not matched:
        return _bounded_text(" ".join(chunks[:4]), limit=limit)
    center = matched[0]
    selected = chunks[max(0, center - 3) : min(len(chunks), center + 5)]
    return _bounded_text(" ".join(selected), limit=limit)


def _sentence_with_terms(transcript: str, terms: Iterable[str]) -> str | None:
    norm_terms = [_norm(term) for term in terms if _norm(term)]
    for sentence in _sentences(transcript):
        if any(term in _norm(sentence) for term in norm_terms):
            return _bounded_text(sentence, limit=260)
    return None


def _sentences(value: str) -> list[str]:
    return [
        _clean_text(chunk)
        for chunk in re.split(r"(?<=[.!?])\s+|\n+", str(value or ""))
        if _clean_text(chunk)
    ]


def _business_signal_count(value: str) -> int:
    text = _norm(value)
    return _count_terms(text, _B2B_TERMS) + _count_terms(text, _SCALE_TERMS)


def _count_terms(value: str, terms: Iterable[str]) -> int:
    return sum(1 for term in terms if _norm(term) in value)


def _has_any(value: str, terms: Iterable[str]) -> bool:
    text = _norm(value)
    return any(_norm(term) in text for term in terms)


def _meaningful_text(value: str | None, *, min_chars: int) -> bool:
    text = _clean_text(value or "")
    return len(text) >= min_chars and _word_count(text) >= max(5, min_chars // 9)


def _is_generic_gap(value: str) -> bool:
    text = _norm(value)
    generic = (
        "улучшить коммуникацию",
        "быть внимательнее",
        "лучше выявлять",
        "повысить качество",
        "уточнить у клиента текущий процесс и потребности",
        "не было выяснено, как устроен текущий процесс",
    )
    return any(item in text for item in generic) and _word_count(value) < 14


def _is_generic_context(value: str) -> bool:
    text = _norm(value)
    generic = (
        "без понимания потребностей клиента",
        "предложение может быть нерелевантным",
        "клиент еще не сформулировал свои потребности",
        "недостаточно данных",
    )
    return any(item in text for item in generic)


def _is_generic_next_action(value: str) -> bool:
    text = _norm(value)
    generic = (
        "уточнить у клиента текущий процесс и потребности",
        "сначала уточнить у клиента текущий процесс",
        "уточнить потребности клиента",
    )
    return any(item in text for item in generic) and not _has_any(
        text,
        ("демо", "встреч", "созвон", "резюмировать", "зафиксировать", "кто принимает", "критер"),
    )


def _proof_strength_rank(value: str) -> int:
    return {"strong": 0, "medium": 1, "weak": 2}.get(value, 9)


def _source_rank(value: str) -> int:
    if value.startswith("report_evidence.block_candidates"):
        return 0
    if value == "report_evidence.semantic_case":
        return 1
    if value.startswith("transcript."):
        return 2
    return 3


def _word_count(value: str | None) -> int:
    return len(re.findall(r"[a-zа-яё0-9]+", str(value or ""), flags=re.IGNORECASE))


def _first_sentence(value: str | None, *, limit: int) -> str:
    text = _clean_text(value or "")
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    return _bounded_text(parts[0] if parts else text, limit=limit)


def _bounded_text(value: str | None, *, limit: int) -> str:
    text = _clean_text(value or "")
    if len(text) <= limit:
        return text
    cropped = text[:limit].rsplit(" ", 1)[0].strip()
    return cropped or text[:limit].strip()


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: str | None) -> str:
    return _clean_text(value).casefold().replace("ё", "е")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "да"}
    if isinstance(value, int):
        return value == 1
    return bool(value)


def _obj_get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _dict_get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _nested_text(mapping: dict[str, Any], path: tuple[str, ...]) -> str | None:
    current: Any = mapping
    for key in path:
        current = _as_dict(current).get(key)
    return _first_text(current)


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            value = value.get("text") or value.get("summary") or value.get("value")
        text = _clean_text(str(value))
        if text:
            return text
    return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
