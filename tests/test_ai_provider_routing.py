"""Unit tests for deterministic AI provider routing."""

from __future__ import annotations

import os
import importlib.util
import json
import sys
import tempfile
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.calls.analyzer import (
    APPROVED_INSTRUCTION_VERSION,
    EXPERIMENTAL_CONTEXT_EVIDENCE_INSTRUCTION_VERSION,
    EXPERIMENTAL_UNIVERSAL_EVIDENCE_INSTRUCTION_VERSION,
    CallsAnalyzer,
)
from app.agents.calls.extractor import CallsExtractor
from app.agents.calls.orchestrator import CallsManualPilotOrchestrator
from app.agents.calls.openai_chat_compat import build_chat_completion_kwargs
from app.core_shared.ai_routing import AIProviderRouter
from app.core_shared.config.settings import Settings
from app.core_shared.exceptions import AnalysisError, ExtractionError, SemanticAnalysisError
from app.agents.calls.schemas import TranscriptResult


def _build_settings(**overrides: object) -> Settings:
    """Create isolated settings for routing tests."""
    base = {
        "database_url": "postgresql://user:pass@localhost:5432/test_db",
        "postgres_db": "test_db",
        "postgres_user": "user",
        "postgres_password": "pass",
        "redis_url": "redis://:pass@localhost:6379/0",
        "redis_password": "pass",
        "openai_api_key": "test-key",
        "openai_model_classify": "gpt-4o-mini",
        "openai_model_analyze": "gpt-4o",
        "openai_model_stt": "whisper-1",
        "assemblyai_api_key": "test-key",
        "assemblyai_language": "ru",
        "stt_provider": "assemblyai",
        "manual_live_stt_provider": "",
        "stt_language": "ru",
        "ai_stt_routing_policy": "fixed",
        "ai_stt_fixed_account_alias": "",
        "ai_stt_force_account_alias": "",
        "ai_llm1_routing_policy": "fixed",
        "ai_llm1_fixed_account_alias": "",
        "ai_llm1_force_account_alias": "",
        "ai_llm2_routing_policy": "fixed",
        "ai_llm2_fixed_account_alias": "",
        "ai_llm2_force_account_alias": "",
        "onlinepbx_domain": "example.onpbx.ru",
        "onlinepbx_api_key": "test-key",
        "bitrix24_webhook_url": "",
    }
    base.update(overrides)
    return Settings(**base)


def _llm_simulation_contract_available() -> bool:
    """Return True once the shared LLM simulation integration is present."""
    module_candidates = (
        "app.agents.calls.llm_simulation",
        "app.core_shared.llm_simulation",
        "app.core_shared.ai_llm_simulation",
        "app.core_shared.llm_simulation_executor",
        "app.core_shared.config.llm_simulation",
        "app.core_shared.testing.llm_simulation",
    )
    for name in module_candidates:
        try:
            if importlib.util.find_spec(name) is not None:
                return True
        except ModuleNotFoundError:
            continue
    return "ai_llm_simulation_enabled" in getattr(Settings, "model_fields", {})


def _simulation_metadata_is_marked(metadata: dict[str, object]) -> bool:
    """Accept a small set of explicit simulation audit markers."""
    if metadata.get("simulated") is True:
        return True
    if metadata.get("execution_status") == "simulated":
        return True
    return "simulat" in json.dumps(metadata, ensure_ascii=False).lower()


def _simulation_artifact_metadata_present(metadata: dict[str, object]) -> bool:
    """Return True when routing metadata points at simulation input/output artifacts."""
    flattened = json.dumps(metadata, ensure_ascii=False)
    if "/tmp/asa_llm_sim_runs/" in flattened:
        return True
    return any("artifact" in str(key).lower() and value for key, value in metadata.items())


def _simulation_env() -> dict[str, str]:
    return {
        "AI_LLM_SIMULATION_ENABLED": "true",
        "AI_LLM_SIMULATION_RUN_ID": "routing-test-run",
        "AI_LLM_SIMULATION_SEED": "routing-test-seed",
    }


def _subagent_env(artifact_dir: str) -> dict[str, str]:
    return {
        "AI_LLM_SIMULATION_ENABLED": "false",
        "AI_LLM_EXECUTION_MODE": "subagent_runtime",
        "AI_LLM_SUBAGENT_RUNTIME_ENABLED": "false",
        "AI_LLM_SUBAGENT_RUNTIME_LAYERS": "",
        "AI_LLM_SUBAGENT_COMMAND": "",
        "AI_LLM_SUBAGENT_RUN_ID": "routing-subagent-test-run",
        "AI_LLM_SUBAGENT_ARTIFACT_DIR": artifact_dir,
    }


