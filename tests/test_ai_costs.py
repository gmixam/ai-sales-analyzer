"""Unit tests for estimated AI cost accounting."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

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

CORE_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.calls.ai_costs import (  # noqa: E402
    estimate_call_processing_costs,
    estimate_run_ai_costs,
    merge_split_ai_costs,
)


class AICostsTest(unittest.TestCase):
    def test_estimates_stt_and_llm_current_run_costs(self) -> None:
        interaction = SimpleNamespace(
            id="call-1",
            duration_sec=121,
            metadata_={
                "ai_routing": {
                    "stt": {
                        "layer": "stt",
                        "selected_provider": "openai",
                        "selected_model": "whisper-1",
                        "execution_status": "executed",
                        "executed": True,
                        "request_kind": "speech_to_text",
                        "usage": {"duration_sec": 121, "billable_minutes": 3},
                    },
                    "llm2_history": [
                        {
                            "layer": "llm2",
                            "selected_provider": "openai",
                            "selected_model": "gpt-5.4-mini",
                            "execution_status": "executed",
                            "executed": True,
                            "request_kind": "llm2a_facts_scenes",
                            "usage": {
                                "prompt_tokens": 1000,
                                "completion_tokens": 200,
                                "total_tokens": 1200,
                            },
                        }
                    ],
                }
            },
        )
        result = estimate_run_ai_costs(
            build_summary={"transcripts_built": 1, "analyses_built": 1},
            artifacts=[SimpleNamespace(interaction=interaction)],
            reports=[],
            selected_interactions_count=1,
            manager_day_budget_usdt=1.0,
        )

        self.assertEqual(result["currency"], "USDT")
        self.assertEqual(result["cost_status"], "partial")
        self.assertEqual(result["stt_cost_usdt"], 0.018)
        self.assertEqual(result["llm2_cost_usdt"], 0.00165)
        self.assertEqual(result["budget_status"], "within_budget")

    def test_missing_price_is_not_reported_as_zero(self) -> None:
        interaction = SimpleNamespace(
            id="call-1",
            duration_sec=60,
            metadata_={
                "ai_routing": {
                    "llm2": {
                        "layer": "llm2",
                        "selected_provider": "openai",
                        "selected_model": "unknown-model",
                        "execution_status": "executed",
                        "executed": True,
                        "request_kind": "approved_contract_generation",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                    }
                }
            },
        )
        result = estimate_run_ai_costs(
            build_summary={"transcripts_built": 0, "analyses_built": 1},
            artifacts=[SimpleNamespace(interaction=interaction)],
            reports=[],
            selected_interactions_count=1,
        )

        self.assertEqual(result["cost_status"], "price_missing")
        self.assertEqual(result["llm2_cost_usdt"], None)
        self.assertEqual(result["total_current_run_cost_usdt"], 0.0)

    def test_reuse_does_not_add_current_run_cost(self) -> None:
        interaction = SimpleNamespace(
            id="call-1",
            duration_sec=180,
            metadata_={
                "ai_routing": {
                    "stt": {
                        "layer": "stt",
                        "selected_provider": "openai",
                        "selected_model": "whisper-1",
                        "execution_status": "executed",
                        "executed": True,
                        "usage": {"duration_sec": 180},
                    }
                }
            },
        )
        result = estimate_run_ai_costs(
            build_summary={"transcripts_built": 0, "transcripts_reused": 1, "analyses_built": 0},
            artifacts=[SimpleNamespace(interaction=interaction)],
            reports=[],
            selected_interactions_count=1,
        )

        self.assertEqual(result["cost_status"], "not_used")
        self.assertEqual(result["total_current_run_cost_usdt"], 0.0)
        self.assertEqual(result["by_layer"], [])

    def test_estimates_call_processing_upstream_stt_and_llm1(self) -> None:
        result = estimate_call_processing_costs(
            execution_entries=[
                {
                    "layer": "stt",
                    "interaction_id": "call-1",
                    "provider": "openai",
                    "model": "whisper-1",
                    "duration_sec": 121,
                    "usage": {"duration_sec": 121},
                },
                {
                    "artifact_kind": "llm1_first_pass",
                    "interaction_id": "call-1",
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
                },
                {
                    "artifact_kind": "llm1_first_pass",
                    "interaction_id": "call-reused",
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
                    "reused": True,
                },
            ],
            planned={"transcripts_built": 1, "llm1_first_pass_built": 1},
            mode="ensure",
        )

        self.assertEqual(result["schema_version"], "split_upstream_ai_costs_v1")
        self.assertEqual(result["cost_status"], "available")
        self.assertEqual(result["stt_cost_usdt"], 0.018)
        self.assertEqual(result["llm1_cost_usdt"], 0.00165)
        self.assertEqual(result["total_current_run_cost_usdt"], 0.01965)
        self.assertEqual(len(result["by_layer"]), 2)

    def test_call_processing_missing_usage_is_not_zero(self) -> None:
        result = estimate_call_processing_costs(
            execution_entries=[
                {
                    "artifact_kind": "llm1_first_pass",
                    "interaction_id": "call-1",
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "usage": {"total_tokens": 1200},
                }
            ],
            mode="ensure",
        )

        self.assertEqual(result["cost_status"], "usage_missing")
        self.assertEqual(result["llm1_cost_usdt"], None)
        self.assertEqual(result["total_current_run_cost_usdt"], 0.0)

    def test_call_processing_dry_run_has_no_billable_work(self) -> None:
        result = estimate_call_processing_costs(
            execution_entries=[
                {
                    "layer": "stt",
                    "interaction_id": "call-1",
                    "provider": "openai",
                    "model": "whisper-1",
                    "duration_sec": 60,
                }
            ],
            planned={"transcripts_built": 1},
            mode="dry_run",
        )

        self.assertEqual(result["cost_status"], "no_billable_work")
        self.assertEqual(result["total_current_run_cost_usdt"], 0.0)
        self.assertEqual(result["by_layer"], [])

    def test_merge_split_ai_costs_preserves_top_level_contract(self) -> None:
        upstream = estimate_call_processing_costs(
            execution_entries=[
                {
                    "layer": "stt",
                    "interaction_id": "call-1",
                    "provider": "openai",
                    "model": "whisper-1",
                    "duration_sec": 60,
                }
            ],
            mode="ensure",
        )
        downstream = {
            "schema_version": "ai_costs_v1",
            "pricing_catalog_version": "ai_cost_pricing_usdt_2026-06-04_v1",
            "currency": "USDT",
            "cost_status": "available",
            "budget_status": "no_budget_configured",
            "stt_cost_usdt": None,
            "llm1_cost_usdt": None,
            "llm2_cost_usdt": 0.002,
            "llm3_cost_usdt": 0.003,
            "total_current_run_cost_usdt": 0.005,
            "reused_artifact_original_cost_usdt": None,
            "by_layer": [
                {
                    "layer": "llm2",
                    "request_kind": "llm2a",
                    "used_count": 1,
                    "cost_status": "available",
                    "current_run_cost_usdt": 0.002,
                },
                {
                    "layer": "llm3",
                    "request_kind": "manager_daily",
                    "used_count": 1,
                    "cost_status": "available",
                    "current_run_cost_usdt": 0.003,
                },
            ],
        }

        result = merge_split_ai_costs(
            upstream,
            downstream,
            counters={"transcribed_calls": 1, "analyzed_calls": 1, "manager_day_reports": 1},
        )

        self.assertEqual(result["schema_version"], "split_ai_costs_v1")
        self.assertEqual(result["cost_status"], "available")
        self.assertEqual(result["stt_cost_usdt"], 0.006)
        self.assertEqual(result["llm2_cost_usdt"], 0.002)
        self.assertEqual(result["llm3_cost_usdt"], 0.003)
        self.assertEqual(result["total_current_run_cost_usdt"], 0.011)
        self.assertEqual(result["cost_per_analyzed_call_usdt"], 0.011)
        self.assertIn("upstream", result)
        self.assertIn("downstream", result)


if __name__ == "__main__":
    unittest.main()
