from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT if (PROJECT_ROOT / "app").exists() else PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from report_scripts import split_secret_partitioning_preflight as preflight  # noqa: E402


def _provider_json(*, api_key_env: str, layer: str) -> str:
    return json.dumps(
        [
            {
                "provider": "openai",
                "account_alias": f"{layer}_main",
                "model": "gpt-4o-mini",
                "api_key_env": api_key_env,
                "enabled": True,
            }
        ]
    )


def _grant() -> str:
    return json.dumps(
        {
            "client_id": "edo-analysis",
            "client_type": "service",
            "role": "admin",
            "allowed_artifact_kinds": ["transcript", "llm1_first_pass"],
            "read_surfaces": ["processed_calls_v1"],
            "created_by_admin": "operator",
            "active": True,
        }
    )


def _analysis_env() -> dict[str, str]:
    return {
        "APP_SERVICE": "analysis",
        "CALL_PROCESSING_MODE": "external_service",
        "CALL_PROCESSING_API_BASE_URL": "http://call-processing.test",
        "CALL_PROCESSING_ACCESS_GRANT_JSON": _grant(),
        "AI_LLM2_INPUT_PROFILE": "compact",
        "AI_LLM2_PROVIDERS_JSON": _provider_json(
            api_key_env="OPENAI_API_KEY_LLM2_MAIN",
            layer="llm2",
        ),
        "OPENAI_API_KEY_LLM2_MAIN": "llm2-test-key",
        "AI_LLM3_PROVIDERS_JSON": _provider_json(
            api_key_env="OPENAI_API_KEY_LLM3_MAIN",
            layer="llm3",
        ),
        "OPENAI_API_KEY_LLM3_MAIN": "llm3-test-key",
    }


def _call_processing_env() -> dict[str, str]:
    return {
        "APP_SERVICE": "call_processing",
        "ONLINEPBX_DOMAIN": "example.onpbx.ru",
        "ONLINEPBX_API_KEY": "onlinepbx-test-key",
        "AI_STT_PROVIDERS_JSON": json.dumps(
            [
                {
                    "provider": "assemblyai",
                    "account_alias": "stt_main",
                    "model": "universal",
                    "api_key_env": "ASSEMBLYAI_API_KEY",
                    "enabled": True,
                }
            ]
        ),
        "ASSEMBLYAI_API_KEY": "stt-test-key",
        "AI_LLM1_PROVIDERS_JSON": _provider_json(
            api_key_env="OPENAI_API_KEY_LLM1_MAIN",
            layer="llm1",
        ),
        "OPENAI_API_KEY_LLM1_MAIN": "llm1-test-key",
    }


def test_analysis_preflight_passes_without_upstream_secrets() -> None:
    summary = preflight.build_summary(
        service="analysis",
        env=_analysis_env(),
        strict=True,
    )

    assert summary["status"] == "passed"
    assert summary["required_missing"] == []
    assert summary["forbidden_present"] == []
    assert "LLM2 route" in summary["required_present"]
    assert "LLM3 route" in summary["required_present"]


def test_analysis_preflight_fails_in_legacy_mode() -> None:
    env = _analysis_env()
    env["CALL_PROCESSING_MODE"] = "legacy"

    summary = preflight.build_summary(service="analysis", env=env, strict=False)

    assert summary["status"] == "failed"
    assert "CALL_PROCESSING_MODE=external_service" in summary["required_missing"]


def test_analysis_preflight_fails_without_api_base_url() -> None:
    env = _analysis_env()
    env["CALL_PROCESSING_API_BASE_URL"] = ""

    summary = preflight.build_summary(service="analysis", env=env, strict=False)

    assert summary["status"] == "failed"
    assert "CALL_PROCESSING_API_BASE_URL" in summary["required_missing"]


def test_strict_analysis_preflight_fails_when_upstream_secrets_are_present() -> None:
    env = _analysis_env()
    env["ONLINEPBX_API_KEY"] = "must-not-be-in-analysis"
    env["AI_STT_PROVIDERS_JSON"] = "[]"
    env["OPENAI_API_KEY_LLM1_MAIN"] = "must-not-be-in-analysis"

    summary = preflight.build_summary(service="analysis", env=env, strict=True)

    assert summary["status"] == "failed"
    assert summary["required_missing"] == []
    assert summary["forbidden_present"] == [
        "ONLINEPBX_API_KEY",
        "AI_STT_PROVIDERS_JSON",
        "OPENAI_API_KEY_LLM1_MAIN",
    ]


def test_call_processing_preflight_passes_without_downstream_secrets() -> None:
    summary = preflight.build_summary(
        service="call-processing",
        env=_call_processing_env(),
        strict=True,
    )

    assert summary["status"] == "passed"
    assert summary["required_missing"] == []
    assert summary["forbidden_present"] == []
    assert "STT route" in summary["required_present"]
    assert "LLM1 route" in summary["required_present"]


def test_call_processing_strict_preflight_fails_with_downstream_secrets() -> None:
    env = _call_processing_env()
    env["OPENAI_API_KEY_LLM2_MAIN"] = "must-not-be-in-call-processing"
    env["SMTP_PASSWORD"] = "business-delivery-secret"

    summary = preflight.build_summary(service="call-processing", env=env, strict=True)

    assert summary["status"] == "failed"
    assert summary["required_missing"] == []
    assert summary["forbidden_present"] == ["OPENAI_API_KEY_LLM2_MAIN", "SMTP_PASSWORD"]


def test_cli_prints_json_summary_and_exit_code(capsys) -> None:
    exit_code = preflight.main(
        ["--service", "analysis", "--strict"],
        env=_analysis_env(),
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["service"] == "analysis"
    assert payload["status"] == "passed"
    assert payload["strict"] is True