class AIProviderRoutingTests(unittest.TestCase):
    def test_kimi_k26_chat_kwargs_force_supported_temperature(self) -> None:
        kwargs = build_chat_completion_kwargs(
            model="kimi-k2.6",
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=8192,
            timeout=30,
            messages=[{"role": "user", "content": "test"}],
        )

        self.assertEqual(kwargs["temperature"], 1)
        self.assertEqual(kwargs["max_tokens"], 8192)

    def test_kimi_k25_chat_kwargs_force_supported_temperature(self) -> None:
        kwargs = build_chat_completion_kwargs(
            model="kimi-k2.5",
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=8192,
            timeout=30,
            messages=[{"role": "user", "content": "test"}],
        )

        self.assertEqual(kwargs["temperature"], 1)
        self.assertEqual(kwargs["max_tokens"], 8192)

    def test_layer_scoped_subagent_runtime_keeps_llm1_on_api(self) -> None:
        from app.agents.calls.llm_simulation import subagent_runtime_enabled

        with patch.dict(
            os.environ,
            {
                "AI_LLM_EXECUTION_MODE": "openai_compatible",
                "AI_LLM_SUBAGENT_RUNTIME_ENABLED": "false",
                "AI_LLM_SUBAGENT_RUNTIME_LAYERS": "llm2,llm3",
            },
            clear=False,
        ):
            self.assertFalse(subagent_runtime_enabled(layer="llm1"))
            self.assertTrue(subagent_runtime_enabled(layer="llm2"))
            self.assertTrue(subagent_runtime_enabled(layer="llm3"))
            self.assertTrue(subagent_runtime_enabled())

    def test_analyzer_prompt_context_includes_report_evidence_contract(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="prompt-context-case",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=300,
            text="Клиент: Скиньте в WhatsApp, я посмотрю.",
            metadata_={
                "external_call_code": "prompt-context-case",
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-05-04 09:00:00",
                "direction": "out",
                "phone": "+77070000000",
            },
        )

        context = analyzer.build_prompt_context(interaction)

        self.assertEqual(
            context["analysis_result_contract_template"]["instruction_version"],
            APPROVED_INSTRUCTION_VERSION,
        )
        self.assertEqual(
            APPROVED_INSTRUCTION_VERSION,
            "edo_sales_mvp1_call_analysis_v15_block_ready",
        )
        self.assertIn("REPORT_EVIDENCE_CONTRACT.md", context["source_of_truth_priority"])
        self.assertIn("report_evidence_contract_markdown", context["approved_sources"])
        report_evidence_source = context["approved_sources"]["report_evidence_contract_markdown"]
        self.assertTrue(
            "Report Evidence Contract" in report_evidence_source
            or "REPORT_EVIDENCE_CONTRACT.md" in report_evidence_source
        )
        self.assertIn("report_evidence", report_evidence_source)

    def test_experimental_v16_prompt_context_adds_context_evidence_overlay(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="prompt-context-v16-case",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=300,
            text="Клиент: Ладно, хорошо, я перезвоню.",
            metadata_={
                "external_call_code": "prompt-context-v16-case",
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-05-14 09:00:00",
                "direction": "out",
                "phone": "+77070000000",
            },
        )

        default_context = analyzer.build_prompt_context(interaction)
        experimental_context = analyzer.build_prompt_context(
            interaction,
            instruction_version=EXPERIMENTAL_CONTEXT_EVIDENCE_INSTRUCTION_VERSION,
        )

        self.assertNotIn(
            "LLM2 v16 Context Evidence Overlay",
            default_context["prompt_assets"]["analyze"],
        )
        self.assertIn(
            "LLM2 v16 Context Evidence Overlay",
            experimental_context["prompt_assets"]["analyze"],
        )
        self.assertEqual(
            experimental_context["analysis_result_contract_template"]["instruction_version"],
            EXPERIMENTAL_CONTEXT_EVIDENCE_INSTRUCTION_VERSION,
        )
        self.assertIn(
            "Do not treat the presence of a short quote as proof",
            experimental_context["prompt_assets"]["analyze"],
        )

    def test_experimental_v17_prompt_context_adds_universal_evidence_overlay(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="prompt-context-v17-case",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=300,
            text="Клиент: Пришлите расчет, потом решим по обучению.",
            metadata_={
                "external_call_code": "prompt-context-v17-case",
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-05-18 09:00:00",
                "direction": "out",
                "phone": "+77070000000",
            },
        )

        default_assets = analyzer.get_prompt_assets()
        experimental_assets = analyzer.get_prompt_assets(
            instruction_version=EXPERIMENTAL_UNIVERSAL_EVIDENCE_INSTRUCTION_VERSION,
        )
        experimental_context = analyzer.build_prompt_context(
            interaction,
            instruction_version=EXPERIMENTAL_UNIVERSAL_EVIDENCE_INSTRUCTION_VERSION,
        )

        self.assertEqual(
            EXPERIMENTAL_UNIVERSAL_EVIDENCE_INSTRUCTION_VERSION,
            "edo_sales_mvp1_call_analysis_v17_univ_evidence",
        )
        self.assertNotIn(
            "LLM2 v17 Universal Evidence Boundary Overlay",
            default_assets.analyze,
        )
        self.assertIn(
            "LLM2 v17 Universal Evidence Boundary Overlay",
            experimental_assets.analyze,
        )
        self.assertIn(
            "LLM3 and the deterministic report layer own final block selection",
            experimental_assets.analyze,
        )
        self.assertIn(
            "LLM2 v17 Universal Evidence Boundary Overlay",
            experimental_context["prompt_assets"]["analyze"],
        )
        self.assertEqual(
            experimental_context["analysis_result_contract_template"]["instruction_version"],
            EXPERIMENTAL_UNIVERSAL_EVIDENCE_INSTRUCTION_VERSION,
        )

    def test_analyzer_score_population_handles_dict_wrapped_stage_scores(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        contract = {
            "score": {"checklist_score": {}},
            "score_by_stage": [
                {"stage_score": {"score": 2}, "max_stage_score": {"max_score": 4}},
                {"stage_score": {"value": 1}, "max_stage_score": {"value": 2}},
            ],
        }

        analyzer._populate_checklist_score(contract)

        self.assertEqual(contract["score"]["checklist_score"]["total_points"], 3)
        self.assertEqual(contract["score"]["checklist_score"]["max_points"], 6)
        self.assertEqual(contract["score"]["checklist_score"]["score_percent"], 50.0)

    def test_fixed_policy_resolves_configured_alias(self) -> None:
        settings = _build_settings(
            ai_stt_routing_policy="fixed",
            ai_stt_fixed_account_alias="stt_fallback",
            ai_stt_providers_json="""
            [
              {
                "provider": "assemblyai",
                "account_alias": "stt_primary",
                "model": "assemblyai_default",
                "api_key_env": "ASSEMBLYAI_API_KEY",
                "priority": 1
              },
              {
                "provider": "openai",
                "account_alias": "stt_fallback",
                "model": "whisper-1",
                "api_key_env": "OPENAI_API_KEY",
                "priority": 2
              }
            ]
            """,
        )
        router = AIProviderRouter(app_settings=settings)

        plan = router.build_route_plan(layer="stt", subject_key="case-1")

        self.assertEqual(plan.policy, "fixed")
        self.assertEqual(plan.current_candidate().account_alias, "stt_fallback")

    def test_failover_policy_advances_to_next_candidate(self) -> None:
        settings = _build_settings(
            ai_llm2_routing_policy="failover",
            ai_llm2_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm2_primary",
                "model": "gpt-4o",
                "api_key_env": "OPENAI_API_KEY",
                "priority": 1
              },
              {
                "provider": "openai",
                "account_alias": "llm2_fallback",
                "model": "gpt-4.1",
                "api_key_env": "OPENAI_API_KEY",
                "priority": 2
              }
            ]
            """,
        )
        router = AIProviderRouter(app_settings=settings)

        plan = router.build_route_plan(layer="llm2", subject_key="interaction-1")
        can_fallback = plan.mark_attempt_failure("timeout")

        self.assertTrue(can_fallback)
        self.assertTrue(plan.fallback_used)
        self.assertEqual(plan.current_candidate().account_alias, "llm2_fallback")
        self.assertTrue(plan.to_metadata()["provider_failure"])

    def test_weighted_ab_is_deterministic_for_same_subject(self) -> None:
        settings = _build_settings(
            ai_llm1_routing_policy="weighted_ab",
            ai_llm1_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm1_a",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
                "priority": 1,
                "weight": 3
              },
              {
                "provider": "openai",
                "account_alias": "llm1_b",
                "model": "gpt-4.1-mini",
                "api_key_env": "OPENAI_API_KEY",
                "priority": 1,
                "weight": 1
              }
            ]
            """,
        )
        router = AIProviderRouter(app_settings=settings)

        first = router.build_route_plan(layer="llm1", subject_key="same-subject")
        second = router.build_route_plan(layer="llm1", subject_key="same-subject")
        sample_aliases = {
            router.build_route_plan(layer="llm1", subject_key=f"subject-{idx}")
            .current_candidate()
            .account_alias
            for idx in range(20)
        }

        self.assertEqual(first.current_candidate().account_alias, second.current_candidate().account_alias)
        self.assertTrue(sample_aliases.issubset({"llm1_a", "llm1_b"}))
        self.assertGreaterEqual(len(sample_aliases), 1)

    def test_manual_force_override_wins_over_pool_policy(self) -> None:
        settings = _build_settings(
            ai_llm2_routing_policy="failover",
            ai_llm2_force_account_alias="llm2_forced",
            ai_llm2_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm2_primary",
                "model": "gpt-4o",
                "api_key_env": "OPENAI_API_KEY",
                "priority": 1
              },
              {
                "provider": "openai",
                "account_alias": "llm2_forced",
                "model": "gpt-4.1",
                "api_key_env": "OPENAI_API_KEY",
                "priority": 99
              }
            ]
            """,
        )
        router = AIProviderRouter(app_settings=settings)

        plan = router.build_route_plan(layer="llm2", subject_key="interaction-2")

        self.assertEqual(plan.policy, "manual_force")
        self.assertTrue(plan.forced_override)
        self.assertEqual(plan.current_candidate().account_alias, "llm2_forced")

    def test_single_provider_mode_stays_backward_compatible(self) -> None:
        settings = _build_settings(
            stt_provider="assemblyai",
            ai_stt_providers_json="",
        )
        router = AIProviderRouter(app_settings=settings)

        plan = router.build_route_plan(layer="stt", subject_key="legacy-case")

        self.assertEqual(plan.policy, "fixed")
        self.assertEqual(plan.current_candidate().provider, "assemblyai")
        self.assertEqual(plan.current_candidate().account_alias, "legacy_assemblyai_primary")

    def test_supported_stt_candidate_has_execution_capability(self) -> None:
        settings = _build_settings(
            ai_stt_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "stt_openai",
                "model": "whisper-1",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://example-openai-compatible.test/v1"
              }
            ]
            """,
        )
        router = AIProviderRouter(app_settings=settings)

        plan = router.build_route_plan(layer="stt", subject_key="stt-supported")
        candidate = plan.current_candidate()
        router.ensure_execution_compatibility(
            candidate,
            executor_label="STT OpenAI-compatible executor",
            required_execution_mode="openai_compatible",
        )

        metadata = plan.to_metadata()
        self.assertEqual(candidate.execution_mode, "openai_compatible")
        self.assertTrue(candidate.supports_api_base)
        self.assertEqual(metadata["selected_execution_mode"], "openai_compatible")

    def test_unsupported_stt_candidate_fails_fast_with_explicit_adapter_error(self) -> None:
        settings = _build_settings(
            ai_stt_providers_json="""
            [
              {
                "provider": "deepgram",
                "account_alias": "stt_deepgram",
                "model": "nova-3",
                "api_key_env": "OPENAI_API_KEY"
              }
            ]
            """,
        )
        router = AIProviderRouter(app_settings=settings)
        extractor = CallsExtractor(
            department_id="00000000-0000-0000-0000-000000000001",
            db=None,
        )
        extractor.ai_router = router
        candidate = router.build_route_plan(layer="stt", subject_key="stt-unsupported").current_candidate()

        with self.assertRaisesRegex(ExtractionError, "Unsupported STT adapter path"):
            extractor._transcribe_with_candidate(
                audio_path=Path(__file__),
                interaction_id="stt-unsupported",
                candidate=candidate,
            )

    def test_legacy_manual_live_stt_override_still_selects_whisper(self) -> None:
        settings = _build_settings(
            stt_provider="assemblyai",
            manual_live_stt_provider="whisper",
            openai_model_stt="whisper-1",
            ai_stt_providers_json="",
        )
        router = AIProviderRouter(app_settings=settings)

        plan = router.build_route_plan(
            layer="stt",
            subject_key="manual-live-case",
            provider_override="whisper",
        )

        self.assertEqual(plan.policy, "manual_force")
        self.assertEqual(plan.current_candidate().provider, "openai")
        self.assertEqual(plan.current_candidate().model, "whisper-1")

    def test_supported_llm2_candidate_has_openai_compatible_capability(self) -> None:
        settings = _build_settings(
            ai_llm2_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm2_primary",
                "model": "gpt-4o",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://example-openai-compatible.test/v1"
              }
            ]
            """,
        )
        router = AIProviderRouter(app_settings=settings)

        plan = router.build_route_plan(layer="llm2", subject_key="llm2-supported")
        candidate = plan.current_candidate()
        router.ensure_execution_compatibility(
            candidate,
            executor_label="LLM-2 OpenAI-compatible executor",
            required_execution_mode="openai_compatible",
        )

        self.assertEqual(candidate.execution_mode, "openai_compatible")
        self.assertTrue(plan.to_metadata()["selected_requires_openai_compatible_api"])

    def test_supported_llm1_candidate_has_openai_compatible_capability(self) -> None:
        settings = _build_settings(
            ai_llm1_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm1_primary",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://example-openai-compatible.test/v1"
              }
            ]
            """,
        )
        router = AIProviderRouter(app_settings=settings)

        plan = router.build_route_plan(layer="llm1", subject_key="llm1-supported")
        candidate = plan.current_candidate()
        router.ensure_execution_compatibility(
            candidate,
            executor_label="LLM-1 OpenAI-compatible executor",
            required_execution_mode="openai_compatible",
        )

        metadata = plan.to_metadata(request_kind="classification_first_pass")
        self.assertEqual(candidate.execution_mode, "openai_compatible")
        self.assertEqual(metadata["request_kind"], "classification_first_pass")
        self.assertEqual(metadata["execution_status"], "executed")

    @unittest.skipUnless(
        _llm_simulation_contract_available(),
        "shared LLM simulation executor/settings integration is not present yet",
    )
    def test_llm1_simulation_bypasses_openai_and_persists_routing_artifacts(self) -> None:
        settings = _build_settings(
            ai_llm1_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm1_simulated_route",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://example-openai-compatible.test/v1"
              }
            ]
            """,
        )
        analyzer = CallsAnalyzer(
            department_id="00000000-0000-0000-0000-000000000001",
            db=None,
        )
        analyzer.ai_router = AIProviderRouter(app_settings=settings)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="sim-llm1-call",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=240,
            text="Клиент попросил отправить материалы и вернуться завтра.",
            metadata_={"external_call_code": "sim-llm1-call"},
        )

        with patch.dict(os.environ, _simulation_env(), clear=False), patch(
            "app.agents.calls.analyzer.OpenAI",
            side_effect=AssertionError("OpenAI must not be called in LLM simulation mode"),
        ):
            result = analyzer._request_llm1_first_pass(
                interaction=interaction,
                instruction_version="test-instruction",
            )

        self.assertIsInstance(result["classification"], dict)
        self.assertIsInstance(result["summary"], dict)
        self.assertIn("follow_up", result)
        llm1_metadata = interaction.metadata_["ai_routing"]["llm1"]
        self.assertEqual(llm1_metadata["selected_account_alias"], "llm1_simulated_route")
        self.assertEqual(llm1_metadata["request_kind"], "classification_first_pass")
        self.assertTrue(_simulation_metadata_is_marked(llm1_metadata))
        self.assertTrue(_simulation_artifact_metadata_present(llm1_metadata))

    @unittest.skipUnless(
        _llm_simulation_contract_available(),
        "shared LLM simulation executor/settings integration is not present yet",
    )
    def test_llm2_simulation_returns_valid_contract_json_and_persists_routing_artifacts(self) -> None:
        settings = _build_settings(
            ai_llm2_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm2_simulated_route",
                "model": "gpt-4o",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://example-openai-compatible.test/v1"
              }
            ]
            """,
        )
        analyzer = CallsAnalyzer(
            department_id="00000000-0000-0000-0000-000000000001",
            db=None,
        )
        analyzer.ai_router = AIProviderRouter(app_settings=settings)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="sim-llm2-call",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=360,
            text=(
                "Клиент: Скиньте КП в WhatsApp, я посмотрю. "
                "Менеджер: Хорошо, отправлю и завтра перезвоню."
            ),
            metadata_={
                "external_call_code": "sim-llm2-call",
                "call_date": "2026-05-14 09:00:00",
                "direction": "out",
            },
        )
        messages = [
            {"role": "system", "content": analyzer.get_prompt_assets().analyze},
            {
                "role": "user",
                "content": json.dumps(
                    analyzer.build_prompt_context(
                        interaction=interaction,
                        instruction_version=APPROVED_INSTRUCTION_VERSION,
                    ),
                    ensure_ascii=False,
                ),
            },
        ]

        with patch.dict(os.environ, _simulation_env(), clear=False), patch(
            "app.agents.calls.analyzer.OpenAI",
            side_effect=AssertionError("OpenAI must not be called in LLM simulation mode"),
        ):
            content = analyzer._request_analysis_content(
                interaction=interaction,
                messages=messages,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
            )

        raw = json.loads(content)
        self.assertIsInstance(raw, dict)
        normalized = analyzer._load_and_validate_contract(
            content=content,
            interaction=interaction,
            instruction_version=APPROVED_INSTRUCTION_VERSION,
        )
        self.assertEqual(normalized["call"]["call_id"], str(interaction.id))
        self.assertIsInstance(normalized["score_by_stage"], list)
        self.assertTrue(normalized["score_by_stage"])
        llm2_metadata = interaction.metadata_["ai_routing"]["llm2"]
        self.assertEqual(llm2_metadata["selected_account_alias"], "llm2_simulated_route")
        self.assertEqual(llm2_metadata["request_kind"], "approved_contract_generation")
        self.assertTrue(_simulation_metadata_is_marked(llm2_metadata))
        self.assertTrue(_simulation_artifact_metadata_present(llm2_metadata))

    def test_llm2_layered_pass_repairs_malformed_json_once(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            metadata_={},
            text="Клиент попросил материалы.",
        )

        with patch.object(
            analyzer,
            "_request_llm_content",
            side_effect=[
                '{"pass":"LLM-2A","scenes":[{"what_happened":"обрыв}',
                '{"pass":"LLM-2A","scenes":[],"evidence_ledger":[]}',
            ],
        ) as request_mock:
            artifact = analyzer._request_llm2_layered_pass(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
                request_kind="llm2a_facts_scenes",
                system_prompt="Return LLM2A JSON.",
                prompt_context={
                    "llm1_first_pass": {},
                    "checklist_definition": {},
                },
                previous_artifacts={},
                admission_gate={"admitted": True},
            )

        self.assertEqual(artifact["pass"], "LLM-2A")
        self.assertEqual(request_mock.call_count, 2)
        self.assertEqual(
            request_mock.call_args_list[1].kwargs["request_kind"],
            "llm2a_facts_scenes_json_repair",
        )
        diagnostics = artifact["_runtime_input_diagnostics"]
        self.assertTrue(diagnostics["repair_used"])
        self.assertEqual(diagnostics["repair_count"], 1)
        self.assertIsInstance(diagnostics["wall_time_sec"], float)
        self.assertIsInstance(diagnostics["repair_wall_time_sec"], float)

    def test_llm2_layered_pass_captures_provider_usage_diagnostics(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            metadata_={},
            text="Клиент попросил материалы.",
        )

        def request_with_usage(**kwargs: object) -> str:
            analyzer._store_ai_routing_metadata(
                interaction=interaction,
                layer_metadata={
                    "layer": "llm2",
                    "request_kind": kwargs["request_kind"],
                    "selected_provider": "moonshot",
                    "selected_account_alias": "kimi_llm2_main",
                    "selected_model": "kimi-k2.6",
                    "usage": {
                        "prompt_tokens": 120,
                        "completion_tokens": 34,
                        "total_tokens": 154,
                    },
                },
            )
            return '{"pass":"LLM-2A","scenes":[],"evidence_ledger":[]}'

        with patch.object(analyzer, "_request_llm_content", side_effect=request_with_usage):
            artifact = analyzer._request_llm2_layered_pass(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
                request_kind="llm2a_facts_scenes",
                system_prompt="Return LLM2A JSON.",
                prompt_context={
                    "llm1_first_pass": {},
                    "checklist_definition": {},
                },
                previous_artifacts={},
                admission_gate={"admitted": True},
            )

        diagnostics = artifact["_runtime_input_diagnostics"]
        self.assertEqual(diagnostics["provider"], "moonshot")
        self.assertEqual(diagnostics["account_alias"], "kimi_llm2_main")
        self.assertEqual(diagnostics["model"], "kimi-k2.6")
        self.assertEqual(diagnostics["usage"]["total_tokens"], 154)

    def test_llm2_compact_profile_removes_full_contract_from_payloads(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="compact-call",
            duration_sec=240,
            metadata_={
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-06-01T05:22:43+00:00",
                "direction": "out",
                "phone": "+77070000000",
                "segments": [{"speaker": "manager", "text": "Добрый день"}],
            },
            text="Добрый день. Клиент попросил материалы.",
        )
        prompt_context = {
            "llm1_first_pass": {
                "classification": {
                    "call_type": "sales_primary",
                    "analysis_eligibility": "eligible",
                },
                "summary": {"short_summary": "Клиент попросил материалы."},
                "analysis_focus": ["next step"],
            },
            "checklist_definition": {"large": "checklist" * 200, "stages": [{"stage_code": "x"}]},
            "analysis_result_contract_template": {"large": "contract" * 200},
            "approved_sources": {"report_evidence_contract_markdown": "large report contract" * 200},
        }
        llm2a = {
            "scenes": [{"scene_id": "scene_001", "what_happened": "Запрос материалов"}],
            "evidence_ledger": [
                {"evidence_id": "ev_001", "scene_id": "scene_001", "text": "Клиент попросил материалы."},
                {"evidence_id": "ev_002", "scene_id": "scene_001", "text": "Менеджер отправит материалы."},
                {"evidence_id": "ev_003", "scene_id": "scene_002", "text": "Нерелевантная цитата."},
            ],
            "business_outcome_signal": {
                "status": "open",
                "confidence": "medium",
                "reason": "Клиент попросил материалы.",
                "evidence_ids": ["ev_002"],
            },
        }
        llm2b = {
            "criteria_results": [
                {
                    "criterion_code": "cn_fixed_next_step",
                    "criterion_name": "Зафиксировал конкретный следующий шаг",
                    "stage_code": "completion_next_step",
                    "score": 1,
                    "max_score": 2,
                    "comment": "Long criterion comment should not be copied into LLM2D compact payload.",
                    "evidence_ids": ["ev_001"],
                },
                {
                    "criterion_code": "cn_owner",
                    "criterion_name": "Назвал ответственного",
                    "stage_code": "completion_next_step",
                    "score": 0,
                    "max_score": 2,
                    "comment": "Another long criterion comment should stay out.",
                    "evidence_ids": ["ev_001"],
                },
                {
                    "criterion_code": "cn_timing",
                    "criterion_name": "Назвал срок",
                    "stage_code": "completion_next_step",
                    "score": 0,
                    "max_score": 2,
                    "comment": "Third weak criterion should be counted but not listed as a full item.",
                    "evidence_ids": ["ev_001"],
                },
            ],
            "stage_scores": [{"stage_code": "completion_next_step", "score": 1}],
            "gap_claims": [
                {
                    "claim_id": "claim_001",
                    "claim": "Нет закрепленного следующего контакта.",
                    "stage_code": "completion_next_step",
                    "claim_type": "manager_gap",
                    "evidence_ids": ["ev_001"],
                    "expected_behavior": "Long expected behavior should stay out of LLM2D.",
                    "observed_behavior": "Long observed behavior should stay out of LLM2D.",
                    "confidence": "high",
                },
                {"claim_id": "claim_002", "claim": "Rejected claim must not be passed.", "evidence_ids": ["ev_003"]},
            ],
        }
        llm2c = {
            "proof_cards": [
                {
                    "proof_id": "proof_001",
                    "claim_id": "claim_001",
                    "stage_code": "completion_next_step",
                    "claim": "Нет закрепленного следующего контакта.",
                    "claim_type": "manager_gap",
                    "proof_status": "proven",
                    "gap_proven": True,
                    "supporting_evidence_ids": ["ev_001"],
                    "evidence_quote": "Клиент попросил материалы.",
                },
                {
                    "proof_id": "proof_002",
                    "claim_id": "claim_002",
                    "proof_status": "insufficient",
                    "supporting_evidence_ids": ["ev_003"],
                },
            ]
        }

        full = analyzer._build_llm2_layered_user_payload(
            interaction=interaction,
            request_kind="llm2d_recommendations",
            prompt_context=prompt_context,
            previous_artifacts={"llm2a": llm2a, "llm2b": llm2b, "llm2c": llm2c},
            admission_gate={"admitted": True},
            input_profile="full",
        )
        compact = analyzer._build_llm2_layered_user_payload(
            interaction=interaction,
            request_kind="llm2d_recommendations",
            prompt_context=prompt_context,
            previous_artifacts={"llm2a": llm2a, "llm2b": llm2b, "llm2c": llm2c},
            admission_gate={"admitted": True},
            input_profile="compact",
        )

        self.assertIn("mvp1_contract_shape", full)
        self.assertIn("report_evidence_contract_v1", full)
        self.assertIn("llm2a_artifact", full)
        self.assertNotIn("mvp1_contract_shape", compact)
        self.assertNotIn("report_evidence_contract_v1", compact)
        self.assertNotIn("llm2a_artifact", compact)
        self.assertNotIn("criteria_results", compact)
        self.assertNotIn("stage_scores", compact)
        self.assertNotIn("proof_cards", compact)
        self.assertNotIn("quality_rules", compact)
        self.assertNotIn("output_contract", compact)
        self.assertEqual(compact["input_profile"], "compact")
        self.assertIn("scoring_context", compact)
        self.assertEqual(
            compact["scoring_context"]["stage_scores"][0]["stage_code"],
            "completion_next_step",
        )
        self.assertNotIn("weak_criteria", compact["scoring_context"])
        self.assertEqual(
            compact["scoring_context"]["weak_stage_counts"],
            [{"stage_code": "completion_next_step", "weak_count": 3}],
        )
        self.assertEqual(
            len(compact["scoring_context"]["weak_examples_by_stage"][0]["examples"]),
            2,
        )
        self.assertNotIn(
            "Long criterion comment",
            json.dumps(compact, ensure_ascii=False),
        )
        self.assertEqual(
            [claim["claim_id"] for claim in compact["recommendation_sources"]["gap_claims"]],
            ["claim_001"],
        )
        self.assertNotIn(
            "expected_behavior",
            compact["recommendation_sources"]["gap_claims"][0],
        )
        self.assertNotIn(
            "observed_behavior",
            compact["recommendation_sources"]["gap_claims"][0],
        )
        self.assertNotIn(
            "confidence",
            compact["recommendation_sources"]["gap_claims"][0],
        )
        self.assertEqual(
            compact["recommendation_sources"]["accepted_proof_cards"][0]["proof_id"],
            "proof_001",
        )
        self.assertNotIn(
            "evidence_quote",
            compact["recommendation_sources"]["accepted_proof_cards"][0],
        )
        self.assertEqual(compact["evidence_ledger"][0]["evidence_id"], "ev_001")
        self.assertEqual(
            {item["evidence_id"] for item in compact["evidence_ledger"]},
            {"ev_001", "ev_002"},
        )
        self.assertEqual(
            compact["outcome_facts"]["business_outcome"]["evidence_ids"],
            ["ev_002"],
        )
        self.assertLess(
            len(json.dumps(compact, ensure_ascii=False)),
            len(json.dumps(full, ensure_ascii=False)) * 0.55,
        )

    def test_llm2c_compact_no_claims_bypasses_provider_with_valid_artifact(self) -> None:
        from app.agents.calls.llm2_layered_analysis import normalize_llm2_layered_analysis

        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="compact-no-claims",
            duration_sec=120,
            metadata_={},
            text="Клиент попросил материалы.",
        )
        llm2a = {
            "pass": "LLM-2A",
            "call_id": str(interaction.id),
            "scenes": [
                {"scene_id": "scene_001", "what_happened": "Запрос материалов"},
                {"scene_id": "scene_002", "what_happened": "Нерелевантная сцена"},
            ],
            "evidence_ledger": [
                {"evidence_id": "ev_001", "scene_id": "scene_001", "text": "Клиент попросил материалы."},
                {"evidence_id": "ev_002", "scene_id": "scene_002", "text": "Нерелевантная цитата."},
            ],
        }
        llm2b = {
            "pass": "LLM-2B",
            "call_id": str(interaction.id),
            "criteria_results": [],
            "strength_claims": [],
            "gap_claims": [],
        }

        with patch.dict(os.environ, {"AI_LLM2_INPUT_PROFILE": "compact"}, clear=False), patch.object(
            analyzer,
            "_request_llm_content",
            return_value='{"pass":"LLM-2C","proof_cards":[]}',
        ) as request_mock:
            artifact = analyzer._request_llm2_layered_pass(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
                request_kind="llm2c_claim_proof",
                system_prompt="Return LLM2C JSON.",
                prompt_context={},
                previous_artifacts={"llm2a": llm2a, "llm2b": llm2b},
                admission_gate={"admitted": True},
            )

        request_mock.assert_not_called()
        self.assertEqual(artifact["pass"], "LLM-2C")
        self.assertEqual(artifact["artifact_version"], "llm2_pass_2c_v1")
        self.assertEqual(artifact["call_id"], str(interaction.id))
        self.assertEqual(artifact["proof_cards"], [])
        self.assertEqual(artifact["claim_audit"]["input_claim_count"], 0)
        self.assertEqual(artifact["claim_audit"]["proven_count"], 0)
        self.assertEqual(artifact["claim_audit"]["softened_count"], 0)
        self.assertEqual(artifact["claim_audit"]["rejected_count"], 0)
        self.assertEqual(artifact["claim_audit"]["insufficient_count"], 0)
        self.assertEqual(artifact["notes"], [])
        self.assertEqual(artifact["fail_closed"]["unmatched_claim_ids"], [])
        self.assertEqual(artifact["fail_closed"]["reject_reasons"], [])
        diagnostics = artifact["_runtime_input_diagnostics"]
        self.assertTrue(diagnostics["bypass_used"])
        self.assertEqual(diagnostics["bypass_reason"], "no_claims")
        self.assertEqual(diagnostics["input_profile"], "compact")

        normalized = normalize_llm2_layered_analysis(
            {
                "llm2a": llm2a,
                "llm2b": llm2b,
                "llm2c": artifact,
                "llm2d": {
                    "pass": "LLM-2D",
                    "call_id": str(interaction.id),
                    "recommendations": [],
                    "final_normalized_analysis": {},
                },
            },
            transcript=interaction.text,
            validate_evidence=False,
        )
        self.assertTrue(
            normalized.scores_detail["layered_analysis"]["pass_artifacts"]["llm2c"][
                "valid_shape"
            ]
        )
        self.assertEqual(
            normalized.scores_detail["layered_analysis"]["proof_card_counts"]["total"],
            0,
        )

    def test_llm2c_compact_non_empty_claims_calls_provider_without_quality_rules(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="compact-with-claims",
            duration_sec=120,
            metadata_={},
            text="Клиент попросил материалы.",
        )
        llm2a = {
            "pass": "LLM-2A",
            "call_id": str(interaction.id),
            "scenes": [
                {"scene_id": "scene_001", "what_happened": "Запрос материалов"},
                {"scene_id": "scene_002", "what_happened": "Нерелевантная сцена"},
            ],
            "evidence_ledger": [
                {"evidence_id": "ev_001", "scene_id": "scene_001", "text": "Клиент попросил материалы."},
                {"evidence_id": "ev_002", "scene_id": "scene_002", "text": "Нерелевантная цитата."},
            ],
        }
        llm2b = {
            "pass": "LLM-2B",
            "call_id": str(interaction.id),
            "strength_claims": [],
            "gap_claims": [
                {
                    "claim_id": "claim_001",
                    "claim": "Manager did not anchor a next contact.",
                    "stage_code": "completion_next_step",
                    "claim_scope": "scene",
                    "claim_type": "manager_gap",
                    "scene_ids": ["scene_001"],
                    "evidence_ids": ["ev_001"],
                    "expected_behavior": "Long static expected behavior should stay out.",
                    "observed_behavior": "Long observed behavior should stay out.",
                    "confidence": "high",
                }
            ],
        }

        with patch.dict(os.environ, {"AI_LLM2_INPUT_PROFILE": "compact"}, clear=False), patch.object(
            analyzer,
            "_request_llm_content",
            return_value=json.dumps(
                {
                    "pass": "LLM-2C",
                    "call_id": str(interaction.id),
                    "proof_cards": [],
                    "claim_audit": {"input_claim_count": 1},
                }
            ),
        ) as request_mock:
            artifact = analyzer._request_llm2_layered_pass(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
                request_kind="llm2c_claim_proof",
                system_prompt="Return LLM2C JSON.",
                prompt_context={},
                previous_artifacts={"llm2a": llm2a, "llm2b": llm2b},
                admission_gate={"admitted": True},
            )

        request_mock.assert_called_once()
        user_payload = json.loads(request_mock.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(user_payload["claims"]["gap_claims"][0]["claim_id"], "claim_001")
        self.assertNotIn("expected_behavior", user_payload["claims"]["gap_claims"][0])
        self.assertNotIn("observed_behavior", user_payload["claims"]["gap_claims"][0])
        self.assertNotIn("confidence", user_payload["claims"]["gap_claims"][0])
        self.assertEqual(
            [scene["scene_id"] for scene in user_payload["scene_index"]],
            ["scene_001"],
        )
        self.assertEqual(
            [item["evidence_id"] for item in user_payload["evidence_ledger"]],
            ["ev_001"],
        )
        self.assertIn("task_contract", user_payload)
        self.assertNotIn("quality_rules", user_payload["task_contract"])
        self.assertFalse(artifact["_runtime_input_diagnostics"]["bypass_used"])

    def test_llm2a_compact_profile_uses_single_dialogue_input_without_segment_timestamps(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="compact-call",
            duration_sec=120,
            metadata_={
                "manager_name": "Тестовый менеджер",
                "segments": [
                    {
                        "speaker": "manager",
                        "text": "Добрый день, звоню по заявке.",
                        "start_ms": 1000,
                        "end_ms": 2500,
                    },
                    {
                        "speaker": "client",
                        "text": "Пришлите материалы, я посмотрю.",
                        "start_ms": 2600,
                        "end_ms": 4200,
                    },
                ],
            },
            text="Добрый день, звоню по заявке. Пришлите материалы, я посмотрю.",
        )
        payload = analyzer._build_llm2_layered_user_payload(
            interaction=interaction,
            request_kind="llm2a_facts_scenes",
            prompt_context={
                "llm1_first_pass": {
                    "classification": {
                        "call_type": "sales_primary",
                        "analysis_eligibility": "eligible",
                    },
                    "summary": {"short_summary": "Клиент попросил материалы."},
                },
                "checklist_definition": {"large": "checklist" * 200},
            },
            previous_artifacts={},
            admission_gate={"admitted": True},
            input_profile="compact",
        )

        self.assertNotIn("transcript", payload)
        self.assertNotIn("segments", payload)
        self.assertIn("dialogue", payload)
        self.assertEqual(payload["dialogue"][0]["turn_id"], "turn_001")
        self.assertEqual(payload["dialogue"][0]["speaker"], "manager")
        self.assertEqual(payload["dialogue"][0]["text"], "Добрый день, звоню по заявке.")
        self.assertNotIn("start_ms", payload["dialogue"][0])
        self.assertNotIn("end_ms", payload["dialogue"][0])

    def test_llm2b_compact_profile_removes_repeated_score_rules_from_rubric(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="compact-call",
            duration_sec=120,
            metadata_={},
            text="Клиент попросил материалы.",
        )
        llm2a = {
            "scenes": [{"scene_id": "scene_001", "what_happened": "Запрос материалов"}],
            "evidence_ledger": [
                {"evidence_id": "ev_001", "scene_id": "scene_001", "text": "Клиент попросил материалы."}
            ],
            "business_outcome_signal": {"status": "open", "evidence_ids": ["ev_001"]},
        }
        payload = analyzer._build_llm2_layered_user_payload(
            interaction=interaction,
            request_kind="llm2b_scoring_gaps",
            prompt_context={
                "llm1_first_pass": {},
                "checklist_definition": {"large": "checklist" * 200},
            },
            previous_artifacts={"llm2a": llm2a},
            admission_gate={"admitted": True},
            input_profile="compact",
        )

        rubric_text = json.dumps(payload["compact_scoring_rubric"], ensure_ascii=False)
        self.assertNotIn("score_rules", rubric_text)
        self.assertIn("criterion_code", rubric_text)
        self.assertIn("criterion_name", rubric_text)
        self.assertIn("max_score", rubric_text)

    def test_llm2_compact_profile_diagnostics_are_non_secret_aggregates(self) -> None:
        diagnostics = CallsAnalyzer._llm2_payload_diagnostics(
            request_kind="llm2a_facts_scenes",
            input_profile="compact",
            user_payload={
                "call_id": "call-1",
                "dialogue": [{"turn_id": "turn_001", "text": "секретный текст звонка"}],
                "metadata": {"manager_name": "Менеджер"},
            },
        )

        self.assertEqual(diagnostics["input_profile"], "compact")
        self.assertFalse(diagnostics["contains_transcript"])
        self.assertFalse(diagnostics["contains_segments"])
        self.assertNotIn("секретный текст звонка", json.dumps(diagnostics, ensure_ascii=False))

    def test_llm1_subagent_runtime_bypasses_openai_and_persists_artifacts(self) -> None:
        settings = _build_settings(
            ai_llm1_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm1_subagent_route",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://example-openai-compatible.test/v1"
              }
            ]
            """,
        )
        analyzer = CallsAnalyzer(
            department_id="00000000-0000-0000-0000-000000000001",
            db=None,
        )
        analyzer.ai_router = AIProviderRouter(app_settings=settings)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="subagent-llm1-call",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=240,
            text="Клиент попросил отправить материалы и вернуться завтра.",
            metadata_={"external_call_code": "subagent-llm1-call"},
        )
        runner_result = {
            "classification": {
                "call_type": "sales_primary",
                "scenario_type": "repeat_contact",
            },
            "summary": {"short_summary": "Клиент попросил материалы."},
            "follow_up": {
                "next_step_fixed": True,
                "next_step_type": "callback",
                "next_step_text": "Вернуться завтра.",
            },
            "data_quality": {"classification_quality": "subagent"},
            "analysis_focus": ["Проверить конкретность следующего шага."],
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            _subagent_env(tmpdir),
            clear=False,
        ), patch(
            "app.agents.calls.llm_simulation._run_subagent_runner",
            return_value=runner_result,
        ), patch(
            "app.agents.calls.analyzer.OpenAI",
            side_effect=AssertionError("OpenAI must not be called in subagent runtime mode"),
        ):
            result = analyzer._request_llm1_first_pass(
                interaction=interaction,
                instruction_version="test-instruction",
            )

        self.assertEqual(result["classification"]["call_type"], "sales_primary")
        llm1_metadata = interaction.metadata_["ai_routing"]["llm1"]
        self.assertEqual(llm1_metadata["selected_account_alias"], "codex_subagent_runtime")
        self.assertEqual(
            llm1_metadata["planned_real_llm_route"]["selected_account_alias"],
            "llm1_subagent_route",
        )
        self.assertEqual(llm1_metadata["selected_execution_mode"], "subagent_runtime")
        self.assertEqual(llm1_metadata["actual_execution_mode"], "subagent_runtime")
        self.assertEqual(llm1_metadata["execution_status"], "subagent_executed")
        self.assertEqual(llm1_metadata["request_kind"], "classification_first_pass")
        self.assertIn("routing-subagent-test-run", llm1_metadata["input_artifact"])
        self.assertIn("routing-subagent-test-run", llm1_metadata["output_artifact"])

    def test_llm2_subagent_runtime_fails_closed_when_runner_is_unavailable(self) -> None:
        settings = _build_settings(
            ai_llm2_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm2_subagent_route",
                "model": "gpt-4o",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://example-openai-compatible.test/v1"
              }
            ]
            """,
        )
        analyzer = CallsAnalyzer(
            department_id="00000000-0000-0000-0000-000000000001",
            db=None,
        )
        analyzer.ai_router = AIProviderRouter(app_settings=settings)
        interaction = SimpleNamespace(id=uuid4(), metadata_={})

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                **_subagent_env(tmpdir),
                "AI_LLM_SUBAGENT_COMMAND": "definitely_missing_subagent_cmd",
            },
            clear=False,
        ), patch(
            "app.agents.calls.analyzer.OpenAI",
            side_effect=AssertionError("OpenAI must not be called in subagent runtime mode"),
        ):
            with self.assertRaisesRegex(AnalysisError, "subagent runtime failed"):
                analyzer._request_analysis_content(
                    interaction=interaction,
                    messages=[{"role": "user", "content": "test"}],
                    instruction_version="test-instruction",
                )

        llm2_metadata = interaction.metadata_["ai_routing"]["llm2"]
        self.assertEqual(llm2_metadata["selected_account_alias"], "codex_subagent_runtime")
        self.assertEqual(llm2_metadata["selected_execution_mode"], "subagent_runtime")
        self.assertEqual(llm2_metadata["execution_status"], "subagent_failed")
        self.assertTrue(llm2_metadata["provider_failure"])
        self.assertIn("routing-subagent-test-run", llm2_metadata["input_artifact"])
        self.assertIn("routing-subagent-test-run", llm2_metadata["output_artifact"])

    def test_llm1_first_pass_executes_and_persists_usage_metadata(self) -> None:
        settings = _build_settings(
            ai_llm1_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm1_primary",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://example-openai-compatible.test/v1"
              }
            ]
            """,
        )
        analyzer = CallsAnalyzer(
            department_id="00000000-0000-0000-0000-000000000001",
            db=None,
        )
        analyzer.ai_router = AIProviderRouter(app_settings=settings)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="call-1",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=240,
            text="Клиент попросил прислать материалы и вернуться завтра.",
            metadata_={},
        )

        class _FakeOpenAI:
            def __init__(self, **_kwargs) -> None:
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(
                        create=lambda **_kwargs: SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(
                                        content=json.dumps(
                                            {
                                                "classification": {
                                                    "call_type": "sales_primary",
                                                    "scenario_type": "warm_webinar_or_lead",
                                                },
                                                "summary": {
                                                    "short_summary": "Клиент попросил материалы.",
                                                    "next_step_text": "Отправить материалы и перезвонить завтра.",
                                                },
                                                "follow_up": {
                                                    "next_step_fixed": True,
                                                    "next_step_type": "materials_sent",
                                                    "next_step_text": "Отправить материалы и вернуться завтра.",
                                                },
                                                "data_quality": {
                                                    "classification_quality": "usable",
                                                    "analysis_quality": "usable",
                                                },
                                                "analysis_focus": [
                                                    "Проверить, был ли следующий шаг зафиксирован конкретно.",
                                                ],
                                            },
                                            ensure_ascii=False,
                                        )
                                    )
                                )
                            ],
                            usage=SimpleNamespace(
                                prompt_tokens=11,
                                completion_tokens=7,
                                total_tokens=18,
                            ),
                        )
                    )
                )

        with patch("app.agents.calls.analyzer.OpenAI", _FakeOpenAI):
            result = analyzer._request_llm1_first_pass(
                interaction=interaction,
                instruction_version="test-instruction",
            )

        self.assertEqual(result["classification"]["call_type"], "sales_primary")
        self.assertEqual(result["follow_up"]["next_step_fixed"], True)
        llm1_metadata = interaction.metadata_["ai_routing"]["llm1"]
        self.assertEqual(llm1_metadata["selected_account_alias"], "llm1_primary")
        self.assertEqual(llm1_metadata["request_kind"], "classification_first_pass")
        self.assertEqual(llm1_metadata["execution_status"], "executed")
        self.assertEqual(llm1_metadata["selected_api_key_env"], "OPENAI_API_KEY")
        self.assertEqual(llm1_metadata["usage"]["total_tokens"], 18)

    def test_stt_openai_transcribe_persists_actual_execution_site_metadata(self) -> None:
        settings = _build_settings(
            ai_stt_routing_policy="fixed",
            ai_stt_fixed_account_alias="stt_main",
            ai_stt_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "stt_main",
                "model": "whisper-1",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://api.openai.com/v1",
                "endpoint": "/audio/transcriptions",
                "priority": 1
              }
            ]
            """,
        )
        extractor = CallsExtractor(
            department_id="00000000-0000-0000-0000-000000000001",
            db=None,
        )
        extractor.ai_router = AIProviderRouter(app_settings=settings)

        with patch.object(
            extractor,
            "_transcribe_with_candidate",
            return_value=(
                TranscriptResult(
                    interaction_id="stt-case",
                    full_text="test transcript",
                    segments=[],
                ),
                {
                    "executed_endpoint_path": "/audio/transcriptions",
                    "provider_request_id": "req_stt_123",
                },
            ),
        ):
            _result, metadata = extractor.transcribe(
                audio_path=Path(__file__),
                interaction_id="stt-case",
            )

        self.assertEqual(metadata["selected_provider"], "openai")
        self.assertEqual(metadata["selected_account_alias"], "stt_main")
        self.assertEqual(metadata["selected_api_key_env"], "OPENAI_API_KEY")
        self.assertEqual(metadata["selected_model"], "whisper-1")
        self.assertEqual(metadata["selected_api_base"], "https://api.openai.com/v1")
        self.assertEqual(metadata["selected_endpoint"], "/audio/transcriptions")
        self.assertEqual(metadata["executed_endpoint_path"], "/audio/transcriptions")
        self.assertEqual(metadata["provider_request_id"], "req_stt_123")
        self.assertEqual(metadata["execution_status"], "executed")
        self.assertEqual(metadata["request_kind"], "speech_to_text")

    def test_incompatible_llm2_candidate_fails_fast_and_persists_failure_metadata(self) -> None:
        settings = _build_settings(
            ai_llm2_providers_json="""
            [
              {
                "provider": "anthropic",
                "account_alias": "llm2_anthropic",
                "model": "claude-3-7-sonnet",
                "api_key_env": "OPENAI_API_KEY",
                "api_base": "https://example-anthropic.test"
              }
            ]
            """,
        )
        analyzer = CallsAnalyzer(
            department_id="00000000-0000-0000-0000-000000000001",
            db=None,
        )
        analyzer.ai_router = AIProviderRouter(app_settings=settings)
        interaction = SimpleNamespace(id=uuid4(), metadata_={})

        with self.assertRaisesRegex(
            AnalysisError,
            "Provider 'anthropic' account 'llm2_anthropic' is routing-valid",
        ):
            analyzer._request_analysis_content(
                interaction=interaction,
                messages=[{"role": "user", "content": "test"}],
                instruction_version="test-instruction",
            )

        llm2_metadata = interaction.metadata_["ai_routing"]["llm2"]
        self.assertTrue(llm2_metadata["provider_failure"])
        self.assertEqual(llm2_metadata["selected_provider"], "anthropic")
        self.assertEqual(llm2_metadata["selected_execution_mode"], None)
        self.assertEqual(llm2_metadata["attempted"][0]["status"], "failed")
        self.assertIn("routing-valid", llm2_metadata["attempted"][0]["error"])

    def test_analyzer_metadata_persistence_helper_stores_selected_route(self) -> None:
        interaction = SimpleNamespace(id=uuid4(), metadata_={})
        layer_metadata = {
            "layer": "llm2",
            "selected_provider": "openai",
            "selected_account_alias": "llm2_primary",
            "selected_model": "gpt-4o",
            "policy": "failover",
            "fallback_used": False,
            "provider_failure": False,
            "forced_override": False,
            "selected_execution_mode": "openai_compatible",
            "attempted": [],
        }

        CallsAnalyzer._store_ai_routing_metadata(
            interaction=interaction,
            layer_metadata=layer_metadata,
        )

        self.assertIn("ai_routing", interaction.metadata_)
        self.assertEqual(
            interaction.metadata_["ai_routing"]["llm2"]["selected_account_alias"],
            "llm2_primary",
        )

    def test_agreement_deadline_normalization_fits_existing_db_limit(self) -> None:
        self.assertEqual(
            CallsManualPilotOrchestrator._normalize_agreement_deadline(
                {
                    "due_date_text": "2026-04-02T22:30:00+00:00",
                    "due_date_iso": "2026-04-02T22:30:00+00:00",
                }
            ),
            "2026-04-02 22:30",
        )
        self.assertEqual(
            CallsManualPilotOrchestrator._normalize_agreement_deadline(
                {
                    "due_date_text": "Очень длинное описание дедлайна, которое явно не помещается в текущее поле",
                    "due_date_iso": None,
                }
            ),
            "Очень длинное описан",
        )

    def test_semantically_empty_contract_is_preserved_when_semantic_validation_disabled(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="call-semantic-empty",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=240,
            metadata_={
                "external_call_code": "call-semantic-empty",
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-04-07 10:00:00",
                "direction": "out",
                "phone": "+77070000000",
            },
        )

        normalized = analyzer._validate_and_normalize_contract(
            raw_contract={
                "classification": {
                    "call_type": "sales_primary",
                    "scenario_type": "repeat_contact",
                },
                "summary": {
                    "short_summary": "Короткий звонок без содержательного анализа.",
                },
                "score_by_stage": [],
                "strengths": [],
                "gaps": [],
                "recommendations": [],
                "follow_up": {
                    "next_step_fixed": False,
                    "reason_not_fixed": "не определено",
                },
            },
            interaction=interaction,
            instruction_version="edo_sales_mvp1_call_analysis_v1",
        )

        self.assertEqual(normalized["classification"]["call_type"], "sales_primary")
        self.assertNotIn("analysis_eligibility", normalized["classification"])
        self.assertEqual(normalized["score"]["checklist_score"]["score_percent"], 0.0)
        self.assertEqual(normalized["score_by_stage"], [])

    def test_analyzer_repairs_max_score_and_enriches_reporting_fields(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="call-enriched",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=300,
            metadata_={
                "external_call_code": "call-enriched",
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-04-24 10:00:00",
                "direction": "out",
                "phone": "+77070000000",
            },
        )

        normalized = analyzer._validate_and_normalize_contract(
            raw_contract={
                "classification": {
                    "call_type": "sales_primary",
                    "scenario_type": "repeat_contact",
                    "analysis_eligibility": "eligible",
                },
                "summary": {"short_summary": "Продажный звонок с зоной роста."},
                "score_by_stage": [
                    {
                        "stage_code": "qualification_primary",
                        "stage_name": "Квалификация и первичная потребность",
                        "criteria_results": [
                            {
                                "criterion_code": "qp_current_process",
                                "criterion_name": "Выяснил, как сейчас устроен процесс / документооборот",
                                "score": 0,
                                "comment": "Менеджер не выяснил текущий процесс клиента.",
                                "evidence": "Вопрос о текущем процессе не прозвучал.",
                            },
                            {
                                "criterion_code": "qp_no_early_pitch",
                                "criterion_name": "Не ушёл в презентацию слишком рано",
                                "score": 2,
                                "comment": "Менеджер сначала уточнял контекст.",
                                "evidence": "Менеджер не перегружал клиента презентацией.",
                            },
                        ],
                    }
                ],
                "strengths": [],
                "gaps": [],
                "recommendations": [],
                "evidence_fragments": [],
            },
            interaction=interaction,
            instruction_version="edo_sales_mvp1_call_analysis_v1",
        )

        first_criterion = normalized["score_by_stage"][0]["criteria_results"][0]
        self.assertEqual(first_criterion["max_score"], 2)
        self.assertEqual(normalized["score_by_stage"][0]["max_stage_score"], 4)
        self.assertEqual(
            normalized["gaps"][0]["title"],
            "Выяснил, как сейчас устроен процесс / документооборот",
        )
        self.assertEqual(
            normalized["strengths"][0]["title"],
            "Не ушёл в презентацию слишком рано",
        )
        self.assertIn("процесс", normalized["recommendations"][0]["better_phrase"])
        self.assertEqual(normalized["evidence_fragments"][0]["fragment_type"], "missed_opportunity")

    def test_analyzer_guardrail_repairs_sales_score_not_eligible_conflict(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="call-sales-conflict",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=57,
            metadata_={
                "external_call_code": "call-sales-conflict",
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-04-28 14:53:00",
                "direction": "out",
                "phone": "+77070000000",
            },
        )

        normalized = analyzer._validate_and_normalize_contract(
            raw_contract={
                "classification": {
                    "call_type": "sales_primary",
                    "scenario_type": "cold_outbound",
                    "analysis_eligibility": "not_eligible",
                    "eligibility_reason": "duration_below_threshold",
                },
                "summary": {"short_summary": "Короткий, но содержательный продажный звонок."},
                "score_by_stage": [
                    {
                        "stage_code": "contact_start",
                        "stage_name": "Первичный контакт",
                        "criteria_results": [
                            {
                                "criterion_code": "cs_intro_and_company",
                                "criterion_name": "Представился и обозначил компанию",
                                "score": 2,
                                "comment": "Менеджер понятно представился.",
                                "evidence": "Добрый день, это менеджер Dogovor24.",
                            },
                            {
                                "criterion_code": "cs_permission_and_relevance",
                                "criterion_name": "Проверил уместность разговора / возможность говорить",
                                "score": 2,
                                "comment": "Менеджер уточнил, удобно ли говорить.",
                                "evidence": "Вам удобно сейчас коротко обсудить?",
                            },
                            {
                                "criterion_code": "cs_reason_for_call",
                                "criterion_name": "Понятно обозначил причину звонка",
                                "score": 1,
                                "comment": "Причина звонка обозначена кратко.",
                                "evidence": "Звоню по вопросу электронного документооборота.",
                            },
                            {
                                "criterion_code": "cs_tone_and_clarity",
                                "criterion_name": "Сохранил нейтральный, вежливый и понятный тон",
                                "score": 1,
                                "comment": "Тон был корректным.",
                                "evidence": "Менеджер говорил спокойно.",
                            },
                        ],
                    }
                ],
                "strengths": [],
                "gaps": [],
                "recommendations": [],
                "evidence_fragments": [],
            },
            interaction=interaction,
            instruction_version="edo_sales_mvp1_call_analysis_v1",
        )

        self.assertEqual(normalized["classification"]["analysis_eligibility"], "eligible")
        self.assertEqual(
            normalized["classification"]["eligibility_reason"],
            "positive_sales_score_with_sales_evidence",
        )
        self.assertEqual(normalized["score"]["checklist_score"]["score_percent"], 75.0)

    def test_analyzer_guardrail_preserves_support_not_eligible_when_semantic_validation_disabled(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="call-support",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=240,
            metadata_={
                "external_call_code": "call-support",
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-04-28 15:10:00",
                "direction": "in",
                "phone": "+77070000000",
            },
        )

        normalized = analyzer._validate_and_normalize_contract(
            raw_contract={
                "classification": {
                    "call_type": "support",
                    "scenario_type": "hot_incoming_contact",
                    "analysis_eligibility": "not_eligible",
                    "eligibility_reason": "support_only_interaction",
                },
                "summary": {"short_summary": "Технический вопрос клиента."},
                "score_by_stage": [],
                "strengths": [],
                "gaps": [],
                "recommendations": [],
                "evidence_fragments": [],
            },
            interaction=interaction,
            instruction_version="edo_sales_mvp1_call_analysis_v1",
        )

        self.assertEqual(normalized["classification"]["analysis_eligibility"], "not_eligible")
        self.assertEqual(normalized["score"]["checklist_score"]["score_percent"], 0.0)

    def test_analyzer_guardrail_repairs_duration_ge_reason_for_short_call(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = SimpleNamespace(
            id=uuid4(),
            external_id="call-short-reason",
            department_id=uuid4(),
            manager_id=None,
            source="onlinepbx",
            duration_sec=112,
            metadata_={
                "external_call_code": "call-short-reason",
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-04-28 15:20:00",
                "direction": "out",
                "phone": "+77070000000",
            },
        )

        normalized = analyzer._validate_and_normalize_contract(
            raw_contract={
                "classification": {
                    "call_type": "sales_primary",
                    "scenario_type": "cold_outbound",
                    "analysis_eligibility": "eligible",
                    "eligibility_reason": "duration_ge_180_sec_and_sales_relevant",
                },
                "summary": {"short_summary": "Продажный звонок с оценкой."},
                "score_by_stage": [
                    {
                        "stage_code": "contact_start",
                        "stage_name": "Первичный контакт",
                        "criteria_results": [
                            {
                                "criterion_code": "cs_intro_and_company",
                                "criterion_name": "Представился и обозначил компанию",
                                "score": 2,
                                "comment": "Менеджер представился.",
                                "evidence": "Меня зовут ...",
                            }
                        ],
                    }
                ],
                "strengths": [],
                "gaps": [],
                "recommendations": [],
                "evidence_fragments": [],
            },
            interaction=interaction,
            instruction_version="edo_sales_mvp1_call_analysis_v1",
        )

        self.assertEqual(normalized["classification"]["analysis_eligibility"], "eligible")
        self.assertNotIn("duration_ge_180_sec", normalized["classification"]["eligibility_reason"])

    def test_analyzer_can_mark_semantic_empty_support_call_as_not_coachable(self) -> None:
        error = SemanticAnalysisError(
            "Analyzer returned a semantically empty analysis contract.",
            interaction_id="support-call",
            raw_response="{}",
            normalized_result={"classification": {"call_type": "support"}},
            reason_code="semantically_empty_analysis",
        )
        self.assertTrue(
            CallsAnalyzer._should_mark_not_coachable(
                error=error,
                llm1_first_pass={"classification": {"call_type": "support"}},
            )
        )
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        marked = analyzer._mark_not_coachable_result(
            normalized_result=error.normalized_result,
            llm1_first_pass={"classification": {"call_type": "support"}},
        )
        self.assertEqual(marked["classification"]["analysis_eligibility"], "not_eligible")
        self.assertEqual(marked["score_by_stage"], [])

    def test_semantic_retry_instruction_preserves_report_evidence_minimum(self) -> None:
        error = SemanticAnalysisError(
            "Analyzer returned a semantically empty analysis contract.",
            interaction_id="sales-call",
            raw_response="{}",
            normalized_result={"classification": {"call_type": "sales_primary"}},
            reason_code="semantically_empty_analysis",
        )

        instruction = CallsAnalyzer._build_analysis_retry_instruction(error)

        self.assertIn('report_evidence_version="v1"', instruction)
        self.assertIn("`report_evidence.semantic_case`", instruction)
        self.assertIn("`report_block_fit`", instruction)
        self.assertIn("block role", instruction)
        self.assertIn("problem_fit", instruction)
        self.assertIn("proof_type", instruction)
        self.assertIn("counter_evidence", instruction)
        self.assertIn("For `fit=false` or not-relevant block items, prefer `coaching_moment=null`", instruction)
        self.assertIn("never use `none` or `insufficient` there", instruction)
        self.assertIn("every `fit=true` item must include", instruction)
        self.assertIn("canonical `stage_code`", instruction)
        self.assertIn("must be a non-empty exact transcript substring", instruction)
        self.assertIn("`case_type=insufficient_evidence`", instruction)
        self.assertIn("`manager_coaching_moments` must contain at least one item", instruction)
        self.assertIn("return an explicit `evidence_quality=insufficient`", instruction)
        self.assertIn("Do not return `follow_up_candidates` for `refusal`, `tech_service`, or `not_suitable`", instruction)

    def test_analyzer_rejects_fit_true_block_candidate_without_stage_code(self) -> None:
        with self.assertRaises(AnalysisError) as ctx:
            CallsAnalyzer._validate_report_evidence_block_candidate_stage_codes(
                contract={
                    "report_evidence": {
                        "block_candidates": {
                            "situation_day": {
                                "fit": True,
                                "score": 80,
                            }
                        }
                    }
                },
                allowed_stage_codes={"qualification_primary"},
                interaction_id="sales-call",
                raw_response="{}",
            )

        self.assertIn("report_evidence.block_candidates.situation_day.stage_code", str(ctx.exception))

    def test_analyzer_rejects_fit_true_block_candidate_unknown_stage_code(self) -> None:
        with self.assertRaises(AnalysisError) as ctx:
            CallsAnalyzer._validate_report_evidence_block_candidate_stage_codes(
                contract={
                    "report_evidence": {
                        "block_candidates": {
                            "situation_day": {
                                "fit": True,
                                "score": 80,
                                "stage_code": "support",
                            }
                        }
                    }
                },
                allowed_stage_codes={"qualification_primary"},
                interaction_id="sales-call",
                raw_response="{}",
            )

        self.assertIn("unknown stage_code", str(ctx.exception))

    def test_persist_analysis_stores_raw_llm_response_separately_from_normalized_result(self) -> None:
        class _FakeQuery:
            def filter(self, *_args, **_kwargs):
                return self

            def first(self):
                return None

            def delete(self, **_kwargs):
                return None

        class _FakeDb:
            def __init__(self) -> None:
                self.added: list[object] = []

            def query(self, _model):
                return _FakeQuery()

            def add(self, obj):
                self.added.append(obj)

            def commit(self):
                return None

            def refresh(self, _obj):
                return None

        orchestrator = object.__new__(CallsManualPilotOrchestrator)
        orchestrator.db = _FakeDb()
        interaction = SimpleNamespace(
            id=uuid4(),
            department_id=uuid4(),
            manager_id=None,
        )
        result = {
            "instruction_version": "edo_sales_mvp1_call_analysis_v1",
            "score": {"checklist_score": {"score_percent": 81.0}},
            "summary": {"short_summary": "Нормализованный approved result."},
            "strengths": [{"title": "Сильная сторона"}],
            "gaps": [{"title": "Зона роста"}],
            "recommendations": [{"title": "Рекомендация"}],
            "analytics_tags": ["demo"],
            "agreements": [],
            "product_signals": [],
        }
        CallsAnalyzer._store_analysis_forensics(
            interaction=interaction,
            raw_llm_response='{"raw":"llm2 payload"}',
            normalized_result=result,
            failure_reason=None,
        )

        analysis = CallsManualPilotOrchestrator.persist_analysis(
            orchestrator,
            interaction=interaction,
            result=result,
        )

        self.assertEqual(analysis.raw_llm_response, '{"raw":"llm2 payload"}')
        self.assertEqual(analysis.scores_detail, result)
        self.assertFalse(analysis.is_failed)

    def test_persist_analysis_accepts_string_agreement_items(self) -> None:
        class _FakeQuery:
            def filter(self, *_args, **_kwargs):
                return self

            def first(self):
                return None

            def delete(self, **_kwargs):
                return None

        class _FakeDb:
            def __init__(self) -> None:
                self.added: list[object] = []

            def query(self, _model):
                return _FakeQuery()

            def add(self, obj):
                self.added.append(obj)

            def commit(self):
                return None

            def refresh(self, _obj):
                return None

        orchestrator = object.__new__(CallsManualPilotOrchestrator)
        orchestrator.db = _FakeDb()
        interaction = SimpleNamespace(
            id=uuid4(),
            department_id=uuid4(),
            manager_id=None,
        )
        result = {
            "instruction_version": "edo_sales_mvp1_call_analysis_v1",
            "score": {"checklist_score": {"score_percent": 81.0}},
            "summary": {"short_summary": "Нормализованный approved result."},
            "strengths": [],
            "gaps": [],
            "recommendations": [],
            "analytics_tags": [],
            "agreements": ["Клиент договорился прислать документы после разговора."],
            "product_signals": [],
        }

        CallsManualPilotOrchestrator.persist_analysis(
            orchestrator,
            interaction=interaction,
            result=result,
        )

        agreements = [obj for obj in orchestrator.db.added if obj.__class__.__name__ == "Agreement"]
        self.assertEqual(len(agreements), 1)
        self.assertEqual(
            agreements[0].text,
            "Клиент договорился прислать документы после разговора.",
        )

    def test_persist_failed_analysis_keeps_raw_forensics_and_reason_code(self) -> None:
        class _FakeQuery:
            def filter(self, *_args, **_kwargs):
                return self

            def first(self):
                return None

            def delete(self, **_kwargs):
                return None

        class _FakeDb:
            def __init__(self) -> None:
                self.added: list[object] = []

            def query(self, _model):
                return _FakeQuery()

            def add(self, obj):
                self.added.append(obj)

            def commit(self):
                return None

            def refresh(self, _obj):
                return None

        orchestrator = object.__new__(CallsManualPilotOrchestrator)
        orchestrator.db = _FakeDb()
        interaction = SimpleNamespace(
            id=uuid4(),
            department_id=uuid4(),
            manager_id=None,
        )
        normalized_result = {
            "instruction_version": "edo_sales_mvp1_call_analysis_v1",
            "score": {"checklist_score": {"score_percent": 0.0}},
            "summary": {"short_summary": "Пустой нормализованный контракт."},
            "score_by_stage": [],
            "strengths": [],
            "gaps": [],
            "recommendations": [],
            "analytics_tags": [],
        }
        error = SemanticAnalysisError(
            "Analyzer returned a semantically empty analysis contract.",
            interaction_id=str(interaction.id),
            raw_response='{"model":"empty"}',
            normalized_result=normalized_result,
            reason_code="semantically_empty_analysis",
        )

        analysis = CallsManualPilotOrchestrator.persist_failed_analysis(
            orchestrator,
            interaction=interaction,
            error=error,
        )

        self.assertTrue(analysis.is_failed)
        self.assertEqual(analysis.fail_reason, "semantically_empty_analysis")
        self.assertEqual(analysis.raw_llm_response, '{"model":"empty"}')
        self.assertEqual(analysis.scores_detail, normalized_result)


if __name__ == "__main__":
    unittest.main()
