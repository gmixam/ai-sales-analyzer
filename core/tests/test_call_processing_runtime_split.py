from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT if (PROJECT_ROOT / "app").exists() else PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.core_shared.config.settings import Settings  # noqa: E402
from app.core_shared.exceptions import ConfigurationError  # noqa: E402
from app.core_shared.workers.celery_app import (  # noqa: E402
    ANALYSIS_QUEUE,
    CALL_PROCESSING_QUEUE,
    DEFAULT_QUEUE,
    SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK,
    SCHEDULED_REPORTING_TASK,
    build_beat_schedule,
    build_task_routes,
    build_worker_queues,
    scheduled_reporting_queue,
)

CALL_PROCESSING_ACCESS_GRANT_JSON = (
    '{"client_id":"edo-analysis","client_type":"service","role":"admin",'
    '"allowed_artifact_kinds":["transcript","transcript_segments","llm1_first_pass"],'
    '"read_surfaces":["processed_calls_v1"],"created_by_admin":"operator"}'
)


def _base_settings(**overrides: object) -> Settings:
    data: dict[str, object] = {
        "database_url": "postgresql://user:pass@localhost:5432/test_db",
        "postgres_db": "test_db",
        "postgres_user": "user",
        "postgres_password": "pass",
        "redis_url": "redis://:pass@localhost:6379/0",
        "redis_password": "pass",
        "app_env": "production",
        "openai_api_key": "test-key",
        "assemblyai_api_key": "test-key",
        "stt_provider": "assemblyai",
        "onlinepbx_domain": "example.onpbx.ru",
        "onlinepbx_api_key": "test-key",
        "strict_service_secret_partitioning": False,
        "openai_api_key_stt_main": "",
        "openai_api_key_llm1_main": "",
        "openai_api_key_llm2_main": "",
        "openai_api_key_llm3_main": "",
        "ai_stt_providers_json": "",
        "ai_stt_fixed_account_alias": "",
        "ai_stt_force_account_alias": "",
        "ai_llm1_providers_json": "",
        "ai_llm1_fixed_account_alias": "",
        "ai_llm1_force_account_alias": "",
        "ai_llm2_providers_json": "",
        "ai_llm2_fixed_account_alias": "",
        "ai_llm2_force_account_alias": "",
        "ai_llm3_providers_json": "",
        "ai_llm3_fixed_account_alias": "",
        "ai_llm3_force_account_alias": "",
        "smtp_user": "",
        "smtp_password": "",
        "telegram_bot_token": "",
        "test_delivery_email_to": "",
        "test_delivery_telegram_chat_id": "",
    }
    data.update(overrides)
    return Settings(**data)


def test_analysis_external_service_starts_without_upstream_provider_secrets() -> None:
    settings = _base_settings(
        app_service="analysis",
        call_processing_mode="external_service",
        call_processing_api_base_url="http://call-processing.test",
        call_processing_access_grant_json=CALL_PROCESSING_ACCESS_GRANT_JSON,
        openai_api_key="",
        assemblyai_api_key="",
        onlinepbx_domain="",
        onlinepbx_api_key="",
    )

    assert settings.app_service == "analysis"
    assert settings.call_processing_mode == "external_service"
    assert settings.onlinepbx_base_url == ""


def test_analysis_service_rejects_missing_external_service_endpoint() -> None:
    with pytest.raises(ConfigurationError, match="CALL_PROCESSING_API_BASE_URL"):
        _base_settings(
            app_service="analysis",
            call_processing_mode="external_service",
            call_processing_api_base_url="",
            call_processing_access_grant_json=CALL_PROCESSING_ACCESS_GRANT_JSON,
            openai_api_key="",
            assemblyai_api_key="",
            onlinepbx_domain="",
            onlinepbx_api_key="",
        )


def test_strict_analysis_service_rejects_upstream_secrets_and_provider_config() -> None:
    with pytest.raises(
        ConfigurationError,
        match="forbids upstream secrets/config.*AI_LLM1_PROVIDERS_JSON.*OPENAI_API_KEY_LLM1_MAIN",
    ):
        _base_settings(
            app_service="analysis",
            call_processing_mode="external_service",
            call_processing_api_base_url="http://call-processing.test",
            call_processing_access_grant_json=CALL_PROCESSING_ACCESS_GRANT_JSON,
            strict_service_secret_partitioning=True,
            onlinepbx_domain="",
            onlinepbx_api_key="",
            assemblyai_api_key="",
            openai_api_key_llm1_main="llm1-secret",
            ai_llm1_providers_json="""
            [
              {
                "provider": "openai",
                "account_alias": "llm1_main",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY_LLM1_MAIN"
              }
            ]
            """,
        )


