#!/usr/bin/env python3
"""Container-visible runner for AI_LLM_SUBAGENT_RUNNER_CMD.

This file intentionally mirrors the repository-root runner so Docker services,
where `/app` maps to `core/`, can execute the same contract-preserving runtime
without access to the repository root.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))


def _install_default_env() -> None:
    defaults = {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/test_db",
        "POSTGRES_DB": "test_db",
        "POSTGRES_USER": "user",
        "POSTGRES_PASSWORD": "pass",
        "REDIS_URL": "redis://:pass@localhost:6379/0",
        "REDIS_PASSWORD": "pass",
        "OPENAI_API_KEY": "test-key",
        "ASSEMBLYAI_API_KEY": "test-key",
        "ONLINEPBX_DOMAIN": "example.onpbx.ru",
        "ONLINEPBX_API_KEY": "test-key",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _read_request() -> dict[str, Any]:
    raw = ""
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
    if not raw:
        input_path = os.getenv("AI_LLM_SUBAGENT_INPUT_PATH", "").strip()
        if input_path:
            raw = Path(input_path).read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError("No subagent input JSON was provided")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Subagent input JSON must be an object")
    return parsed


def _messages(request: dict[str, Any]) -> list[dict[str, str]]:
    messages = request.get("messages")
    if not isinstance(messages, list):
        return []
    return [item for item in messages if isinstance(item, dict)]


def _llm_context(request: dict[str, Any]) -> dict[str, Any]:
    from app.agents.calls import llm_simulation

    context = llm_simulation._parse_last_user_json(_messages(request))
    return context if isinstance(context, dict) else {}


def _run_contract(request: dict[str, Any]) -> dict[str, Any]:
    from app.agents.calls import llm_simulation

    layer = str(request.get("layer") or "").strip().lower()
    request_kind = str(request.get("request_kind") or "").strip()

    if layer == "llm1":
        result = llm_simulation._simulate_llm1(_llm_context(request))
        return {
            "status": "verified",
            "layer": layer,
            "request_kind": request_kind,
            "content": json.dumps(result, ensure_ascii=False),
        }
    if layer == "llm2":
        context = _llm_context(request)
        if request_kind.startswith("llm2a_"):
            result = llm_simulation._simulate_llm2a(context)
        elif request_kind.startswith("llm2b_"):
            result = llm_simulation._simulate_llm2b(context)
        elif request_kind.startswith("llm2c_"):
            result = llm_simulation._simulate_llm2c(context)
        elif request_kind.startswith("llm2d_"):
            result = llm_simulation._simulate_llm2d(context)
        else:
            result = llm_simulation._simulate_llm2(
                context,
                instruction_version=request.get("instruction_version"),
            )
        return {
            "status": "verified",
            "layer": layer,
            "request_kind": request_kind,
            "content": json.dumps(result, ensure_ascii=False),
        }
    if layer == "llm3":
        payload = request.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        if request_kind == "situation_day_daily_composer":
            return llm_simulation._simulate_llm3_daily_situation(payload)
        if request_kind == "call_breakdown_composer":
            return llm_simulation._simulate_llm3_call_breakdown(payload)
        if request_kind == "voice_of_customer_composer":
            return llm_simulation._simulate_llm3_voice_of_customer(payload)
        if request_kind == "call_tomorrow_wording_composer":
            return llm_simulation._simulate_llm3_call_tomorrow(payload)
        return {"status": "failed", "reason": f"unsupported_llm3_request:{request_kind}"}
    return {"status": "failed", "reason": f"unsupported_layer:{layer or 'unknown'}"}


def _write_output(result: dict[str, Any]) -> None:
    output_path = os.getenv("AI_LLM_SUBAGENT_OUTPUT_PATH", "").strip()
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, default=str))


def main() -> int:
    _install_default_env()
    try:
        _write_output(_run_contract(_read_request()))
    except Exception as exc:
        failure = {"status": "failed", "reason": "runner_error", "error": str(exc)}
        _write_output(failure)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
