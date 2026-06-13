from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT if (PROJECT_ROOT / "app").exists() else PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.core_shared.config.settings import Settings
from app.core_shared.exceptions import ConfigurationError
from app.core_shared.workers.celery_app import (
    ANALYSIS_QUEUE,
    CALL_PROCESSING_QUEUE,
    DEFAULT_QUEUE,
    SCHEDULED_REPORTING_TASK,
    build_task_routes,
    build_worker_queues,
    scheduled_reporting_queue,
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
    }
    data.update(overrides)
    return Settings(**data)


def test_analysis_external_service_starts_without_upstream_provider_secrets() -> None:
    settings = _base_settings(
        app_service="analysis",
        call_processing_mode="external_service",
        call_processing_api_base_url="http://call-processing.test",
        call_processing_access_grant_json=(
            '{"client_id":"edo-analysis","client_type":"service","role":"admin",'
            '"allowed_artifact_kinds":["transcript","transcript_segments","llm1_first_pass"],'
            '"read_surfaces":["processed_calls_v1"],"created_by_admin":"operator"}'
        ),
        openai_api_key="",
        assemblyai_api_key="",
        onlinepbx_domain="",
        onlinepbx_api_key="",
    )

    assert settings.app_service == "analysis"
    assert settings.call_processing_mode == "external_service"
    assert settings.onlinepbx_base_url == ""


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


def test_analysis_service_rejects_legacy_call_processing_mode() -> None:
    with pytest.raises(ConfigurationError, match="APP_SERVICE=analysis requires"):
        _base_settings(
            app_service="analysis",
            call_processing_mode="legacy",
            call_processing_api_base_url="http://call-processing.test",
            call_processing_access_grant_json='{"client_id":"edo-analysis","client_type":"service","role":"admin","created_by_admin":"operator"}',
        )


def test_celery_queue_routing_is_split_by_service_identity() -> None:
    assert build_worker_queues("call_processing") == CALL_PROCESSING_QUEUE
    assert build_worker_queues("analysis") == f"{ANALYSIS_QUEUE},{DEFAULT_QUEUE}"
    assert build_worker_queues("monolith_legacy") == "calls,default,analysis,call_processing"

    assert scheduled_reporting_queue("analysis") == ANALYSIS_QUEUE
    assert scheduled_reporting_queue("call_processing") == DEFAULT_QUEUE
    assert build_task_routes("analysis")[SCHEDULED_REPORTING_TASK]["queue"] == ANALYSIS_QUEUE
    assert build_task_routes("monolith_legacy")[SCHEDULED_REPORTING_TASK]["queue"] == DEFAULT_QUEUE
