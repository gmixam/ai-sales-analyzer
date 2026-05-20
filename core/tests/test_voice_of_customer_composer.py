from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "voice_of_customer_composer.py"
PROMPT_PATH = CORE_ROOT / "app" / "agents" / "calls" / "prompts" / "voice_of_customer_composer_v2.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("voice_of_customer_composer", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _artifact(transcript: str, *, call_id: str | None = None, report_evidence: dict | None = None):
    interaction_id = call_id or str(uuid4())
    return SimpleNamespace(
        interaction=SimpleNamespace(
            id=interaction_id,
            text=transcript,
            metadata_={
                "call_date": "2026-05-15 06:07:00",
                "contact_phone": "+77070000000",
            },
        ),
        analysis=SimpleNamespace(
            scores_detail={
                "report_evidence_version": "v1",
                "report_evidence": report_evidence or {},
                "evidence_fragments": [],
                "product_signals": [],
            }
        ),
        original_analysis=None,
        call_started_at=datetime(2026, 5, 15, 6, 7, tzinfo=UTC),
    )


class VoiceOfCustomerComposerTests(unittest.TestCase):
    def test_prompt_mentions_orphan_quote_and_signal_specific_recommendation(self) -> None:
        text = PROMPT_PATH.read_text(encoding="utf-8")

        self.assertIn("Ладно, хорошо, я перезвоню", text)
        self.assertIn("recommendation must follow", text)
        self.assertIn("mini-scene", text)
        self.assertIn("What does the client actually mean", text)
        self.assertIn("How should the manager work with that meaning", text)

    def test_problematic_short_callback_quote_with_contract_action_is_rejected(self) -> None:
        module = _load_module()
        call_id = str(uuid4())
        transcript = (
            "Менеджер: Я отправлю информацию в WhatsApp. "
            "Клиент: Ладно, хорошо, я перезвоню. "
            "Менеджер: Хорошо, буду ждать."
        )
        legacy_voice = {
            "situations": [
                {
                    "call_id": call_id,
                    "client_call_reference": "Клиент • 2026-05-15 • 06:07",
                    "quote": "Ладно, хорошо, я перезвоню",
                    "context": "Клиент якобы готовит договор.",
                    "interpretation": "Клиент якобы готовит договор.",
                    "manager_action": "Что сделать: отправить договор клиенту.",
                    "customer_signal": "document_or_signature_need",
                    "source": "legacy_voice_of_customer",
                }
            ]
        }

        result = module.compose_voice_of_customer(
            [_artifact(transcript, call_id=call_id)],
            legacy_voice_of_customer=legacy_voice,
            llm3_enabled=False,
        )

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["rows"], [])
        rejected = result["voice_of_customer_quality"]["rejected"]
        self.assertTrue(rejected)
        self.assertIn("recommendation_contract_without_context", rejected[0]["rejection_reason"])

    def test_expands_short_material_request_to_mini_scene(self) -> None:
        module = _load_module()
        call_id = str(uuid4())
        transcript = (
            "Клиент: Нам интересно электронное подписание договоров, потому что часть документов "
            "идет на бумаге. Менеджер: Могу отправить информацию и тарифы. "
            "Клиент: Скиньте в WhatsApp, я посмотрю. Менеджер: Хорошо, отправлю."
        )
        report_evidence = {
            "voice_of_customer": [
                {
                    "usable_in_report": True,
                    "speaker": "client",
                    "business_signal": "medium",
                    "quote": "Скиньте в WhatsApp, я посмотрю.",
                    "meaning": "Клиент согласовал канал для материалов после обсуждения электронного подписания.",
                    "topic": "whatsapp materials",
                }
            ]
        }

        result = module.compose_voice_of_customer(
            [_artifact(transcript, call_id=call_id, report_evidence=report_evidence)],
            llm3_enabled=False,
        )

        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["rows"]), 1)
        self.assertIn("Клиент: Скиньте в WhatsApp", result["rows"][0][1])
        self.assertGreaterEqual(len(result["rows"][0][1].split()), 14)
        self.assertIn("follow-up", result["rows"][0][2])

    def test_llm3_result_can_be_used_when_quality_passes(self) -> None:
        module = _load_module()
        call_id = str(uuid4())
        transcript = (
            "Клиент: Нам нужно подписывать договоры через ЭЦП. "
            "Менеджер: Да, можем показать сценарий. "
            "Клиент: Тогда покажите, как это работает для договора."
        )
        report_evidence = {
            "voice_of_customer": [
                {
                    "usable_in_report": True,
                    "speaker": "client",
                    "business_signal": "high",
                    "quote": "Тогда покажите, как это работает для договора.",
                    "meaning": "Клиент просит показать сценарий подписания договора.",
                    "topic": "договор ЭЦП",
                }
            ]
        }

        def fake_request(_payload):
            return {
                "status": "verified",
                "situations": [
                    {
                        "call_id": call_id,
                        "client_call_reference": "Клиент • 2026-05-15 • 06:07",
                        "quote": "Тогда покажите, как это работает для договора.",
                        "quote_context": (
                            "Клиент: Нам нужно подписывать договоры через ЭЦП. "
                            "Менеджер: Да, можем показать сценарий. "
                            "Клиент: Тогда покажите, как это работает для договора."
                        ),
                        "context": (
                            "Клиент просит показать сценарий подписания договора. "
                            "Что сделать: предложить демо по документному процессу."
                        ),
                        "interpretation": (
                            "Клиент просит показать сценарий подписания договора. "
                            "Что сделать: предложить демо по документному процессу."
                        ),
                        "manager_action": "Что сделать: предложить демо по документному процессу.",
                        "customer_signal": "document_or_signature_need",
                        "source": "llm3",
                    }
                ],
                "rows": [
                    [
                        "Клиент • 2026-05-15 • 06:07",
                        (
                            "Клиент: Нам нужно подписывать договоры через ЭЦП. "
                            "Менеджер: Да, можем показать сценарий. "
                            "Клиент: Тогда покажите, как это работает для договора."
                        ),
                        (
                            "Клиент просит показать сценарий подписания договора. "
                            "Что сделать: предложить демо по документному процессу."
                        ),
                    ]
                ],
            }

        module._request_llm3_voice_of_customer = fake_request
        result = module.compose_voice_of_customer(
            [_artifact(transcript, call_id=call_id, report_evidence=report_evidence)],
            llm3_enabled=True,
        )

        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["selection_diagnostics"]["llm3"]["llm3_used"])
        self.assertEqual(result["source_note"], "report_evidence.voice_of_customer_composer.v2")
        self.assertEqual(result["selection_diagnostics"]["composer_version"], "voice_of_customer_composer_v2")

    def test_llm3_v2_customer_scenes_are_normalized(self) -> None:
        module = _load_module()
        call_id = str(uuid4())
        transcript = (
            "Клиент: Нам нужно подписывать договоры через ЭЦП. "
            "Менеджер: Да, можем показать сценарий. "
            "Клиент: Тогда покажите, как это работает для договора."
        )
        report_evidence = {
            "voice_of_customer": [
                {
                    "usable_in_report": True,
                    "speaker": "client",
                    "business_signal": "high",
                    "quote": "Тогда покажите, как это работает для договора.",
                    "meaning": "Клиент просит показать сценарий подписания договора.",
                    "topic": "договор ЭЦП",
                }
            ]
        }

        def fake_request(_payload):
            return {
                "status": "verified",
                "customer_scenes": [
                    {
                        "signal_id": _payload["signals"][0]["signal_id"],
                        "call_id": call_id,
                        "client_call_reference": "Клиент • 2026-05-15 • 06:07",
                        "scene_summary": "Клиент обсуждает электронное подписание и просит показать сценарий работы с договором.",
                        "quote": "Тогда покажите, как это работает для договора.",
                        "quote_context": (
                            "Клиент: Нам нужно подписывать договоры через ЭЦП. "
                            "Менеджер: Да, можем показать сценарий. "
                            "Клиент: Тогда покажите, как это работает для договора."
                        ),
                        "dialogue_evidence": [
                            {"speaker": "client", "text": "Нам нужно подписывать договоры через ЭЦП."},
                            {"speaker": "manager", "text": "Да, можем показать сценарий."},
                            {"speaker": "client", "text": "Тогда покажите, как это работает для договора."},
                        ],
                        "customer_meaning": "Это не общий интерес, а запрос на понятный документный сценарий.",
                        "manager_response": "Предложить короткое демо по подписанию договора и зафиксировать участников.",
                        "why_action_follows": "Клиент просит показать работу именно для договора, поэтому следующий шаг должен быть демонстрацией процесса.",
                        "customer_signal": "document_or_signature_need",
                        "source": "voice_of_customer_composer",
                    }
                ],
                "situations": [],
                "rows": [],
            }

        module._request_llm3_voice_of_customer = fake_request
        result = module.compose_voice_of_customer(
            [_artifact(transcript, call_id=call_id, report_evidence=report_evidence)],
            llm3_enabled=True,
        )

        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["selection_diagnostics"]["llm3"]["llm3_used"])
        self.assertEqual(len(result["customer_scenes"]), 1)
        self.assertIn("документный сценарий", result["customer_scenes"][0]["customer_meaning"])
        self.assertEqual(len(result["customer_scenes"][0]["dialogue_evidence"]), 3)
        self.assertEqual(len(result["rows"][0]), 3)

    def test_llm3_material_action_without_material_context_falls_back(self) -> None:
        module = _load_module()
        call_id = str(uuid4())
        transcript = (
            "Клиент: Я могу сама перезвонить в пятницу после обеда. "
            "Менеджер: Хорошо, тогда жду вашего звонка."
        )
        report_evidence = {
            "voice_of_customer": [
                {
                    "usable_in_report": True,
                    "speaker": "client",
                    "business_signal": "medium",
                    "quote": "Я могу сама перезвонить в пятницу после обеда.",
                    "meaning": "Клиент переносит контакт на пятницу после обеда.",
                    "topic": "timing",
                }
            ]
        }

        def fake_request(_payload):
            return {
                "status": "verified",
                "situations": [
                    {
                        "call_id": call_id,
                        "quote": "Я могу сама перезвонить в пятницу после обеда.",
                        "quote_context": (
                            "Клиент: Я могу сама перезвонить в пятницу после обеда. "
                            "Менеджер: Хорошо, тогда жду вашего звонка."
                        ),
                        "interpretation": "Клиент переносит контакт на пятницу.",
                        "manager_action": "Что сделать: отправить материалы в WhatsApp и назначить follow-up.",
                        "customer_signal": "timing_or_internal_discussion",
                    }
                ],
                "rows": [
                    [
                        "Клиент • 2026-05-15 • 06:07",
                        (
                            "Клиент: Я могу сама перезвонить в пятницу после обеда. "
                            "Менеджер: Хорошо, тогда жду вашего звонка."
                        ),
                        "Клиент переносит контакт. Что сделать: отправить материалы в WhatsApp.",
                    ]
                ],
            }

        module._request_llm3_voice_of_customer = fake_request
        result = module.compose_voice_of_customer(
            [_artifact(transcript, call_id=call_id, report_evidence=report_evidence)],
            llm3_enabled=True,
        )

        self.assertEqual(result["status"], "verified")
        self.assertFalse(result["selection_diagnostics"]["llm3"]["llm3_used"])
        self.assertEqual(
            result["selection_diagnostics"]["llm3"]["llm3_rejection_reason"],
            "quality_gate_failed_after_llm3",
        )
        rendered = " ".join(" ".join(map(str, row)) for row in result["rows"]).lower()
        self.assertNotIn("отправить материалы", rendered)
        self.assertTrue("вернуться" in rendered or "возврат" in rendered)

    def test_callback_signal_does_not_invent_internal_discussion(self) -> None:
        module = _load_module()
        call_id = str(uuid4())
        transcript = (
            "Сторона 1: Так, всё принято. Это ваш номер, я через некоторое время смогу?\n"
            "Сторона 2: Рабочий, да. Ну, можете, да, звонить.\n"
            "Клиент: Да, всё принято, хорошо. Я вам перезвоню. Спасибо.\n"
            "Сторона 1: Всё, хорошо тогда."
        )
        report_evidence = {
            "voice_of_customer": [
                {
                    "usable_in_report": True,
                    "speaker": "client",
                    "business_signal": "medium",
                    "quote": "Да, всё принято, хорошо. Я вам перезвоню. Спасибо.",
                    "meaning": "Клиент забирает следующий контакт на себя.",
                    "topic": "timing",
                }
            ]
        }

        result = module.compose_voice_of_customer(
            [_artifact(transcript, call_id=call_id, report_evidence=report_evidence)],
            llm3_enabled=False,
        )

        rendered = " ".join(" ".join(map(str, row)) for row in result["rows"]).lower()
        self.assertEqual(result["status"], "verified")
        self.assertNotIn("с кем клиент будет обсуждать", rendered)
        self.assertNotIn("обсуждать решение", rendered)
        self.assertIn("я перезвоню", rendered)
        self.assertTrue("точку возврата" in rendered or "вернуться" in rendered)

    def test_llm3_callback_scene_internal_discussion_is_repaired_and_speakers_are_consistent(self) -> None:
        module = _load_module()
        call_id = str(uuid4())
        transcript = (
            "Сторона 1: Так, всё принято. Это ваш номер, я через некоторое время смогу?\n"
            "Сторона 2: Рабочий, да. Ну, можете, да, звонить.\n"
            "Клиент: Да, всё принято, хорошо. Я вам перезвоню. Спасибо.\n"
            "Сторона 1: Всё, хорошо тогда."
        )
        report_evidence = {
            "voice_of_customer": [
                {
                    "usable_in_report": True,
                    "speaker": "client",
                    "business_signal": "medium",
                    "quote": "Да, всё принято, хорошо. Я вам перезвоню. Спасибо.",
                    "meaning": "Клиент забирает следующий контакт на себя.",
                    "topic": "timing",
                }
            ]
        }

        def fake_request(_payload):
            return {
                "status": "verified",
                "customer_scenes": [
                    {
                        "signal_id": _payload["signals"][0]["signal_id"],
                        "call_id": call_id,
                        "client_call_reference": "Клиент • 2026-05-15 • 06:07",
                        "scene_summary": "Клиент говорит, что перезвонит через некоторое время.",
                        "quote": "Да, всё принято, хорошо. Я вам перезвоню. Спасибо.",
                        "quote_context": _payload["signals"][0]["quote_context"],
                        "dialogue_evidence": [
                            {"speaker": "unknown", "text": "Так, всё принято. Это ваш номер, я через некоторое время смогу?"},
                            {"speaker": "unknown", "text": "Рабочий, да. Ну, можете, да, звонить."},
                            {"speaker": "client", "text": "Да, всё принято, хорошо. Я вам перезвоню. Спасибо."},
                        ],
                        "customer_meaning": "Клиент не готов принять решение в моменте и переносит следующий контакт.",
                        "manager_response": "Уточнить, с кем клиент будет обсуждать решение, когда вернуться к разговору и какой следующий шаг зафиксировать.",
                        "why_action_follows": "Клиент выразил намерение перезвонить.",
                        "customer_signal": "timing_or_internal_discussion",
                    }
                ],
                "situations": [],
                "rows": [],
            }

        module._request_llm3_voice_of_customer = fake_request
        result = module.compose_voice_of_customer(
            [_artifact(transcript, call_id=call_id, report_evidence=report_evidence)],
            llm3_enabled=True,
        )

        scene = result["customer_scenes"][0]
        self.assertTrue(result["selection_diagnostics"]["llm3"]["llm3_used"])
        self.assertNotIn("обсуждать решение", scene["manager_response"].lower())
        self.assertTrue(all(turn["speaker"].startswith("side_") for turn in scene["dialogue_evidence"]))

    def test_document_show_scenario_is_not_misclassified_as_price_request(self) -> None:
        module = _load_module()

        category = module._signal_category(
            quote="Тогда покажите, как это работает для договора.",
            context="Клиент просит показать сценарий подписания договора.",
        )

        self.assertEqual(category, "document_or_signature_need")

    def test_refusal_and_service_issue_take_priority_over_document_words(self) -> None:
        module = _load_module()

        refusal = module._signal_category(
            quote="Пока не будем подписывать",
            context="Клиент говорит, что такого количества кассиров нет.",
        )
        service = module._signal_category(
            quote="Я договор купли-продажи заполнила и не смогла сохранить.",
            context="Клиент пришел с проблемой сохранения документа.",
        )

        self.assertEqual(refusal, "refusal_or_not_now")
        self.assertEqual(service, "service_or_usage_issue")

    def test_process_objection_does_not_become_interest_signal(self) -> None:
        module = _load_module()

        category = module._signal_category(
            quote="Нет, пока, наверное, мы больше получаем через услуг, чем предоставляем.",
            context="Клиент объясняет, что текущий объем не подходит для активного внедрения.",
        )

        self.assertEqual(category, "current_process_objection")

    def test_interest_recommendation_contradiction_is_rejected(self) -> None:
        module = _load_module()
        signal = module.VoiceCustomerSignal(
            signal_id="s1",
            call_id="c1",
            source="llm3",
            quote="Нет, пока, наверное, мы больше получаем через услуг, чем предоставляем.",
            quote_context=(
                "Клиент: Нет, пока, наверное, мы больше получаем через услуг, чем предоставляем. "
                "Менеджер: Понял."
            ),
            interpretation="Клиент не проявил активного интереса.",
            manager_action="Что сделать: перевести интерес в следующий шаг с целью, участниками и сроком.",
            customer_signal="interest_signal",
            score=10,
        )

        self.assertEqual(
            module.VoiceOfCustomerQualityGate()._rejection_reason(signal),
            "recommendation_interest_contradicts_context",
        )

    def test_refusal_signal_rejects_sales_push_recommendation(self) -> None:
        module = _load_module()
        signal = module.VoiceCustomerSignal(
            signal_id="s1",
            call_id="c1",
            source="llm3",
            quote="Ну, вообще, да, слышала, но не знаю, нет, наверное, не рассматриваю.",
            quote_context=(
                "Клиент: Ну, вообще, да, слышала, но не знаю, нет, наверное, не рассматриваю. "
                "Менеджер: Понял. У вас не такие большие объемы? "
                "Клиент: Да, да, не такие большие объемы."
            ),
            interpretation="Клиент не рассматривает ЭДО из-за небольших объемов.",
            manager_action="Что сделать: предложить показать сценарий подписания договора.",
            customer_signal="refusal_or_not_now",
            score=10,
        )

        self.assertEqual(
            module.VoiceOfCustomerQualityGate()._rejection_reason(signal),
            "recommendation_sales_push_after_refusal",
        )

    def test_unknown_segment_speakers_are_inferred_for_mini_scene(self) -> None:
        module = _load_module()
        call_id = str(uuid4())
        artifact = SimpleNamespace(
            interaction=SimpleNamespace(
                id=call_id,
                text="",
                metadata_={
                    "segments": [
                        {"speaker": "A", "text": "Я могу сама перезвонить в пятницу после обеда."},
                        {"speaker": "A", "text": "Хорошо, тогда жду вашего звонка."},
                    ],
                    "call_date": "2026-05-15 06:07:00",
                },
            ),
            analysis=SimpleNamespace(scores_detail={"report_evidence": {}, "evidence_fragments": [], "product_signals": []}),
            original_analysis=None,
            call_started_at=datetime(2026, 5, 15, 6, 7, tzinfo=UTC),
        )
        call = module.VoiceOfCustomerInputAdapter().normalize_calls([artifact])[0]
        joined = module._join_turns(module._call_turns(call))

        self.assertIn("Клиент: Я могу сама перезвонить", joined)
        self.assertIn("Менеджер: Хорошо, тогда жду", joined)


if __name__ == "__main__":
    unittest.main()
