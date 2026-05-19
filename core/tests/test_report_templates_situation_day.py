from __future__ import annotations

import sys
import unittest
import importlib.util
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "report_templates.py"


def _load_report_templates_module():
    spec = importlib.util.spec_from_file_location("report_templates", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SituationDayTemplateTests(unittest.TestCase):
    def test_coaching_view_uses_new_structure_without_context_mini_card(self) -> None:
        report_templates = _load_report_templates_module()
        section = {
            "id": "situation_day",
            "label": "СИТУАЦИЯ ДНЯ",
            "kind": "situation_card",
            "situation_title": "Сложный запрос не доведен до плана",
            "dialogue_excerpt": {
                "client_call_reference": "Айгуль • 14.05.2026 • 11:20",
                "turns": [
                    {"speaker": "client", "text": "Мне нужно понять стоимость."},
                    {"speaker": "manager", "text": "Я уточню и перезвоню."},
                ],
            },
            "coaching_view": {
                "pattern_title": "Следующий шаг остался общим",
                "moment_summary": "Клиент попросил стоимость, а менеджер не закрепил срок ответа.",
                "what_happened": "Менеджер сказал, что уточнит и перезвонит.",
                "what_was_missing": "Не назван срок возврата и формат продолжения.",
                "next_time_action": "Назвать срок ответа и договориться о следующем контакте.",
                "scripts": ["Вернусь сегодня до 17:00 с расчетом и предложу следующий шаг."],
            },
        }

        text_lines = report_templates._section_to_text_lines(section)
        html = report_templates._render_html_section(section)

        self.assertLess(text_lines.index("Суть момента: Клиент попросил стоимость, а менеджер не закрепил срок ответа."), text_lines.index("Что произошло: Менеджер сказал, что уточнит и перезвонит."))
        self.assertIn("В чем ошибка менеджера: Не назван срок возврата и формат продолжения.", text_lines)
        self.assertIn("Как сделать лучше: Назвать срок ответа и договориться о следующем контакте.", text_lines)
        self.assertIn("Варианты речёвок:", text_lines)
        self.assertIn("Суть момента", html)
        self.assertIn("В чем ошибка менеджера", html)
        self.assertIn("Варианты речёвок", html)
        self.assertNotIn("<strong>Контекст</strong>", html)


if __name__ == "__main__":
    unittest.main()
