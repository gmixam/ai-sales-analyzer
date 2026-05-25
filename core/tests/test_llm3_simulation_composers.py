from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
CALLS_ROOT = CORE_ROOT / "app" / "agents" / "calls"
_MISSING = object()


class FakeLLMSimulation(types.ModuleType):
    def __init__(self, responses: dict[str, dict[str, Any]]):
        super().__init__("app.agents.calls.llm_simulation")
        self.responses = responses
        self.requests: list[dict[str, Any]] = []
        self.artifacts: list[tuple[str, Any]] = []

    def is_llm_simulation_enabled(self, layer: str | None = None) -> bool:
        return layer == "llm3"

    def request_llm3_composer(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        return dict(self.responses[kwargs["request_kind"]])

    def write_simulation_artifact(self, artifact_name: str, payload: Any, **_kwargs: Any) -> None:
        self.artifacts.append((artifact_name, payload))


@contextmanager
def _installed_fake_simulation(responses: dict[str, dict[str, Any]]):
    saved_modules = {
        name: sys.modules.get(name, _MISSING)
        for name in (
            "app",
            "app.agents",
            "app.agents.calls",
            "app.agents.calls.llm_simulation",
        )
    }
    app_package = sys.modules.get("app")
    if app_package is None:
        app_package = types.ModuleType("app")
        app_package.__path__ = []  # type: ignore[attr-defined]
        sys.modules["app"] = app_package
    agents_package = sys.modules.get("app.agents")
    if agents_package is None:
        agents_package = types.ModuleType("app.agents")
        agents_package.__path__ = []  # type: ignore[attr-defined]
        sys.modules["app.agents"] = agents_package
    calls_package = sys.modules.get("app.agents.calls")
    if calls_package is None:
        calls_package = types.ModuleType("app.agents.calls")
        calls_package.__path__ = []  # type: ignore[attr-defined]
        sys.modules["app.agents.calls"] = calls_package
    setattr(app_package, "agents", agents_package)
    setattr(agents_package, "calls", calls_package)
    previous_attr = getattr(calls_package, "llm_simulation", _MISSING)
    fake = FakeLLMSimulation(responses)
    sys.modules["app.agents.calls.llm_simulation"] = fake
    setattr(calls_package, "llm_simulation", fake)
    try:
        yield fake
    finally:
        if previous_attr is _MISSING:
            delattr(calls_package, "llm_simulation")
        else:
            setattr(calls_package, "llm_simulation", previous_attr)
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


def _call_tomorrow() -> dict[str, Any]:
    return {
        "contacts": [
            {
                "interaction_id": "call-1",
                "client_call_reference": "Алия • 2026-05-19 • 10:00",
                "status": "open",
                "priority_code": "warm",
                "priority_label": "Тёплый",
                "deadline": None,
                "reason": "Клиент попросил материалы в WhatsApp и готов посмотреть предложение.",
                "next_step": "Отправить материал и согласовать дату возврата к обсуждению.",
                "opening_script": "Добрый день. Отправил материалы, как договорились.",
                "recommendation": "Отправить материал и согласовать дату возврата к обсуждению.",
                "action_profile": "materials_request",
                "signal_text": "Клиент: Скиньте в WhatsApp, я посмотрю.",
                "evidence_signal_text": "Клиент попросил материалы в WhatsApp.",
            }
        ],
        "selection_diagnostics": {},
    }


class LLM3SimulationComposerIntegrationTests(unittest.TestCase):
    def test_request_functions_use_simulation_executor_and_artifact_hooks(self) -> None:
        daily = _load_module("situation_day_daily_composer.py", "test_llm3_daily")
        breakdown = _load_module("call_breakdown_composer.py", "test_llm3_breakdown")
        voice = _load_module("voice_of_customer_composer.py", "test_llm3_voice")
        tomorrow = _load_module("call_tomorrow_wording_composer.py", "test_llm3_tomorrow")
        responses = {
            "situation_day_daily_composer": {"status": "insufficient"},
            "call_breakdown_composer": {"status": "insufficient"},
            "voice_of_customer_composer": {"status": "insufficient"},
            "call_tomorrow_wording_composer": {"status": "verified", "contacts": []},
        }

        with _installed_fake_simulation(responses) as fake:
            daily._request_llm3_daily_situation({"candidates": []})
            breakdown._request_llm3_call_breakdown({"selected_call": {"call_id": "call-1"}})
            voice._request_llm3_voice_of_customer({"signals": []})
            tomorrow._request_llm3_call_tomorrow_wording({"contacts": []})

        self.assertEqual(
            [request["request_kind"] for request in fake.requests],
            [
                "situation_day_daily_composer",
                "call_breakdown_composer",
                "voice_of_customer_composer",
                "call_tomorrow_wording_composer",
            ],
        )
        self.assertTrue(all(request["layer"] == "llm3" for request in fake.requests))
        self.assertTrue(all(request["prompt"] for request in fake.requests))
        self.assertEqual(
            [name for name, _payload in fake.artifacts],
            [
                "llm3_situation_day_input.json",
                "llm3_situation_day_output.json",
                "llm3_call_breakdown_input.json",
                "llm3_call_breakdown_output.json",
                "llm3_voice_of_customer_input.json",
                "llm3_voice_of_customer_output.json",
                "llm3_call_tomorrow_input.json",
                "llm3_call_tomorrow_output.json",
            ],
        )
        self.assertTrue(all(payload.get("_routing", {}).get("simulation") for _name, payload in fake.artifacts[1::2]))

    def test_simulated_call_tomorrow_json_still_passes_normalizer(self) -> None:
        module = _load_module("call_tomorrow_wording_composer.py", "test_llm3_tomorrow_normalized")
        responses = {
            "call_tomorrow_wording_composer": {
                "status": "verified",
                "contacts": [
                    {
                        "contact_key": "call-1",
                        "reason": "Клиент согласовал WhatsApp как канал и ждёт материалы, поэтому важно закрепить следующий контакт.",
                        "next_step": "Отправить материалы и сразу договориться, когда вернуться к вопросам.",
                        "opening_script": "Добрый день, отправил материалы в WhatsApp. Когда удобно обсудить вопросы?",
                        "why_this_wording": "Фраза продолжает согласованный канал и фиксирует следующий шаг.",
                    }
                ],
            }
        }

        with _installed_fake_simulation(responses):
            result = module.compose_call_tomorrow_wording(_call_tomorrow(), llm3_enabled=True)

        contact = result["contacts"][0]
        diagnostics = result["selection_diagnostics"]["wording_composer"]
        self.assertEqual(contact["interaction_id"], "call-1")
        self.assertEqual(contact["priority_code"], "warm")
        self.assertIn("закрепить следующий контакт", contact["reason"])
        self.assertTrue(diagnostics["llm3_used"])
        self.assertEqual(diagnostics["llm3_routing"]["provider"], "llm_simulation")


if __name__ == "__main__":
    unittest.main()
