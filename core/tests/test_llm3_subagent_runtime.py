from __future__ import annotations

import os
import importlib.util
import json
import sys
import tempfile
import textwrap
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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
CALLS_ROOT = CORE_ROOT / "app" / "agents" / "calls"
REPO_ROOT = CORE_ROOT.parent
REPOSITORY_RUNNER = next(
    path
    for path in (
        REPO_ROOT / "scripts" / "llm_subagent_contract_runner.py",
        CORE_ROOT / "report_scripts" / "llm_subagent_contract_runner.py",
    )
    if path.exists()
)
_MISSING = object()


@contextmanager
def _installed_llm_simulation_module():
    module_names = (
        "app",
        "app.agents",
        "app.agents.calls",
        "app.core_shared",
        "app.core_shared.config",
        "app.core_shared.config.settings",
        "app.agents.calls.llm_simulation",
    )
    saved_modules = {name: sys.modules.get(name, _MISSING) for name in module_names}
    app_package = types.ModuleType("app")
    app_package.__path__ = []  # type: ignore[attr-defined]
    agents_package = types.ModuleType("app.agents")
    agents_package.__path__ = []  # type: ignore[attr-defined]
    calls_package = types.ModuleType("app.agents.calls")
    calls_package.__path__ = []  # type: ignore[attr-defined]
    core_shared_package = types.ModuleType("app.core_shared")
    core_shared_package.__path__ = []  # type: ignore[attr-defined]
    config_package = types.ModuleType("app.core_shared.config")
    config_package.__path__ = []  # type: ignore[attr-defined]
    settings_module = types.ModuleType("app.core_shared.config.settings")
    settings_module.settings = SimpleNamespace(
        ai_llm_simulation_enabled=False,
        ai_llm_simulation_artifact_dir="/tmp/asa_llm_sim_runs",
        ai_llm_simulation_run_id="",
        ai_llm_simulation_seed="",
        ai_llm_execution_mode="openai_compatible",
        ai_llm_subagent_runtime_enabled=False,
        ai_llm_subagent_timeout_sec=300,
        openai_timeout_sec=30,
    )
    sys.modules["app"] = app_package
    sys.modules["app.agents"] = agents_package
    sys.modules["app.agents.calls"] = calls_package
    sys.modules["app.core_shared"] = core_shared_package
    sys.modules["app.core_shared.config"] = config_package
    sys.modules["app.core_shared.config.settings"] = settings_module
    setattr(app_package, "agents", agents_package)
    setattr(app_package, "core_shared", core_shared_package)
    setattr(agents_package, "calls", calls_package)
    setattr(core_shared_package, "config", config_package)
    setattr(config_package, "settings", settings_module)

    llm_simulation = _load_module(
        "llm_simulation.py",
        "app.agents.calls.llm_simulation",
    )
    setattr(calls_package, "llm_simulation", llm_simulation)
    try:
        yield llm_simulation
    finally:
        for name, module in reversed(saved_modules.items()):
            if module is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _load_module(filename: str, module_name: str):
    path = CALLS_ROOT / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class LLM3SubagentRuntimeTests(unittest.TestCase):
    def test_repository_runner_handshake_for_llm2_content_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "AI_LLM_EXECUTION_MODE": "subagent_runtime",
                "AI_LLM_SIMULATION_ENABLED": "false",
                "AI_LLM_SUBAGENT_RUNNER_CMD": f"{sys.executable} {REPOSITORY_RUNNER}",
                "AI_LLM_SUBAGENT_ARTIFACT_DIR": tmp,
                "AI_LLM_SUBAGENT_RUN_ID": "subagent-repo-runner-llm2",
            }
            context = {
                "interaction": {
                    "id": "call-llm2-runner",
                    "text": "Клиент попросил отправить материалы и вернуться завтра.",
                },
                "analysis_result_contract_template": {
                    "classification": {},
                    "summary": {},
                    "follow_up": {},
                    "data_quality": {},
                },
                "checklist_definition": {
                    "stages": [
                        {
                            "stage_code": "completion_next_step",
                            "stage_name": "Завершение",
                            "criteria": [
                                {
                                    "criterion_code": "cn_owner_and_deadline",
                                    "criterion_name": "Определил кто делает и когда",
                                }
                            ],
                        }
                    ]
                },
            }

            with _installed_llm_simulation_module() as llm_simulation:
                with patch.dict(os.environ, env, clear=False):
                    result = llm_simulation.request_subagent_llm_content(
                        layer="llm2",
                        request_kind="approved_contract_generation",
                        messages=[
                            {
                                "role": "user",
                                "content": json.dumps(context, ensure_ascii=False),
                            }
                        ],
                        subject_key="call-llm2-runner",
                        instruction_version="test-instruction",
                    )

            content = json.loads(result.content)
            output_payload = json.loads(
                Path(result.metadata["output_artifact"]).read_text(encoding="utf-8")
            )
            self.assertEqual(result.metadata["execution_status"], "subagent_executed")
            self.assertEqual(output_payload["status"], "verified")
            self.assertIsInstance(output_payload["content"], str)
            self.assertEqual(content["classification"]["call_type"], "sales_primary")
            self.assertEqual(content["instruction_version"], "test-instruction")
            self.assertTrue(content["score_by_stage"])
            self.assertTrue(Path(result.metadata["input_artifact"]).exists())

    def test_repository_runner_handshake_for_llm3_direct_composer_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "AI_LLM_EXECUTION_MODE": "subagent_runtime",
                "AI_LLM_SIMULATION_ENABLED": "false",
                "AI_LLM_SUBAGENT_RUNNER_CMD": f"{sys.executable} {REPOSITORY_RUNNER}",
                "AI_LLM_SUBAGENT_ARTIFACT_DIR": tmp,
                "AI_LLM_SUBAGENT_RUN_ID": "subagent-repo-runner-llm3",
            }

            with _installed_llm_simulation_module() as llm_simulation:
                with patch.dict(os.environ, env, clear=False):
                    result = llm_simulation.request_llm3_composer(
                        request_kind="call_tomorrow_wording_composer",
                        subject_key="call_tomorrow_wording_composer",
                        prompt="Return JSON.",
                        payload={
                            "contacts": [
                                {
                                    "contact_key": "client-1",
                                    "reason": "Клиент ждет материалы.",
                                    "next_step": "Позвонить завтра.",
                                }
                            ]
                        },
                    )

            output_artifact = Path(result["_routing"]["output_artifact"])
            output_payload = json.loads(output_artifact.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["contacts"][0]["contact_key"], "client-1")
            self.assertEqual(result["_routing"]["provider"], "subagent_runtime")
            self.assertNotIn("content", output_payload)
            self.assertTrue(output_artifact.exists())

    def test_llm3_direct_composer_uses_openai_compatible_when_simulation_is_off(self) -> None:
        env = {
            "AI_LLM_EXECUTION_MODE": "openai_compatible",
            "AI_LLM_SIMULATION_ENABLED": "false",
            "AI_LLM_SUBAGENT_RUNTIME_ENABLED": "false",
            "OPENAI_API_KEY_LLM3_MAIN": "test-llm3-key",
        }
        saved_openai = sys.modules.get("openai", _MISSING)
        saved_ai_routing = sys.modules.get("app.core_shared.ai_routing", _MISSING)
        calls: list[dict[str, object]] = []

        class FakeCandidate:
            endpoint = None
            model = "gpt-test-llm3"
            api_base = "https://example.test/v1"
            timeout_sec = 17
            max_retries_for_this_provider = 0

            def resolved_api_key(self) -> str:
                return os.environ["OPENAI_API_KEY_LLM3_MAIN"]

        class FakeRoutePlan:
            def __init__(self) -> None:
                self.candidate = FakeCandidate()
                self.success_count = 0
                self.failure_count = 0

            def current_candidate(self) -> FakeCandidate:
                return self.candidate

            def mark_attempt_success(self) -> None:
                self.success_count += 1

            def mark_attempt_failure(self, error: str) -> bool:
                self.failure_count += 1
                return False

            def to_metadata(self, **kwargs: object) -> dict[str, object]:
                return {
                    "layer": "llm3",
                    "selected_provider": "openai",
                    "selected_account_alias": "llm3_main",
                    "selected_model": self.candidate.model,
                    "selected_execution_mode": "openai_compatible",
                    "request_kind": kwargs.get("request_kind"),
                    "usage": kwargs.get("usage"),
                    "execution_status": "executed",
                }

        class FakeAIProviderRouter:
            @staticmethod
            def ensure_execution_compatibility(*args: object, **kwargs: object) -> None:
                return None

            def build_route_plan(self, *, layer: str, subject_key: str) -> FakeRoutePlan:
                self.layer = layer
                self.subject_key = subject_key
                return FakeRoutePlan()

        class FakeCompletions:
            def create(self, **kwargs: object) -> SimpleNamespace:
                calls.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps(
                                    {"status": "verified", "contacts": []},
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

        class FakeOpenAI:
            def __init__(self, *, api_key: str, base_url: str | None) -> None:
                self.api_key = api_key
                self.base_url = base_url
                self.chat = SimpleNamespace(completions=FakeCompletions())

        openai_module = types.ModuleType("openai")
        openai_module.OpenAI = FakeOpenAI
        ai_routing_module = types.ModuleType("app.core_shared.ai_routing")
        ai_routing_module.AIProviderRouter = FakeAIProviderRouter

        try:
            sys.modules["openai"] = openai_module
            sys.modules["app.core_shared.ai_routing"] = ai_routing_module
            with _installed_llm_simulation_module() as llm_simulation:
                with patch.dict(os.environ, env, clear=False):
                    result = llm_simulation.request_llm3_composer(
                        request_kind="call_tomorrow_wording_composer",
                        subject_key="call_tomorrow_wording_composer",
                        prompt="Return JSON.",
                        payload={"contacts": []},
                    )
        finally:
            if saved_openai is _MISSING:
                sys.modules.pop("openai", None)
            else:
                sys.modules["openai"] = saved_openai
            if saved_ai_routing is _MISSING:
                sys.modules.pop("app.core_shared.ai_routing", None)
            else:
                sys.modules["app.core_shared.ai_routing"] = saved_ai_routing

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["_routing"]["selected_provider"], "openai")
        self.assertEqual(result["_routing"]["selected_execution_mode"], "openai_compatible")
        self.assertEqual(result["_routing"]["usage"]["total_tokens"], 18)
        self.assertEqual(calls[0]["model"], "gpt-test-llm3")
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})

    def test_llm3_composer_adapters_use_subagent_runtime_and_named_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = Path(tmp) / "runner.py"
            runner.write_text(
                textwrap.dedent(
                    """
                    import json
                    import sys

                    request = json.load(sys.stdin)
                    print(json.dumps({
                        "status": "verified",
                        "request_kind": request["request_kind"],
                        "contacts": [],
                    }))
                    """
                ),
                encoding="utf-8",
            )
            env = {
                "AI_LLM_EXECUTION_MODE": "subagent_runtime",
                "AI_LLM_SIMULATION_ENABLED": "false",
                "AI_LLM_SUBAGENT_RUNNER_CMD": f"{sys.executable} {runner}",
                "AI_LLM_SIMULATION_ARTIFACT_DIR": tmp,
                "AI_LLM_SIMULATION_RUN_ID": "subagent-routing-test",
            }

            with _installed_llm_simulation_module():
                daily = _load_module(
                    "situation_day_daily_composer.py",
                    "test_subagent_situation_day_daily_composer",
                )
                breakdown = _load_module(
                    "call_breakdown_composer.py",
                    "test_subagent_call_breakdown_composer",
                )
                voice = _load_module(
                    "voice_of_customer_composer.py",
                    "test_subagent_voice_of_customer_composer",
                )
                tomorrow = _load_module(
                    "call_tomorrow_wording_composer.py",
                    "test_subagent_call_tomorrow_wording_composer",
                )
                with patch.dict(os.environ, env, clear=False):
                    results = [
                        daily._request_llm3_daily_situation({"candidates": []}),
                        breakdown._request_llm3_call_breakdown(
                            {"selected_call": {"call_id": "call-1"}}
                        ),
                        voice._request_llm3_voice_of_customer({"signals": []}),
                        tomorrow._request_llm3_call_tomorrow_wording({"contacts": []}),
                    ]

            routing = results[-1]["_routing"]
            run_dir = Path(tmp) / "subagent-routing-test"
            self.assertEqual(
                [result["request_kind"] for result in results],
                [
                    "situation_day_daily_composer",
                    "call_breakdown_composer",
                    "voice_of_customer_composer",
                    "call_tomorrow_wording_composer",
                ],
            )
            self.assertEqual(routing["provider"], "subagent_runtime")
            self.assertEqual(routing["selected_execution_mode"], "subagent_runtime")
            self.assertFalse(routing["simulation"])
            self.assertTrue((run_dir / "llm3_situation_day_input.json").exists())
            self.assertTrue((run_dir / "llm3_situation_day_output.json").exists())
            self.assertTrue((run_dir / "llm3_call_breakdown_input.json").exists())
            self.assertTrue((run_dir / "llm3_call_breakdown_output.json").exists())
            self.assertTrue((run_dir / "llm3_voice_of_customer_input.json").exists())
            self.assertTrue((run_dir / "llm3_voice_of_customer_output.json").exists())
            self.assertTrue((run_dir / "llm3_call_tomorrow_input.json").exists())
            self.assertTrue((run_dir / "llm3_call_tomorrow_output.json").exists())
            self.assertTrue(Path(routing["input_artifact"]).exists())
            self.assertTrue(Path(routing["output_artifact"]).exists())

    def test_subagent_runtime_fails_closed_without_runner_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "AI_LLM_EXECUTION_MODE": "subagent_runtime",
                "AI_LLM_SIMULATION_ENABLED": "true",
                "AI_LLM_SUBAGENT_RUNNER_CMD": "",
                "AI_LLM_AGENT_RUNNER_CMD": "",
                "AI_LLM_SUBAGENT_COMMAND": "",
                "AI_LLM_SIMULATION_ARTIFACT_DIR": tmp,
                "AI_LLM_SIMULATION_RUN_ID": "subagent-fail-closed-test",
            }

            with _installed_llm_simulation_module() as llm_simulation:
                with patch.dict(os.environ, env, clear=False):
                    self.assertTrue(llm_simulation.subagent_runtime_enabled())
                    self.assertEqual(llm_simulation._subagent_runner_command(), [])
                    self.assertEqual(llm_simulation._subagent_command(), "")
                    with self.assertRaisesRegex(RuntimeError, "subagent runtime unavailable"):
                        llm_simulation.request_llm3_composer(
                            request_kind="call_tomorrow_wording_composer",
                            subject_key="call_tomorrow_wording_composer",
                            prompt="Return JSON.",
                            payload={"contacts": []},
                        )

            run_dir = Path(tmp) / "subagent-fail-closed-test"
            failure_outputs = list(run_dir.glob("*_output.json"))
            self.assertTrue(failure_outputs)
            self.assertIn(
                "subagent_runner_unavailable",
                failure_outputs[0].read_text(encoding="utf-8"),
            )

    def test_subagent_artifact_counter_counts_indexed_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "0001_llm2_call_input.json").write_text("{}", encoding="utf-8")
            (run_dir / "0001_llm2_call_output.json").write_text("{}", encoding="utf-8")
            (run_dir / "0002_llm3_call_input.json").write_text("{}", encoding="utf-8")
            (run_dir / "0002_llm3_call_output.json").write_text("{}", encoding="utf-8")

            with _installed_llm_simulation_module() as llm_simulation:
                counts = llm_simulation.count_subagent_artifacts(run_dir)

            self.assertEqual(counts["input_files"], 2)
            self.assertEqual(counts["output_files"], 2)


if __name__ == "__main__":
    unittest.main()
