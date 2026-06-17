from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4


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

from app.agents.call_processing import LLM1FirstPassPayload  # noqa: E402
from app.agents.calls.analyzer import APPROVED_INSTRUCTION_VERSION, CallsAnalyzer  # noqa: E402
from app.core_shared.exceptions import AnalysisError  # noqa: E402


def _interaction() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        external_id="llm1-external-mode-call",
        department_id=uuid4(),
        manager_id=None,
        source="onlinepbx",
        duration_sec=360,
        text="Client: Please send the materials. Manager: I will send them today.",
        metadata_={"external_call_code": "llm1-external-mode-call"},
    )


def _artifact(*, include_speaker_role_mapping: bool = True) -> LLM1FirstPassPayload:
    payload = LLM1FirstPassPayload(
        prompt_version="llm1_v1",
        provider="openai",
        model="gpt-test",
        classification={
            "call_type": "sales_primary",
            "scenario_type": "warm_webinar_or_lead",
            "analysis_eligibility": "eligible",
            "eligibility_reason": "sales_relevant_exchange",
        },
        summary={"brief": "Client asked for materials; manager agreed to send them."},
        follow_up={"next_step": "Send materials."},
        data_quality={"transcript_quality": "sufficient"},
        analysis_focus=["Check whether the manager fixed a concrete next step."],
    )
    if include_speaker_role_mapping:
        payload.speaker_role_mapping = {
            "source": "llm1_role_attribution",
            "stt_provider": "openai",
            "stt_model": "whisper-1",
            "diarization_source": "whisper_time_segments_without_speaker_labels",
            "roles": [
                {
                    "raw_speaker": "A",
                    "role": "unknown",
                    "confidence": "low",
                    "evidence": [],
                    "notes": "Whisper did not provide speaker diarization",
                }
            ],
            "dialogue_turns": [
                {
                    "role": "client",
                    "text": "Client: Please send the materials.",
                    "confidence": "medium",
                    "evidence": ["asks for materials"],
                },
                {
                    "role": "manager",
                    "text": "Manager: I will send them today.",
                    "confidence": "medium",
                    "evidence": ["commits to send materials"],
                },
            ],
            "quality": {
                "diarization_quality": "low",
                "role_attribution_quality": "medium",
                "warnings": ["technical_speaker_labels_unavailable"],
            },
        }
    return payload


class CallProcessingLLM1ExternalModeTests(unittest.TestCase):
    def test_legacy_mode_still_invokes_runtime_llm1(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()

        with patch.dict(os.environ, {"CALL_PROCESSING_MODE": "legacy"}, clear=False), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            return_value={"analysis_focus": ["legacy focus"]},
        ) as llm1, patch.object(
            analyzer,
            "_analyze_call_with_layered_llm2",
            return_value={"ok": True},
        ) as llm2:
            result = analyzer.analyze_call(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
            )

        self.assertEqual(result, {"ok": True})
        llm1.assert_called_once()
        llm2.assert_called_once()
        self.assertEqual(llm2.call_args.kwargs["llm1_first_pass"]["analysis_focus"], ["legacy focus"])

    def test_external_mode_uses_valid_artifact_without_calling_llm1(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()
        captured: dict = {}

        def fake_llm2(**kwargs):
            captured.update(kwargs["llm1_first_pass"])
            return {"ok": True}

        with patch.dict(
            os.environ,
            {"CALL_PROCESSING_MODE": "external_service"},
            clear=False,
        ), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            side_effect=AssertionError("LLM-1 runtime must not run"),
        ) as llm1, patch.object(
            analyzer,
            "_request_llm_content",
            side_effect=AssertionError("LLM-1 content request must not run"),
        ), patch.object(
            analyzer,
            "_analyze_call_with_layered_llm2",
            side_effect=fake_llm2,
        ) as llm2:
            result = analyzer.analyze_call(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
                llm1_first_pass_artifact=_artifact(),
            )

        self.assertEqual(result, {"ok": True})
        llm1.assert_not_called()
        llm2.assert_called_once()
        self.assertEqual(captured["analysis_focus"], ["Check whether the manager fixed a concrete next step."])
        self.assertEqual(captured["classification"]["call_type"], "sales_primary")
        self.assertEqual(
            captured["speaker_role_mapping"]["diarization_source"],
            "whisper_time_segments_without_speaker_labels",
        )
        self.assertEqual(captured["speaker_role_mapping"]["roles"][0]["role"], "unknown")
        self.assertEqual(
            captured["speaker_role_mapping"]["dialogue_turns"][1]["role"],
            "manager",
        )

    def test_external_mode_accepts_legacy_artifact_without_speaker_mapping(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()
        captured: dict = {}

        def fake_llm2(**kwargs):
            captured.update(kwargs["llm1_first_pass"])
            return {"ok": True}

        with patch.dict(
            os.environ,
            {"CALL_PROCESSING_MODE": "external_service"},
            clear=False,
        ), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            side_effect=AssertionError("LLM-1 runtime must not run"),
        ), patch.object(
            analyzer,
            "_analyze_call_with_layered_llm2",
            side_effect=fake_llm2,
        ):
            result = analyzer.analyze_call(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
                llm1_first_pass_artifact=_artifact(include_speaker_role_mapping=False),
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["speaker_role_mapping"], {})

    def test_external_mode_missing_artifact_fails_before_llm2(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()

        with patch.dict(
            os.environ,
            {"CALL_PROCESSING_MODE": "external_service"},
            clear=False,
        ), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            side_effect=AssertionError("LLM-1 runtime must not run"),
        ) as llm1, patch.object(
            analyzer,
            "_analyze_call_with_layered_llm2",
            side_effect=AssertionError("LLM-2 must not run"),
        ) as llm2:
            with self.assertRaisesRegex(AnalysisError, "partial-missing: llm1_first_pass_v1"):
                analyzer.analyze_call(
                    interaction=interaction,
                    instruction_version=APPROVED_INSTRUCTION_VERSION,
                )

        llm1.assert_not_called()
        llm2.assert_not_called()


if __name__ == "__main__":
    unittest.main()
