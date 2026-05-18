from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Any


os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "user")
os.environ.setdefault("POSTGRES_PASSWORD", "pass")
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("REDIS_PASSWORD", "pass")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("ASSEMBLYAI_API_KEY", "test-key")
os.environ.setdefault("ONLINEPBX_DOMAIN", "example.onpbx.ru")
os.environ.setdefault("ONLINEPBX_API_KEY", "test-key")


CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.calls.report_evidence import validate_report_evidence  # noqa: E402


TRANSCRIPT = (
    "Клиент: Скиньте в WhatsApp, я посмотрю. "
    "Менеджер: Хорошо, отправлю информацию."
)


def _block_item(
    *,
    fit: bool,
    score: int,
    reason_code: str,
    evidence_type: str,
    block_role: str | None = None,
    title_mode: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "fit": fit,
        "score": score,
        "reason_code": reason_code,
        "evidence_type": evidence_type,
    }
    if block_role is not None:
        item["block_role"] = block_role
    if title_mode is not None:
        item["title_mode"] = title_mode
    return item


def _valid_detail() -> dict[str, Any]:
    return {
        "report_evidence_version": "v1",
        "report_evidence": {
            "semantic_case": {
                "case_title": "Открытый интерес без срока возврата",
                "case_type": "growth_zone",
                "stage_code": "completion_next_step",
                "priority": "high",
                "evidence_quality": "direct",
                "core_meaning": (
                    "Клиент готов посмотреть материалы, но менеджер не закрепил "
                    "дату следующего контакта."
                ),
                "why_this_call_matters": (
                    "Открытый интерес может потеряться, если не перевести его "
                    "в конкретное действие."
                ),
                "customer_signal": (
                    "Клиент попросил отправить материалы в WhatsApp и оставил "
                    "разговор открытым."
                ),
                "manager_behavior": (
                    "Менеджер согласился отправить информацию, но не уточнил "
                    "срок возврата к обсуждению."
                ),
                "coaching_diagnosis": (
                    "Интерес клиента нужно переводить в проверяемый следующий шаг."
                ),
                "recommended_next_action": (
                    "Отправить материалы и согласовать дату следующего контакта."
                ),
                "best_dialogue_fragment": [
                    {
                        "speaker": "client",
                        "text": "Скиньте в WhatsApp, я посмотрю.",
                        "timestamp_start": None,
                        "timestamp_end": None,
                    },
                    {
                        "speaker": "manager",
                        "text": "Хорошо, отправлю информацию.",
                        "timestamp_start": None,
                        "timestamp_end": None,
                    },
                ],
                "report_block_fit": {
                    "situation_day": _block_item(
                        fit=True,
                        score=88,
                        reason_code="manager_gap_with_direct_evidence",
                        evidence_type="manager_gap",
                        block_role="coaching_problem",
                        title_mode="problem",
                    ),
                    "call_breakdown": _block_item(
                        fit=True,
                        score=82,
                        reason_code="coachable_manager_moment",
                        evidence_type="manager_gap",
                        block_role="coaching_problem",
                        title_mode="problem",
                    ),
                    "voice_of_customer": _block_item(
                        fit=True,
                        score=76,
                        reason_code="direct_customer_signal",
                        evidence_type="customer_signal",
                        block_role="customer_signal",
                        title_mode="neutral",
                    ),
                    "additional_situations": _block_item(
                        fit=False,
                        score=20,
                        reason_code="not_relevant_for_block",
                        evidence_type="none",
                    ),
                    "call_tomorrow": _block_item(
                        fit=False,
                        score=20,
                        reason_code="no_follow_up_needed",
                        evidence_type="none",
                    ),
                },
                "usable_in_report": True,
            },
            "situation_candidates": [],
            "manager_coaching_moments": [],
            "voice_of_customer": [],
            "additional_situations": [],
            "follow_up_candidates": [],
            "quote_bank": [],
        },
    }


def _valid_situation_day_block_candidate() -> dict[str, Any]:
    return {
        "fit": True,
        "score": 86,
        "role": "coaching_problem",
        "title_mode": "problem",
        "stage_code": "completion_next_step",
        "main_thesis": (
            "Менеджер отправляет материалы, но не переводит интерес клиента "
            "в дату возврата."
        ),
        "what_happened": (
            "Клиент попросил отправить материалы в WhatsApp, а менеджер "
            "согласился отправить информацию."
        ),
        "why_it_matters": (
            "Без срока возврата открытый интерес клиента может не перейти "
            "в следующий контакт."
        ),
        "what_was_missing": (
            "Не был зафиксирован срок возврата к обсуждению после отправки материалов."
        ),
        "better_next_action": (
            "После отправки материалов согласовать конкретную дату следующего контакта."
        ),
        "proof_type": "sequence_inference",
        "proof_explanation": (
            "Вывод основан на последовательности: клиент просит материалы, "
            "менеджер обещает отправить, срок возврата не звучит."
        ),
        "supporting_quote": "Хорошо, отправлю информацию.",
        "quote_role": "supports_context",
        "counter_evidence": [],
        "insufficiency_reason": None,
    }


