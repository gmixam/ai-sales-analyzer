from __future__ import annotations

import sys
import unittest
import importlib.util
import re
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

    def test_insufficient_situation_day_hides_internal_fields(self) -> None:
        report_templates = _load_report_templates_module()
        section = {
            "id": "situation_day",
            "label": "СИТУАЦИЯ ДНЯ",
            "kind": "situation_card",
            "coaching_view": {
                "pattern_title": "Нет надежно подтвержденной ситуации дня",
                "situation_day_evidence_status": "insufficient",
                "proof_strength": "insufficient",
                "insufficiency_reason": "situation_day_quote_not_grounded_in_transcript",
                "moment_summary": "Нет данных",
                "what_happened": "Механизм не нашел достаточно сильную мини-сцену.",
                "manager_error": "Нет данных",
                "next_time_action": "Нет данных",
                "scripts": ["Нет данных"],
            },
        }

        text_lines = report_templates._section_to_text_lines(section)
        html = report_templates._render_html_section(section)

        self.assertEqual(
            text_lines,
            [
                "Данных для этого блока недостаточно: не найден надежно подтвержденный "
                "эпизод, который можно безопасно показать менеджеру."
            ],
        )
        self.assertIn("Данных для этого блока недостаточно", html)
        self.assertNotIn("Суть момента", html)
        self.assertNotIn("Что произошло", html)
        self.assertNotIn("В чем ошибка менеджера", html)
        self.assertNotIn("Варианты речёвок", html)
        self.assertNotIn("situation_day_quote_not_grounded_in_transcript", html)

    def test_manager_daily_pdf_insufficient_situation_day_hides_detail_rows(self) -> None:
        report_templates = _load_report_templates_module()
        template = report_templates.load_report_template("manager_daily")
        report = _minimal_manager_daily_report_with_insufficient_situation()

        pdf_bytes, _pages = report_templates._render_pdf_report(report=report, template=template)
        text = _decode_pdf_text(pdf_bytes)

        self.assertIn("Данных для этого блока недостаточно", text)
        self.assertNotIn("Нет надежно подтвержденной ситуации дня", text)
        self.assertNotIn("Фокусный этап", text)
        self.assertNotIn("Что хотел клиент", text)
        self.assertNotIn("Наша задача", text)
        self.assertNotIn("Почему работает", text)


def _minimal_manager_daily_report_with_insufficient_situation() -> dict[str, object]:
    section_ids = [
        "report_header",
        "day_summary",
        "money_on_table",
        "warm_pipeline",
        "review_block",
        "main_focus_for_tomorrow",
        "call_breakdown",
        "voice_of_customer",
        "additional_situations",
        "challenge",
        "call_tomorrow",
        "call_list",
        "morning_card",
    ]
    sections = [{"id": section_id, "label": section_id, "kind": "text"} for section_id in section_ids]
    by_id = {section["id"]: section for section in sections}
    by_id["report_header"].update({"calls_count": 0, "day_score": "Нет базы"})
    by_id["day_summary"].update({"outcome_cols": []})
    by_id["money_on_table"].update({"body": "", "highlight_line": "", "reason_line": "", "note": ""})
    by_id["warm_pipeline"].update({"summary_line": "", "counts_line": "", "conversion_line": "", "average_line": ""})
    by_id["review_block"].update({"stage_rows": []})
    by_id["main_focus_for_tomorrow"].update(
        {
            "label": "КОУЧИНГОВАЯ СИТУАЦИЯ",
            "situation_title": "Нет надежно подтвержденной ситуации дня",
            "scope_note": "Звонок выбран из rolling-window базы за 1 рабочий день.",
            "body": "Механизм не нашел достаточно сильную мини-сцену.",
            "client_need": "Роль собеседника не была уточнена.",
            "manager_task": "До презентации задать 2-3 уточняющих вопроса.",
            "scripts": ["Скрытая речевка"],
            "why_it_works": "Скрытое объяснение.",
            "coaching_view": {
                "situation_day_evidence_status": "insufficient",
                "pattern_title": "Нет надежно подтвержденной ситуации дня",
                "what_happened": "Механизм не нашел достаточно сильную мини-сцену.",
            },
        }
    )
    by_id["call_breakdown"].update({"rows": [], "summary_line": ""})
    by_id["voice_of_customer"].update({"rows": []})
    by_id["additional_situations"].update({"situations": []})
    by_id["challenge"].update({"goal_line": "", "today_line": "", "record_line": "", "phrase_line": ""})
    by_id["call_tomorrow"].update({"rows": []})
    by_id["call_list"].update({"columns": ["#", "Клиент", "Тип / суть", "Контекст", "Статус"], "rows": []})
    by_id["morning_card"].update(
        {
            "greeting": "",
            "summary_line": "",
            "financial_line": "",
            "call_tomorrow_contacts": [],
            "challenge": "",
        }
    )
    return {
        "metadata_line": "test",
        "title": "Ежедневный разбор звонков",
        "subtitle": "Тест",
        "hero_focus": "",
        "footer": "footer",
        "sections": sections,
    }


def _decode_pdf_text(pdf_bytes: bytes) -> str:
    chunks = []
    for match in re.finditer(rb"BT .*?<([0-9A-F]+)> Tj ET", pdf_bytes):
        chunks.append(bytes.fromhex(match.group(1).decode("ascii")).decode("utf-16-be"))
    return "\n".join(chunks)


if __name__ == "__main__":
    unittest.main()
