"""Isolated Voice Of Customer composer for manager daily reports.

The composer is intentionally independent from ``reporting.py``.  It reads
ReportArtifact-like objects and legacy voice payloads through getattr/dict
helpers, builds grounded customer-signal candidates, optionally asks LLM3 to
write the final block, and falls back to a deterministic writer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app.agents.calls.openai_chat_compat import build_chat_completion_kwargs
from app.agents.calls.openai_usage import extract_openai_usage_metadata

VOICE_OF_CUSTOMER_COMPOSER_VERSION = "voice_of_customer_composer_v2"
VOICE_OF_CUSTOMER_PROMPT_VERSION = "voice_of_customer_composer_v2"
VOICE_OF_CUSTOMER_SOURCE = "report_evidence.voice_of_customer_composer.v2"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "voice_of_customer_composer_v2.md"

_VAGUE_CALLBACK_QUOTES = (
    "ладно хорошо я перезвоню",
    "хорошо я перезвоню",
    "я перезвоню",
    "ладно хорошо",
)

_CLIENT_SIGNAL_TERMS = (
    "интерес",
    "расскаж",
    "посовет",
    "перезвон",
    "скиньте",
    "отправ",
    "whatsapp",
    "ватсап",
    "коммерческое",
    "кп",
    "тариф",
    "цена",
    "договор",
    "документ",
    "подпис",
    "эцп",
    "эдо",
    "доступ",
    "кабинет",
    "пользовател",
    "сотрудник",
    "роль",
    "юрлиц",
    "юрид",
    "интеграц",
    "достаточно",
    "текущ",
    "незнаком",
    "безопас",
)

_CONTRACT_ACTION_TERMS = ("договор", "договора", "документ", "подпис", "эцп", "эдо")
_PROPOSAL_ACTION_TERMS = ("кп", "коммерческое", "предложение", "тариф", "цена", "прайс")
_DEMO_ACTION_TERMS = ("демо", "показ", "встреч", "созвон", "кабинет", "доступ", "роль")
_MATERIAL_ACTION_TERMS = ("whatsapp", "ватсап", "почт", "материал", "отправ", "скин")
_TIMING_ACTION_TERMS = ("перезвон", "позвон", "позже", "посовет", "обсуд")
_INTERNAL_DISCUSSION_TERMS = (
    "коллег",
    "руковод",
    "лпр",
    "директор",
    "бухгалтер",
    "юрист",
    "решение внутри",
    "обсудить внутри",
    "посоветоваться",
    "согласовать внутри",
)
_UNSUPPORTED_INTERNAL_ACTION_TERMS = (
    "с кем клиент будет обсуждать",
    "обсуждать решение",
    "обсудить решение",
    "покажет коллег",
    "показать коллег",
    "согласует с коллег",
)
_PROCESS_OBJECTION_TERMS = (
    "достаточно",
    "текущ",
    "система",
    "решение",
    "закрывает",
    "получаем",
    "предоставляем",
    "количества",
    "кассиров",
)
_TRUST_RISK_TERMS = ("незнаком", "безопас", "не отвечаю")
_REFUSAL_OR_NOT_NOW_TERMS = (
    "не будем подписывать",
    "не хотят заключать",
    "не будем заключать",
    "не рассматриваю",
    "не рассматриваем",
    "не рассматривает",
    "пока нет",
    "сейчас нет",
    "не рассматриваем",
    "не продлевать",
    "не такие большие объем",
    "не такие большие объём",
    "небольшие объем",
    "небольшие объём",
)
_SERVICE_ISSUE_TERMS = (
    "не смог",
    "не смогла",
    "не получилось",
    "ошибка",
    "не сохраня",
    "не открыва",
    "проблем",
)


@dataclass(slots=True, frozen=True)
class VoiceCustomerCallInput:
    call_id: str
    transcript: str = ""
    analysis: dict[str, Any] = field(default_factory=dict)
    report_evidence: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    call_started_at: datetime | None = None
    client_label: str | None = None
    client_phone: str | None = None


@dataclass(slots=True, frozen=True)
class VoiceCustomerSignal:
    signal_id: str
    call_id: str
    source: str
    quote: str
    quote_context: str
    interpretation: str
    manager_action: str
    customer_signal: str | None
    score: float
    speaker: str = "client"
    client_label: str | None = None
    client_phone: str | None = None
    date_label: str | None = None
    time_label: str | None = None
    client_call_reference: str | None = None
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_customer_scene(self) -> dict[str, Any]:
        meaning = _meaning_without_action(self.interpretation, self.manager_action)
        return {
            "signal_id": self.signal_id,
            "call_id": self.call_id,
            "client_call_reference": self.client_call_reference,
            "scene_summary": self.quote_context,
            "quote": self.quote,
            "quote_context": self.quote_context,
            "dialogue_evidence": _normalize_dialogue_evidence([], fallback_text=self.quote_context),
            "customer_meaning": meaning or self.interpretation,
            "manager_response": self.manager_action,
            "why_action_follows": _why_action_follows(self.customer_signal),
            "customer_signal": self.customer_signal,
            "source": self.source,
            "evidence_refs": list(self.evidence_refs),
        }

    def to_situation(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "client_label": self.client_label,
            "client_phone": self.client_phone,
            "date_label": self.date_label,
            "time_label": self.time_label,
            "client_call_reference": self.client_call_reference,
            "quote": self.quote,
            "quote_context": self.quote_context,
            "quote_context_source": "voice_of_customer_composer",
            "context": self.interpretation,
            "interpretation": self.interpretation,
            "manager_action": self.manager_action,
            "manager_action_source": "voice_of_customer_composer",
            "customer_signal": self.customer_signal,
            "source": self.source,
            "evidence_refs": list(self.evidence_refs),
            "proof_refs": list(self.evidence_refs),
        }

    def to_row(self) -> list[str]:
        return [
            self.client_call_reference or self.client_label or self.call_id,
            self.quote_context or self.quote,
            self.interpretation,
        ]

    def to_diagnostic(self, reason: str | None = None) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "call_id": self.call_id,
            "source": self.source,
            "quote": self.quote,
            "score": round(self.score, 2),
            "customer_signal": self.customer_signal,
            "rejection_reason": reason,
            "diagnostics": dict(self.diagnostics),
        }


class VoiceOfCustomerInputAdapter:
    def normalize_calls(
        self,
        artifacts: Iterable[Any],
        *,
        report_evidence_index: dict[str, dict[str, Any]] | None = None,
    ) -> list[VoiceCustomerCallInput]:
        calls: list[VoiceCustomerCallInput] = []
        for artifact in artifacts or []:
            call = self._normalize_one(artifact, report_evidence_index=report_evidence_index or {})
            if call is not None:
                calls.append(call)
        return calls

    def _normalize_one(
        self,
        artifact: Any,
        *,
        report_evidence_index: dict[str, dict[str, Any]],
    ) -> VoiceCustomerCallInput | None:
        interaction = _obj_get(artifact, "interaction") or {}
        analysis_obj = _obj_get(artifact, "analysis") or _obj_get(artifact, "original_analysis")
        call_id = _first_text(
            _obj_get(interaction, "id"),
            _dict_get(artifact, "call_id"),
            _dict_get(artifact, "interaction_id"),
        )
        if not call_id:
            return None
        metadata = _as_dict(_obj_get(interaction, "metadata_") or _obj_get(interaction, "metadata"))
        metadata.update(_as_dict(_dict_get(artifact, "metadata")))
        analysis = _as_dict(_obj_get(analysis_obj, "scores_detail") or _dict_get(artifact, "analysis"))
        indexed = _as_dict(report_evidence_index.get(call_id))
        report_evidence = _as_dict(indexed.get("report_evidence") or analysis.get("report_evidence"))
        started_at = _coerce_datetime(
            _obj_get(artifact, "call_started_at")
            or metadata.get("call_date")
            or metadata.get("started_at")
        )
        return VoiceCustomerCallInput(
            call_id=call_id,
            transcript=_first_text(_obj_get(interaction, "text"), _dict_get(artifact, "transcript")) or "",
            analysis=analysis,
            report_evidence=report_evidence,
            metadata=metadata,
            call_started_at=started_at,
            client_label=_first_text(metadata.get("contact_name"), metadata.get("client_name")),
            client_phone=_first_text(
                metadata.get("contact_phone"),
                metadata.get("phone"),
                _nested(analysis, ("call", "contact_phone")),
            ),
        )


class VoiceOfCustomerCandidateBuilder:
    def build(
        self,
        calls: list[VoiceCustomerCallInput],
        *,
        legacy_voice_of_customer: dict[str, Any] | None = None,
    ) -> list[VoiceCustomerSignal]:
        signals: list[VoiceCustomerSignal] = []
        calls_by_id = {call.call_id: call for call in calls}
        signals.extend(self._from_legacy(legacy_voice_of_customer, calls_by_id))
        for call in calls:
            signals.extend(self._from_proof_cards(call))
            signals.extend(self._from_report_evidence(call))
            signals.extend(self._from_analysis_facts(call))
        return _dedupe_signals(signals)

    def _from_legacy(
        self,
        legacy: dict[str, Any] | None,
        calls_by_id: dict[str, VoiceCustomerCallInput],
    ) -> list[VoiceCustomerSignal]:
        result: list[VoiceCustomerSignal] = []
        for index, item in enumerate(_as_dict(legacy).get("situations") or []):
            raw = _as_dict(item)
            call_id = _first_text(raw.get("call_id"))
            call = calls_by_id.get(call_id or "") if call_id else _first_call(calls_by_id)
            if call is None:
                continue
            proof_refs = _verified_proof_refs(raw, source=_first_text(raw.get("source"), "legacy_voice_of_customer") or "legacy_voice_of_customer")
            if not proof_refs:
                continue
            quote = _first_text(raw.get("quote")) or ""
            context = _first_text(raw.get("quote_context"), raw.get("context"), raw.get("interpretation")) or ""
            quote_context = _expand_quote_context(call=call, quote=quote, provided_context=context)
            category = _signal_category(quote=quote, context=quote_context or context)
            action = _first_text(raw.get("manager_action")) or _action_for_signal(category, quote_context or context)
            result.append(
                self._signal(
                    call=call,
                    source=_first_text(raw.get("source"), "legacy_voice_of_customer") or "legacy_voice_of_customer",
                    index=index,
                    quote=quote,
                    quote_context=quote_context,
                    interpretation=_interpretation_for_signal(
                        category=category,
                        context=_first_text(raw.get("interpretation"), raw.get("context"), quote_context) or "",
                        action=action,
                    ),
                    manager_action=action,
                    customer_signal=category,
                    evidence_refs=proof_refs,
                    base_score=52.0,
                )
            )
        return result

    def _from_proof_cards(self, call: VoiceCustomerCallInput) -> list[VoiceCustomerSignal]:
        result: list[VoiceCustomerSignal] = []
        for index, raw_card in enumerate(call.report_evidence.get("proof_cards") or []):
            proof_card = _as_dict(raw_card)
            if not proof_card or not _proof_card_is_verified(proof_card):
                continue
            claim_type = _text(proof_card.get("claim_type")).lower()
            if claim_type not in {"customer_signal", "service_issue", "business_outcome"}:
                continue
            quote, speaker = _proof_card_quote_and_speaker(proof_card)
            if not quote:
                continue
            quote_context = _expand_quote_context(call=call, quote=quote, provided_context=_text(proof_card.get("claim")))
            category = _signal_category_from_proof_card(proof_card) or _signal_category(
                quote=quote,
                context=quote_context or _text(proof_card.get("claim")),
            )
            action = _action_for_signal(category, quote_context)
            result.append(
                self._signal(
                    call=call,
                    source="report_evidence.proof_cards",
                    index=index,
                    quote=quote,
                    quote_context=quote_context,
                    interpretation=_interpretation_for_signal(
                        category=category,
                        context=_first_text(proof_card.get("claim"), quote_context) or "",
                        action=action,
                    ),
                    manager_action=action,
                    customer_signal=category,
                    evidence_refs=_proof_refs_from_card(
                        proof_card,
                        source="report_evidence.proof_cards",
                        quote=quote,
                    ),
                    base_score=74.0,
                    speaker=speaker,
                )
            )
        return result

    def _from_report_evidence(self, call: VoiceCustomerCallInput) -> list[VoiceCustomerSignal]:
        result: list[VoiceCustomerSignal] = []
        for index, raw_item in enumerate(call.report_evidence.get("voice_of_customer") or []):
            raw = _as_dict(raw_item)
            if not raw or raw.get("usable_in_report") is False:
                continue
            proof_refs = _verified_proof_refs(raw, source="report_evidence.voice_of_customer")
            if not proof_refs:
                continue
            speaker = _normalize_speaker(raw.get("speaker"))
            if speaker not in {"client", "unknown", "context"}:
                continue
            quote = _first_text(raw.get("quote")) or ""
            context = _first_text(raw.get("quote_context"), raw.get("meaning"), raw.get("context")) or ""
            quote_context = _expand_quote_context(call=call, quote=quote, provided_context=context)
            category = _signal_category(
                quote=quote,
                context=" ".join([quote_context, context, _first_text(raw.get("topic")) or ""]),
            )
            action = _action_for_signal(category, quote_context or context)
            result.append(
                self._signal(
                    call=call,
                    source="report_evidence.voice_of_customer",
                    index=index,
                    quote=quote,
                    quote_context=quote_context,
                    interpretation=_interpretation_for_signal(
                        category=category,
                        context=context or quote_context,
                        action=action,
                    ),
                    manager_action=action,
                    customer_signal=category,
                    evidence_refs=proof_refs,
                    base_score=66.0,
                    speaker=speaker,
                )
            )
        semantic_case = _as_dict(call.report_evidence.get("semantic_case"))
        turns = _turns_from_candidate(semantic_case)
        customer_turn = next((turn for turn in turns if turn.get("speaker") in {"client", "unknown"}), None)
        if customer_turn:
            proof_refs = _verified_proof_refs(semantic_case, source="report_evidence.semantic_case")
            if not proof_refs:
                return result
            quote = _first_text(customer_turn.get("text")) or ""
            quote_context = _expand_quote_context(call=call, quote=quote, provided_context="")
            context = _first_text(
                semantic_case.get("customer_signal"),
                semantic_case.get("core_meaning"),
                semantic_case.get("why_this_call_matters"),
            ) or quote_context
            category = _signal_category(quote=quote, context=context)
            result.append(
                self._signal(
                    call=call,
                    source="report_evidence.semantic_case",
                    index=0,
                    quote=quote,
                    quote_context=quote_context,
                    interpretation=_interpretation_for_signal(
                        category=category,
                        context=context,
                        action=_action_for_signal(category, context),
                    ),
                    manager_action=_action_for_signal(category, context),
                    customer_signal=category,
                    evidence_refs=proof_refs,
                    base_score=70.0,
                    speaker=_first_text(customer_turn.get("speaker"), "client") or "client",
                )
            )
        return result

    def _from_analysis_facts(self, call: VoiceCustomerCallInput) -> list[VoiceCustomerSignal]:
        result: list[VoiceCustomerSignal] = []
        for index, frag in enumerate(call.analysis.get("evidence_fragments") or []):
            raw = _as_dict(frag)
            proof_refs = _verified_proof_refs(raw, source="analysis.evidence_fragments")
            if not proof_refs:
                continue
            quote = _first_text(raw.get("client_text"))
            if not quote:
                continue
            context = _first_text(raw.get("why"), raw.get("summary"), raw.get("context")) or ""
            quote_context = _expand_quote_context(call=call, quote=quote, provided_context=context)
            category = _signal_category(quote=quote, context=context or quote_context)
            action = _action_for_signal(category, quote_context or context)
            result.append(
                self._signal(
                    call=call,
                    source="analysis.evidence_fragments",
                    index=index,
                    quote=quote,
                    quote_context=quote_context,
                    interpretation=_interpretation_for_signal(
                        category=category,
                        context=context or quote_context,
                        action=action,
                    ),
                    manager_action=action,
                    customer_signal=category,
                    evidence_refs=proof_refs,
                    base_score=58.0,
                )
            )
        for index, sig in enumerate(call.analysis.get("product_signals") or []):
            raw = _as_dict(sig)
            proof_refs = _verified_proof_refs(raw, source="analysis.product_signals")
            if not proof_refs:
                continue
            quote = _first_text(raw.get("quote"))
            if not quote:
                continue
            topic = _first_text(raw.get("topic")) or ""
            quote_context = _expand_quote_context(call=call, quote=quote, provided_context=topic)
            category = _signal_category(quote=quote, context=topic or quote_context)
            action = _action_for_signal(category, quote_context or topic)
            result.append(
                self._signal(
                    call=call,
                    source="analysis.product_signals",
                    index=index,
                    quote=quote,
                    quote_context=quote_context,
                    interpretation=_interpretation_for_signal(
                        category=category,
                        context=topic or quote_context,
                        action=action,
                    ),
                    manager_action=action,
                    customer_signal=category,
                    evidence_refs=proof_refs,
                    base_score=54.0,
                )
            )
        return result

    def _signal(
        self,
        *,
        call: VoiceCustomerCallInput,
        source: str,
        index: int,
        quote: str,
        quote_context: str,
        interpretation: str,
        manager_action: str,
        customer_signal: str | None,
        evidence_refs: list[dict[str, Any]],
        base_score: float,
        speaker: str = "client",
    ) -> VoiceCustomerSignal:
        started_at = call.call_started_at
        date_label = started_at.date().isoformat() if started_at else None
        time_label = started_at.strftime("%H:%M") if started_at else None
        reference = " • ".join(
            item
            for item in (call.client_label or call.client_phone or "Клиент", date_label, time_label)
            if item
        )
        score = base_score
        score += min(_signal_term_count(" ".join([quote, quote_context])), 8) * 4
        score += min(_word_count(quote_context), 80) / 8
        if _normalize_speaker(speaker) == "client":
            score += 6
        return VoiceCustomerSignal(
            signal_id=f"{call.call_id}:{source}:{index}:{_loose_norm(quote)[:40]}",
            call_id=call.call_id,
            source=source,
            quote=_clip(quote, limit=220),
            quote_context=_clip(quote_context, limit=760),
            interpretation=_clip(interpretation, limit=520),
            manager_action=_clip(manager_action, limit=260),
            customer_signal=customer_signal,
            score=score,
            speaker=_normalize_speaker(speaker),
            client_label=call.client_label,
            client_phone=call.client_phone,
            date_label=date_label,
            time_label=time_label,
            client_call_reference=reference,
            evidence_refs=evidence_refs or [{"source": source, "quote": quote}],
            diagnostics={
                "quote_words": _word_count(quote),
                "context_words": _word_count(quote_context),
            },
        )


class VoiceOfCustomerQualityGate:
    def filter(self, signals: list[VoiceCustomerSignal]) -> tuple[list[VoiceCustomerSignal], dict[str, Any]]:
        accepted: list[VoiceCustomerSignal] = []
        rejected: list[dict[str, Any]] = []
        for signal in sorted(signals, key=lambda item: (-item.score, item.call_id)):
            reason = self._rejection_reason(signal)
            if reason:
                rejected.append(signal.to_diagnostic(reason))
                continue
            accepted.append(signal)
            if len(accepted) >= 4:
                break
        return accepted, {
            "status": "passed" if accepted else "failed",
            "input_count": len(signals),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "rejected": rejected[:12],
            "composer_version": VOICE_OF_CUSTOMER_COMPOSER_VERSION,
        }

    def _rejection_reason(self, signal: VoiceCustomerSignal) -> str | None:
        quote_norm = _loose_norm(signal.quote)
        context = " ".join([signal.quote, signal.quote_context, signal.interpretation])
        evidence_context_norm = _loose_norm(" ".join([signal.quote, signal.quote_context]))
        if signal.speaker not in {"client", "unknown", "context"}:
            return "not_customer_signal"
        if not _has_enough_context(signal.quote_context):
            return "quote_context_too_short"
        if quote_norm and not _quote_supported_by_context(signal.quote, signal.quote_context):
            return "quote_missing_from_context"
        if not _has_cyrillic(" ".join([signal.interpretation, signal.manager_action])):
            return "non_russian_interpretation"
        if not signal.customer_signal and _signal_term_count(context) < 1:
            return "no_customer_signal_terms"
        action_norm = _loose_norm(signal.manager_action)
        interpretation_norm = _loose_norm(signal.interpretation)
        safe_refusal_action = signal.customer_signal == "refusal_or_not_now" and any(
            safe_marker in action_norm for safe_marker in ("не давить", "не продолжать", "сначала")
        )
        if _has_unsupported_internal_discussion_claim(
            " ".join([signal.interpretation, signal.manager_action]),
            evidence=" ".join([signal.quote, signal.quote_context]),
        ):
            return "recommendation_internal_discussion_without_context"
        if (
            "не проявил" in interpretation_norm
            and "интерес" in interpretation_norm
            and "перевести интерес" in action_norm
        ):
            return "recommendation_interest_contradicts_context"
        if _has_any(evidence_context_norm, _REFUSAL_OR_NOT_NOW_TERMS) and _has_any(
            action_norm,
            (*_CONTRACT_ACTION_TERMS, *_PROPOSAL_ACTION_TERMS, *_DEMO_ACTION_TERMS, *_MATERIAL_ACTION_TERMS),
        ):
            if not safe_refusal_action:
                return "recommendation_sales_push_after_refusal"
        if (
            _has_any(action_norm, _CONTRACT_ACTION_TERMS)
            and not _has_any(evidence_context_norm, _CONTRACT_ACTION_TERMS)
            and not safe_refusal_action
        ):
            return "recommendation_contract_without_context"
        if (
            _has_any(action_norm, _PROPOSAL_ACTION_TERMS)
            and not _has_any(evidence_context_norm, _PROPOSAL_ACTION_TERMS)
            and not safe_refusal_action
        ):
            return "recommendation_proposal_without_context"
        if (
            _has_any(action_norm, _MATERIAL_ACTION_TERMS)
            and not _has_any(evidence_context_norm, _MATERIAL_ACTION_TERMS)
            and not safe_refusal_action
        ):
            return "recommendation_material_without_context"
        if not signal.evidence_refs:
            return "missing_proof_refs"
        if any(value in quote_norm for value in _VAGUE_CALLBACK_QUOTES) and not _has_extended_context(signal.quote_context):
            return "vague_callback_without_context"
        return None


class VoiceOfCustomerDeterministicWriter:
    def build(
        self,
        *,
        signals: list[VoiceCustomerSignal],
        quality: dict[str, Any],
        llm3_diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rendered = signals[:4]
        rows = [signal.to_row() for signal in rendered]
        return {
            "status": "verified",
            "is_placeholder": False,
            "situations": [signal.to_situation() for signal in rendered],
            "items": [signal.to_situation() for signal in rendered],
            "signals": [signal.to_situation() for signal in rendered],
            "customer_scenes": [signal.to_customer_scene() for signal in rendered],
            "rows": rows,
            "intro": "Клиентские сигналы сгруппированы по контексту и следующему действию.",
            "source_note": VOICE_OF_CUSTOMER_SOURCE,
            "selection_diagnostics": {
                "composer_version": VOICE_OF_CUSTOMER_COMPOSER_VERSION,
                "prompt_version": VOICE_OF_CUSTOMER_PROMPT_VERSION,
                "selection_mode": "ranked_customer_signals",
                "selected": [signal.to_diagnostic() for signal in rendered],
                "llm3": llm3_diagnostics or {"llm3_enabled": False, "llm3_used": False},
                "quality_gate": quality,
            },
            "voice_of_customer_quality": quality,
        }

    def insufficient(
        self,
        *,
        reason: str,
        quality: dict[str, Any],
        llm3_diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "insufficient",
            "is_placeholder": True,
            "situations": [],
            "items": [],
            "signals": [],
            "customer_scenes": [],
            "rows": [],
            "source_note": VOICE_OF_CUSTOMER_SOURCE,
            "selection_diagnostics": {
                "composer_version": VOICE_OF_CUSTOMER_COMPOSER_VERSION,
                "prompt_version": VOICE_OF_CUSTOMER_PROMPT_VERSION,
                "selection_mode": "quality_gate_failed",
                "reason": reason,
                "llm3": llm3_diagnostics or {"llm3_enabled": False, "llm3_used": False},
                "quality_gate": quality,
            },
            "voice_of_customer_quality": quality,
        }


class VoiceOfCustomerComposer:
    def __init__(
        self,
        *,
        adapter: VoiceOfCustomerInputAdapter | None = None,
        builder: VoiceOfCustomerCandidateBuilder | None = None,
        quality_gate: VoiceOfCustomerQualityGate | None = None,
        writer: VoiceOfCustomerDeterministicWriter | None = None,
    ) -> None:
        self.adapter = adapter or VoiceOfCustomerInputAdapter()
        self.builder = builder or VoiceOfCustomerCandidateBuilder()
        self.quality_gate = quality_gate or VoiceOfCustomerQualityGate()
        self.writer = writer or VoiceOfCustomerDeterministicWriter()

    def compose(
        self,
        artifacts: Iterable[Any],
        *,
        legacy_voice_of_customer: dict[str, Any] | None = None,
        report_evidence_index: dict[str, dict[str, Any]] | None = None,
        llm3_enabled: bool | None = None,
    ) -> dict[str, Any]:
        calls = self.adapter.normalize_calls(
            artifacts,
            report_evidence_index=report_evidence_index,
        )
        candidates = self.builder.build(calls, legacy_voice_of_customer=legacy_voice_of_customer)
        accepted, quality = self.quality_gate.filter(candidates)
        if not accepted:
            return self.writer.insufficient(
                reason="quality_gate_no_valid_customer_signals" if candidates else "no_customer_signals",
                quality=quality,
            )
        llm3_result, llm3_diagnostics = _try_llm3_voice_of_customer(
            build_voice_of_customer_llm3_payload(accepted),
            force_enabled=llm3_enabled,
        )
        if llm3_result is not None:
            llm3_quality = _quality_for_llm3_result(llm3_result, quality)
            if llm3_quality["status"] == "passed":
                llm3_result.setdefault("selection_diagnostics", {})["quality_gate"] = llm3_quality
                llm3_result.setdefault("selection_diagnostics", {})["llm3"] = llm3_diagnostics
                llm3_result["voice_of_customer_quality"] = llm3_quality
                return llm3_result
            llm3_diagnostics["llm3_rejection_reason"] = "quality_gate_failed_after_llm3"
            llm3_diagnostics["llm3_used"] = False
            llm3_diagnostics["llm3_quality"] = llm3_quality
        return self.writer.build(
            signals=accepted,
            quality=quality,
            llm3_diagnostics=llm3_diagnostics,
        )


def compose_voice_of_customer(
    artifacts: Iterable[Any],
    *,
    legacy_voice_of_customer: dict[str, Any] | None = None,
    report_evidence_index: dict[str, dict[str, Any]] | None = None,
    llm3_enabled: bool | None = None,
) -> dict[str, Any]:
    return VoiceOfCustomerComposer().compose(
        artifacts,
        legacy_voice_of_customer=legacy_voice_of_customer,
        report_evidence_index=report_evidence_index,
        llm3_enabled=llm3_enabled,
    )


def build_voice_of_customer_llm3_payload(signals: list[VoiceCustomerSignal]) -> dict[str, Any]:
    return {
        "contract_version": VOICE_OF_CUSTOMER_PROMPT_VERSION,
        "signals": [
            {
                "signal_id": signal.signal_id,
                "call_id": signal.call_id,
                "client_call_reference": signal.client_call_reference,
                "quote": signal.quote,
                "quote_context": signal.quote_context,
                "interpretation": signal.interpretation,
                "manager_action": signal.manager_action,
                "customer_signal": signal.customer_signal,
                "source": signal.source,
                "evidence_refs": signal.evidence_refs,
                "proof_refs": signal.evidence_refs,
                "locked_fields": {
                    "call_id": signal.call_id,
                    "client_call_reference": signal.client_call_reference,
                    "quote": signal.quote,
                    "customer_signal": signal.customer_signal,
                    "evidence_refs": signal.evidence_refs,
                },
            }
            for signal in signals[:8]
        ],
        "output_rules": {
            "rows_min": 1,
            "rows_max": 4,
            "prefer_rows": "2-4 when available",
            "narrative_preferred": True,
            "must_use_customer_or_customer_context_signal": True,
            "fragment_must_be_mini_scene": True,
            "recommendation_must_follow_signal": True,
        },
        "required_output_keys": [
            "status",
            "customer_scenes",
            "situations",
            "rows",
            "source_note",
            "selection_diagnostics",
        ],
    }


def _try_llm3_voice_of_customer(
    payload: dict[str, Any],
    *,
    force_enabled: bool | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "llm3_enabled": _llm3_enabled() if force_enabled is None else bool(force_enabled),
        "llm3_used": False,
        "llm3_prompt_version": VOICE_OF_CUSTOMER_PROMPT_VERSION,
    }
    if not diagnostics["llm3_enabled"]:
        return None, diagnostics
    try:
        raw = _request_llm3_voice_of_customer(payload)
        diagnostics["llm3_raw_status"] = raw.get("status")
        if isinstance(raw.get("_routing"), dict):
            diagnostics["llm3_routing"] = raw.get("_routing")
        normalized, reason = _normalize_llm3_voice_of_customer(raw, payload)
        if normalized is None:
            diagnostics["llm3_rejection_reason"] = reason
            diagnostics["llm3_response"] = _json_safe(raw)
            return None, diagnostics
        diagnostics["llm3_used"] = True
        return normalized, diagnostics
    except Exception as exc:
        diagnostics["llm3_error"] = str(exc)
        return None, diagnostics


def _request_llm3_voice_of_customer(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = _read_llm3_prompt()
    subject_key = "voice_of_customer_composer"
    simulated = _request_llm3_simulation(
        payload=payload,
        prompt=prompt,
        request_kind="voice_of_customer_composer",
        subject_key=subject_key,
        input_artifact="llm3_voice_of_customer_input.json",
        output_artifact="llm3_voice_of_customer_output.json",
        notes="LLM-3 Voice Of Customer composer simulated.",
    )
    if simulated is not None:
        return simulated

    from openai import OpenAI

    from app.core_shared.ai_routing import AIProviderRouter
    from app.core_shared.config.settings import settings

    route_plan = AIProviderRouter().build_route_plan(layer="llm3", subject_key=subject_key)
    candidate = route_plan.current_candidate()
    compatibility_candidate = candidate
    if (candidate.endpoint or "").rstrip("/") == "/chat/completions":
        compatibility_candidate = replace(candidate, endpoint=None)
    AIProviderRouter.ensure_execution_compatibility(
        compatibility_candidate,
        executor_label="LLM-3 Voice Of Customer composer",
        required_execution_mode="openai_compatible",
    )
    client = OpenAI(api_key=candidate.resolved_api_key(), base_url=candidate.api_base)
    response = None
    last_error: Exception | None = None
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
    parsed = json.loads(_extract_openai_message_content(response))
    result = _as_dict(parsed)
    result["_routing"] = route_plan.to_metadata(
        request_kind="voice_of_customer_composer",
        usage=extract_openai_usage_metadata(response),
        notes="LLM-3 Voice Of Customer composer completed.",
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


def _normalize_llm3_voice_of_customer(
    raw: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    if _text(raw.get("status")) != "verified":
        return None, "status_not_verified"
    situations = [_as_dict(item) for item in raw.get("situations") or [] if isinstance(item, dict)]
    customer_scenes = _normalize_customer_scenes(raw.get("customer_scenes"), payload)
    if not situations and customer_scenes:
        situations = [_situation_from_customer_scene(scene) for scene in customer_scenes]
    rows = [list(row) for row in raw.get("rows") or [] if isinstance(row, list)]
    if not situations and rows:
        situations = _situations_from_rows(rows, payload)
    situations = _repair_llm3_situations_with_payload(situations, payload)
    if not (1 <= len(situations) <= 4):
        return None, "situations_count_out_of_range"
    if not customer_scenes:
        customer_scenes = _normalize_customer_scenes(situations, payload)
    rows = [
        [
            _first_text(item.get("client_call_reference"), item.get("client_label"), item.get("call_id")) or "Клиент",
            _first_text(item.get("scene_summary"), item.get("quote_context"), item.get("quote")) or "",
            _first_text(
                item.get("customer_meaning"),
                item.get("interpretation"),
                item.get("context"),
                item.get("manager_action"),
            )
            or "",
        ]
        for item in (customer_scenes or situations)
    ]
    if not (1 <= len(rows) <= 4) or any(len(row) != 3 for row in rows):
        return None, "rows_shape_invalid"
    language_probe = " ".join(
        [
            " ".join(str(cell) for row in rows for cell in row),
            " ".join(
                " ".join(
                    _first_text(
                        scene.get("scene_summary"),
                        scene.get("customer_meaning"),
                        scene.get("manager_response"),
                        scene.get("why_action_follows"),
                    )
                    or ""
                    for scene in customer_scenes
                ).split()
            ),
        ]
    )
    if not _manager_facing_russian_enough(language_probe):
        return None, "manager_facing_language_not_russian"
    result = dict(raw)
    result.pop("_routing", None)
    result.update(
        {
            "status": "verified",
            "is_placeholder": False,
            "situations": situations[:4],
            "items": situations[:4],
            "signals": situations[:4],
            "customer_scenes": customer_scenes[:4],
            "rows": rows[:4],
            "source_note": VOICE_OF_CUSTOMER_SOURCE,
            "selection_diagnostics": {
                **_as_dict(raw.get("selection_diagnostics")),
                "composer_version": VOICE_OF_CUSTOMER_COMPOSER_VERSION,
                "prompt_version": VOICE_OF_CUSTOMER_PROMPT_VERSION,
                "selection_mode": "llm3_voice_of_customer",
                "llm3_used": True,
            },
        }
    )
    return result, None


def _normalize_customer_scenes(value: Any, payload: dict[str, Any]) -> list[dict[str, Any]]:
    signals = [_as_dict(item) for item in _as_dict(payload).get("signals") or []]
    scenes: list[dict[str, Any]] = []
    for index, raw_scene in enumerate(value or []):
        if not isinstance(raw_scene, dict):
            continue
        item = dict(raw_scene)
        source_signal = _matching_payload_signal(item, signals, index)
        quote = _first_text(source_signal.get("quote"), item.get("quote"), item.get("customer_quote")) or ""
        quote_context = _first_text(source_signal.get("quote_context"), item.get("quote_context"), item.get("scene")) or ""
        dialogue = _grounded_dialogue_evidence(
            item.get("dialogue_evidence"),
            fallback_text=quote_context or quote,
            evidence_text=" ".join([quote, quote_context]),
        )
        category = _first_text(source_signal.get("customer_signal"), item.get("customer_signal"))
        manager_response = _first_text(
            item.get("manager_response"),
            item.get("manager_action"),
            item.get("recommended_action"),
            source_signal.get("manager_action"),
        ) or ""
        raw_scene_summary = _first_text(
            item.get("scene_summary"),
            item.get("what_customer_reacted_to"),
            item.get("quote_context"),
            source_signal.get("quote_context"),
        ) or quote_context
        scene_summary = _scene_text_or_source(
            raw_scene_summary,
            fallback=quote_context,
            evidence=" ".join([quote, quote_context]),
            category=category,
            action=manager_response,
            include_action=False,
        )
        raw_customer_meaning = _first_text(
            item.get("customer_meaning"),
            item.get("what_signal_means"),
            item.get("interpretation"),
            item.get("context"),
        ) or ""
        customer_meaning = _scene_text_or_source(
            raw_customer_meaning,
            fallback=_first_text(source_signal.get("interpretation")) or "",
            evidence=" ".join([quote, quote_context]),
            category=category,
            action=manager_response,
            include_action=False,
        )
        why_action_follows = _scene_text_or_source(
            _first_text(
                item.get("why_action_follows"),
                item.get("why_this_action"),
                item.get("proof_explanation"),
            ) or "",
            fallback="",
            evidence=" ".join([quote, quote_context]),
            category=category,
            action="",
            include_action=False,
        )
        scenes.append(
            _repair_callback_scene_without_internal_context(
                {
                    "signal_id": _first_text(item.get("signal_id"), source_signal.get("signal_id")),
                    "call_id": _first_text(source_signal.get("call_id"), item.get("call_id")),
                    "client_call_reference": _first_text(
                        source_signal.get("client_call_reference"),
                        item.get("client_call_reference"),
                        item.get("client_label"),
                    ) or "Клиент",
                    "quote": quote,
                    "quote_context": quote_context,
                    "scene_summary": scene_summary,
                    "customer_meaning": customer_meaning,
                    "manager_response": manager_response,
                    "why_action_follows": why_action_follows,
                    "dialogue_evidence": dialogue,
                    "customer_signal": category,
                    "source": _first_text(source_signal.get("source"), item.get("source"), "voice_of_customer_composer"),
                    "evidence_refs": list(source_signal.get("evidence_refs") or item.get("evidence_refs") or []),
                    "proof_refs": list(source_signal.get("proof_refs") or source_signal.get("evidence_refs") or []),
                },
                evidence=" ".join([quote, quote_context]),
            )
        )
    return scenes[:4]


def _scene_text_or_source(
    value: str,
    *,
    fallback: str,
    evidence: str,
    category: str | None,
    action: str,
    include_action: bool = True,
) -> str:
    text = _text(value)
    fallback_text = _text(fallback)
    if not text:
        return fallback_text
    evidence_norm = _loose_norm(evidence)
    text_norm = _loose_norm(text)
    unsupported_terms = (
        "оплат",
        "счет",
        "счёт",
        "тариф",
        "цена",
        "стоимост",
        "договор",
        "подпис",
        "демо",
        "тестирован",
    )
    if _has_unsupported_internal_discussion_claim(text, evidence=evidence):
        generic = (
            _interpretation_for_signal(category=category, context="", action=action)
            if include_action
            else _generic_meaning_for_category(category)
        )
        return generic or fallback_text
    for term in unsupported_terms:
        if term in text_norm and term not in evidence_norm:
            generic = (
                _interpretation_for_signal(category=category, context="", action=action)
                if include_action
                else _generic_meaning_for_category(category)
            )
            return generic or fallback_text
    return text


def _generic_meaning_for_category(category: str | None) -> str:
    return {
        "proposal_request": "Клиент просит коммерческое предложение; перед ответом нужен контекст.",
        "document_or_signature_need": "Клиентский сигнал связан с документами или подписанием.",
        "roles_access_or_demo_need": "Клиентский сигнал связан с ролями, доступами или показом решения.",
        "materials_channel_request": "Клиент согласует канал продолжения; это нужно закрепить следующим шагом.",
        "interest_signal": "Клиент проявляет интерес; его нужно перевести в конкретный следующий шаг.",
        "timing_or_internal_discussion": "Клиент не подтверждает готовность двигаться дальше сейчас и переводит следующий контакт в неопределённое «я перезвоню».",
        "current_process_objection": "Клиент показывает, что текущий процесс пока закрывает задачу.",
        "trust_or_channel_barrier": "Клиент обозначает барьер доверия или предпочитаемый канал коммуникации.",
        "refusal_or_not_now": "Клиент отказывается или откладывает решение; сначала нужно понять причину и условие возврата.",
        "service_or_usage_issue": "Клиент пришел с рабочей проблемой; сначала нужно закрыть сервисный вопрос.",
    }.get(category or "", "Клиентский сигнал требует уточнения и следующего действия.")


def _situation_from_customer_scene(scene: dict[str, Any]) -> dict[str, Any]:
    meaning = _first_text(scene.get("customer_meaning"), scene.get("scene_summary")) or ""
    action = _first_text(scene.get("manager_response")) or ""
    interpretation = " ".join(part for part in (meaning, action) if part)
    return {
        "signal_id": scene.get("signal_id"),
        "call_id": scene.get("call_id"),
        "client_call_reference": scene.get("client_call_reference"),
        "quote": scene.get("quote"),
        "quote_context": scene.get("quote_context") or scene.get("scene_summary"),
        "context": interpretation,
        "interpretation": interpretation,
        "manager_action": action,
        "customer_signal": scene.get("customer_signal"),
        "source": scene.get("source") or "voice_of_customer_composer",
        "evidence_refs": list(scene.get("evidence_refs") or []),
        "proof_refs": list(scene.get("proof_refs") or scene.get("evidence_refs") or []),
    }


def _normalize_dialogue_evidence(value: Any, *, fallback_text: Any = "") -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw_item in value or []:
        if isinstance(raw_item, dict):
            text = _strip_fragment_prefix(_first_text(raw_item.get("text"), raw_item.get("quote")) or "")
            if text:
                items.append(
                    {
                        "speaker": _normalize_speaker(raw_item.get("speaker")) or "unknown",
                        "text": text,
                    }
                )
        elif isinstance(raw_item, str) and _text(raw_item):
            items.append({"speaker": "unknown", "text": _strip_fragment_prefix(raw_item)})
    if items:
        return _consistent_dialogue_speakers(items[:8])
    fallback = _strip_fragment_prefix(fallback_text)
    if not fallback:
        return []
    matches = list(
        re.finditer(
            r"(Клиент|Менеджер|Контекст|Сторона\s*1|Сторона\s*2|Customer|Manager|Side\s*1|Side\s*2)\s*:\s*",
            fallback,
            flags=re.IGNORECASE,
        )
    )
    if matches:
        parsed: list[dict[str, str]] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(fallback)
            text = fallback[start:end].strip()
            if text:
                parsed.append({"speaker": _normalize_speaker(match.group(1)), "text": text})
        if parsed:
            return _consistent_dialogue_speakers(parsed[:8])
    return [{"speaker": "side_1", "text": fallback}]


def _grounded_dialogue_evidence(
    value: Any,
    *,
    fallback_text: Any,
    evidence_text: Any,
) -> list[dict[str, str]]:
    dialogue = _normalize_dialogue_evidence(value, fallback_text="")
    if dialogue and all(_quote_supported_by_context(turn.get("text"), evidence_text) for turn in dialogue):
        return dialogue
    return _normalize_dialogue_evidence([], fallback_text=fallback_text)


def _consistent_dialogue_speakers(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Avoid mixed certainty such as `Сторона 1` next to `Клиент` in one scene."""
    speakers = {_normalize_speaker(item.get("speaker")) for item in items}
    has_unclear = bool(speakers & {"unknown", "context", "side_1", "side_2"})
    has_named = bool(speakers & {"client", "manager"})
    if has_unclear and not has_named:
        return [
            {**item, "speaker": "side_1" if index % 2 == 0 else "side_2"}
            for index, item in enumerate(items)
        ]
    if not (has_unclear and has_named):
        return items
    return [
        {**item, "speaker": "side_1" if index % 2 == 0 else "side_2"}
        for index, item in enumerate(items)
    ]