class ReportBlockFitCoachingMomentNormalizationTests(unittest.TestCase):
    def _validate(self, detail: dict[str, Any], transcript: str | None = None):
        return validate_report_evidence(detail, TRANSCRIPT if transcript is None else transcript)

    def _issue_codes(self, issues: list[Any]) -> set[str]:
        return {issue.code for issue in issues}

    def test_fit_false_unsupported_coaching_moment_is_dropped(self) -> None:
        detail = _valid_detail()
        block = detail["report_evidence"]["semantic_case"]["report_block_fit"][
            "additional_situations"
        ]
        block["coaching_moment"] = {
            "summary": "Нужно лучше работать с клиентом.",
            "missing_action": None,
            "why_it_matters": None,
            "supporting_quote": "Этой цитаты нет в записи.",
            "evidence_type": "none",
            "confidence": "low",
        }

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        normalized_block = result.normalized["report_evidence"]["semantic_case"][
            "report_block_fit"
        ]["additional_situations"]
        self.assertIsNone(normalized_block["coaching_moment"])
        self.assertIn(
            "coaching_moment_ignored_for_non_fit_block",
            self._issue_codes(result.warnings),
        )

    def test_unsupported_non_quote_type_keeps_moment_and_drops_bad_quote(self) -> None:
        detail = _valid_detail()
        semantic_case = detail["report_evidence"]["semantic_case"]
        semantic_case["best_dialogue_fragment"] = []
        semantic_case["report_block_fit"]["call_breakdown"]["coaching_moment"] = {
            "summary": (
                "В доступной записи не зафиксировано согласование срока "
                "следующего контакта."
            ),
            "missing_action": "Менеджеру стоило согласовать дату возврата к обсуждению.",
            "why_it_matters": (
                "Без срока открытый интерес клиента может не перейти в следующий шаг."
            ),
            "supporting_quote": "Этой цитаты нет в записи.",
            "evidence_type": "insufficient",
            "confidence": "medium",
        }

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        moment = result.normalized["report_evidence"]["semantic_case"][
            "report_block_fit"
        ]["call_breakdown"]["coaching_moment"]
        self.assertEqual(moment["evidence_type"], "absence_in_context")
        self.assertIsNone(moment["supporting_quote"])
        self.assertIn(
            "coaching_moment_evidence_type_normalized",
            self._issue_codes(result.warnings),
        )
        self.assertIn(
            "coaching_moment_supporting_quote_dropped",
            self._issue_codes(result.warnings),
        )

    def test_fit_true_direct_quote_still_requires_grounded_quote(self) -> None:
        detail = _valid_detail()
        detail["report_evidence"]["semantic_case"]["report_block_fit"]["call_breakdown"][
            "coaching_moment"
        ] = {
            "summary": "Менеджер не закрепил срок возврата к обсуждению.",
            "missing_action": "Согласовать дату следующего контакта.",
            "why_it_matters": "Без даты возврата открытый интерес может потеряться.",
            "supporting_quote": "Этой цитаты нет в записи.",
            "evidence_type": "direct_quote",
            "confidence": "high",
        }

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("ungrounded_evidence_text", self._issue_codes(result.errors))

    def test_report_block_fit_direct_gap_context_quote_overclaim_fails(self) -> None:
        detail = _valid_detail()
        detail["report_evidence"]["semantic_case"]["report_block_fit"]["call_breakdown"][
            "coaching_moment"
        ] = {
            "summary": "Менеджер не закрепил срок возврата к обсуждению.",
            "missing_action": "Нужно было согласовать дату следующего контакта.",
            "why_it_matters": "Без даты возврата открытый интерес может потеряться.",
            "supporting_quote": "Хорошо, отправлю информацию.",
            "evidence_type": "direct_quote",
            "confidence": "high",
            "gap_claim": "Менеджер не согласовал срок следующего контакта.",
            "proof_type": "direct_gap",
            "proof_explanation": (
                "Цитата ошибочно выбрана как прямое доказательство отсутствия срока."
            ),
            "quote_role": "proves_gap",
            "counter_evidence": [],
        }

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("coaching_moment_proof_conflict", self._issue_codes(result.errors))

    def test_block_candidate_sequence_inference_context_quote_passes(self) -> None:
        detail = _valid_detail()
        detail["report_evidence"]["block_candidates"] = {
            "situation_day": _valid_situation_day_block_candidate()
        }

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        candidate = result.normalized["report_evidence"]["block_candidates"][
            "situation_day"
        ]
        self.assertEqual(candidate["proof_type"], "sequence_inference")
        self.assertEqual(candidate["quote_role"], "supports_context")

    def test_fit_true_block_candidate_requires_stage_code(self) -> None:
        detail = _valid_detail()
        candidate = _valid_situation_day_block_candidate()
        candidate.pop("stage_code")
        detail["report_evidence"]["block_candidates"] = {"situation_day": candidate}

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("block_candidate_missing_stage_code", self._issue_codes(result.errors))

    def test_fit_false_block_candidate_may_omit_stage_code(self) -> None:
        detail = _valid_detail()
        detail["report_evidence"]["block_candidates"] = {
            "money_on_table": {
                "fit": False,
                "score": 0,
                "role": "neutral_summary",
                "title_mode": "neutral",
                "proof_type": "context_support",
                "proof_explanation": "Коммерческого сигнала в звонке нет.",
                "quote_role": "not_applicable",
                "counter_evidence": [],
                "insufficiency_reason": "no_commercial_signal",
            }
        }

        result = self._validate(detail)

        self.assertTrue(result.is_valid)

    def test_call_breakdown_block_candidate_accepts_prompt_field_names(self) -> None:
        detail = _valid_detail()
        detail["report_evidence"]["block_candidates"] = {
            "call_breakdown": {
                "fit": True,
                "score": 82,
                "role": "coaching_problem",
                "title_mode": "problem",
                "stage_code": "completion_next_step",
                "main_thesis": "Звонок подходит для разбора слабого следующего шага.",
                "why_it_matters": "Без срока возврата интерес клиента остается открытым.",
                "proof_type": "sequence_inference",
                "proof_explanation": (
                    "Клиент попросил материалы, менеджер согласился отправить, "
                    "но дата следующего контакта не прозвучала."
                ),
                "supporting_quote": "Хорошо, отправлю информацию.",
                "quote_role": "supports_context",
                "counter_evidence": [],
                "moments": [
                    {
                        "situation": "Менеджер согласился отправить материалы.",
                        "essence": "Открытый интерес не получил контрольную точку.",
                        "proof_explanation": (
                            "В доступном фрагменте есть отправка материалов "
                            "без даты возврата."
                        ),
                        "better_action": "Сразу предложить дату следующего контакта.",
                    }
                ],
            }
        }

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        moment = result.normalized["report_evidence"]["block_candidates"][
            "call_breakdown"
        ]["moments"][0]
        self.assertEqual(
            moment["better_action"],
            "Сразу предложить дату следующего контакта.",
        )

    def test_block_candidate_direct_gap_context_quote_overclaim_fails(self) -> None:
        detail = _valid_detail()
        candidate = _valid_situation_day_block_candidate()
        candidate["proof_type"] = "direct_gap"
        candidate["quote_role"] = "proves_gap"
        candidate["proof_explanation"] = (
            "Цитата ошибочно выбрана как прямое доказательство того, "
            "что менеджер не зафиксировал срок возврата."
        )
        detail["report_evidence"]["block_candidates"] = {"situation_day": candidate}

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn(
            "block_candidate_direct_gap_overclaim",
            self._issue_codes(result.errors),
        )

    def test_block_candidate_quote_role_mismatch_fails(self) -> None:
        detail = _valid_detail()
        candidate = _valid_situation_day_block_candidate()
        candidate["quote_role"] = "proves_gap"
        detail["report_evidence"]["block_candidates"] = {"situation_day": candidate}

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn(
            "block_candidate_quote_role_conflict",
            self._issue_codes(result.errors),
        )

    def test_block_candidate_duplicate_missing_and_action_fails(self) -> None:
        detail = _valid_detail()
        candidate = _valid_situation_day_block_candidate()
        candidate["better_next_action"] = candidate["what_was_missing"]
        detail["report_evidence"]["block_candidates"] = {"situation_day": candidate}

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn(
            "block_candidate_duplicate_missing_action",
            self._issue_codes(result.errors),
        )

    def test_call_breakdown_block_candidate_requires_moments(self) -> None:
        detail = _valid_detail()
        detail["report_evidence"]["block_candidates"] = {
            "call_breakdown": {
                "fit": True,
                "score": 80,
                "role": "coaching_problem",
                "title_mode": "problem",
                "stage_code": "completion_next_step",
                "main_thesis": "Менеджер не закрепил срок возврата после запроса материалов.",
                "why_it_matters": "Без срока возврата интерес клиента остается открытым.",
                "proof_type": "absence_in_context",
                "proof_explanation": (
                    "В доступном фрагменте есть обещание отправить материалы, "
                    "но нет даты следующего контакта."
                ),
                "supporting_quote": None,
                "quote_role": "not_applicable",
                "counter_evidence": [],
            }
        }

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn(
            "block_candidate_missing_required_field",
            self._issue_codes(result.errors),
        )


if __name__ == "__main__":
    unittest.main()