def test_non_strict_analysis_service_warns_about_upstream_secret_leak() -> None:
    with pytest.warns(RuntimeWarning, match="APP_SERVICE=analysis"):
        settings = _base_settings(
            app_service="analysis",
            call_processing_mode="external_service",
            call_processing_api_base_url="http://call-processing.test",
            call_processing_access_grant_json=CALL_PROCESSING_ACCESS_GRANT_JSON,
            onlinepbx_domain="",
            onlinepbx_api_key="leaked-onlinepbx-key",
            assemblyai_api_key="",
        )

    assert settings.app_service == "analysis"


def test_call_processing_requires_source_and_stt_secrets_but_not_delivery() -> None:
    settings = _base_settings(
        app_service="call_processing",
        smtp_user="",
        smtp_password="",
        telegram_bot_token="",
        ai_llm2_providers_json="",
        ai_llm3_providers_json="",
    )

    assert settings.app_service == "call_processing"
    assert settings.has_smtp is False
    assert settings.has_telegram is False

    with pytest.raises(ConfigurationError, match="ONLINEPBX_DOMAIN"):
        _base_settings(app_service="call_processing", onlinepbx_domain="")

    with pytest.raises(ConfigurationError, match="ASSEMBLYAI_API_KEY"):
        _base_settings(app_service="call_processing", assemblyai_api_key="")


def test_strict_call_processing_service_rejects_downstream_provider_secrets() -> None:
    with pytest.raises(
        ConfigurationError,
        match="forbids downstream provider secrets/config.*OPENAI_API_KEY_LLM2_MAIN",
    ):
        _base_settings(
            app_service="call_processing",
            strict_service_secret_partitioning=True,
            openai_api_key_llm2_main="llm2-secret",
        )


def test_monolith_legacy_keeps_shared_secret_compatibility() -> None:
    settings = _base_settings(
        app_service="monolith_legacy",
        strict_service_secret_partitioning=True,
        openai_api_key_llm1_main="llm1-secret",
        openai_api_key_llm2_main="llm2-secret",
        openai_api_key_llm3_main="llm3-secret",
        smtp_password="smtp-secret",
        telegram_bot_token="telegram-secret",
    )

    assert settings.app_service == "monolith_legacy"
    assert settings.has_smtp is False
    assert settings.has_telegram is True


def test_analysis_service_rejects_legacy_call_processing_mode() -> None:
    with pytest.raises(ConfigurationError, match="APP_SERVICE=analysis requires"):
        _base_settings(
            app_service="analysis",
            call_processing_mode="legacy",
            call_processing_api_base_url="http://call-processing.test",
            call_processing_access_grant_json=CALL_PROCESSING_ACCESS_GRANT_JSON,
        )


def test_celery_queue_routing_is_split_by_service_identity() -> None:
    assert build_worker_queues("call_processing") == CALL_PROCESSING_QUEUE
    assert build_worker_queues("analysis") == f"{ANALYSIS_QUEUE},{DEFAULT_QUEUE}"
    assert build_worker_queues("monolith_legacy") == "calls,default,analysis,call_processing"

    assert scheduled_reporting_queue("analysis") == ANALYSIS_QUEUE
    assert scheduled_reporting_queue("call_processing") == DEFAULT_QUEUE
    assert build_task_routes("analysis")[SCHEDULED_REPORTING_TASK]["queue"] == ANALYSIS_QUEUE
    assert build_task_routes("monolith_legacy")[SCHEDULED_REPORTING_TASK]["queue"] == DEFAULT_QUEUE
    assert build_task_routes("analysis")[SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK]["queue"] == CALL_PROCESSING_QUEUE


def test_celery_beat_schedule_is_split_by_service_identity() -> None:
    analysis_schedule = build_beat_schedule("analysis")
    assert "scheduled-reviewable-reporting-scan" in analysis_schedule
    assert "scheduled-call-processing-daily-upstream" not in analysis_schedule

    disabled_call_processing_schedule = build_beat_schedule(
        "call_processing",
        call_processing_daily_upstream_enabled=False,
    )
    assert disabled_call_processing_schedule == {}

    call_processing_schedule = build_beat_schedule(
        "call_processing",
        call_processing_daily_upstream_enabled=True,
        call_processing_daily_upstream_hour=0,
        call_processing_daily_upstream_minute=0,
    )
    assert "scheduled-call-processing-daily-upstream" in call_processing_schedule
    assert "scheduled-reviewable-reporting-scan" not in call_processing_schedule
    assert (
        call_processing_schedule["scheduled-call-processing-daily-upstream"]["task"]
        == SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK
    )
    assert (
        call_processing_schedule["scheduled-call-processing-daily-upstream"]["options"]["queue"]
        == CALL_PROCESSING_QUEUE
    )
