from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "call_breakdown_composer.py"
PROMPT_PATH = CORE_ROOT / "app" / "agents" / "calls" / "prompts" / "call_breakdown_composer_v2.md"


def _load_call_breakdown_composer_module():
    if not MODULE_PATH.exists():
        raise AssertionError(f"Missing implementation module: {MODULE_PATH}")
    spec = importlib.util.spec_from_file_location("call_breakdown_composer", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _eldar_b2b_inputs(call_id: str) -> dict:
    selected_call = {
        "call_id": call_id,
        "client_label": "Эльдар",
        "client_phone": "+77070000000",
        "date_label": "14.05.2026",
        "time_label": "09:48",
        "client_call_reference": "Эльдар • 14.05.2026 • 09:48",
        "stage_code": "completion_next_step",
        "stage_name": "Завершение и следующий шаг",
    }
    transcript_scenes = [
        {
            "scene_id": "requirements",
            "call_id": call_id,
            "stage_code": "needs_discovery",
            "purpose": "requirements",
            "summary": (
                "Клиент описал сеть из 16 школ, общий кабинет, роли и доступы "
                "для разных школ и головного офиса."
            ),
            "turns": [
                {
                    "speaker": "client",
                    "text": (
                        "У нас сеть частных школ, всего 16 школ по Казахстану. "
                        "Каждая школа как отдельное юрлицо, но нужен общий кабинет."
                    ),
                    "start_sec": 48,
                    "end_sec": 63,
                },
                {
                    "speaker": "client",
                    "text": (
                        "Директора и сотрудники одной школы не должны видеть "
                        "договоры другой школы, а головной офис должен видеть все договора."
                    ),
                    "start_sec": 64,
                    "end_sec": 83,
                },
                {
                    "speaker": "manager",
                    "text": "Да, понял, доступы можно разграничить.",
                    "start_sec": 84,
                    "end_sec": 89,
                },
            ],
            "evidence_refs": [
                {
                    "ref_id": "requirements:16-schools-access",
                    "call_id": call_id,
                    "scene_id": "requirements",
                    "turn_indexes": [0, 1, 2],
                    "quote": (
                        "У нас сеть частных школ, всего 16 школ по Казахстану. "
                        "Каждая школа как отдельное юрлицо, но нужен общий кабинет."
                    ),
                }
            ],
        },
        {
            "scene_id": "closing",
            "call_id": call_id,
            "stage_code": "completion_next_step",
            "purpose": "next_step",
            "summary": (
                "После сложного запроса менеджер завершил разговор общим обещанием "
                "уточнить техническую схему и перезвонить."
            ),
            "turns": [
                {
                    "speaker": "client",
                    "text": (
                        "Нам важно подписывать через ЭЦП, потому что по SMS могут "
                        "быть юридические риски."
                    ),
                    "start_sec": 116,
                    "end_sec": 130,
                },
                {
                    "speaker": "manager",
                    "text": "Давайте сейчас уточню техническую схему и перезвоню.",
                    "start_sec": 131,
                    "end_sec": 138,
                },
                {
                    "speaker": "client",
                    "text": "Хорошо, тогда жду от вас обратную связь.",
                    "start_sec": 139,
                    "end_sec": 144,
                },
            ],
            "evidence_refs": [
                {
                    "ref_id": "closing:vague-clarify-callback",
                    "call_id": call_id,
                    "scene_id": "closing",
                    "turn_indexes": [0, 1, 2],
                    "quote": "Давайте сейчас уточню техническую схему и перезвоню.",
                }
            ],
        },
    ]
    situation_evidence_packet = {
        "status": "verified",
        "call_id": call_id,
        "problem_title": "Сложный B2B-запрос не переведен в управляемый следующий шаг",
        "client_context": (
            "Эльдар описал сеть из 16 школ, общий кабинет, разграничение доступов "
            "по школам и головной офис с доступом ко всем договорам."
        ),
        "observed_manager_behavior": (
            "Менеджер подтвердил, что доступы можно разграничить, но не резюмировал "
            "требования и закончил обещанием уточнить техническую схему."
        ),
        "missing_action": (
            "Не было резюме требований, уточнения ролей и назначения демо или "
            "созвона с конкретной целью."
        ),
        "causal_link": (
            "Такой запрос нужно вести как проектную продажу; иначе клиент получает "
            "общий ответ вместо понятного плана внедрения."
        ),
        "manager_lesson": (
            "Резюмировать требования клиента и закрепить следующий шаг: демо или "
            "созвон по общему кабинету, ролям доступа и ЭЦП."
        ),
        "dialogue_excerpt": {"call_id": call_id, "turns": transcript_scenes[0]["turns"] + transcript_scenes[1]["turns"]},
        "proof_type": "sequence_inference",
        "proof_strength": "strong",
    }
    llm2_facts = {
        "business_outcome": "Клиенту нужен корпоративный сценарий ЭДО для сети школ.",
        "call_report_summary": (
            "Клиент описал сложную структуру доступа, менеджер пообещал уточнить "
            "техническую схему."
        ),
        "score_by_stage": [
            {"stage_code": "needs_discovery", "stage_name": "Выявление потребности", "score": 62},
            {"stage_code": "completion_next_step", "stage_name": "Завершение и следующий шаг", "score": 48},
        ],
        "report_evidence": {},
        "semantic_case": {},
        "manager_coaching_moments": [],
        "block_candidates": {},
    }
    return {
        "selected_call": selected_call,
        "transcript_scenes": transcript_scenes,
        "situation_evidence_packet": situation_evidence_packet,
        "llm2_facts": llm2_facts,
    }


def _simple_followup_inputs(call_id: str) -> dict:
    selected_call = {
        "call_id": call_id,
        "client_label": "Айгуль",
        "client_phone": "+77071112233",
        "date_label": "14.05.2026",
        "time_label": "11:20",
        "client_call_reference": "Айгуль • 14.05.2026 • 11:20",
        "stage_code": "completion_next_step",
        "stage_name": "Завершение и следующий шаг",
    }
    turns = [
        {
            "speaker": "client",
            "text": "Мне нужно понять стоимость и когда можно начать работу.",
        },
        {
            "speaker": "manager",
            "text": "Я уточню расчет и завтра вам перезвоню.",
        },
        {
            "speaker": "client",
            "text": "Хорошо, буду ждать вашего звонка.",
        },
    ]
    transcript_scenes = [
        {
            "scene_id": "closing",
            "call_id": call_id,
            "stage_code": "completion_next_step",
            "purpose": "next_step",
            "summary": "Клиент попросил стоимость и срок старта, менеджер ответил общим обещанием перезвонить завтра.",
            "turns": turns,
            "evidence_refs": [
                {
                    "ref_id": "closing:vague-callback",
                    "call_id": call_id,
                    "scene_id": "closing",
                    "turn_indexes": [0, 1, 2],
                    "quote": "Я уточню расчет и завтра вам перезвоню.",
                }
            ],
        }
    ]
    situation_evidence_packet = {
        "status": "verified",
        "call_id": call_id,
        "problem_title": "Следующий шаг остался общим",
        "client_context": "Клиент спросил стоимость и срок начала работы.",
        "observed_manager_behavior": "Менеджер ответил общим обещанием уточнить расчет и перезвонить завтра.",
        "missing_action": "Не был назван точный срок возврата, формат продолжения и что именно клиент получит.",
        "causal_link": "Без конкретного следующего шага клиент не понимает, когда и с чем менеджер вернется.",
        "manager_lesson": "Закрывать разговор конкретным временем, результатом и форматом продолжения.",
        "dialogue_excerpt": {"call_id": call_id, "turns": turns},
        "proof_type": "sequence_inference",
        "proof_strength": "medium",
    }
    llm2_facts = {
        "business_outcome": "Клиент ждет расчет стоимости и срок старта.",
        "call_report_summary": "Менеджер пообещал уточнить и перезвонить, но не закрепил конкретику.",
        "score_by_stage": [
            {"stage_code": "completion_next_step", "stage_name": "Завершение и следующий шаг", "score": 52}
        ],
    }
    return {
        "selected_call": selected_call,
        "transcript_scenes": transcript_scenes,
        "situation_evidence_packet": situation_evidence_packet,
        "llm2_facts": llm2_facts,
    }


class CallBreakdownComposerPromptTests(unittest.TestCase):
    def test_prompt_contract_requires_grounding_and_non_duplication(self) -> None:
        text = PROMPT_PATH.read_text(encoding="utf-8")

        self.assertIn("1 to 4", text)
        self.assertIn("evidence_refs", text)
        self.assertIn("Do not invent", text)
        self.assertIn("Do not duplicate Situation Day", text)
        self.assertIn("mini-scene", text)
        self.assertIn("Narrative Rules", text)
        self.assertIn("Compatibility Rows", text)
        self.assertIn("call_story", text)
        self.assertIn("key_turning_points", text)
        self.assertIn("must not become a second", text)
        self.assertIn("call\nwalkthrough", text)
        self.assertIn("Treat `transcript_scenes` as the main evidence source", text)
        self.assertIn("report_evidence.call_breakdown_composer.v2", text)


class CallBreakdownComposerTests(unittest.TestCase):
    def test_eldar_b2b_call_builds_grounded_multi_moment_breakdown(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        inputs = _eldar_b2b_inputs(call_id)

        result = module.compose_call_breakdown(
            selected_call=inputs["selected_call"],
            transcript_scenes=inputs["transcript_scenes"],
            situation_evidence_packet=inputs["situation_evidence_packet"],
            llm2_facts=inputs["llm2_facts"],
            llm3_enabled=False,
        )

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["call_id"], call_id)
        self.assertEqual(result["call_breakdown_source"], "report_evidence.call_breakdown_composer.v2")
        self.assertEqual(result["source_note"], "report_evidence.call_breakdown_composer.v2")

        moments = result.get("moments") or []
        rows = result.get("rows") or []
        self.assertGreaterEqual(len(moments), 2)
        self.assertLessEqual(len(moments), 4)
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(all(moment.get("call_id") == call_id for moment in moments))
        self.assertTrue(all(moment.get("evidence_refs") for moment in moments))

        rendered_rows = " ".join(" ".join(map(str, row)) for row in rows).lower()
        self.assertIn("16 школ", rendered_rows)
        self.assertIn("общий кабинет", rendered_rows)
        self.assertIn("доступ", rendered_rows)
        self.assertIn("давайте сейчас уточню", rendered_rows)
        self.assertRegex(rendered_rows, r"резюм|правильно понял")
        self.assertRegex(rendered_rows, r"демо|созвон")
        self.assertNotIn("coachable-момент", rendered_rows)

        situation_title = inputs["situation_evidence_packet"]["problem_title"].lower()
        moment_whats = [str(row[1] if len(row) > 1 else "").lower().strip() for row in rows]
        self.assertNotIn(situation_title, moment_whats)

    def test_deterministic_non_b2b_rows_do_not_render_meta_coachable_wording(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        selected_call = {
            "call_id": call_id,
            "client_label": "Айгуль",
            "client_call_reference": "Айгуль • 14.05.2026 • 11:20",
            "stage_code": "completion_next_step",
            "stage_name": "Завершение и следующий шаг",
        }
        transcript_scenes = [
            {
                "scene_id": "closing",
                "call_id": call_id,
                "purpose": "next_step",
                "turns": [
                    {
                        "speaker": "client",
                        "text": "Мне нужно понять стоимость и когда можно начать.",
                    },
                    {
                        "speaker": "manager",
                        "text": "Я уточню и позже вам перезвоню.",
                    },
                    {
                        "speaker": "client",
                        "text": "Хорошо, буду ждать.",
                    },
                ],
            }
        ]
        situation_evidence_packet = {
            "status": "verified",
            "call_id": call_id,
            "problem_title": "Следующий шаг остался общим",
            "client_context": "Клиент спросил стоимость и срок начала работы.",
            "observed_manager_behavior": "Менеджер ответил общим обещанием уточнить и перезвонить.",
            "missing_action": "не был назван срок возврата и конкретный формат продолжения",
            "causal_link": "Без срока клиент не понимает, когда ждать ответ.",
            "manager_lesson": "вернуться сегодня до 17:00 с расчетом стоимости",
            "dialogue_excerpt": {"call_id": call_id, "turns": transcript_scenes[0]["turns"]},
            "proof_type": "direct_quote",
            "proof_strength": "medium",
        }

        result = module.compose_call_breakdown(
            selected_call=selected_call,
            transcript_scenes=transcript_scenes,
            situation_evidence_packet=situation_evidence_packet,
            llm2_facts={"score_by_stage": []},
            llm3_enabled=False,
        )

        rendered_rows = " ".join(" ".join(map(str, row)) for row in result.get("rows") or []).lower()
        self.assertNotIn("coachable-момент", rendered_rows)
        self.assertIn("срок", rendered_rows)
        self.assertIn("сегодня до 17:00", rendered_rows)

    def test_llm3_payload_preserves_selected_verified_call_scope(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        inputs = _eldar_b2b_inputs(call_id)

        payload = module.build_call_breakdown_llm3_payload(
            selected_call=inputs["selected_call"],
            transcript_scenes=inputs["transcript_scenes"],
            situation_evidence_packet=inputs["situation_evidence_packet"],
            llm2_facts=inputs["llm2_facts"],
        )

        self.assertEqual(payload["contract_version"], "call_breakdown_composer_v2")
        self.assertEqual(payload["selected_call"]["call_id"], call_id)
        self.assertEqual(payload["situation_evidence_packet"]["call_id"], call_id)
        self.assertTrue(payload["transcript_scenes"])
        self.assertTrue(
            all(scene.get("call_id") == call_id for scene in payload["transcript_scenes"])
        )
        self.assertTrue(payload["composition_rules"]["complex_b2b_detected"])
        self.assertEqual(payload["composition_rules"]["verified_min_moments"], 2)
        self.assertEqual(payload["composition_rules"]["verified_target_moments"], 3)
        self.assertIn("required_output_keys", payload)
        self.assertTrue(payload["composition_rules"]["narrative_preferred"])

    def test_llm3_payload_contains_bounded_facts_and_proof_cards_not_legacy_soup(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        inputs = _simple_followup_inputs(call_id)
        llm2_facts = {
            **inputs["llm2_facts"],
            "full_transcript": "RAW FULL TRANSCRIPT MUST NOT REACH LLM3",
            "report_evidence": {
                "block_candidates": {"legacy": "LEGACY SOUP MUST NOT REACH LLM3"},
                "proof_cards": [
                    {
                        "proof_id": "proof-1",
                        "claim_id": "claim-1",
                        "stage_code": "completion_next_step",
                        "claim": "Следующий шаг не закреплен конкретно.",
                        "proof_status": "proven",
                        "proof_type": "sequence_inference",
                        "evidence_quote": "Я уточню расчет и завтра вам перезвоню.",
                    }
                ],
            },
        }

        payload = module.build_call_breakdown_llm3_payload(
            selected_call=inputs["selected_call"],
            transcript_scenes=inputs["transcript_scenes"],
            situation_evidence_packet=inputs["situation_evidence_packet"],
            llm2_facts=llm2_facts,
        )

        payload_text = str(payload)
        self.assertNotIn("RAW FULL TRANSCRIPT", payload_text)
        self.assertNotIn("LEGACY SOUP", payload_text)
        self.assertEqual(payload["llm2_facts"]["proof_cards"][0]["proof_id"], "proof-1")
        self.assertEqual(payload["llm2_facts"]["proof_cards"][0]["proof_status"], "proven")
        self.assertTrue(payload["composition_rules"]["llm2_facts_are_bounded"])

    def test_llm3_payload_allows_one_grounded_moment_for_simple_call(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        inputs = _simple_followup_inputs(call_id)

        payload = module.build_call_breakdown_llm3_payload(
            selected_call=inputs["selected_call"],
            transcript_scenes=inputs["transcript_scenes"],
            situation_evidence_packet=inputs["situation_evidence_packet"],
            llm2_facts=inputs["llm2_facts"],
        )

        self.assertFalse(payload["composition_rules"]["complex_b2b_detected"])
        self.assertEqual(payload["composition_rules"]["verified_min_moments"], 1)

    def test_llm3_single_simple_moment_is_accepted(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        inputs = _simple_followup_inputs(call_id)

        def fake_request(_payload):
            fragment = module._join_turns(inputs["transcript_scenes"][0]["turns"])
            return {
                "status": "verified",
                "call_id": call_id,
                "rows": [
                    [
                        "Момент 1 - Общий следующий шаг",
                        "Что было не так: Менеджер не закрепил точное время возврата и результат для клиента.",
                        f"Фрагмент: {fragment}",
                        "Сказать: завтра до 12:00 вернусь с расчетом стоимости и предложу время короткого созвона.",
                    ],
                ],
                "moments": [
                    {
                        "moment": "Момент 1 - Общий следующий шаг",
                        "call_id": call_id,
                        "what": "Менеджер не закрепил точное время возврата и результат для клиента.",
                        "moment_summary": "Следующий шаг остался общим обещанием.",
                        "supporting_quote": fragment,
                        "better": "Сказать: завтра до 12:00 вернусь с расчетом стоимости и предложу время короткого созвона.",
                        "proof_type": "sequence_inference",
                        "proof_explanation": "В мини-сцене клиент ждет расчет, а менеджер обещает перезвонить без времени и результата.",
                        "evidence_refs": inputs["transcript_scenes"][0]["evidence_refs"],
                    },
                ],
                "_routing": {
                    "layer": "llm3",
                    "request_kind": "call_breakdown_composer",
                    "execution_status": "simulated",
                    "simulated": True,
                    "simulation_run_id": "composer-test-run",
                    "input_artifact": "/tmp/asa_llm_sim_runs/composer-test-run/llm3_call_breakdown_input.json",
                    "output_artifact": "/tmp/asa_llm_sim_runs/composer-test-run/llm3_call_breakdown_output.json",
                },
            }

        module._request_llm3_call_breakdown = fake_request
        result = module.compose_call_breakdown(
            selected_call=inputs["selected_call"],
            transcript_scenes=inputs["transcript_scenes"],
            situation_evidence_packet=inputs["situation_evidence_packet"],
            llm2_facts=inputs["llm2_facts"],
            llm3_enabled=True,
        )

        self.assertTrue(result["selection_diagnostics"]["llm3_used"])
        self.assertFalse(result["selection_diagnostics"]["deterministic_fallback_used"])
        self.assertEqual(len(result["rows"]), 1)
        self.assertTrue(result.get("call_story"))
        self.assertTrue(result.get("key_turning_points"))
        self.assertIn("завтра до 12:00", result["rows"][0][3])
        self.assertEqual(
            result["selection_diagnostics"]["llm3_routing"]["execution_status"],
            "simulated",
        )

    def test_llm3_breakdown_without_grounded_fragment_or_proof_id_falls_back(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        inputs = _simple_followup_inputs(call_id)
        invented_fragment = (
            "Клиент: Нам нужен другой продукт, которого нет в исходных сценах. "
            "Менеджер: Тогда я обещаю подготовить специальный договор завтра. "
            "Клиент: Жду договор и отдельную скидку, хотя этого не было в payload."
        )

        def fake_request(_payload):
            return {
                "status": "verified",
                "call_id": call_id,
                "call_story": "Модель пытается построить уверенный разбор на неподтвержденном фрагменте.",
                "what_manager_missed": "Менеджер якобы не закрепил специальный договор.",
                "better_path": "Нужно якобы обещать отдельную скидку.",
                "rows": [
                    [
                        "Момент 1 - Неподтвержденный фрагмент",
                        "Что было не так: Разбор опирается на фразу, которой нет во входных сценах.",
                        f"Фрагмент: {invented_fragment}",
                        "Сказать: вернуться со специальным договором и скидкой.",
                    ],
                ],
                "moments": [
                    {
                        "moment": "Момент 1 - Неподтвержденный фрагмент",
                        "call_id": call_id,
                        "what": "Разбор опирается на фразу, которой нет во входных сценах.",
                        "moment_summary": "Неподтвержденный фрагмент не должен стать уверенным разбором.",
                        "supporting_quote": invented_fragment,
                        "better": "Сказать: вернуться со специальным договором и скидкой.",
                        "proof_type": "sequence_inference",
                        "proof_explanation": "Нет proof_id и grounded fragment.",
                        "evidence_refs": [{"source": "llm3_untrusted"}],
                    },
                ],
            }

        module._request_llm3_call_breakdown = fake_request
        result = module.compose_call_breakdown(
            selected_call=inputs["selected_call"],
            transcript_scenes=inputs["transcript_scenes"],
            situation_evidence_packet=inputs["situation_evidence_packet"],
            llm2_facts=inputs["llm2_facts"],
            llm3_enabled=True,
        )

        diagnostics = result["selection_diagnostics"]
        self.assertTrue(diagnostics["deterministic_fallback_used"])
        self.assertFalse(diagnostics["llm3_used"])
        self.assertEqual(
            diagnostics["llm3"]["llm3_rejection_reason"],
            "row_1_ungrounded_proof_fragment",
        )

    def test_weak_llm3_b2b_breakdown_falls_back_to_deterministic_result(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        inputs = _eldar_b2b_inputs(call_id)

        def fake_request(_payload):
            return {
                "status": "verified",
                "call_id": call_id,
                "rows": [
                    [
                        "Момент 1 - Требования",
                        "Менеджер не резюмировал требования.",
                        "Фрагмент: А, 16 школ нужно?",
                        "Сказать: резюмировать требования.",
                    ],
                ],
                "moments": [
                    {
                        "moment": "Момент 1 - Требования",
                        "call_id": call_id,
                        "what": "Менеджер не резюмировал требования.",
                        "moment_summary": "Пробел в фиксации требований.",
                        "supporting_quote": "А, 16 школ нужно?",
                        "better": "Сказать: резюмировать требования.",
                        "proof_type": "sequence_inference",
                        "proof_explanation": "Фраза показывает незакрепленный контекст.",
                        "evidence_refs": [{"quote": "А, 16 школ нужно?"}],
                    },
                ],
            }

        module._request_llm3_call_breakdown = fake_request
        result = module.compose_call_breakdown(
            selected_call=inputs["selected_call"],
            transcript_scenes=inputs["transcript_scenes"],
            situation_evidence_packet=inputs["situation_evidence_packet"],
            llm2_facts=inputs["llm2_facts"],
            llm3_enabled=True,
        )

        diagnostics = result["selection_diagnostics"]
        self.assertTrue(diagnostics["deterministic_fallback_used"])
        self.assertFalse(diagnostics["llm3_used"])
        self.assertEqual(
            diagnostics["llm3"]["llm3_rejection_reason"],
            "complex_b2b_requires_two_moments",
        )
        self.assertGreaterEqual(len(result["rows"]), 3)

    def test_segment_scenes_expand_beyond_situation_excerpt(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        artifact = SimpleNamespace(
            interaction=SimpleNamespace(
                metadata_={
                    "segments": [
                        {
                            "speaker": "A",
                            "text": "Смотрите, у нас сеть частных школ и мы рассматриваем подписание через ЭЦП.",
                            "start_ms": 0,
                            "end_ms": 8000,
                        },
                        {
                            "speaker": "A",
                            "text": "Понял. А вообще сколько у вас примерно документов в месяц?",
                            "start_ms": 8000,
                            "end_ms": 13000,
                        },
                        {
                            "speaker": "A",
                            "text": "Нам нужно, чтобы каждая школа была в общем кабинете и головной офис видел все договора.",
                            "start_ms": 13000,
                            "end_ms": 22000,
                        },
                        {
                            "speaker": "A",
                            "text": "Давайте сейчас уточню и перезвоню.",
                            "start_ms": 22000,
                            "end_ms": 26000,
                        },
                    ]
                }
            )
        )

        artifact_turns = module._turns_from_artifact_segments(artifact)
        scenes = module._transcript_scenes_from_packet(
            call_id=call_id,
            stage_code="completion_next_step",
            context_text="Клиент описал сеть школ, общий кабинет и доступы.",
            turns=[{"speaker": "context", "text": "Давайте сейчас уточню."}],
            packet={"dialogue_excerpt": {"turns": [{"speaker": "context", "text": "Давайте сейчас уточню."}]}},
            artifact_turns=artifact_turns,
        )

        purposes = {scene.get("purpose") for scene in scenes}
        self.assertIn("discovery", purposes)
        self.assertIn("requirements", purposes)
        self.assertIn("next_step", purposes)
        self.assertGreaterEqual(len(module._turns_from_scenes(scenes)), 4)
        self.assertTrue(
            all(
                turn.get("speaker") == "unknown"
                for turn in artifact_turns
            )
        )

    def test_llm3_short_fragment_is_repaired_from_transcript_scene(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        inputs = _eldar_b2b_inputs(call_id)

        def fake_request(_payload):
            return {
                "status": "verified",
                "call_id": call_id,
                "rows": [
                    [
                        "Момент 1 - Требования клиента",
                        "Что было не так: Менеджер не резюмировал требования клиента.",
                        inputs["transcript_scenes"][0]["turns"][0]["text"],
                        "Сказать: резюмировать требования клиента.",
                    ],
                    [
                        "Момент 2 - Квалификация пользователей",
                        "Что было не так: Менеджер не уточнил роли пользователей.",
                        inputs["transcript_scenes"][0]["turns"][1]["text"],
                        "Сказать: уточнить роли и доступы.",
                    ],
                    [
                        "Момент 3 - Управляемый следующий шаг",
                        "Что было не так: Менеджер оставил следующий шаг общим.",
                        "Фрагмент: Давайте сейчас уточню.",
                        "Сказать: назначить демо-созвон с целью и участниками.",
                    ],
                ],
                "moments": [
                    {
                        "moment": "Момент 1 - Требования клиента",
                        "call_id": call_id,
                        "what": "Менеджер не резюмировал требования клиента.",
                        "moment_summary": "Требования остались несобранными.",
                        "supporting_quote": inputs["transcript_scenes"][0]["turns"][0]["text"],
                        "better": "Сказать: резюмировать требования клиента.",
                        "proof_type": "sequence_inference",
                        "proof_explanation": "Клиент описал сложный контекст.",
                        "evidence_refs": inputs["transcript_scenes"][0]["evidence_refs"],
                    },
                    {
                        "moment": "Момент 2 - Квалификация пользователей",
                        "call_id": call_id,
                        "what": "Менеджер не уточнил роли пользователей.",
                        "moment_summary": "Роли и доступы остались без фиксации.",
                        "supporting_quote": inputs["transcript_scenes"][0]["turns"][1]["text"],
                        "better": "Сказать: уточнить роли и доступы.",
                        "proof_type": "sequence_inference",
                        "proof_explanation": "Клиент описал разные группы доступа.",
                        "evidence_refs": inputs["transcript_scenes"][0]["evidence_refs"],
                    },
                    {
                        "moment": "Момент 3 - Управляемый следующий шаг",
                        "call_id": call_id,
                        "what": "Менеджер оставил следующий шаг общим.",
                        "moment_summary": "Не назначен конкретный формат продолжения.",
                        "supporting_quote": "Давайте сейчас уточню.",
                        "better": "Сказать: назначить демо-созвон с целью и участниками.",
                        "proof_type": "sequence_inference",
                        "proof_explanation": "Фраза требует соседнего контекста закрытия.",
                        "evidence_refs": inputs["transcript_scenes"][1]["evidence_refs"],
                    },
                ],
            }

        module._request_llm3_call_breakdown = fake_request
        result = module.compose_call_breakdown(
            selected_call=inputs["selected_call"],
            transcript_scenes=inputs["transcript_scenes"],
            situation_evidence_packet=inputs["situation_evidence_packet"],
            llm2_facts=inputs["llm2_facts"],
            llm3_enabled=True,
        )

        self.assertTrue(result["selection_diagnostics"]["llm3_used"])
        self.assertFalse(result["selection_diagnostics"]["deterministic_fallback_used"])
        self.assertGreater(len(result["rows"][2][2]), 90)
        self.assertIn("ЭЦП", result["rows"][2][2])

    def test_llm3_user_role_counter_evidence_softens_absolute_missing_claim(self) -> None:
        module = _load_call_breakdown_composer_module()
        call_id = str(uuid4())
        inputs = _eldar_b2b_inputs(call_id)
        inputs["transcript_scenes"][0]["turns"].insert(
            2,
            {
                "speaker": "manager",
                "text": "А сколько в вашей команде планирует пользоваться системой?",
                "start_sec": 83,
                "end_sec": 88,
            },
        )
        inputs["transcript_scenes"][0]["evidence_refs"].append(
            {
                "ref_id": "requirements:manager-users-question",
                "call_id": call_id,
                "scene_id": "requirements",
                "turn_indexes": [2],
                "quote": "А сколько в вашей команде планирует пользоваться системой?",
            }
        )

        def fake_request(_payload):
            requirement_fragment = module._join_turns(inputs["transcript_scenes"][0]["turns"])
            closing_fragment = module._join_turns(inputs["transcript_scenes"][1]["turns"])
            return {
                "status": "verified",
                "call_id": call_id,
                "rows": [
                    [
                        "Момент 1 - Требования",
                        "Что было не так: Менеджер не резюмировал требования клиента.",
                        f"Фрагмент: {requirement_fragment}",
                        "Сказать: резюмировать требования клиента.",
                    ],
                    [
                        "Момент 2 - Пользователи",
                        "Что было не так: Менеджер не уточнил, кто будет использовать систему.",
                        f"Фрагмент: {requirement_fragment}",
                        "Сказать: уточнить роли, доступы и участников следующего шага.",
                    ],
                    [
                        "Момент 3 - Следующий шаг",
                        "Что было не так: Менеджер оставил следующий шаг общим.",
                        f"Фрагмент: {closing_fragment}",
                        "Сказать: назначить демо-созвон с целью и участниками.",
                    ],
                ],
                "moments": [
                    {
                        "moment": "Момент 1 - Требования",
                        "call_id": call_id,
                        "what": "Менеджер не резюмировал требования клиента.",
                        "moment_summary": "Требования остались несобранными.",
                        "supporting_quote": requirement_fragment,
                        "better": "Сказать: резюмировать требования клиента.",
                        "proof_type": "sequence_inference",
                        "proof_explanation": "Клиент описал сложный контекст.",
                        "evidence_refs": inputs["transcript_scenes"][0]["evidence_refs"],
                    },
                    {
                        "moment": "Момент 2 - Пользователи",
                        "call_id": call_id,
                        "what": "Менеджер не уточнил, кто будет использовать систему.",
                        "moment_summary": "Не уточнил пользователей и роли.",
                        "supporting_quote": requirement_fragment,
                        "better": "Сказать: уточнить роли, доступы и участников следующего шага.",
                        "proof_type": "sequence_inference",
                        "proof_explanation": "Менеджер не уточнил, кто будет использовать систему.",
                        "evidence_refs": inputs["transcript_scenes"][0]["evidence_refs"],
                    },
                    {
                        "moment": "Момент 3 - Следующий шаг",
                        "call_id": call_id,
                        "what": "Менеджер оставил следующий шаг общим.",
                        "moment_summary": "Не назначен конкретный формат продолжения.",
                        "supporting_quote": closing_fragment,
                        "better": "Сказать: назначить демо-созвон с целью и участниками.",
                        "proof_type": "sequence_inference",
                        "proof_explanation": "Фраза требует соседнего контекста закрытия.",
                        "evidence_refs": inputs["transcript_scenes"][1]["evidence_refs"],
                    },
                ],
            }

        module._request_llm3_call_breakdown = fake_request
        result = module.compose_call_breakdown(
            selected_call=inputs["selected_call"],
            transcript_scenes=inputs["transcript_scenes"],
            situation_evidence_packet=inputs["situation_evidence_packet"],
            llm2_facts=inputs["llm2_facts"],
            llm3_enabled=True,
        )

        self.assertTrue(result["selection_diagnostics"]["llm3_used"])
        self.assertFalse(result["selection_diagnostics"]["deterministic_fallback_used"])
        self.assertEqual(
            result["selection_diagnostics"]["counter_evidence_gate"]["status"],
            "repaired",
        )
        rendered = " ".join(
            [
                " ".join(" ".join(map(str, row)) for row in result["rows"]),
                " ".join(str(moment.get("what")) for moment in result["moments"]),
                " ".join(str(moment.get("proof_explanation")) for moment in result["moments"]),
            ]
        ).lower()
        self.assertNotIn("не уточнил, кто будет использовать", rendered)
        self.assertIn("начал уточнять", rendered)
        self.assertIn("но не зафиксировал роли", rendered)
        self.assertIn("сколько в вашей команде", rendered)


if __name__ == "__main__":
    unittest.main()
