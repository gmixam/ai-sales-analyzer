"""Daily Situation Day composer prototype for LLM3 report composition.

The module accepts an already prepared day-level input package.  It does not
reanalyze calls or read transcripts; it selects one grounded manager-gap scene
and can optionally ask LLM3 to polish the final block under the same evidence
constraints.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from app.agents.calls.openai_chat_compat import build_chat_completion_kwargs

SITUATION_DAY_DAILY_COMPOSER_VERSION = "situation_day_daily_composer_v2"
SITUATION_DAY_DAILY_PROMPT_VERSION = "situation_day_daily_composer_v2"
SITUATION_DAY_DAILY_SOURCE = "report_evidence.situation_day_daily_composer.v2"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "situation_day_daily_composer_v2.md"

MANAGER_GAP_TYPES = {"manager_gap", "manager_coaching_moment", "stage_gap"}
FORBIDDEN_MANAGER_ERROR_TYPES = {"customer_signal", "service_issue", "tech_service", "support_issue"}
WEAK_PROOF = {"weak", "low", "insufficient"}
STRONG_OR_MEDIUM_PROOF = {"strong", "medium", "high", "direct", "indirect"}


@dataclass(slots=True, frozen=True)
class DailySituationCandidate:
    candidate_id: str
    call_id: str
    evidence_type: str
    score: float
    source: str
    stage_code: str | None
    proof_type: str | None
    situation_title: str
    moment_summary: str
    what_happened: str
    manager_error: str
    evidence_scene: str
    supporting_quote: str | None
    why_it_matters: str
    next_time_action: str
    call_context_summary: str | None = None
    evidence_quotes: list[str] = field(default_factory=list)
    dialogue_turns: list[dict[str, str]] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    source_fact_ids: list[str] = field(default_factory=list)
    proof_strength: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_payload_item(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "call_id": self.call_id,
            "evidence_type": self.evidence_type,
            "score": self.score,
            "source": self.source,
            "stage_code": self.stage_code,
            "proof_type": self.proof_type,
            "situation_title": self.situation_title,
            "moment_summary": self.moment_summary,
            "what_happened": self.what_happened,
            "manager_error": self.manager_error,
            "evidence_scene": self.evidence_scene,
            "dialogue_turns": list(self.dialogue_turns),
            "supporting_quote": self.supporting_quote,
            "call_context_summary": self.call_context_summary,
            "evidence_quotes": list(self.evidence_quotes),
            "why_it_matters": self.why_it_matters,
            "next_time_action": self.next_time_action,
            "scripts": list(self.scripts),
            "source_fact_ids": list(self.source_fact_ids),
            "proof_strength": self.proof_strength,
        }

    def to_rejected(self, reason: str) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "call_id": self.call_id,
            "evidence_type": self.evidence_type,
            "score": self.score,
            "source": self.source,
            "stage_code": self.stage_code,
            "proof_type": self.proof_type,
            "reason": reason,
        }


def compose_daily_situation_day(
    daily_input: dict[str, Any],
    *,
    llm3_enabled: bool | None = None,
) -> dict[str, Any]:
    """Return one verified or insufficient daily Situation Day candidate."""

    candidates, extraction_diagnostics = _extract_daily_candidates(daily_input)
    daily_focus = _daily_focus_payload(daily_input)
    focus_stage_code = _daily_focus_stage_code(daily_focus)
    eligible: list[DailySituationCandidate] = []
    rejected: list[dict[str, Any]] = []
    for candidate in candidates:
        valid, reason = _candidate_is_eligible(candidate)
        if valid:
            eligible.append(candidate)
        else:
            rejected.append(candidate.to_rejected(reason))

    eligible.sort(key=_rank_key)
    llm3_diagnostics: dict[str, Any] = {
        "llm3_enabled": _llm3_enabled() if llm3_enabled is None else bool(llm3_enabled),
        "llm3_used": False,
        "llm3_prompt_version": SITUATION_DAY_DAILY_PROMPT_VERSION,
    }

    if not eligible:
        return _insufficient(
            reason="no_manager_gap_scene",
            rejected_candidates=rejected,
            diagnostics={
                "composer_version": SITUATION_DAY_DAILY_COMPOSER_VERSION,
                "candidate_count": len(candidates),
                "eligible_count": 0,
                "daily_focus": daily_focus,
                "extraction": extraction_diagnostics,
                "llm3": llm3_diagnostics,
            },
        )

    if focus_stage_code:
        focus_eligible = [
            candidate for candidate in eligible if (candidate.stage_code or "").strip() == focus_stage_code
        ]
        if not focus_eligible:
            return _insufficient(
                reason="no_focus_stage_manager_gap_scene",
                rejected_candidates=rejected
                + [
                    item.to_rejected("non_focus_stage_manager_gap")
                    for item in eligible
                    if (item.stage_code or "").strip() != focus_stage_code
                ],
                diagnostics={
                    "composer_version": SITUATION_DAY_DAILY_COMPOSER_VERSION,
                    "candidate_count": len(candidates),
                    "eligible_count": len(eligible),
                    "focus_eligible_count": 0,
                    "daily_focus": daily_focus,
                    "extraction": extraction_diagnostics,
                    "llm3": llm3_diagnostics,
                },
            )
        rejected.extend(
            item.to_rejected("non_focus_stage_manager_gap")
            for item in eligible
            if (item.stage_code or "").strip() != focus_stage_code
        )
        eligible = focus_eligible

    selected = eligible[0]
    if llm3_diagnostics["llm3_enabled"]:
        llm3_result, llm3_diagnostics = _try_llm3_daily_situation(
            build_daily_situation_llm3_payload(
                {
                    "daily_focus": daily_focus,
                    "candidates": [item.to_payload_item() for item in eligible],
                }
            ),
            eligible,
            llm3_diagnostics,
            daily_focus=daily_focus,
        )
        if llm3_result is not None:
            llm3_result["diagnostics"] = {
                **llm3_result.get("diagnostics", {}),
                "composer_version": SITUATION_DAY_DAILY_COMPOSER_VERSION,
                "candidate_count": len(candidates),
                "eligible_count": len(eligible),
                "focus_eligible_count": len(eligible) if focus_stage_code else None,
                "daily_focus": daily_focus,
                "extraction": extraction_diagnostics,
                "llm3": llm3_diagnostics,
            }
            llm3_result["rejected_candidates"] = rejected + [
                item.to_rejected("lower_ranked_manager_gap")
                for item in eligible
                if item.call_id != llm3_result.get("selected_call_id")
            ]
            return llm3_result

    return _result_from_candidate(
        selected,
        rejected_candidates=rejected + [
            item.to_rejected("lower_ranked_manager_gap") for item in eligible[1:]
        ],
        selection_reason="best_manager_gap_scene_by_score",
        diagnostics={
            "composer_version": SITUATION_DAY_DAILY_COMPOSER_VERSION,
            "candidate_count": len(candidates),
            "eligible_count": len(eligible),
            "focus_eligible_count": len(eligible) if focus_stage_code else None,
            "daily_focus": daily_focus,
            "extraction": extraction_diagnostics,
            "llm3": llm3_diagnostics,
        },
    )


def build_daily_situation_llm3_payload(daily_input: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded LLM3 payload without transcripts or full call analysis."""

    daily_focus = _daily_focus_payload(daily_input)
    provided_candidates = daily_input.get("candidates")
    if isinstance(provided_candidates, list):
        candidates = [
            _candidate_from_item(_as_dict(item), fallback_index=index)
            for index, item in enumerate(provided_candidates)
        ]
        candidates = [candidate for candidate in candidates if candidate is not None]
    else:
        candidates, _diagnostics = _extract_daily_candidates(daily_input)

    eligible = [candidate for candidate in candidates if _candidate_is_eligible(candidate)[0]]
    eligible.sort(key=_rank_key)
    return {
        "contract_version": SITUATION_DAY_DAILY_PROMPT_VERSION,
        "daily_focus": daily_focus,
        "instruction": (
            "Choose one manager_gap candidate for Ситуация дня inside daily_focus.stage_code "
            "or return insufficient. "
            "Explain the selected episode as a coherent manager-facing mini-brief. "
            "Use only provided candidate fields; never use or request raw call text."
        ),
        "forbidden": [
            "Do not recalculate scores.",
            "Do not perform full call analysis.",
            "Do not change the daily focus stage or replace its problem with a generic next-step issue.",
            "Do not invent facts, quotes, scenes, scripts, call ids, names, volumes, dates, or products.",
            "Do not select customer_signal or service_issue as manager_error.",
        ],
        "candidates": [candidate.to_payload_item() for candidate in eligible[:8]],
        "required_output_keys": [
            "status",
            "selected_call_id",
            "situation_title",
            "moment_summary",
            "what_happened",
            "call_context_summary",
            "manager_error",
            "stage_code",
            "proof_type",
            "evidence_scene",
            "dialogue_turns",
            "evidence_quotes",
            "supporting_quote",
            "why_it_matters",
            "next_time_action",
            "scripts",
            "rejected_candidates",
            "selection_reason",
            "source_fact_ids",
            "diagnostics",
        ],
    }


