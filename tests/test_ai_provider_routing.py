"""Unit tests for deterministic AI provider routing."""

from __future__ import annotations

import os
import json
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.calls.analyzer import CallsAnalyzer
from app.agents.calls.extractor import CallsExtractor
from app.agents.calls.orchestrator import CallsManualPilotOrchestrator
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


class AIProviderRoutingTests(unittest.TestCase):
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

    def test_semantically_empty_contract_is_rejected_after_shape_validation(self) -> None:
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

        with self.assertRaises(SemanticAnalysisError) as ctx:
            analyzer._validate_and_normalize_contract(
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

        self.assertEqual(ctx.exception.reason_code, "semantically_empty_analysis")
        self.assertEqual(ctx.exception.normalized_result["score"]["checklist_score"]["score_percent"], 0.0)
        self.assertEqual(ctx.exception.normalized_result["score_by_stage"], [])
        self.assertIn('"score_by_stage": []', ctx.exception.raw_response)

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
