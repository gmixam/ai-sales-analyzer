from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "situation_day_writer.py"
SPEC = importlib.util.spec_from_file_location("situation_day_writer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
situation_day_writer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = situation_day_writer
SPEC.loader.exec_module(situation_day_writer)

compose_situation_day_view = situation_day_writer.compose_situation_day_view


class SituationDayWriterTests(unittest.TestCase):
    def test_raw_dialogue_does_not_become_what_happened(self) -> None:
        selected = {
            "pattern_title": "КП без квалификации",
            "what_happened": (
                "Клиент: Можете отправить коммерческое предложение? "
                "Менеджер: Да, отправлю в WhatsApp."
            ),
            "client_context": "Клиент попросил КП после короткого интереса к ЭДО.",
            "what_was_missing": "Менеджер не уточнил объем, критерии и следующий шаг.",
            "next_time_action": "Задать 2-3 вопроса и назначить демо.",
        }

        result = compose_situation_day_view(selected)

        self.assertNotEqual(result["what_happened"], selected["what_happened"])
        self.assertNotIn("Клиент:", result["what_happened"])
        self.assertNotIn("Менеджер:", result["what_happened"])
        self.assertIn("Клиент попросил КП", result["what_happened"])
        self.assertFalse(result["situation_day_writer_quality"]["raw_dialogue_used_as_what_happened"])

    def test_long_fragment_like_dialogue_is_rewritten_to_summary(self) -> None:
        selected = {
            "pattern_title": "КП согласовали без минимальной квалификации",
            "what_happened": (
                "Потом, может, уже и с другими клиентами тоже начать работу через эту систему. "
                "Понял. Да, а вам сейчас интересует бесплатная версия протестировать? "
                "В бесплатной версии мы не можем отправлять документы или можем? "
                "У вас будет лимит до пяти документов. Тогда давайте КП, я посмотрю."
            ),
            "client_context": "Клиент обсуждал тестирование системы и возможность отправки документов.",
            "what_was_missing": "Менеджер не уточнил объем, роли и критерии решения перед КП.",
            "next_time_action": "Сначала уточнить параметры, потом согласовать КП.",
        }

        result = compose_situation_day_view(selected)

        self.assertNotEqual(result["what_happened"], selected["what_happened"])
        self.assertIn("Клиент обсуждал тестирование системы", result["what_happened"])
        self.assertIn("Менеджер не уточнил", result["what_happened"])
        self.assertLess(len(result["what_happened"]), len(selected["what_happened"]))

    def test_short_claim_is_expanded_into_narrative(self) -> None:
        selected = {
            "pattern_title": "Следующий шаг не закреплен",
            "what_happened": "Менеджер не уточнил, кто и когда выполнит следующий шаг.",
            "client_context": "Клиент был готов продолжить после внутреннего согласования.",
            "what_was_missing": "Менеджер не уточнил, кто и когда выполнит следующий шаг.",
        }

        result = compose_situation_day_view(selected)

        self.assertNotEqual(result["what_happened"], selected["what_happened"])
        self.assertIn("Клиент был готов продолжить", result["what_happened"])
        self.assertIn("Проблема для разбора", result["what_happened"])

    def test_low_confidence_uses_supporting_quote_inside_what_happened(self) -> None:
        selected = {
            "pattern_title": "Следующий шаг не закреплен",
            "what_happened": "Менеджер не уточнил следующий шаг.",
            "supporting_quote": "Я свяжусь, получается, завтра.",
            "what_was_missing": "Менеджер не уточнил, кто и когда выполнит следующий шаг.",
        }

        result = compose_situation_day_view(selected)

        self.assertIn("Сохраненный фрагмент показывает ситуацию", result["what_happened"])
        self.assertIn("Я свяжусь, получается, завтра", result["what_happened"])
        self.assertIn("Проблема для разбора", result["what_happened"])

    def test_scripts_have_minimum_two_items(self) -> None:
        selected = {
            "pattern_title": "Следующий шаг не закреплен",
            "what_happened": "Клиент проявил интерес, а менеджер завершил разговор обещанием уточнить детали.",
            "what_was_missing": "Не было конкретного времени следующего контакта.",
            "next_time_action": "Согласовать дату и участников демо.",
            "scripts": ["Давайте согласуем короткое демо на завтра."],
        }

        result = compose_situation_day_view(selected)

        self.assertGreaterEqual(len(result["scripts"]), 2)
        self.assertIn("Давайте согласуем короткое демо на завтра.", result["scripts"])

    def test_unknown_speakers_use_low_confidence_without_known_role_labels(self) -> None:
        selected = {
            "pattern_title": "Не разобран B2B-контекст",
            "what_happened": "Спикер 1: У нас 150 АВР в месяц. Спикер 2: Я уточню тариф.",
            "client_context": "В фрагменте обсуждали объем документов и тариф.",
            "what_was_missing": "Не было резюме процесса и управляемого следующего шага.",
        }
        turns = [
            {"speaker": "speaker_1", "text": "У нас 150 АВР в месяц."},
            {"speaker": "speaker_2", "text": "Я уточню тариф."},
        ]

        result = compose_situation_day_view(selected, dialogue_turns=turns)

        self.assertEqual(result["role_confidence"], "low")
        self.assertNotIn("Клиент:", result["evidence_explanation"])
        self.assertNotIn("Менеджер:", result["evidence_explanation"])
        self.assertNotIn("Клиент:", result["what_happened"])
        self.assertNotIn("Менеджер:", result["what_happened"])

    def test_manager_client_speakers_give_high_confidence_and_role_evidence(self) -> None:
        selected = {
            "pattern_title": "КП отправлено без квалификации",
            "what_happened": "Клиент запросил КП, менеджер не уточнил параметры сделки.",
            "what_was_missing": "Менеджер не спросил объем, сроки и ЛПР.",
            "next_time_action": "Уточнить параметры и предложить демо.",
        }
        turns = [
            {"speaker": "client", "text": "Можете отправить коммерческое предложение?"},
            {"speaker": "manager", "text": "Да, отправлю в WhatsApp."},
        ]

        result = compose_situation_day_view(selected, dialogue_turns=turns)

        self.assertEqual(result["role_confidence"], "high")
        self.assertIn("Клиент: Можете отправить коммерческое предложение?", result["evidence_explanation"])
        self.assertIn("Менеджер: Да, отправлю в WhatsApp.", result["evidence_explanation"])


if __name__ == "__main__":
    unittest.main()