def _extract_daily_candidates(
    daily_input: dict[str, Any],
) -> tuple[list[DailySituationCandidate], dict[str, Any]]:
    raw_items: list[Any] = []
    for path in (
        ("situation_day",),
        ("candidates",),
        ("situation_day_candidates",),
        ("evidence_items",),
        ("items",),
        ("facts",),
        ("routing", "situation_day"),
        ("routed_blocks", "situation_day"),
        ("blocks", "situation_day"),
        ("report_blocks", "situation_day"),
    ):
        value = _deep_get(daily_input, path)
        if isinstance(value, list):
            raw_items.extend(value)
        elif isinstance(value, dict):
            raw_items.append(value)
    raw_items.extend(_candidate_items_from_daily_calls(daily_input.get("calls")))

    seen: set[str] = set()
    candidates: list[DailySituationCandidate] = []
    for index, raw_item in enumerate(raw_items):
        item = _as_dict(raw_item)
        identity = json.dumps(
            {
                "id": _first_text(item.get("candidate_id"), item.get("item_id"), item.get("id")),
                "call_id": _first_text(item.get("call_id"), item.get("interaction_id")),
                "source": item.get("source"),
                "score": item.get("score"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if identity in seen:
            continue
        seen.add(identity)
        candidate = _candidate_from_item(item, fallback_index=index)
        if candidate is not None:
            candidates.append(candidate)
    return candidates, {"raw_items_count": len(raw_items), "candidates_count": len(candidates)}


def _daily_focus_payload(daily_input: dict[str, Any]) -> dict[str, Any] | None:
    focus = _as_dict(daily_input.get("daily_focus"))
    stage_code = _first_text(focus.get("stage_code"))
    if not stage_code:
        return None
    return {
        "stage_code": stage_code,
        "stage_id": _first_text(focus.get("stage_id")),
        "stage_name": _first_text(focus.get("stage_name")),
        "problem_statement": _first_text(focus.get("problem_statement")),
        "problem_signal": _first_text(focus.get("problem_signal")),
        "challenge_metric_source": _first_text(focus.get("challenge_metric_source")),
        "confidence": _first_text(focus.get("confidence")),
    }


def _daily_focus_stage_code(daily_focus: dict[str, Any] | None) -> str:
    return str((daily_focus or {}).get("stage_code") or "").strip()


def _candidate_items_from_daily_calls(value: Any) -> list[dict[str, Any]]:
    """Flatten the day-level `calls` package into manager-gap candidates."""
    result: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return result
    for call_index, raw_call in enumerate(value):
        call = _as_dict(raw_call)
        call_id = _first_text(call.get("call_id"), call.get("interaction_id"))
        if not call_id:
            continue
        manager_gaps = [
            text
            for text in (_first_text(item) for item in call.get("manager_gaps") or [])
            if text
        ]
        scenes = [
            _as_dict(scene)
            for scene in call.get("evidence_scenes") or []
            if isinstance(scene, dict)
            and _norm(scene.get("evidence_type")) in MANAGER_GAP_TYPES
        ]
        for scene_index, scene in enumerate(scenes):
            rendered_scene = _render_dialogue(scene.get("turns") or []) or _first_text(
                scene.get("summary"),
                scene.get("quote"),
            )
            quote = _first_text(scene.get("quote"), scene.get("supporting_quote"))
            if not rendered_scene and not quote:
                continue
            manager_gap = (
                manager_gaps[min(scene_index, len(manager_gaps) - 1)]
                if manager_gaps
                else _first_text(scene.get("summary"))
            )
            customer_context = _first_text(
                *(call.get("customer_signals") or []),
                call.get("call_summary"),
                call.get("llm2_summary"),
                scene.get("summary"),
            )
            item = {
                "candidate_id": _first_text(
                    scene.get("scene_id"),
                    f"{call_id}:daily_call:{call_index}:{scene_index}",
                ),
                "call_id": call_id,
                "evidence_type": "manager_gap",
                "score": _daily_call_candidate_score(call=call, scene=scene),
                "source": _first_text(scene.get("source"), "situation_day_daily_input.calls"),
                "stage_code": _first_text(scene.get("stage_code"), call.get("stage_code")),
                "proof_type": _first_text(scene.get("proof_type"), "sequence_inference"),
                "proof_strength": _first_text(scene.get("proof_strength"), "medium"),
                "situation_title": _first_text(scene.get("summary"), manager_gap, call.get("call_summary")),
                "moment_summary": _first_text(
                    manager_gap,
                    scene.get("summary"),
                    call.get("llm2_summary"),
                    call.get("call_summary"),
                ),
                "what_happened": _daily_call_what_happened(
                    customer_context=customer_context,
                    manager_gap=manager_gap,
                    quote=quote,
                ),
                "manager_error": manager_gap,
                "customer_context": customer_context,
                "evidence_scene": rendered_scene,
                "dialogue_turns": _compact_dialogue_turns(scene.get("turns") or []),
                "supporting_quote": quote,
                "why_it_matters": _first_text(
                    customer_context,
                    "Иначе следующий шаг остается на стороне клиента и сделка теряет управляемость.",
                ),
                "next_time_action": _first_text(scene.get("next_time_action")),
                "source_fact_ids": list(call.get("source_fact_ids") or []),
            }
            result.append(item)
    return result


def _daily_call_candidate_score(*, call: dict[str, Any], scene: dict[str, Any]) -> float:
    explicit_score = _score(scene)
    if explicit_score:
        return explicit_score
    call_score = _score(call)
    if call_score:
        return max(0.0, 100.0 - call_score)
    strength = _norm(scene.get("proof_strength"))
    return {"strong": 80.0, "direct": 80.0, "medium": 60.0, "indirect": 60.0}.get(strength, 40.0)


def _daily_call_what_happened(
    *,
    customer_context: str,
    manager_gap: str,
    quote: str,
) -> str:
    context = _bounded(customer_context, 360)
    gap = _bounded(manager_gap, 320)
    evidence = _bounded(quote, 220)
    parts: list[str] = []
    if context:
        parts.append(f"Контекст звонка: {context}")
    if evidence:
        parts.append(f"Подтверждающий фрагмент: «{evidence}»")
    if gap:
        parts.append(f"Проблема для разбора: {gap}")
    return ". ".join(part.strip().rstrip(".") for part in parts if part).strip() + "."


def _candidate_from_item(item: dict[str, Any], *, fallback_index: int) -> DailySituationCandidate | None:
    call_id = _first_text(item.get("call_id"), item.get("interaction_id"), item.get("selected_call_id"))
    if not call_id:
        return None

    evidence_type = _norm(_first_text(item.get("evidence_type"), item.get("type"), item.get("case_type")))
    if not evidence_type:
        evidence_type = _infer_evidence_type(item)

    supporting_quote = _first_text(
        item.get("supporting_quote"),
        item.get("quote"),
        item.get("transcript_excerpt"),
    )
    evidence_scene = _scene_text(item)
    dialogue_turns = _compact_dialogue_turns(
        item.get("dialogue_turns")
        or item.get("dialogue_fragment")
        or item.get("best_dialogue_fragment")
        or item.get("turns")
        or []
    )
    evidence_quotes = _evidence_quotes(item, supporting_quote=supporting_quote, dialogue_turns=dialogue_turns)
    what_happened = _first_text(item.get("what_happened"), item.get("moment_summary"), evidence_scene)
    manager_error = _first_text(
        item.get("manager_error"),
        item.get("manager_gap"),
        item.get("what_was_missing"),
        item.get("missing_action"),
    )
    scripts = _scripts(item)
    next_time_action = _first_text(
        item.get("next_time_action"),
        item.get("better_next_action"),
        item.get("recommended_next_action"),
        item.get("manager_action"),
    )
    if not next_time_action and scripts:
        next_time_action = scripts[0]

    return DailySituationCandidate(
        candidate_id=_first_text(
            item.get("candidate_id"),
            item.get("item_id"),
            item.get("evidence_id"),
            item.get("id"),
            f"daily_situation:{fallback_index}",
        )
        or f"daily_situation:{fallback_index}",
        call_id=call_id,
        evidence_type=evidence_type,
        score=_score(item),
        source=_first_text(item.get("source"), item.get("path")) or "daily_input",
        stage_code=_first_text(item.get("stage_code")) or None,
        proof_type=_norm(_first_text(item.get("proof_type"))) or None,
        situation_title=_first_text(
            item.get("situation_title"),
            item.get("problem_title"),
            item.get("title"),
            item.get("main_thesis"),
            "Ситуация дня",
        )
        or "Ситуация дня",
        moment_summary=_first_text(item.get("moment_summary"), item.get("summary"), what_happened)
        or what_happened,
        what_happened=what_happened,
        manager_error=manager_error,
        evidence_scene=evidence_scene,
        dialogue_turns=dialogue_turns,
        supporting_quote=supporting_quote,
        call_context_summary=_first_text(
            item.get("call_context_summary"),
            item.get("customer_context"),
            item.get("moment_summary"),
            item.get("summary"),
        )
        or None,
        evidence_quotes=evidence_quotes,
        why_it_matters=_first_text(item.get("why_it_matters"), item.get("business_impact"))
        or "Иначе следующий шаг остается на стороне клиента и сделка теряет управляемость.",
        next_time_action=next_time_action
        or "Зафиксировать конкретный следующий шаг: цель, срок и ответственного.",
        scripts=_ensure_scripts(scripts, next_time_action),
        source_fact_ids=_source_fact_ids(item),
        proof_strength=_norm(
            _first_text(item.get("proof_strength"), item.get("evidence_strength"), item.get("confidence"))
        )
        or None,
        diagnostics={"raw_evidence_type": evidence_type},
    )


def _candidate_is_eligible(candidate: DailySituationCandidate) -> tuple[bool, str]:
    if candidate.evidence_type in FORBIDDEN_MANAGER_ERROR_TYPES:
        return False, f"{candidate.evidence_type}_forbidden"
    if candidate.evidence_type not in MANAGER_GAP_TYPES:
        return False, "not_manager_gap"
    if candidate.proof_strength and candidate.proof_strength in WEAK_PROOF:
        return False, "weak_proof"
    if candidate.proof_strength and candidate.proof_strength not in STRONG_OR_MEDIUM_PROOF:
        return False, "weak_proof"
    if not candidate.evidence_scene:
        return False, "no_evidence_scene"
    if not candidate.manager_error:
        return False, "no_manager_error"
    return True, "eligible_manager_gap"


def _result_from_candidate(
    candidate: DailySituationCandidate,
    *,
    rejected_candidates: list[dict[str, Any]],
    selection_reason: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "verified",
        "selected_call_id": candidate.call_id,
        "situation_title": candidate.situation_title,
        "moment_summary": candidate.moment_summary,
        "what_happened": candidate.what_happened,
        "call_context_summary": candidate.call_context_summary,
        "manager_error": candidate.manager_error,
        "stage_code": candidate.stage_code,
        "proof_type": candidate.proof_type,
        "evidence_scene": candidate.evidence_scene,
        "dialogue_turns": list(candidate.dialogue_turns),
        "evidence_quotes": list(candidate.evidence_quotes),
        "supporting_quote": candidate.supporting_quote,
        "why_it_matters": candidate.why_it_matters,
        "next_time_action": candidate.next_time_action,
        "scripts": _ensure_scripts(candidate.scripts, candidate.next_time_action),
        "rejected_candidates": rejected_candidates,
        "selection_reason": selection_reason,
        "source_fact_ids": list(candidate.source_fact_ids),
        "diagnostics": diagnostics,
    }


def _insufficient(
    *,
    reason: str,
    rejected_candidates: list[dict[str, Any]],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "insufficient",
        "selected_call_id": None,
        "situation_title": None,
        "moment_summary": None,
        "what_happened": None,
        "manager_error": None,
        "evidence_scene": None,
        "call_context_summary": None,
        "evidence_quotes": [],
        "supporting_quote": None,
        "why_it_matters": None,
        "next_time_action": None,
        "scripts": [],
        "rejected_candidates": rejected_candidates,
        "selection_reason": reason,
        "source_fact_ids": [],
        "diagnostics": diagnostics,
    }


def _try_llm3_daily_situation(
    payload: dict[str, Any],
    candidates: list[DailySituationCandidate],
    diagnostics: dict[str, Any],
    *,
    daily_focus: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        raw = _request_llm3_daily_situation(payload)
        diagnostics = dict(diagnostics)
        diagnostics["llm3_raw_status"] = raw.get("status")
        if isinstance(raw.get("_routing"), dict):
            diagnostics["llm3_routing"] = raw.get("_routing")
        normalized, reason = _normalize_llm3_daily_situation(raw, candidates, daily_focus=daily_focus)
        if normalized is None:
            diagnostics["llm3_rejection_reason"] = reason
            diagnostics["llm3_response"] = _json_safe(raw)
            return None, diagnostics
        diagnostics["llm3_used"] = True
        return normalized, diagnostics
    except Exception as exc:
        diagnostics = dict(diagnostics)
        diagnostics["llm3_error"] = str(exc)
        return None, diagnostics


def _request_llm3_daily_situation(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = _read_llm3_prompt()
    simulated = _request_llm3_simulation(
        payload=payload,
        prompt=prompt,
        request_kind="situation_day_daily_composer",
        subject_key="daily_situation_day",
        input_artifact="llm3_situation_day_input.json",
        output_artifact="llm3_situation_day_output.json",
        notes="LLM-3 Daily Situation Day composer simulated.",
    )
    if simulated is not None:
        return simulated

    from dataclasses import replace as dataclass_replace

    from openai import OpenAI

    from app.core_shared.ai_routing import AIProviderRouter
    from app.core_shared.config.settings import settings

    route_plan = AIProviderRouter().build_route_plan(
        layer="llm3",
        subject_key="daily_situation_day",
    )
    candidate = route_plan.current_candidate()
    compatibility_candidate = candidate
    if (candidate.endpoint or "").rstrip("/") == "/chat/completions":
        compatibility_candidate = dataclass_replace(candidate, endpoint=None)
    AIProviderRouter.ensure_execution_compatibility(
        compatibility_candidate,
        executor_label="LLM-3 Daily Situation Day composer",
        required_execution_mode="openai_compatible",
    )
    client = OpenAI(api_key=candidate.resolved_api_key(), base_url=candidate.api_base)
    response = None
    last_error: Exception | None = None
    for _ in range(max(1, candidate.max_retries_for_this_provider + 1)):
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
    parsed = json.loads(_extract_openai_message_content(response))
    result = _as_dict(parsed)
    result["_routing"] = route_plan.to_metadata(
        request_kind="situation_day_daily_composer",
        notes="LLM-3 Daily Situation Day composer completed.",
    )
    return result


def _request_llm3_simulation(
    *,
    payload: dict[str, Any],
    prompt: str,
    request_kind: str,
    subject_key: str,
    input_artifact: str,
    output_artifact: str,
    notes: str,
) -> dict[str, Any] | None:
    try:
        from app.agents.calls import llm_simulation
    except Exception:
        return None

    enabled = _llm_simulation_enabled(llm_simulation)
    if enabled is False:
        return None
    executor = _llm_simulation_executor(llm_simulation)
    if executor is None:
        if enabled is True:
            raise RuntimeError("LLM simulation is enabled but no LLM-3 simulation executor is available")
        return None

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    context = {
        "layer": "llm3",
        "node": request_kind,
        "request_kind": request_kind,
        "subject_key": subject_key,
        "prompt": prompt,
        "system_prompt": prompt,
        "payload": payload,
        "input_payload": payload,
        "messages": messages,
        "input_artifact": input_artifact,
        "input_artifact_name": input_artifact,
        "output_artifact": output_artifact,
        "output_artifact_name": output_artifact,
    }
    _write_llm_simulation_artifact(llm_simulation, input_artifact, payload, context)
    raw = _call_llm_simulation_callable(executor, context)
    if raw is None:
        if enabled is True:
            raise RuntimeError("LLM simulation is enabled but executor returned no LLM-3 result")
        return None
    result = _as_dict(raw)
    result.setdefault(
        "_routing",
        {
            "layer": "llm3",
            "provider": "llm_simulation",
            "simulation": True,
            "request_kind": request_kind,
            "subject_key": subject_key,
            "notes": notes,
        },
    )
    _write_llm_simulation_artifact(llm_simulation, output_artifact, result, context)
    return result


def _llm_simulation_enabled(llm_simulation: Any) -> bool | None:
    for name in (
        "is_llm_simulation_enabled",
        "llm_simulation_enabled",
        "simulation_enabled",
        "is_enabled",
        "enabled",
    ):
        value = getattr(llm_simulation, name, None)
        if callable(value):
            try:
                return bool(value(layer="llm3"))
            except TypeError:
                return bool(value())
        if value is not None:
            return bool(value)
    return None


def _llm_simulation_executor(llm_simulation: Any) -> Any | None:
    for name in (
        "request_llm3_composer",
        "request_llm3",
        "request_llm_simulation",
        "run_llm_simulation",
        "simulate_llm_call",
        "simulate",
        "execute",
    ):
        executor = getattr(llm_simulation, name, None)
        if callable(executor):
            return executor
    return None


def _write_llm_simulation_artifact(
    llm_simulation: Any,
    artifact_name: str,
    payload: Any,
    context: dict[str, Any],
) -> None:
    for name in (
        "write_llm_artifact",
        "write_simulation_artifact",
        "save_llm_artifact",
        "save_simulation_artifact",
        "record_llm_artifact",
        "record_artifact",
    ):
        writer = getattr(llm_simulation, name, None)
        if callable(writer):
            _call_llm_simulation_callable(
                writer,
                {
                    **context,
                    "artifact_name": artifact_name,
                    "name": artifact_name,
                    "filename": artifact_name,
                    "data": payload,
                    "value": payload,
                    "payload": payload,
                },
            )
            return


def _call_llm_simulation_callable(func: Any, kwargs: dict[str, Any]) -> Any:
    import inspect

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(**kwargs)
    parameters = signature.parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return func(**kwargs)
    accepted = {
        name: kwargs[name]
        for name in parameters
        if name in kwargs
    }
    if accepted or not parameters:
        return func(**accepted)
    if len(parameters) == 1:
        return func(kwargs["payload"])
    return func(**accepted)


def _normalize_llm3_daily_situation(
    raw: dict[str, Any],
    candidates: list[DailySituationCandidate],
    *,
    daily_focus: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    if _norm(raw.get("status")) != "verified":
        return None, "status_not_verified"
    selected_call_id = _first_text(raw.get("selected_call_id"))
    selected = next((candidate for candidate in candidates if candidate.call_id == selected_call_id), None)
    if selected is None:
        return None, "selected_call_id_not_in_payload"
    focus_stage_code = _daily_focus_stage_code(daily_focus)
    if focus_stage_code and (selected.stage_code or "").strip() != focus_stage_code:
        return None, "selected_candidate_not_in_daily_focus_stage"
    if _llm3_claim_replaces_focus_with_next_step(raw, selected=selected, daily_focus=daily_focus):
        return None, "llm3_output_replaced_focus_with_generic_next_step"
    raw_stage_code = _first_text(raw.get("stage_code"))
    if raw_stage_code and selected.stage_code and raw_stage_code != selected.stage_code:
        return None, "stage_code_changed"
    raw_proof_type = _norm(_first_text(raw.get("proof_type")))
    if raw_proof_type and selected.proof_type and raw_proof_type != selected.proof_type:
        return None, "proof_type_changed"
    raw_proof_strength = _norm(_first_text(raw.get("proof_strength"), raw.get("confidence")))
    if raw_proof_strength and selected.proof_strength and raw_proof_strength != selected.proof_strength:
        return None, "proof_strength_changed"

    scene = _first_text(raw.get("evidence_scene"))
    if not _is_grounded(scene, selected.evidence_scene, selected.supporting_quote):
        scene = selected.evidence_scene
    quote = _first_text(raw.get("supporting_quote"))
    if quote and not _is_grounded(quote, selected.evidence_scene, selected.supporting_quote):
        quote = selected.supporting_quote
    evidence_quotes = _merged_evidence_quotes(
        _grounded_evidence_quotes(raw.get("evidence_quotes"), selected),
        selected.evidence_quotes,
    )
    raw_dialogue_turns = _grounded_dialogue_turns(raw.get("dialogue_turns"), selected)

    rewritten = replace(
        selected,
        situation_title=_bounded(_first_text(raw.get("situation_title"), selected.situation_title), 220),
        moment_summary=_bounded(_first_text(raw.get("moment_summary"), selected.moment_summary), 900),
        what_happened=_bounded(_first_text(raw.get("what_happened"), selected.what_happened), 1800),
        call_context_summary=_bounded(
            _first_text(raw.get("call_context_summary"), selected.call_context_summary, selected.moment_summary),
            1100,
        )
        or None,
        manager_error=selected.manager_error,
        evidence_scene=_bounded(scene or selected.evidence_scene, 2600),
        dialogue_turns=raw_dialogue_turns or selected.dialogue_turns,
        evidence_quotes=evidence_quotes or selected.evidence_quotes,
        supporting_quote=_bounded(quote or selected.supporting_quote or "", 700) or None,
        why_it_matters=_bounded(_first_text(raw.get("why_it_matters"), selected.why_it_matters), 900),
        next_time_action=selected.next_time_action,
        scripts=_ensure_scripts(selected.scripts, selected.next_time_action),
        source_fact_ids=selected.source_fact_ids,
    )
    valid, reason = _candidate_is_eligible(rewritten)
    if not valid:
        return None, reason
    if len(rewritten.scripts) < 2:
        return None, "scripts_less_than_2"
    return (
        _result_from_candidate(
            rewritten,
            rejected_candidates=[],
            selection_reason=_first_text(raw.get("selection_reason"), "llm3_daily_situation_selection")
            or "llm3_daily_situation_selection",
            diagnostics={"llm3_composed": True},
        ),
        "",
    )


def _llm3_claim_replaces_focus_with_next_step(
    raw: dict[str, Any],
    *,
    selected: DailySituationCandidate,
    daily_focus: dict[str, Any] | None,
) -> bool:
    focus_stage_code = _daily_focus_stage_code(daily_focus)
    if not focus_stage_code or focus_stage_code == "completion_next_step":
        return False
    if (selected.stage_code or "").strip() == "completion_next_step":
        return False
    candidate_claim = " ".join(
        text
        for text in (
            selected.situation_title,
            selected.manager_error,
            selected.next_time_action,
        )
        if text
    )
    if _looks_like_next_step_claim(candidate_claim):
        return False
    raw_claim = " ".join(
        text
        for text in (
            _first_text(raw.get("situation_title")),
            _first_text(raw.get("manager_error")),
            _first_text(raw.get("next_time_action")),
            " ".join(str(item) for item in raw.get("scripts") or []),
        )
        if text
    )
    return _looks_like_next_step_claim(raw_claim)


def _looks_like_next_step_claim(value: str) -> bool:
    text = _norm(value)
    if not text:
        return False
    has_next_step = "следующ" in text and any(token in text for token in ("шаг", "контакт", "касани"))
    has_owner_deadline = "владел" in text and "срок" in text
    has_fixing = any(token in text for token in ("закреп", "зафикс", "договор")) and any(
        token in text for token in ("срок", "время", "дат", "контакт", "шаг")
    )
    return has_next_step or has_owner_deadline or has_fixing


def _scene_text(item: dict[str, Any]) -> str:
    text = _first_text(
        item.get("evidence_scene"),
        item.get("scene"),
        item.get("dialogue_scene"),
        item.get("what_happened"),
        item.get("summary"),
        item.get("quote_context"),
        item.get("supporting_quote"),
        item.get("quote"),
    )
    if text:
        return text
    for key in ("dialogue_fragment", "best_dialogue_fragment", "turns", "evidence_refs"):
        value = item.get(key)
        if isinstance(value, list):
            rendered = _render_dialogue(value)
            if rendered:
                return rendered
    return ""


def _render_dialogue(value: list[Any]) -> str:
    parts: list[str] = []
    for raw in value[:10]:
        item = _as_dict(raw)
        text = _first_text(item.get("text"), item.get("quote"), raw)
        if not text:
            continue
        speaker = _first_text(item.get("speaker"), item.get("role"))
        if _norm(speaker) == "client":
            speaker = "Клиент"
        elif _norm(speaker) == "manager":
            speaker = "Менеджер"
        parts.append(f"{speaker}: {text}" if speaker else text)
    return " / ".join(parts)


def _compact_dialogue_turns(value: list[Any]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for raw in value[:10]:
        item = _as_dict(raw)
        text = _bounded(_first_text(item.get("text"), item.get("quote"), raw), 700)
        if not text:
            continue
        speaker = _norm(_first_text(item.get("speaker"), item.get("role"), "unknown"))
        if speaker in {"customer", "buyer", "клиент", "заказчик"}:
            speaker = "client"
        elif speaker in {"agent", "seller", "sales", "менеджер", "оператор"}:
            speaker = "manager"
        elif speaker not in {"client", "manager", "unknown", "context", "evidence"}:
            speaker = "unknown"
        turns.append({"speaker": speaker, "text": text})
    return turns


def _evidence_quotes(
    item: dict[str, Any],
    *,
    supporting_quote: str | None,
    dialogue_turns: list[dict[str, str]],
) -> list[str]:
    quotes: list[str] = []
    value = item.get("evidence_quotes")
    if isinstance(value, list):
        for raw in value:
            text = _bounded(_first_text(raw), 700)
            if text and text not in quotes:
                quotes.append(text)
    if supporting_quote:
        quote = _bounded(supporting_quote, 700)
        if quote and quote not in quotes:
            quotes.append(quote)
    for turn in dialogue_turns:
        text = _bounded(turn.get("text"), 700)
        if text and text not in quotes and len(quotes) < 6:
            quotes.append(text)
    return quotes[:8]


def _grounded_evidence_quotes(value: Any, selected: DailySituationCandidate) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for raw in value:
        quote = _bounded(_first_text(raw), 700)
        if quote and _is_grounded(quote, selected.evidence_scene, selected.supporting_quote):
            result.append(quote)
    return result[:8]


def _grounded_dialogue_turns(value: Any, selected: DailySituationCandidate) -> list[dict[str, str]]:
    turns = _compact_dialogue_turns(value if isinstance(value, list) else [])
    result: list[dict[str, str]] = []
    for turn in turns:
        text = turn.get("text") or ""
        if _is_grounded(text, selected.evidence_scene, selected.supporting_quote):
            result.append(turn)
    return result[:10]


def _merged_evidence_quotes(*groups: list[str]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for quote in group:
            text = _bounded(quote, 700)
            if text and text not in result:
                result.append(text)
            if len(result) >= 8:
                return result
    return result


def _scripts(item: dict[str, Any]) -> list[str]:
    value = item.get("scripts")
    if isinstance(value, list):
        return [_bounded(text, 360) for text in (_first_text(part) for part in value) if text]
    script = _first_text(item.get("script"), item.get("suggested_phrase"), item.get("recommended_phrase"))
    return [script] if script else []


def _ensure_scripts(scripts: list[str], next_time_action: str | None) -> list[str]:
    result = [_bounded(script, 360) for script in scripts if _first_text(script)]
    defaults = [
        next_time_action or "Давайте зафиксируем следующий шаг: когда возвращаемся к обсуждению и кто участвует?",
        "Правильно понимаю задачу так: есть конкретный сценарий, критерии и срок. Предлагаю назначить короткий следующий шаг и пройти по ним.",
    ]
    for script in defaults:
        clean = _bounded(script, 360)
        if clean and clean not in result:
            result.append(clean)
        if len(result) >= 2:
            break
    return result[:5]


def _source_fact_ids(item: dict[str, Any]) -> list[str]:
    value = item.get("source_fact_ids")
    if isinstance(value, list):
        return [_first_text(part) for part in value if _first_text(part)]
    refs = item.get("evidence_refs")
    if isinstance(refs, list):
        result: list[str] = []
        for ref in refs:
            ref_dict = _as_dict(ref)
            fact_id = _first_text(ref_dict.get("fact_id"), ref_dict.get("id"), ref_dict.get("item_id"))
            if fact_id:
                result.append(fact_id)
        return result
    fact_id = _first_text(item.get("source_fact_id"), item.get("fact_id"), item.get("item_id"))
    return [fact_id] if fact_id else []


def _infer_evidence_type(item: dict[str, Any]) -> str:
    role = _norm(_first_text(item.get("role"), item.get("block_role")))
    case_type = _norm(_first_text(item.get("case_type")))
    source = _norm(_first_text(item.get("source"), item.get("path")))
    reason = _norm(_first_text(item.get("reason_code"), item.get("reason")))
    if role == "customer_signal" or case_type == "customer_signal" or "customer_signal" in reason:
        return "customer_signal"
    if case_type == "service_issue" or "service" in source or "service" in reason:
        return "service_issue"
    if role in {"coaching_problem", "manager_gap"} or "situation_day" in source:
        return "manager_gap"
    if _first_text(item.get("manager_error"), item.get("manager_gap"), item.get("what_was_missing")):
        return "manager_gap"
    return ""


def _rank_key(candidate: DailySituationCandidate) -> tuple[int, float, str]:
    strength_rank = {"strong": 0, "high": 0, "direct": 0, "medium": 1, "indirect": 1}
    return (strength_rank.get(candidate.proof_strength or "", 1), -candidate.score, candidate.call_id)


def _llm3_enabled() -> bool:
    try:
        from app.core_shared.config.settings import settings
    except Exception:
        return False
    return bool(settings.llm3_enabled)


def _read_llm3_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return "Return one JSON object. Use only provided candidates and never invent facts."


def _extract_openai_message_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    return content or ""


def _deep_get(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        return dict(attrs)
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
        elif isinstance(value, (int, float)):
            text = str(value)
        elif isinstance(value, list):
            text = _render_dialogue(value).strip()
        else:
            text = str(value).strip()
        if text:
            return text
    return ""


def _norm(value: Any) -> str:
    return _first_text(value).lower().strip()


def _score(item: dict[str, Any]) -> float:
    value = item.get("score", item.get("priority_score", item.get("rank_score", 0)))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _bounded(value: Any, limit: int) -> str:
    text = _first_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _is_grounded(value: str | None, scene: str, quote: str | None) -> bool:
    text = _first_text(value)
    if not text:
        return True
    haystacks = [_norm(scene), _norm(quote)]
    needle = _norm(text)
    return any(needle in haystack or haystack in needle for haystack in haystacks if haystack)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)
