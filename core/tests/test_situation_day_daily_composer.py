from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

for name in ("app", "app.agents", "app.agents.calls"):
    module = sys.modules.setdefault(name, types.ModuleType(name))
    module.__path__ = []  # type: ignore[attr-defined]

chat_compat = types.ModuleType("app.agents.calls.openai_chat_compat")
chat_compat.build_chat_completion_kwargs = lambda **kwargs: kwargs
sys.modules["app.agents.calls.openai_chat_compat"] = chat_compat

usage = types.ModuleType("app.agents.calls.openai_usage")
usage.extract_openai_usage_metadata = lambda response: {}
sys.modules["app.agents.calls.openai_usage"] = usage

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "situation_day_daily_composer.py"
SPEC = importlib.util.spec_from_file_location("situation_day_daily_composer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
situation_day_daily_composer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = situation_day_daily_composer
SPEC.loader.exec_module(situation_day_daily_composer)

compose_daily_situation_day = situation_day_daily_composer.compose_daily_situation_day
build_daily_situation_llm3_payload = (
    situation_day_daily_composer.build_daily_situation_llm3_payload
)


def _manager_gap(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "item_id": "gap-1",
        "call_id": "call-gap",
        "evidence_type": "manager_gap",
        "proof_strength": "strong",
        "case_status_candidate": "strong",
        "score": 84,
        "source": "report_evidence.manager_gap[0]",
        "stage_code": "completion_next_step",
        "situation_title": "Следующий шаг остался без управления",
        "moment_summary": "Клиент попросил КП, менеджер согласился отправить без уточнений.",
        "what_happened": "Клиент попросил КП, менеджер сразу согласился отправить материалы.",
        "manager_error": "Менеджер не уточнил критерии, срок и участников решения.",
        "evidence_scene": "Клиент: Отправьте КП. Менеджер: Да, отправлю в WhatsApp.",
        "supporting_quote": "Да, отправлю в WhatsApp.",
        "why_it_matters": "Сделка остается без понятного следующего шага.",
        "next_time_action": "Сначала уточнить задачу и закрепить дату возврата.",
        "scripts": ["Давайте уточню задачу и срок, чтобы КП было предметным."],
        "source_fact_ids": ["fact-gap-1"],
    }
    item.update(overrides)
    return item


def _customer_signal(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "item_id": "signal-1",
        "call_id": "call-signal",
        "evidence_type": "customer_signal",
        "proof_strength": "strong",
        "score": 99,
        "source": "report_evidence.voice_of_customer[0]",
        "stage_code": "completion_next_step",
        "situation_title": "Клиент проявил интерес",
        "moment_summary": "Клиент попросил отправить материалы.",
        "what_happened": "Клиент попросил КП и сказал, что посмотрит.",
        "manager_error": "Клиентский сигнал, не ошибка менеджера.",
        "evidence_scene": "Клиент: Скиньте КП, я посмотрю.",
        "supporting_quote": "Скиньте КП, я посмотрю.",
        "why_it_matters": "Есть интерес клиента.",
        "next_time_action": "Отправить материалы.",
        "scripts": ["Отправлю материалы."],
        "source_fact_ids": ["fact-signal-1"],
    }
    item.update(overrides)
    return item


def _llm3_response(candidate: dict[str, object], **overrides: object) -> dict[str, object]:
    stage_code = str(candidate.get("stage_code") or "")
    result: dict[str, object] = {
        "status": "verified",
        "case_status": "strong",
        "focus_case_selection": {
            "focus_stage_code": stage_code,
            "focus_stage_source": "score_by_stage.priority",
            "case_status": "strong",
            "selected_call_id": candidate["call_id"],
            "selected_case_stage_code": stage_code,
            "selection_reason": "best_available_focus_stage_case",
            "evidence_level": "strong",
            "wording_mode": "confident",
            "rejection_reasons": [],
        },
        "selected_call_id": candidate["call_id"],
        "situation_title": candidate["situation_title"],
        "moment_summary": candidate["moment_summary"],
        "what_happened": candidate["what_happened"],
        "call_context_summary": candidate.get("call_context_summary"),
        "manager_error": candidate["manager_error"],
        "stage_code": stage_code,
        "proof_type": candidate["proof_type"],
        "evidence_scene": candidate["evidence_scene"],
        "dialogue_turns": candidate["dialogue_turns"],
        "evidence_quotes": candidate["evidence_quotes"],
        "supporting_quote": candidate["supporting_quote"],
        "why_it_matters": candidate["why_it_matters"],
        "next_time_action": candidate["next_time_action"],
        "scripts": [
            "Давайте уточню задачу и срок, чтобы КП было предметным.",
            "Когда удобно вернуться к обсуждению после того, как вы посмотрите КП?",
        ],
        "call_breakdown_seed": {
            "call_id": candidate["call_id"],
            "stage_code": stage_code,
            "case_status": "strong",
        },
        "selection_reason": "best_available_focus_stage_case",
    }
    result.update(overrides)
    return result


class SituationDayDailyComposerTests(unittest.TestCase):
    def test_payload_keeps_only_manager_gap_candidates_for_llm3(self) -> None:
        payload = build_daily_situation_llm3_payload(
            {"evidence_items": [_customer_signal(score=100), _manager_gap(score=70)]}
        )

        self.assertEqual([item["call_id"] for item in payload["candidates"]], ["call-gap"])
        self.assertEqual(payload["candidates"][0]["evidence_type"], "manager_gap")

    def test_returns_insufficient_when_only_customer_signals(self) -> None:
        result = compose_daily_situation_day(
            {"evidence_items": [_customer_signal()]},
            llm3_enabled=False,
        )

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["case_status"], "weak_blocked")
        self.assertIsNone(result["selected_call_id"])
        self.assertEqual(result["selection_reason"], "no_manager_gap_scene")
        self.assertEqual(result["rejected_candidates"][0]["reason"], "customer_signal_forbidden")

    def test_without_llm3_returns_blocked_instead_of_deterministic_case(self) -> None:
        result = compose_daily_situation_day(
            {"routing": {"situation_day": [_manager_gap(scripts=[])]}},
            llm3_enabled=False,
        )

        required = {
            "status",
            "case_status",
            "focus_case_selection",
            "selected_call_id",
            "situation_title",
            "moment_summary",
            "what_happened",
            "manager_error",
            "evidence_scene",
            "supporting_quote",
            "why_it_matters",
            "next_time_action",
            "scripts",
            "rejected_candidates",
            "selection_reason",
            "source_fact_ids",
            "diagnostics",
        }
        self.assertTrue(required.issubset(result.keys()))
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["case_status"], "weak_blocked")
        self.assertEqual(result["selection_reason"], "llm3_focus_case_selection_unavailable")
        self.assertEqual(result["scripts"], [])

    def test_llm3_payload_includes_contract_and_no_full_transcript(self) -> None:
        payload = build_daily_situation_llm3_payload(
            {
                "daily_focus": {"stage_code": "completion_next_step"},
                "evidence_items": [_manager_gap()],
                "transcript": "Клиент: полный текст не должен попасть в payload",
                "analysis": {"full_call_analysis": "не должен попасть"},
            }
        )

        candidates_text = str(payload["candidates"]).lower()
        self.assertNotIn("полный текст", candidates_text)
        self.assertNotIn("не должен попасть", candidates_text)
        forbidden = " ".join(payload["forbidden"]).lower()
        self.assertIn("do not recalculate scores", forbidden)
        self.assertIn("do not perform full call analysis", forbidden)
        self.assertIn("do not select a visible case outside daily_focus.stage_code", forbidden)
        self.assertEqual(payload["focus_case_selection_contract"]["visible_case_status"], ["strong", "workable"])

    def test_reads_day_level_calls_package_from_input_builder(self) -> None:
        payload = build_daily_situation_llm3_payload(
            {
                "calls": [
                    {
                        "call_id": "call-from-builder",
                        "score": 42,
                        "manager_gaps": ["Менеджер не закрепил дату следующего контакта."],
                        "evidence_scenes": [
                            {
                                "source": "report_evidence.manager_coaching_moments",
                                "evidence_type": "manager_gap",
                                "proof_type": "sequence_inference",
                                "proof_strength": "strong",
                                "stage_code": "completion_next_step",
                                "quote": "Хорошо, отправлю вам информацию.",
                                "turns": [
                                    {"speaker": "client", "text": "Скиньте условия, я посмотрю."},
                                    {"speaker": "manager", "text": "Хорошо, отправлю вам информацию."},
                                ],
                                "next_time_action": "Согласовать дату возврата к вопросу.",
                            }
                        ],
                        "source_fact_ids": ["fact-from-builder"],
                    }
                ]
            }
        )

        candidate = payload["candidates"][0]
        self.assertEqual(candidate["call_id"], "call-from-builder")
        self.assertEqual(candidate["stage_code"], "completion_next_step")
        self.assertEqual(candidate["proof_type"], "sequence_inference")
        self.assertIn("Клиент:", candidate["evidence_scene"])
        self.assertEqual(candidate["source_fact_ids"], ["fact-from-builder"])

    def test_llm3_decision_selects_score_priority_stage_case(self) -> None:
        original_request = situation_day_daily_composer._request_llm3_daily_situation

        def fake_request(payload):
            candidate = next(item for item in payload["candidates"] if item["call_id"] == "call-objection")
            return _llm3_response(candidate)

        try:
            situation_day_daily_composer._request_llm3_daily_situation = fake_request
            result = compose_daily_situation_day(
                {
                    "daily_focus": {"stage_code": "objection_handling"},
                    "evidence_items": [
                        _manager_gap(
                            call_id="call-next-step",
                            score=99,
                            stage_code="completion_next_step",
                        ),
                        _manager_gap(
                            call_id="call-objection",
                            score=50,
                            stage_code="objection_handling",
                            manager_error="Менеджер не уточнил, что именно смущает клиента в цене.",
                        ),
                    ],
                },
                llm3_enabled=True,
            )
        finally:
            situation_day_daily_composer._request_llm3_daily_situation = original_request

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["case_status"], "strong")
        self.assertEqual(result["selected_call_id"], "call-objection")
        self.assertEqual(result["stage_code"], "objection_handling")
        self.assertEqual(result["focus_case_selection"]["selected_case_stage_code"], "objection_handling")

    def test_payload_does_not_filter_out_candidates_before_llm3_decision(self) -> None:
        payload = build_daily_situation_llm3_payload(
            {
                "daily_focus": {"stage_code": "objection_handling"},
                "evidence_items": [
                    _manager_gap(call_id="call-next-step", score=99, stage_code="completion_next_step"),
                    _manager_gap(call_id="call-objection", score=50, stage_code="objection_handling"),
                ],
            }
        )

        self.assertEqual(payload["focus_candidate_count"], 1)
        self.assertEqual(
            {item["call_id"] for item in payload["candidates"]},
            {"call-next-step", "call-objection"},
        )

    def test_llm3_related_stage_visible_case_becomes_blocked_mismatch(self) -> None:
        original_request = situation_day_daily_composer._request_llm3_daily_situation

        def fake_request(payload):
            candidate = payload["candidates"][0]
            response = _llm3_response(candidate)
            response["focus_case_selection"] = {
                **response["focus_case_selection"],
                "focus_stage_code": "needs_discovery",
                "selected_case_stage_code": "qualification_primary",
                "selection_reason": "wrong_stage_candidate",
            }
            return response

        try:
            situation_day_daily_composer._request_llm3_daily_situation = fake_request
            result = compose_daily_situation_day(
                {
                    "daily_focus": {"stage_code": "needs_discovery"},
                    "evidence_items": [
                        _manager_gap(
                            call_id="call-qualification",
                            stage_code="qualification_primary",
                            manager_error="Менеджер не уточнил роль собеседника.",
                        )
                    ],
                },
                llm3_enabled=True,
            )
        finally:
            situation_day_daily_composer._request_llm3_daily_situation = original_request

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["case_status"], "blocked_mismatch")
        self.assertIsNone(result["selected_call_id"])
        self.assertEqual(result["focus_case_selection"]["focus_stage_code"], "needs_discovery")
        self.assertEqual(result["focus_case_selection"]["selected_case_stage_code"], "qualification_primary")

    def test_llm3_weak_blocked_decision_is_preserved(self) -> None:
        original_request = situation_day_daily_composer._request_llm3_daily_situation

        def fake_request(payload):
            return {
                "status": "insufficient",
                "case_status": "weak_blocked",
                "focus_case_selection": {
                    "focus_stage_code": "needs_discovery",
                    "focus_stage_source": "score_by_stage.priority",
                    "case_status": "weak_blocked",
                    "selected_call_id": None,
                    "selected_case_stage_code": None,
                    "selection_reason": "no_readable_focus_stage_scene",
                    "evidence_level": "weak",
                    "wording_mode": "blocked",
                    "rejection_reasons": ["no_readable_focus_stage_scene"],
                },
                "selected_call_id": None,
                "selection_reason": "no_readable_focus_stage_scene",
            }

        try:
            situation_day_daily_composer._request_llm3_daily_situation = fake_request
            result = compose_daily_situation_day(
                {
                    "daily_focus": {"stage_code": "needs_discovery"},
                    "evidence_items": [
                        _manager_gap(
                            call_id="call-qualification",
                            stage_code="qualification_primary",
                        )
                    ],
                },
                llm3_enabled=True,
            )
        finally:
            situation_day_daily_composer._request_llm3_daily_situation = original_request

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["case_status"], "weak_blocked")
        self.assertEqual(result["wording_mode"], "blocked")

    def test_no_deterministic_related_stage_selection_when_llm3_disabled(self) -> None:
        result = compose_daily_situation_day(
            {
                "daily_focus": {"stage_code": "needs_discovery"},
                "evidence_items": [
                    _manager_gap(
                        call_id="call-qualification",
                        stage_code="qualification_primary",
                    )
                ],
            },
            llm3_enabled=False,
        )

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["case_status"], "weak_blocked")
        self.assertIsNone(result["selected_call_id"])
        self.assertEqual(result["selection_reason"], "llm3_focus_case_selection_unavailable")
        self.assertEqual(result["diagnostics"]["daily_focus"]["stage_code"], "needs_discovery")
        self.assertEqual(result["diagnostics"]["focus_eligible_count"], 0)
        self.assertFalse(result["diagnostics"]["focus_fallback_used"])

    def test_llm3_generic_next_step_rewrite_is_rejected_without_fallback_case(self) -> None:
        original_request = situation_day_daily_composer._request_llm3_daily_situation

        def fake_request(payload):
            candidate = payload["candidates"][0]
            return _llm3_response(
                candidate,
                situation_title="Закрепить следующий шаг конкретнее",
                manager_error="Следующий шаг не был закреплен достаточно конкретно по владельцу и сроку.",
                next_time_action="В конце разговора назвать действие, владельца и точное время.",
                scripts=[
                    "Давайте зафиксируем следующий шаг.",
                    "Когда я могу вернуться к вам?",
                ],
            )

        try:
            situation_day_daily_composer._request_llm3_daily_situation = fake_request
            result = compose_daily_situation_day(
                {
                    "daily_focus": {"stage_code": "objection_handling"},
                    "evidence_items": [
                        _manager_gap(
                            call_id="call-objection",
                            stage_code="objection_handling",
                            situation_title="Возражение по цене осталось неразобранным",
                            manager_error="Менеджер не уточнил, что именно смущает клиента в цене.",
                            next_time_action="Сначала уточнить, что именно кажется дорогим.",
                            scripts=["Что именно в цене вызывает сомнение: бюджет или сравнение?"],
                        )
                    ],
                },
                llm3_enabled=True,
            )
        finally:
            situation_day_daily_composer._request_llm3_daily_situation = original_request

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["selection_reason"], "llm3_focus_case_selection_unavailable")
        self.assertEqual(
            result["diagnostics"]["llm3"]["llm3_rejection_reason"],
            "llm3_output_replaced_focus_with_generic_next_step",
        )

    def test_llm3_stage_or_proof_label_rewrite_is_corrected_to_selected_candidate(self) -> None:
        original_request = situation_day_daily_composer._request_llm3_daily_situation

        def fake_request(payload):
            candidate = payload["candidates"][0]
            return _llm3_response(
                candidate,
                stage_code="completion_next_step",
                proof_type="direct_quote",
                selection_reason="llm3_rewrote_stage_and_proof",
            )

        try:
            situation_day_daily_composer._request_llm3_daily_situation = fake_request
            result = compose_daily_situation_day(
                {
                    "daily_focus": {"stage_code": "objection_handling"},
                    "evidence_items": [
                        _manager_gap(
                            call_id="call-objection",
                            stage_code="objection_handling",
                            proof_type="sequence_inference",
                            manager_error="Менеджер не уточнил, что именно смущает клиента в цене.",
                        )
                    ],
                },
                llm3_enabled=True,
            )
        finally:
            situation_day_daily_composer._request_llm3_daily_situation = original_request

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["selection_reason"], "llm3_rewrote_stage_and_proof")
        self.assertEqual(result["stage_code"], "objection_handling")
        self.assertEqual(result["proof_type"], "sequence_inference")
        self.assertTrue(result["diagnostics"]["stage_code_corrected_to_candidate"])
        self.assertTrue(result["diagnostics"]["proof_type_corrected_to_candidate"])

    def test_llm3_simulated_json_preserves_daily_normalizer_and_routing_diagnostics(self) -> None:
        original_request = situation_day_daily_composer._request_llm3_daily_situation

        def fake_request(payload):
            candidate = payload["candidates"][0]
            response = _llm3_response(
                candidate,
                selection_reason="llm3_simulation_selected_manager_gap",
            )
            response["_routing"] = {
                "layer": "llm3",
                "request_kind": "situation_day_daily_composer",
                "execution_status": "simulated",
                "simulated": True,
                "simulation_run_id": "composer-test-run",
                "input_artifact": "/tmp/asa_llm_sim_runs/composer-test-run/llm3_situation_day_input.json",
                "output_artifact": "/tmp/asa_llm_sim_runs/composer-test-run/llm3_situation_day_output.json",
            }
            return response

        try:
            situation_day_daily_composer._request_llm3_daily_situation = fake_request
            result = compose_daily_situation_day(
                {
                    "daily_focus": {"stage_code": "completion_next_step"},
                    "evidence_items": [_manager_gap()],
                },
                llm3_enabled=True,
            )
        finally:
            situation_day_daily_composer._request_llm3_daily_situation = original_request

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["selection_reason"], "llm3_simulation_selected_manager_gap")
        llm3_diagnostics = result["diagnostics"]["llm3"]
        self.assertTrue(llm3_diagnostics["llm3_used"])
        self.assertEqual(llm3_diagnostics["llm3_routing"]["execution_status"], "simulated")
        self.assertIn("/tmp/asa_llm_sim_runs/", llm3_diagnostics["llm3_routing"]["input_artifact"])


if __name__ == "__main__":
    unittest.main()
