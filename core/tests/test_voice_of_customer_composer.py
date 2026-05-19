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
PROMPT_PATH = CORE_ROOT / "app" / "agents" / "calls" / "prompts" / "voice_of_customer_composer_v1.md"


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
        self.assertEqual(result["source_note"], "report_evidence.voice_of_customer_composer.v1")

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
        self.assertIn("когда вернуться", rendered)

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
