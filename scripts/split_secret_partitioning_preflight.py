#!/usr/bin/env python3
"""Preflight split-service secret partitioning from the current environment."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

SERVICE_ANALYSIS = "analysis"
SERVICE_CALL_PROCESSING = "call-processing"

ANALYSIS_FORBIDDEN_ENV = (
    "ONLINEPBX_DOMAIN",
    "ONLINEPBX_API_KEY",
    "ONLINEPBX_API_BASE_URL",
    "ONLINEPBX_CDR_URL",
    "ASSEMBLYAI_API_KEY",
    "OPENAI_API_KEY_STT_MAIN",
    "AI_STT_PROVIDERS_JSON",
    "AI_STT_FIXED_ACCOUNT_ALIAS",
    "AI_STT_FORCE_ACCOUNT_ALIAS",
    "STT_PROVIDER",
    "MANUAL_LIVE_STT_PROVIDER",
    "OPENAI_API_KEY_LLM1_MAIN",
    "AI_LLM1_PROVIDERS_JSON",
    "AI_LLM1_FIXED_ACCOUNT_ALIAS",
    "AI_LLM1_FORCE_ACCOUNT_ALIAS",
)

CALL_PROCESSING_DOWNSTREAM_ENV = (
    "OPENAI_API_KEY_LLM2_MAIN",
    "OPENAI_API_KEY_LLM3_MAIN",
    "AI_LLM2_PROVIDERS_JSON",
    "AI_LLM2_FIXED_ACCOUNT_ALIAS",
    "AI_LLM2_FORCE_ACCOUNT_ALIAS",
    "AI_LLM3_PROVIDERS_JSON",
    "AI_LLM3_FIXED_ACCOUNT_ALIAS",
    "AI_LLM3_FORCE_ACCOUNT_ALIAS",
    "SMTP_PASSWORD",
    "TEST_DELIVERY_EMAIL_TO",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID_ROP",
    "TEST_DELIVERY_TELEGRAM_CHAT_ID",
)

TRUTHY = {"1", "true", "yes", "y", "on"}


def _present(env: Mapping[str, str], key: str) -> bool:
    return str(env.get(key, "")).strip() != ""


def _value(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key, "")).strip()


def _is_truthy(env: Mapping[str, str], key: str) -> bool:
    return _value(env, key).lower() in TRUTHY


def _add_required(
    *,
    label: str,
    ok: bool,
    required_present: list[str],
    required_missing: list[str],
) -> None:
    target = required_present if ok else required_missing
    target.append(label)


def _json_object_required(env: Mapping[str, str], key: str) -> tuple[bool, str | None]:
    raw = _value(env, key)
    if not raw:
        return False, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False, f"{key} must be valid JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        return False, f"{key} must decode to a JSON object"
    return True, None


def _route_from_providers_json(
    *,
    env: Mapping[str, str],
    layer: str,
    providers_key: str,
) -> tuple[bool, list[str]]:
    raw = _value(env, providers_key)
    if not raw:
        return False, []

    warnings: list[str] = []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False, [f"{providers_key} must be valid JSON: {exc.msg}"]
    if not isinstance(parsed, list):
        return False, [f"{providers_key} must decode to a list of provider entries"]

    enabled_entries = [
        item
        for item in parsed
        if isinstance(item, dict) and bool(item.get("enabled", True))
    ]
    if not enabled_entries:
        return False, [f"{providers_key} has no enabled provider entries"]

    valid_entry_found = False
    for index, entry in enumerate(enabled_entries):
        missing_fields = [
            field
            for field in ("provider", "model", "api_key_env")
            if not str(entry.get(field, "")).strip()
        ]
        if missing_fields:
            fields = ", ".join(missing_fields)
            warnings.append(
                f"{providers_key}[{index}] missing required route fields: {fields}"
            )
            continue
        api_key_env = str(entry["api_key_env"]).strip()
        if not _present(env, api_key_env):
            warnings.append(
                f"{providers_key}[{index}] references missing or empty env {api_key_env}"
            )
            continue
        valid_entry_found = True

    if not valid_entry_found and not warnings:
        warnings.append(f"{providers_key} has no usable enabled {layer} route")
    return valid_entry_found, warnings


def _llm_route_ok(
    *,
    env: Mapping[str, str],
    layer: str,
    providers_key: str,
    fallback_keys: Sequence[str],
) -> tuple[bool, list[str]]:
    json_route_ok, warnings = _route_from_providers_json(
        env=env,
        layer=layer,
        providers_key=providers_key,
    )
    if json_route_ok:
        return True, warnings

    for key in fallback_keys:
        if _present(env, key):
            fallback_warnings = warnings[:]
            fallback_warnings.append(
                f"{layer.upper()} route uses legacy fallback env {key}; prefer {providers_key}"
            )
            return True, fallback_warnings
    return False, warnings


def _stt_route_ok(env: Mapping[str, str]) -> tuple[bool, list[str]]:
    json_route_ok, warnings = _route_from_providers_json(
        env=env,
        layer="stt",
        providers_key="AI_STT_PROVIDERS_JSON",
    )
    if json_route_ok:
        return True, warnings

    provider = _value(env, "STT_PROVIDER").lower() or "assemblyai"
    if provider == "assemblyai":
        return _present(env, "ASSEMBLYAI_API_KEY"), warnings
    if provider in {"openai", "whisper"}:
        return (
            _present(env, "OPENAI_API_KEY_STT_MAIN") or _present(env, "OPENAI_API_KEY"),
            warnings,
        )
    warnings.append(f"Unsupported STT_PROVIDER for preflight route check: {provider}")
    return False, warnings


def _forbidden_present(env: Mapping[str, str], keys: Sequence[str]) -> list[str]:
    return [key for key in keys if _present(env, key)]


def _analysis_summary(env: Mapping[str, str], *, strict: bool) -> dict[str, Any]:
    required_present: list[str] = []
    required_missing: list[str] = []
    warnings: list[str] = []

    _add_required(
        label="APP_SERVICE=analysis",
        ok=_value(env, "APP_SERVICE") == "analysis",
        required_present=required_present,
        required_missing=required_missing,
    )
    _add_required(
        label="CALL_PROCESSING_MODE=external_service",
        ok=_value(env, "CALL_PROCESSING_MODE") == "external_service",
        required_present=required_present,
        required_missing=required_missing,
    )
    _add_required(
        label="CALL_PROCESSING_API_BASE_URL",
        ok=_present(env, "CALL_PROCESSING_API_BASE_URL"),
        required_present=required_present,
        required_missing=required_missing,
    )
    grant_ok, grant_warning = _json_object_required(env, "CALL_PROCESSING_ACCESS_GRANT_JSON")
    _add_required(
        label="CALL_PROCESSING_ACCESS_GRANT_JSON",
        ok=grant_ok,
        required_present=required_present,
        required_missing=required_missing,
    )
    if grant_warning:
        warnings.append(grant_warning)

    llm2_ok, llm2_warnings = _llm_route_ok(
        env=env,
        layer="llm2",
        providers_key="AI_LLM2_PROVIDERS_JSON",
        fallback_keys=("OPENAI_API_KEY_LLM2_MAIN", "OPENAI_API_KEY"),
    )
    warnings.extend(llm2_warnings)
    _add_required(
        label="LLM2 route",
        ok=llm2_ok,
        required_present=required_present,
        required_missing=required_missing,
    )

    llm3_ok, llm3_warnings = _llm_route_ok(
        env=env,
        layer="llm3",
        providers_key="AI_LLM3_PROVIDERS_JSON",
        fallback_keys=("OPENAI_API_KEY_LLM3_MAIN",),
    )
    warnings.extend(llm3_warnings)
    _add_required(
        label="LLM3 route",
        ok=llm3_ok,
        required_present=required_present,
        required_missing=required_missing,
    )

    _add_required(
        label="AI_LLM2_INPUT_PROFILE=compact",
        ok=_value(env, "AI_LLM2_INPUT_PROFILE") == "compact",
        required_present=required_present,
        required_missing=required_missing,
    )

    if _is_truthy(env, "AI_LLM_SIMULATION_ENABLED"):
        warnings.append("AI_LLM_SIMULATION_ENABLED is enabled for analysis preflight")
    if _is_truthy(env, "AI_LLM_SUBAGENT_RUNTIME_ENABLED"):
        warnings.append("AI_LLM_SUBAGENT_RUNTIME_ENABLED is enabled for analysis preflight")

    forbidden_present = _forbidden_present(env, ANALYSIS_FORBIDDEN_ENV)
    for key in forbidden_present:
        warnings.append(f"analysis profile includes upstream-only env {key}")

    failed = bool(required_missing) or (strict and bool(forbidden_present))
    status = "failed" if failed else ("warning" if forbidden_present or warnings else "passed")
    return {
        "service": SERVICE_ANALYSIS,
        "status": status,
        "required_present": required_present,
        "required_missing": required_missing,
        "forbidden_present": forbidden_present,
        "warnings": warnings,
        "strict": strict,
    }


def _call_processing_summary(env: Mapping[str, str], *, strict: bool) -> dict[str, Any]:
    required_present: list[str] = []
    required_missing: list[str] = []
    warnings: list[str] = []

    _add_required(
        label="APP_SERVICE=call_processing",
        ok=_value(env, "APP_SERVICE") == "call_processing",
        required_present=required_present,
        required_missing=required_missing,
    )
    _add_required(
        label="ONLINEPBX_DOMAIN",
        ok=_present(env, "ONLINEPBX_DOMAIN"),
        required_present=required_present,
        required_missing=required_missing,
    )
    _add_required(
        label="ONLINEPBX_API_KEY",
        ok=_present(env, "ONLINEPBX_API_KEY"),
        required_present=required_present,
        required_missing=required_missing,
    )

    stt_ok, stt_warnings = _stt_route_ok(env)
    warnings.extend(stt_warnings)
    _add_required(
        label="STT route",
        ok=stt_ok,
        required_present=required_present,
        required_missing=required_missing,
    )

    llm1_ok, llm1_warnings = _llm_route_ok(
        env=env,
        layer="llm1",
        providers_key="AI_LLM1_PROVIDERS_JSON",
        fallback_keys=("OPENAI_API_KEY_LLM1_MAIN", "OPENAI_API_KEY"),
    )
    warnings.extend(llm1_warnings)
    _add_required(
        label="LLM1 route",
        ok=llm1_ok,
        required_present=required_present,
        required_missing=required_missing,
    )

    forbidden_present = _forbidden_present(env, CALL_PROCESSING_DOWNSTREAM_ENV)
    for key in forbidden_present:
        warnings.append(f"call-processing profile includes downstream-only env {key}")

    failed = bool(required_missing) or (strict and bool(forbidden_present))
    status = "failed" if failed else ("warning" if forbidden_present or warnings else "passed")
    return {
        "service": SERVICE_CALL_PROCESSING,
        "status": status,
        "required_present": required_present,
        "required_missing": required_missing,
        "forbidden_present": forbidden_present,
        "warnings": warnings,
        "strict": strict,
    }


def build_summary(
    *,
    service: str,
    env: Mapping[str, str] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Return a JSON-serializable preflight summary for one split service."""
    source_env = env if env is not None else os.environ
    normalized_service = service.strip().lower()
    if normalized_service == SERVICE_ANALYSIS:
        return _analysis_summary(source_env, strict=strict)
    if normalized_service in {SERVICE_CALL_PROCESSING, "call_processing"}:
        return _call_processing_summary(source_env, strict=strict)
    raise ValueError(f"Unsupported service: {service}")


def _print_text(summary: dict[str, Any]) -> None:
    print(f"Split secret partitioning preflight: {summary['service']}")
    print(f"Status: {summary['status']}")
    print(f"Strict: {summary['strict']}")
    print(f"Required present: {len(summary['required_present'])}")
    print(f"Required missing: {len(summary['required_missing'])}")
    for item in summary["required_missing"]:
        print(f"- missing: {item}")
    print(f"Forbidden present: {len(summary['forbidden_present'])}")
    for item in summary["forbidden_present"]:
        print(f"- forbidden: {item}")
    if summary["warnings"]:
        print("Warnings:")
        for warning in summary["warnings"]:
            print(f"- {warning}")


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service",
        required=True,
        choices=(SERVICE_ANALYSIS, SERVICE_CALL_PROCESSING, "call_processing"),
        help="Split service profile to inspect.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when forbidden service-boundary env vars are present.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format. JSON is the default for automation.",
    )
    args = parser.parse_args(argv)

    summary = build_summary(service=args.service, env=env, strict=args.strict)
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        _print_text(summary)
    return 1 if summary["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
