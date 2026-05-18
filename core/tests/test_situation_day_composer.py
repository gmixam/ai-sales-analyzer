from __future__ import annotations

import sys
import unittest
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "situation_day_composer.py"
SPEC = importlib.util.spec_from_file_location("situation_day_composer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
situation_day_composer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = situation_day_composer
SPEC.loader.exec_module(situation_day_composer)

SituationDayComposer = situation_day_composer.SituationDayComposer
build_llm3_contract_payload = situation_day_composer.build_llm3_contract_payload
build_situation_day_candidate_pool = situation_day_composer.build_situation_day_candidate_pool
compose_situation_day = situation_day_composer.compose_situation_day


def _artifact(
    transcript: str,
    *,
    interaction_id: str | None = None,
    report_evidence: dict | None = None,
) -> SimpleNamespace:
    interaction_uuid = interaction_id or str(uuid4())
    return SimpleNamespace(
        interaction=SimpleNamespace(
            id=interaction_uuid,
            text=transcript,
            duration_sec=300,
            metadata_={
                "call_date": "2026-05-14 09:48:54",
                "contact_phone": "+77070000000",
            },
        ),
        analysis=SimpleNamespace(
            id=str(uuid4()),
            scores_detail={
                "report_evidence_version": "v1",
                "report_evidence": report_evidence or {},
            },
        ),
        original_analysis=None,
        manager=None,
        call_started_at=datetime(2026, 5, 14, 9, 48, 54, tzinfo=UTC),
    )


class SituationDayComposerTests(unittest.TestCase):
    def test_no_data_when_no_artifacts(self) -> None:
        result = compose_situation_day([])

        self.assertEqual(result["status"], "no_data")
        self.assertTrue(result["no_verified_situation_day"])
        self.assertEqual(result["quality_diagnostics"]["reason"], "no_calls")

    def test_detects_proposal_without_microqualification(self) -> None:
        call_id = str(uuid4())
        transcript = (
            "Клиент: Расскажите, пожалуйста, про электронную платформу для подписания "
            "договоров не на бумажном носителе. У нас с основным заказчиком договоры "
            "уже подписываются электронно, а с другими контрагентами часть договоров "
            "пока идет на бумаге. Клиент: Вы можете коммерческое предложение просто "
            "отправить? Менеджер: Да, отправлю коммерческое предложение в WhatsApp. "
            "Клиент: Хорошо, меня зовут Камали. Менеджер: Спасибо, отправлю."
        )

        result = compose_situation_day([_artifact(transcript, interaction_id=call_id)])

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["selected_call_id"], call_id)
        self.assertEqual(result["proof_type"], "sequence_inference")
        self.assertIn("КП", result["problem_title"])
        self.assertIn("сколько", result["suggested_phrase"])
        self.assertEqual(result["coaching_view"]["source"], "report_evidence.situation_day_composer.v1")

    def test_prefers_complex_b2b_over_simple_interest(self) -> None:
        b2b_call_id = str(uuid4())
        interest_call_id = str(uuid4())
        b2b_transcript = (
            "Клиент: У нас сеть частных школ, всего 16 школ по Казахстану. Каждая "
            "школа как отдельное юрлицо, но нужен общий кабинет. Директора и "
            "сотрудники одной школы не должны видеть договоры другой школы, а "
            "головной офис должен видеть все договора. Пользователей может быть до "
            "50, пик подписаний идет с мая по сентябрь. Менеджер: Да, понял, "
            "доступы можно разграничить. Клиент: Нам важно подписывать через ЭЦП, "
            "потому что по SMS могут быть юридические риски. Менеджер: Давайте я "
            "сейчас уточню техническую схему и перезвоню."
        )
        interest_transcript = (
            "Клиент: Нам интересно посмотреть электронное подписание договоров. "
            "Менеджер: Я уточню и отправлю информацию. Клиент: Хорошо, жду."
        )

        result = compose_situation_day(
            [
                _artifact(interest_transcript, interaction_id=interest_call_id),
                _artifact(b2b_transcript, interaction_id=b2b_call_id),
            ]
        )

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["selected_call_id"], b2b_call_id)
        self.assertIn("B2B", result["problem_title"])
        self.assertIn("16 школ", result["client_context"])
        self.assertIn("встреч", result["suggested_phrase"])

    def test_uses_report_evidence_block_candidate(self) -> None:
        call_id = str(uuid4())
        transcript = (
            "Клиент: У нас 150 АВР в месяц, бухгалтерия создает документы, "
            "региональный менеджер проверяет ставку и реквизиты. Нужны роли "
            "доступа по регионам и общий доступ руководства. Менеджер: Да, можно. "
            "Клиент: Тогда я ожидаю сумму тарифа до 10 человек. Менеджер: Я уточню "
            "тариф и перезвоню."
        )
        report_evidence = {
            "block_candidates": {
                "situation_day": {
                    "fit": True,
                    "score": 91,
                    "role": "coaching_problem",
                    "title_mode": "problem",
                    "stage_code": "completion_next_step",
                    "proof_type": "sequence_inference",
                    "main_thesis": "Сложный B2B-запрос остался без управляемого следующего шага",
                    "client_context": (
                        "Клиент описал процесс АВР: 150 документов в месяц, "
                        "бухгалтерия, региональные менеджеры, роли доступа и тариф до 10 человек."
                    ),
                    "what_happened": (
                        "Клиент сам дал карту процесса, а менеджер отвечал короткими "
                        "подтверждениями и завершил обещанием уточнить тариф."
                    ),
                    "what_was_missing": (
                        "Не было резюме требований, демо, участников встречи и "
                        "конкретного времени следующего шага."
                    ),
                    "why_it_matters": (
                        "Такой запрос нужно вести как проектную продажу, иначе он "
                        "сводится к отправке цены без ценности."
                    ),
                    "better_next_action": (
                        "Резюмировать требования и назначить короткое демо по сценарию АВР."
                    ),
                    "scripts": [
                        (
                            "Правильно понял: 150 АВР в месяц, роли по регионам и "
                            "до 10 пользователей. Давайте покажу этот сценарий на демо."
                        )
                    ],
                    "dialogue_fragment": [
                        {
                            "speaker": "client",
                            "text": "У нас 150 АВР в месяц, бухгалтерия создает документы, региональный менеджер проверяет ставку и реквизиты.",
                        },
                        {
                            "speaker": "manager",
                            "text": "Я уточню тариф и перезвоню.",
                        },
                    ],
                }
            }
        }

        result = compose_situation_day(
            [_artifact(transcript, interaction_id=call_id, report_evidence=report_evidence)]
        )

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["selected_call_id"], call_id)
        self.assertEqual(
            result["selection_diagnostics"]["selected"]["source"],
            "report_evidence.block_candidates.situation_day",
        )

    def test_llm3_contract_payload_is_bounded_to_candidates(self) -> None:
        transcript = (
            "Клиент: Вы можете коммерческое предложение отправить? Менеджер: Да, "
            "отправлю в WhatsApp. Клиент: Хорошо, жду."
        )
        candidates = build_situation_day_candidate_pool([_artifact(transcript)])

        payload = build_llm3_contract_payload(candidates)

        self.assertEqual(payload["contract_version"], "situation_day_composer_v1")
        self.assertLessEqual(len(payload["candidates"]), 8)
        self.assertIn("required_output_keys", payload)

    def test_composer_exposes_internal_candidate_pool(self) -> None:
        composer = SituationDayComposer()
        transcript = (
            "Клиент: Нам интересно решение по ЭДО. Менеджер: Я уточню и перезвоню. "
            "Клиент: Хорошо."
        )

        pool = composer.build_candidate_pool([_artifact(transcript)])

        self.assertTrue(pool)
        self.assertEqual(pool[0].pattern_code, "interest_without_decision")


if __name__ == "__main__":
    unittest.main()
