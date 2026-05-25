from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "call_tomorrow_wording_composer.py"
PROMPT_PATH = CORE_ROOT / "app" / "agents" / "calls" / "prompts" / "call_tomorrow_wording_composer_v1.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("call_tomorrow_wording_composer", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call_tomorrow():
    return {
        "contacts": [
            {
                "interaction_id": "call-1",
                "client_call_reference": "Алия • 2026-05-19 • 10:00",
                "status": "open",
                "priority_code": "warm",
                "priority_label": "Тёплый",
                "deadline": None,
                "reason": "Клиент попросил материалы в WhatsApp и готов посмотреть предложение.",
                "next_step": "Отправить материал и согласовать дату возврата к обсуждению.",
                "opening_script": "Добрый день. Отправил материалы, как договорились. Когда удобно вернуться к обсуждению?",
                "recommendation": "Отправить материал и согласовать дату возврата к обсуждению.",
                "action_profile": "materials_request",
                "signal_text": "Клиент: Скиньте в WhatsApp, я посмотрю.",
                "evidence_signal_text": "Клиент попросил материалы в WhatsApp.",
            }
        ],
        "selection_diagnostics": {},
    }


class CallTomorrowWordingComposerTests(unittest.TestCase):
    def test_prompt_says_not_to_change_selection_or_priority(self) -> None:
        text = PROMPT_PATH.read_text(encoding="utf-8")

        self.assertIn("Do not add, remove, reorder", text)
        self.assertIn("do_not_change_priority_status_deadline", text)
        self.assertIn("same number of contacts", text)

    def test_llm3_wording_updates_only_text_fields(self) -> None:
        module = _load_module()

        def fake_request(_payload):
            return {
                "status": "verified",
                "contacts": [
                    {
                        "contact_key": "call-1",
                        "reason": "Клиент уже согласовал WhatsApp как канал и ждёт материалы, поэтому важно не потерять следующий контакт.",
                        "next_step": "Отправить материалы и сразу договориться, когда вернуться к вопросам.",
                        "opening_script": "Добрый день, отправил материалы в WhatsApp. Когда удобно обсудить вопросы?",
                        "why_this_wording": "Фраза продолжает согласованный канал и сразу фиксирует следующий шаг.",
                    }
                ],
                "_routing": {
                    "layer": "llm3",
                    "request_kind": "call_tomorrow_wording_composer",
                    "execution_status": "simulated",
                    "simulated": True,
                    "simulation_run_id": "composer-test-run",
                    "input_artifact": "/tmp/asa_llm_sim_runs/composer-test-run/llm3_call_tomorrow_input.json",
                    "output_artifact": "/tmp/asa_llm_sim_runs/composer-test-run/llm3_call_tomorrow_output.json",
                },
            }

        module._request_llm3_call_tomorrow_wording = fake_request
        result = module.compose_call_tomorrow_wording(_call_tomorrow(), llm3_enabled=True)
        contact = result["contacts"][0]

        self.assertEqual(contact["interaction_id"], "call-1")
        self.assertEqual(contact["priority_code"], "warm")
        self.assertEqual(contact["status"], "open")
        self.assertIn("не потерять следующий контакт", contact["reason"])
        self.assertIn("Когда удобно обсудить", contact["opening_script"])
        self.assertEqual(contact["wording_source"], "report_evidence.call_tomorrow_wording_composer.v1")
        routing = result["selection_diagnostics"]["wording_composer"]["llm3_routing"]
        self.assertEqual(routing["execution_status"], "simulated")
        self.assertIn("/tmp/asa_llm_sim_runs/", routing["output_artifact"])

    def test_llm3_cannot_change_contact_count(self) -> None:
        module = _load_module()

        def fake_request(_payload):
            return {"status": "verified", "contacts": []}

        module._request_llm3_call_tomorrow_wording = fake_request
        original = _call_tomorrow()
        result = module.compose_call_tomorrow_wording(original, llm3_enabled=True)

        self.assertEqual(result["contacts"][0]["reason"], original["contacts"][0]["reason"])
        self.assertEqual(
            result["selection_diagnostics"]["wording_composer"]["llm3_rejection_reason"],
            "contacts_count_changed",
        )

    def test_refusal_evidence_rejects_sales_push(self) -> None:
        module = _load_module()
        source = {
            "reason": "Клиент не рассматривает ЭДО из-за небольшого объёма.",
            "next_step": "Уточнить причину отказа и условие возврата.",
            "opening_script": "Добрый день. Хотел уточнить, при каких условиях вопрос станет актуален.",
            "signal_text": "не рассматриваю, не такие большие объемы",
            "evidence_signal_text": "не рассматриваю, не такие большие объемы",
        }

        reason = module._wording_rejection_reason(
            source=source,
            reason="Клиент не рассматривает решение.",
            next_step="Назначить демо и отправить КП.",
            opening_script="Добрый день, давайте покажу демо.",
        )

        self.assertEqual(reason, "sales_push_after_refusal")


if __name__ == "__main__":
    unittest.main()