def _strip_fragment_prefix(value: Any) -> str:
    return re.sub(r"^(?:фрагмент|цитата|quote|context)\s*[:—-]\s*", "", _text(value), flags=re.IGNORECASE)


def _repair_llm3_situations_with_payload(
    situations: list[dict[str, Any]],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    signals = [_as_dict(item) for item in _as_dict(payload).get("signals") or []]
    repaired: list[dict[str, Any]] = []
    for index, situation in enumerate(situations):
        item = dict(situation)
        quote_context = _first_text(item.get("quote_context"), item.get("context")) or ""
        source_signal = _matching_payload_signal(item, signals, index)
        source_context = _first_text(source_signal.get("quote_context")) or ""
        if source_context and (
            not _has_enough_context(quote_context)
            or not _looks_like_mini_scene(quote_context)
            or _loose_norm(_first_text(item.get("quote")) or "") not in _loose_norm(quote_context)
        ):
            item["quote_context"] = source_context
        if source_signal:
            item["signal_id"] = source_signal.get("signal_id")
            item["call_id"] = source_signal.get("call_id")
            item["quote"] = source_signal.get("quote")
            item["quote_context"] = source_context or item.get("quote_context")
            item["client_call_reference"] = source_signal.get("client_call_reference")
            item["customer_signal"] = source_signal.get("customer_signal")
            item["source"] = source_signal.get("source")
            item["evidence_refs"] = source_signal.get("evidence_refs") or []
            item["proof_refs"] = source_signal.get("proof_refs") or source_signal.get("evidence_refs") or []
        repaired.append(item)
    return repaired


def _matching_payload_signal(
    situation: dict[str, Any],
    signals: list[dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    signal_id = _first_text(situation.get("signal_id"))
    call_id = _first_text(situation.get("call_id"))
    quote_norm = _loose_norm(situation.get("quote"))
    if signal_id:
        for signal in signals:
            if _first_text(signal.get("signal_id")) == signal_id:
                return signal
    if call_id or quote_norm:
        for signal in signals:
            signal_quote_norm = _loose_norm(signal.get("quote"))
            if call_id and _first_text(signal.get("call_id")) != call_id:
                continue
            if quote_norm and signal_quote_norm and (
                quote_norm in signal_quote_norm or signal_quote_norm in quote_norm
            ):
                return signal
    if 0 <= index < len(signals):
        return signals[index]
    return {}


def _quality_for_llm3_result(result: dict[str, Any], fallback_quality: dict[str, Any]) -> dict[str, Any]:
    signals: list[VoiceCustomerSignal] = []
    for index, item in enumerate(result.get("situations") or []):
        raw = _as_dict(item)
        signals.append(
            VoiceCustomerSignal(
                signal_id=f"llm3:{index}",
                call_id=_first_text(raw.get("call_id"), f"llm3:{index}") or f"llm3:{index}",
                source="llm3",
                quote=_first_text(raw.get("quote")) or "",
                quote_context=_first_text(raw.get("quote_context"), raw.get("context")) or "",
                interpretation=_first_text(raw.get("interpretation"), raw.get("context")) or "",
                manager_action=_first_text(raw.get("manager_action"), raw.get("interpretation")) or "",
                customer_signal=_first_text(raw.get("customer_signal")),
                score=60.0,
                speaker="client",
                evidence_refs=list(raw.get("evidence_refs") or raw.get("proof_refs") or []),
            )
        )
    accepted, quality = VoiceOfCustomerQualityGate().filter(signals)
    quality["source_quality"] = fallback_quality
    quality["accepted_count"] = len(accepted)
    if len(accepted) != len(signals):
        quality["status"] = "failed"
        quality["rejection_reason"] = "llm3_scene_quality_mismatch"
    return quality


def _situations_from_rows(rows: list[list[Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    signals = _as_dict(payload).get("signals") or []
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:4]):
        source_signal = _as_dict(signals[index]) if index < len(signals) else {}
        result.append(
            {
                "call_id": source_signal.get("call_id"),
                "client_call_reference": row[0],
                "quote": source_signal.get("quote") or row[1],
                "quote_context": row[1],
                "context": row[2],
                "interpretation": row[2],
                "manager_action": source_signal.get("manager_action"),
                "customer_signal": source_signal.get("customer_signal"),
                "source": "llm3.rows",
            }
        )
    return result


def _expand_quote_context(
    *,
    call: VoiceCustomerCallInput,
    quote: str,
    provided_context: str,
) -> str:
    turns = _call_turns(call)
    quote_norm = _loose_norm(quote)
    matched_index = None
    if quote_norm:
        for index, turn in enumerate(turns):
            turn_norm = _loose_norm(turn.get("text"))
            if quote_norm and (quote_norm in turn_norm or turn_norm in quote_norm):
                matched_index = index
                break
    if matched_index is not None:
        selected = turns[max(0, matched_index - 2) : min(len(turns), matched_index + 3)]
        joined = _join_turns(selected)
        if _has_enough_context(joined):
            return joined
    if quote_norm:
        for start in range(0, len(turns)):
            for end in range(min(len(turns), start + 5), start + 1, -1):
                selected = turns[start:end]
                joined = _join_turns(selected)
                joined_norm = _loose_norm(joined)
                if quote_norm in joined_norm and _has_enough_context(joined):
                    return joined
    if provided_context and _has_enough_context(provided_context):
        return provided_context
    if provided_context:
        return provided_context
    return _clip(_join_turns(turns[:5]) or quote, limit=760)


def _has_enough_context(value: str) -> bool:
    text = _text(value)
    if not text:
        return False
    if _looks_like_mini_scene(text):
        return True
    return _word_count(text) >= 18


def _looks_like_mini_scene(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    lowered = text.lower()
    labels = len(re.findall(r"\b(?:клиент|менеджер|контекст|customer|manager)\s*:", lowered, flags=re.IGNORECASE))
    return labels >= 2


def _has_extended_context(value: str) -> bool:
    text = _text(value)
    lowered = text.lower()
    return _word_count(text) >= 18 or (
        "клиент:" in lowered
        and ("менеджер:" in lowered or "контекст:" in lowered)
        and _word_count(text) >= 10
    )


def _call_turns(call: VoiceCustomerCallInput) -> list[dict[str, str]]:
    segments = [item for item in call.metadata.get("segments") or [] if isinstance(item, dict)]
    turns: list[dict[str, str]] = []
    for index, segment in enumerate(segments):
        text = _text(segment.get("text"))
        if not text:
            continue
        speaker = _normalize_speaker(segment.get("speaker"))
        if speaker not in {"client", "manager", "unknown", "context"}:
            speaker = _infer_speaker(text)
        turns.append(
            {
                "speaker": speaker if speaker != "unknown" else _infer_speaker(text),
                "text": text,
                "turn_index": str(index),
            }
        )
    if turns:
        return turns
    chunks = call.transcript.splitlines()
    if len(chunks) <= 1:
        chunks = re.split(r"(?<=[.!?])\s+", call.transcript)
    for index, chunk in enumerate(chunks):
        text = _text(chunk)
        if not text:
            continue
        speaker = "context"
        body = text
        match = re.match(r"^([^:]{1,40}):\s*(.+)$", text)
        if match:
            speaker = _normalize_speaker(match.group(1))
            body = match.group(2).strip()
        else:
            speaker = _infer_speaker(text)
        turns.append({"speaker": speaker, "text": body, "turn_index": str(index)})
    return turns


def _turns_from_candidate(raw: dict[str, Any]) -> list[dict[str, str]]:
    raw_turns = None
    for key in ("best_dialogue_fragment", "dialogue_fragment"):
        if isinstance(raw.get(key), list):
            raw_turns = raw.get(key)
            break
    turns: list[dict[str, str]] = []
    for index, turn in enumerate(raw_turns or []):
        item = _as_dict(turn)
        text = _text(item.get("text") or item.get("quote"))
        if text:
            turns.append(
                {
                    "speaker": _normalize_speaker(item.get("speaker") or "unknown"),
                    "text": text,
                    "turn_index": str(index),
                }
            )
    return turns


def _join_turns(turns: list[dict[str, Any]]) -> str:
    normalized_turns = []
    has_unclear = False
    for turn in turns:
        speaker = _normalize_speaker(turn.get("speaker"))
        if speaker in {"unknown", "context"}:
            inferred = _infer_speaker(_text(turn.get("text")))
            speaker = inferred if inferred in {"client", "manager"} else speaker
        if speaker in {"unknown", "context", "side_1", "side_2"}:
            has_unclear = True
        normalized_turns.append({**turn, "speaker": speaker})
    if has_unclear:
        normalized_turns = [
            {
                **turn,
                "speaker": turn.get("speaker")
                if turn.get("speaker") in {"client", "manager"}
                else ("side_1" if index % 2 == 0 else "side_2"),
            }
            for index, turn in enumerate(normalized_turns)
        ]
    labels = {
        "client": "Клиент",
        "customer": "Клиент",
        "manager": "Менеджер",
        "side_1": "Сторона 1",
        "side_2": "Сторона 2",
        "unknown": "Сторона 1",
        "context": "Сторона 1",
    }
    parts = []
    for turn in normalized_turns:
        text = _text(turn.get("text"))
        if not text:
            continue
        speaker = _normalize_speaker(turn.get("speaker"))
        label = labels.get(speaker, "Сторона 1")
        parts.append(f"{label}: {text}")
    return _clip(" ".join(parts), limit=760)


def _verified_proof_refs(payload: dict[str, Any], *, source: str) -> list[dict[str, Any]]:
    proof_card = _as_dict(payload.get("proof_card"))
    if proof_card and _proof_card_is_verified(proof_card):
        quote = _first_text(payload.get("quote"), proof_card.get("evidence_quote")) or ""
        return _proof_refs_from_card(proof_card, source=source, quote=quote)

    refs = []
    for raw_ref in payload.get("proof_refs") or payload.get("evidence_refs") or []:
        ref = _as_dict(raw_ref)
        if not ref:
            continue
        status = _text(ref.get("proof_status") or ref.get("status")).lower()
        if status and status not in {"verified_proof_card", "verified", "proven"}:
            continue
        proof_id = _first_text(ref.get("proof_id"), ref.get("id"))
        evidence_ids = _string_list(ref.get("evidence_ids"))
        quote = _first_text(ref.get("quote"), ref.get("evidence_quote"), payload.get("quote"))
        if proof_id or evidence_ids or quote:
            refs.append(
                {
                    "source": ref.get("source") or source,
                    "proof_id": proof_id,
                    "scene_id": _first_text(ref.get("scene_id")),
                    "evidence_ids": evidence_ids,
                    "quote": quote,
                    "proof_status": "verified_proof_card",
                }
            )
    return refs


def _proof_card_is_verified(proof_card: dict[str, Any]) -> bool:
    if not proof_card:
        return False
    if _text(proof_card.get("reject_reason")):
        return False
    status = _text(proof_card.get("status")).lower()
    if status and status not in {"verified", "proven"}:
        return False
    return True


def _proof_card_quote_and_speaker(proof_card: dict[str, Any]) -> tuple[str | None, str]:
    for raw_item in proof_card.get("supporting_evidence") or []:
        item = _as_dict(raw_item)
        quote = _first_text(item.get("quote"), item.get("text"))
        if quote:
            return quote, _normalize_speaker(item.get("speaker")) or "client"
    return _first_text(proof_card.get("evidence_quote")), "client"


def _proof_refs_from_card(
    proof_card: dict[str, Any],
    *,
    source: str,
    quote: str,
) -> list[dict[str, Any]]:
    return [
        {
            "source": source,
            "proof_id": _first_text(proof_card.get("proof_id"), proof_card.get("id")),
            "scene_id": _first_text(proof_card.get("scene_id")),
            "evidence_ids": _string_list(proof_card.get("evidence_ids")),
            "quote": quote or _first_text(proof_card.get("evidence_quote")),
            "claim": _first_text(proof_card.get("claim")),
            "claim_type": _first_text(proof_card.get("claim_type")),
            "proof_status": "verified_proof_card",
        }
    ]


def _signal_category_from_proof_card(proof_card: dict[str, Any]) -> str | None:
    claim_type = _text(proof_card.get("claim_type")).lower()
    if claim_type == "service_issue":
        return "service_or_usage_issue"
    if claim_type == "customer_signal":
        return _signal_category(
            quote=_first_text(proof_card.get("evidence_quote")) or "",
            context=_first_text(proof_card.get("claim")) or "",
        )
    return None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [text for item in value if (text := _first_text(item))]
    text = _first_text(value)
    return [text] if text else []


def _meaning_without_action(interpretation: str, action: str) -> str:
    text = _text(interpretation)
    action_text = _text(action)
    if action_text and action_text in text:
        text = text.replace(action_text, "").strip()
    return re.sub(r"\s*Что сделать:\s*$", "", text).strip()


def _why_action_follows(category: str | None) -> str:
    return {
        "proposal_request": "Клиент просит КП, поэтому перед отправкой нужно уточнить параметры предложения.",
        "document_or_signature_need": "Сигнал связан с документами, поэтому следующий шаг должен объяснять документный процесс.",
        "roles_access_or_demo_need": "Клиенту нужен сценарий работы, поэтому уместно зафиксировать роли и показать процесс.",
        "materials_channel_request": "Клиент согласовал канал, поэтому важно отправить материалы и закрепить точку возврата.",
        "interest_signal": "Есть интерес, но его нужно перевести в конкретный следующий шаг.",
        "timing_or_internal_discussion": "Клиент переносит инициативу, поэтому менеджеру нужна спокойная точка возврата.",
        "current_process_objection": "Клиент показывает барьер текущего процесса, поэтому сначала нужно уточнить условия изменения.",
        "trust_or_channel_barrier": "Клиент обозначает барьер доверия или канала, поэтому действие должно снизить давление.",
        "refusal_or_not_now": "Клиент отказывается или ставит паузу, поэтому продажное давление нужно заменить уточнением причины.",
        "service_or_usage_issue": "Клиент говорит о рабочей проблеме, поэтому сначала нужно закрыть сервисный вопрос.",
    }.get(category or "", "Действие должно следовать только из сказанного клиентом в мини-сцене.")


def _signal_category(*, quote: str, context: str) -> str | None:
    text = _loose_norm(" ".join([quote, context]))
    quote_text = _loose_norm(quote)
    if _has_any(text, _SERVICE_ISSUE_TERMS):
        return "service_or_usage_issue"
    if _has_any(text, _REFUSAL_OR_NOT_NOW_TERMS):
        return "refusal_or_not_now"
    if _has_any(text, _TRUST_RISK_TERMS):
        return "trust_or_channel_barrier"
    if _has_any(quote_text, _MATERIAL_ACTION_TERMS) and not _has_any(
        quote_text,
        (*_PROPOSAL_ACTION_TERMS, *_CONTRACT_ACTION_TERMS, *_DEMO_ACTION_TERMS),
    ):
        return "materials_channel_request"
    if _has_any(text, _TIMING_ACTION_TERMS):
        return "timing_or_internal_discussion"
    if _has_any(text, _PROCESS_OBJECTION_TERMS):
        return "current_process_objection"
    if _has_any(text, _PROPOSAL_ACTION_TERMS):
        return "proposal_request"
    if _has_any(text, _CONTRACT_ACTION_TERMS):
        return "document_or_signature_need"
    if _has_any(text, _DEMO_ACTION_TERMS):
        return "roles_access_or_demo_need"
    if _has_any(text, _MATERIAL_ACTION_TERMS):
        return "materials_channel_request"
    if "интерес" in text or "расскаж" in text:
        return "interest_signal"
    return None


def _action_for_signal(category: str | None, context: str) -> str:
    if category == "timing_or_internal_discussion":
        if _has_internal_discussion_context(context):
            return "Что сделать: уточнить, с кем клиент будет обсуждать решение, когда вернуться к разговору и какой следующий шаг зафиксировать."
        return "Что сделать: не оставлять контакт на «я перезвоню»; спокойно предложить конкретную точку возврата и оставить клиенту возможность вернуться раньше."
    if category == "current_process_objection":
        return "Что сделать: уточнить, что именно закрывает текущее решение, где остаются ручные операции или риски, и только затем предлагать следующий шаг."
    if category == "trust_or_channel_barrier":
        return "Что сделать: согласовать безопасный канал общения, коротко обозначить цель контакта и не давить повторными звонками без согласованного следующего шага."
    if category == "refusal_or_not_now":
        return "Что сделать: коротко уточнить причину отказа или паузы, зафиксировать условие возврата к разговору и не давить коммерческим предложением."
    if category == "service_or_usage_issue":
        return "Что сделать: сначала помочь закрыть сервисный вопрос клиента, проверить результат и только после этого аккуратно возвращаться к продаже."
    if category == "proposal_request":
        return "Что сделать: перед отправкой КП уточнить объем, пользователей, критерии выбора и срок обсуждения."
    if category == "document_or_signature_need":
        return "Что сделать: связать ответ с документным процессом клиента и предложить показать сценарий подписания."
    if category == "roles_access_or_demo_need":
        return "Что сделать: зафиксировать роли/доступы и предложить демо или созвон по этому сценарию."
    if category == "materials_channel_request":
        return "Что сделать: отправить материалы в согласованный канал и сразу назначить короткий follow-up."
    if category == "interest_signal":
        return "Что сделать: перевести интерес в следующий шаг с целью, участниками и сроком."
    if _has_any(_loose_norm(context), _CONTRACT_ACTION_TERMS):
        return "Что сделать: уточнить документный сценарий клиента и закрепить следующий шаг."
    return "Что сделать: уточнить, что именно клиент хочет решить, и согласовать следующий контакт."


def _interpretation_for_signal(*, category: str | None, context: str, action: str) -> str:
    meaning = _clip(context, limit=260)
    if not meaning:
        meaning = {
            "proposal_request": "Клиент просит коммерческое предложение, значит перед отправкой нужен контекст.",
            "document_or_signature_need": "Клиент говорит о документах или подписании, это сигнал процессной потребности.",
            "roles_access_or_demo_need": "Клиентский сигнал связан с ролями, доступами или показом решения.",
            "materials_channel_request": "Клиент согласует канал продолжения, это нужно закрепить follow-up.",
            "interest_signal": "Клиент проявляет интерес, его нужно перевести в следующий шаг.",
            "timing_or_internal_discussion": (
                "Клиент не подтверждает готовность двигаться дальше сейчас и переводит следующий контакт "
                "в неопределённое «я перезвоню»."
                if not _has_internal_discussion_context(context)
                else "Клиент не готов принять решение в моменте и уводит следующий шаг в обсуждение или обратный звонок."
            ),
            "current_process_objection": "Клиент показывает, что текущее решение или процесс уже закрывает задачу.",
            "trust_or_channel_barrier": "Клиент обозначает барьер доверия или предпочитаемый канал коммуникации.",
            "refusal_or_not_now": "Клиент отказывается или откладывает решение; здесь важнее понять причину и условие возврата, чем продолжать продажу.",
            "service_or_usage_issue": "Клиент пришел с проблемой использования сервиса; сначала нужно решить рабочий вопрос.",
        }.get(category or "", "Клиентский сигнал требует уточнения и следующего действия.")
    if action and action not in meaning:
        return f"{meaning} {action}"
    return meaning


def _dedupe_signals(signals: list[VoiceCustomerSignal]) -> list[VoiceCustomerSignal]:
    best: dict[str, VoiceCustomerSignal] = {}
    for signal in signals:
        key = _loose_norm(signal.quote)[:90] or signal.signal_id
        previous = best.get(key)
        if previous is None or signal.score > previous.score:
            best[key] = signal
    return list(best.values())


def _first_call(calls_by_id: dict[str, VoiceCustomerCallInput]) -> VoiceCustomerCallInput | None:
    return next(iter(calls_by_id.values()), None)


def _signal_term_count(value: str) -> int:
    text = _loose_norm(value)
    return sum(1 for term in _CLIENT_SIGNAL_TERMS if term in text)


def _has_any(value: str, terms: Iterable[str]) -> bool:
    text = _loose_norm(value)
    tokens = set(text.split())
    for term in terms:
        normalized = _loose_norm(term)
        if not normalized:
            continue
        if normalized == "цена":
            if normalized in tokens or "цене" in tokens or "цену" in tokens or "цены" in tokens:
                return True
            continue
        if normalized in text:
            return True
    return False


def _quote_supported_by_context(quote: Any, context: Any) -> bool:
    quote_norm = _loose_norm(quote)
    context_norm = _loose_norm(context)
    if not quote_norm:
        return True
    if quote_norm in context_norm:
        return True
    quote_tokens = [token for token in quote_norm.split() if len(token) >= 3]
    if not quote_tokens:
        return False
    matched = sum(1 for token in quote_tokens if token in context_norm)
    return matched / len(quote_tokens) >= 0.6


def _has_internal_discussion_context(value: Any) -> bool:
    return _has_any(_loose_norm(value), _INTERNAL_DISCUSSION_TERMS)


def _has_unsupported_internal_discussion_claim(value: Any, *, evidence: Any) -> bool:
    text = _loose_norm(value)
    if not _has_any(text, _UNSUPPORTED_INTERNAL_ACTION_TERMS):
        return False
    return not _has_internal_discussion_context(evidence)


def _repair_callback_scene_without_internal_context(
    scene: dict[str, Any],
    *,
    evidence: Any,
) -> dict[str, Any]:
    if not _has_unsupported_internal_discussion_claim(
        " ".join(str(scene.get(key) or "") for key in ("customer_meaning", "manager_response", "why_action_follows")),
        evidence=evidence,
    ):
        return scene
    repaired = dict(scene)
    repaired["customer_meaning"] = _generic_meaning_for_category("timing_or_internal_discussion")
    repaired["manager_response"] = _action_for_signal("timing_or_internal_discussion", str(evidence or ""))
    repaired["why_action_follows"] = (
        "В репликах нет подтверждения внутреннего обсуждения; клиент только переносит инициативу на свой обратный звонок."
    )
    return repaired


def _normalize_speaker(value: Any) -> str:
    speaker = _text(value).lower()
    if speaker in {"client", "customer", "клиент"}:
        return "client"
    if speaker in {"manager", "seller", "agent", "менеджер", "оператор"}:
        return "manager"
    if speaker in {"context", "unknown", ""}:
        return speaker or "unknown"
    if speaker in {"side_1", "side 1", "сторона 1"}:
        return "side_1"
    if speaker in {"side_2", "side 2", "сторона 2"}:
        return "side_2"
    return speaker


def _infer_speaker(text: str) -> str:
    normalized = _loose_norm(text)
    if (
        "сама перезвоню" in normalized
        or "сам перезвоню" in normalized
        or "сама перезвонить" in normalized
        or "сам перезвонить" in normalized
        or ("я могу" in normalized and "вам перезвонить" in normalized)
    ):
        return "client"
    if normalized.startswith(("так то есть", "хорошо ну я понял", "хорошо тогда", "понял", "давайте я уточню")):
        return "manager"
    manager_terms = (
        "подскажите",
        "уточню",
        "отправлю",
        "меня зовут",
        "хотел спросить",
        "можно спросить",
        "а не подскажете",
    )
    client_terms = ("у нас", "нам", "я перезвоню", "скиньте", "интересно", "расскажите")
    manager_score = sum(1 for term in manager_terms if term in normalized)
    client_score = sum(1 for term in client_terms if term in normalized)
    if client_score > manager_score:
        return "client"
    if manager_score > client_score:
        return "manager"
    return "unknown"


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
        return "Compose Voice Of Customer as JSON. Use only provided customer signals."


def _extract_openai_message_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return str(content or "").strip()


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _word_count(value: Any) -> int:
    return len(re.findall(r"[a-zа-яё0-9]+", _text(value), flags=re.IGNORECASE))


def _has_cyrillic(value: Any) -> bool:
    return bool(re.search(r"[а-яё]", _text(value), flags=re.IGNORECASE))


def _manager_facing_russian_enough(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return cyrillic >= 20 and cyrillic >= latin


def _obj_get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _dict_get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _nested(mapping: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = mapping
    for key in path:
        current = _as_dict(current).get(key)
    return current


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            value = value.get("text") or value.get("summary") or value.get("value")
        text = _text(value)
        if text:
            return text
    return None


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clip(value: Any, *, limit: int) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].strip() + "..."


def _loose_norm(value: Any) -> str:
    return re.sub(r"[^0-9a-zа-я]+", " ", _text(value).lower().replace("ё", "е")).strip()


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = _text(value).replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
