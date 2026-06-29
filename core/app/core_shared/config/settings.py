"""Typed application settings loaded from environment variables."""

from __future__ import annotations

import json
import warnings
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core_shared.exceptions import ConfigurationError

APP_SERVICE_CALL_PROCESSING = "call_processing"
APP_SERVICE_ANALYSIS = "analysis"
APP_SERVICE_MONOLITH_LEGACY = "monolith_legacy"
APP_SERVICE_VALUES = (
    APP_SERVICE_CALL_PROCESSING,
    APP_SERVICE_ANALYSIS,
    APP_SERVICE_MONOLITH_LEGACY,
)
CALL_PROCESSING_MODE_VALUES = ("legacy", "external_service")
CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE_VALUES = (
    "managers",
    "department",
    "company",
    "onlinepbx_all",
)
ALERT_LEVEL_VALUES = ("info", "warning", "error", "critical")


class Settings(BaseSettings):
    """Centralized application settings for AI Sales Analyzer."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_service: str = Field(default=APP_SERVICE_MONOLITH_LEGACY)
    app_env: str = Field(default="production")
    log_level: str = Field(default="INFO")
    compose_project_name: str = Field(default="asa")
    strict_service_secret_partitioning: bool = Field(default=False)

    # Database
    database_url: PostgresDsn
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # Redis
    redis_url: RedisDsn
    redis_password: str

    # OpenAI
    openai_api_key: str = Field(default="")
    openai_api_key_stt_main: str = Field(default="")
    openai_api_key_llm1_main: str = Field(default="")
    openai_api_key_llm2_main: str = Field(default="")
    openai_api_key_llm3_main: str = Field(default="")
    openai_model_classify: str = Field(default="gpt-4o-mini")
    openai_model_analyze: str = Field(default="gpt-4o")
    openai_model_stt: str = Field(default="whisper-1")
    openai_max_retries: int = Field(default=3, ge=1)
    openai_timeout_sec: int = Field(default=120, ge=1)
    llm3_enabled: bool = Field(default=False)

    # Speech-to-text
    stt_provider: str = Field(default="assemblyai")
    manual_live_stt_provider: str = Field(default="")
    stt_language: str = Field(default="ru")

    # AssemblyAI
    assemblyai_api_key: str = Field(default="")
    assemblyai_language: str = Field(default="ru")

    # AI routing
    ai_stt_routing_policy: str = Field(default="fixed")
    ai_stt_providers_json: str = Field(default="")
    ai_stt_fixed_account_alias: str = Field(default="")
    ai_stt_force_account_alias: str = Field(default="")
    ai_llm1_routing_policy: str = Field(default="fixed")
    ai_llm1_providers_json: str = Field(default="")
    ai_llm1_fixed_account_alias: str = Field(default="")
    ai_llm1_force_account_alias: str = Field(default="")
    ai_llm2_routing_policy: str = Field(default="fixed")
    ai_llm2_providers_json: str = Field(default="")
    ai_llm2_fixed_account_alias: str = Field(default="")
    ai_llm2_force_account_alias: str = Field(default="")
    ai_llm2_analysis_mode: str = Field(default="layered")
    ai_llm3_routing_policy: str = Field(default="fixed")
    ai_llm3_providers_json: str = Field(default="")
    ai_llm3_fixed_account_alias: str = Field(default="")
    ai_llm3_force_account_alias: str = Field(default="")
    ai_llm_simulation_enabled: bool = Field(default=False)
    ai_llm_simulation_run_id: str = Field(default="")
    ai_llm_simulation_seed: str = Field(default="")
    ai_llm_simulation_artifact_dir: str = Field(default="/tmp/asa_llm_sim_runs")
    ai_llm_execution_mode: str = Field(default="openai_compatible")
    ai_llm_subagent_runtime_enabled: bool = Field(default=False)
    ai_llm_subagent_runtime_layers: str = Field(default="")
    ai_llm_subagent_command: str = Field(default="")
    ai_llm_subagent_run_id: str = Field(default="")
    ai_llm_subagent_artifact_dir: str = Field(default="/tmp/asa_llm_subagent_runs")
    ai_llm_subagent_timeout_sec: int = Field(default=300, ge=1)
    ai_llm2_input_profile: str = Field(default="compact")
    ai_llm2_report_evidence_validation_enabled: bool = Field(default=False)
    ai_llm2_semantic_validation_enabled: bool = Field(default=False)
    ai_cost_manager_day_budget_usdt: float = Field(default=0.0, ge=0)
    ai_cost_warning_threshold_ratio: float = Field(default=0.8, ge=0)
    ai_cost_over_budget_threshold_ratio: float = Field(default=1.0, ge=0)
    call_processing_mode: str = Field(default="legacy")
    call_processing_api_base_url: str = Field(default="")
    call_processing_access_grant_json: str = Field(default="")
    call_processing_client_timeout_sec: int = Field(default=180, ge=1)
    call_processing_daily_upstream_enabled: bool = Field(default=False)
    call_processing_daily_upstream_timezone: str = Field(default="Asia/Almaty")
    call_processing_daily_upstream_hour: int = Field(default=0, ge=0, le=23)
    call_processing_daily_upstream_minute: int = Field(default=0, ge=0, le=59)
    call_processing_daily_upstream_scope_mode: str = Field(default="managers")
    call_processing_daily_upstream_department_id: str = Field(default="")
    call_processing_daily_upstream_manager_ids: list[str] = Field(default_factory=list)
    call_processing_daily_upstream_min_duration_sec: int | None = Field(default=None, ge=1)
    call_processing_daily_upstream_provider_call_budget: int = Field(default=0, ge=0)

    # OnlinePBX
    onlinepbx_domain: str = Field(default="")
    onlinepbx_api_key: str = Field(default="")
    onlinepbx_base_url: str = Field(default="")
    onlinepbx_api_base_url: str = Field(default="")
    onlinepbx_cdr_url: str = Field(default="")

    # Bitrix24
    bitrix24_readonly_enabled: bool = Field(default=True)
    bitrix24_webhook_url: str = Field(default="")
    bitrix24_target_department_ids: list[str] = Field(default_factory=list)

    # SMTP
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587, ge=1)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="")
    alert_email_enabled: bool = Field(default=False)
    alert_email_to: str = Field(default="admin@dogovor24.kz")
    alert_email_min_level: str = Field(default="warning")
    alert_email_on_start: bool = Field(default=True)
    alert_email_on_success: bool = Field(default=False)
    alert_telegram_enabled: bool = Field(default=False)
    alert_telegram_chat_id: str = Field(default="")
    alert_telegram_min_level: str = Field(default="warning")
    alert_telegram_on_start: bool = Field(default=False)
    alert_telegram_on_success: bool = Field(default=False)
    manager_daily_rop_email_enabled: bool = Field(default=True)
    manager_daily_rop_email_to: str = Field(default="edo.rop@dogovor24.kz")

    # Telegram
    telegram_bot_token: str = Field(default="")
    telegram_chat_id_rop: str = Field(default="")

    # Manual pilot mode
    manual_pilot_enabled: bool = Field(default=False)
    manual_pilot_extensions: list[str] = Field(default_factory=list)
    manual_pilot_phones: list[str] = Field(default_factory=list)
    manual_pilot_external_ids: list[str] = Field(default_factory=list)
    manual_pilot_max_calls: int = Field(default=1, ge=1)
    test_delivery_email_to: str = Field(default="")
    test_delivery_telegram_chat_id: str = Field(default="")

    # Calls Agent limits
    calls_min_duration_sec: int = Field(default=180, ge=1)
    calls_max_daily_per_manager: int = Field(default=20, ge=1)
    calls_weekly_pack_size: int = Field(default=15, ge=1)

    @field_validator("app_service")
    @classmethod
    def validate_app_service(cls, value: str) -> str:
        """Normalize and validate the runtime service identity."""
        normalized = value.strip().lower()
        if normalized not in APP_SERVICE_VALUES:
            allowed_values = ", ".join(sorted(APP_SERVICE_VALUES))
            raise ConfigurationError(
                f"Invalid APP_SERVICE value '{value}'. Expected one of: {allowed_values}."
            )
        return normalized

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        """Normalize and validate application environment."""
        normalized = value.strip().lower()
        allowed = {"development", "production"}
        if normalized not in allowed:
            allowed_values = ", ".join(sorted(allowed))
            raise ConfigurationError(
                f"Invalid APP_ENV value '{value}'. Expected one of: {allowed_values}."
            )
        return normalized

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """Normalize log level casing."""
        return value.strip().upper()

    @field_validator("alert_email_min_level", "alert_telegram_min_level")
    @classmethod
    def validate_alert_min_level(cls, value: str) -> str:
        """Normalize and validate the minimum production alert level."""
        normalized = value.strip().lower()
        aliases = {"warn": "warning", "fatal": "critical"}
        normalized = aliases.get(normalized, normalized)
        if normalized not in ALERT_LEVEL_VALUES:
            allowed_values = ", ".join(ALERT_LEVEL_VALUES)
            raise ConfigurationError(
                f"Invalid alert min level value '{value}'. "
                f"Expected one of: {allowed_values}."
            )
        return normalized

    @field_validator("stt_provider", "manual_live_stt_provider")
    @classmethod
    def normalize_stt_provider(cls, value: str) -> str:
        """Normalize STT provider names."""
        return value.strip().lower()

    @field_validator(
        "ai_stt_routing_policy",
        "ai_llm1_routing_policy",
        "ai_llm2_routing_policy",
        "ai_llm3_routing_policy",
    )
    @classmethod
    def normalize_ai_routing_policy(cls, value: str) -> str:
        """Normalize configured AI routing policy names."""
        return value.strip().lower()

    @field_validator("ai_llm_execution_mode")
    @classmethod
    def normalize_ai_llm_execution_mode(cls, value: str) -> str:
        """Normalize the LLM runtime execution mode."""
        return value.strip().lower()

    @field_validator("ai_llm2_analysis_mode")
    @classmethod
    def normalize_ai_llm2_analysis_mode(cls, value: str) -> str:
        """Normalize the LLM-2 analysis orchestration mode."""
        return value.strip().lower()

    @field_validator("call_processing_mode")
    @classmethod
    def validate_call_processing_mode(cls, value: str) -> str:
        """Normalize and validate analysis-side call-processing ownership mode."""
        normalized = value.strip().lower()
        if normalized not in CALL_PROCESSING_MODE_VALUES:
            allowed_values = ", ".join(sorted(CALL_PROCESSING_MODE_VALUES))
            raise ConfigurationError(
                f"Invalid CALL_PROCESSING_MODE value '{value}'. Expected one of: {allowed_values}."
            )
        return normalized

    @field_validator("call_processing_daily_upstream_scope_mode")
    @classmethod
    def validate_call_processing_daily_upstream_scope_mode(cls, value: str) -> str:
        """Normalize and validate scheduled upstream scope selection mode."""
        normalized = value.strip().lower()
        if normalized not in CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE_VALUES:
            allowed_values = ", ".join(CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE_VALUES)
            raise ConfigurationError(
                "Invalid CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE value "
                f"'{value}'. Expected one of: {allowed_values}."
            )
        return normalized

    @model_validator(mode="after")
    def validate_service_secret_boundaries(self) -> Settings:
        """Enforce only the secrets required by the selected service identity."""
        if self.app_service in {
            APP_SERVICE_CALL_PROCESSING,
            APP_SERVICE_MONOLITH_LEGACY,
        }:
            if not self.onlinepbx_domain.strip():
                raise ConfigurationError(
                    "ONLINEPBX_DOMAIN is required for APP_SERVICE=call_processing or monolith_legacy."
                )
            if not self.onlinepbx_api_key.strip():
                raise ConfigurationError(
                    "ONLINEPBX_API_KEY is required for APP_SERVICE=call_processing or monolith_legacy."
                )
            if self.stt_provider == "assemblyai" and not self.assemblyai_api_key.strip():
                raise ConfigurationError(
                    "ASSEMBLYAI_API_KEY is required when STT_PROVIDER=assemblyai for "
                    "APP_SERVICE=call_processing or monolith_legacy."
                )
            if self.stt_provider == "openai" and not self.openai_api_key.strip():
                raise ConfigurationError(
                    "OPENAI_API_KEY is required when STT_PROVIDER=openai for "
                    "APP_SERVICE=call_processing or monolith_legacy."
                )
        if (
            self.app_service == APP_SERVICE_ANALYSIS
            and self.call_processing_mode != "external_service"
        ):
            raise ConfigurationError(
                "APP_SERVICE=analysis requires CALL_PROCESSING_MODE=external_service."
            )
        if self.app_service == APP_SERVICE_ANALYSIS:
            if not self.call_processing_api_base_url.strip():
                raise ConfigurationError(
                    "CALL_PROCESSING_API_BASE_URL is required for APP_SERVICE=analysis."
                )
            if not self.call_processing_access_grant_json.strip():
                raise ConfigurationError(
                    "CALL_PROCESSING_ACCESS_GRANT_JSON is required for APP_SERVICE=analysis."
                )
            self._validate_analysis_forbidden_upstream_secrets()
        if self.app_service == APP_SERVICE_CALL_PROCESSING:
            self._validate_call_processing_forbidden_downstream_secrets()
        return self

    def _validate_analysis_forbidden_upstream_secrets(self) -> None:
        """Warn or fail when analysis receives call-processing-owned secrets."""
        forbidden_secret_fields = {
            "ONLINEPBX_API_KEY": self.onlinepbx_api_key,
            "ASSEMBLYAI_API_KEY": self.assemblyai_api_key,
            "OPENAI_API_KEY_STT_MAIN": self.openai_api_key_stt_main,
            "OPENAI_API_KEY_LLM1_MAIN": self.openai_api_key_llm1_main,
        }
        present = self._present_env_names(forbidden_secret_fields)
        if self._has_enabled_provider_config(self.ai_stt_providers_json):
            present.append("AI_STT_PROVIDERS_JSON")
        if self._has_enabled_provider_config(self.ai_llm1_providers_json):
            present.append("AI_LLM1_PROVIDERS_JSON")

        warning_only = self._present_env_names(
            {
                "ONLINEPBX_DOMAIN": self.onlinepbx_domain,
                "AI_STT_FIXED_ACCOUNT_ALIAS": self.ai_stt_fixed_account_alias,
                "AI_STT_FORCE_ACCOUNT_ALIAS": self.ai_stt_force_account_alias,
                "AI_LLM1_FIXED_ACCOUNT_ALIAS": self.ai_llm1_fixed_account_alias,
                "AI_LLM1_FORCE_ACCOUNT_ALIAS": self.ai_llm1_force_account_alias,
            }
        )
        if present and self.strict_service_secret_partitioning:
            names = ", ".join(sorted(present))
            raise ConfigurationError(
                "STRICT_SERVICE_SECRET_PARTITIONING forbids upstream secrets/config "
                f"for APP_SERVICE=analysis: {names}."
            )
        self._warn_forbidden_secret_partitioning("analysis", present + warning_only)

    def _validate_call_processing_forbidden_downstream_secrets(self) -> None:
        """Warn or fail when call-processing receives analysis-owned provider secrets."""
        present = self._present_env_names(
            {
                "OPENAI_API_KEY_LLM2_MAIN": self.openai_api_key_llm2_main,
                "OPENAI_API_KEY_LLM3_MAIN": self.openai_api_key_llm3_main,
            }
        )
        if self._has_enabled_provider_config(self.ai_llm2_providers_json):
            present.append("AI_LLM2_PROVIDERS_JSON")
        if self._has_enabled_provider_config(self.ai_llm3_providers_json):
            present.append("AI_LLM3_PROVIDERS_JSON")

        delivery_warnings = self._present_env_names(
            {
                "SMTP_PASSWORD": self.smtp_password,
                "TEST_DELIVERY_EMAIL_TO": self.test_delivery_email_to,
                "TEST_DELIVERY_TELEGRAM_CHAT_ID": self.test_delivery_telegram_chat_id,
            }
        )
        if self.telegram_bot_token.strip() and not self.alert_telegram_enabled:
            delivery_warnings.append("TELEGRAM_BOT_TOKEN")
        if present and self.strict_service_secret_partitioning:
            names = ", ".join(sorted(present))
            raise ConfigurationError(
                "STRICT_SERVICE_SECRET_PARTITIONING forbids downstream provider "
                f"secrets/config for APP_SERVICE=call_processing: {names}."
            )
        self._warn_forbidden_secret_partitioning(
            "call_processing",
            present + delivery_warnings,
        )

    @staticmethod
    def _present_env_names(values_by_env_name: dict[str, Any]) -> list[str]:
        """Return env names with non-empty configured values."""
        return [
            name
            for name, value in values_by_env_name.items()
            if str(value or "").strip()
        ]

    @staticmethod
    def _warn_forbidden_secret_partitioning(service: str, names: list[str]) -> None:
        """Emit a non-strict service partitioning warning."""
        if not names:
            return
        warnings.warn(
            "Service secret partitioning warning for "
            f"APP_SERVICE={service}: unexpected env present: "
            f"{', '.join(sorted(set(names)))}.",
            RuntimeWarning,
            stacklevel=3,
        )

    @staticmethod
    def _has_enabled_provider_config(raw_config: str) -> bool:
        """Return True when a provider JSON config contains enabled entries."""
        raw = raw_config.strip()
        if raw == "":
            return False
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return True

        if isinstance(parsed, list):
            entries = parsed
        elif isinstance(parsed, dict):
            if "entries" in parsed and isinstance(parsed["entries"], list):
                entries = parsed["entries"]
            elif "provider" in parsed or "api_key_env" in parsed:
                entries = [parsed]
            else:
                entries = []
        else:
            entries = []

        for entry in entries:
            if not isinstance(entry, dict):
                return True
            enabled = entry.get("enabled", True)
            if isinstance(enabled, str):
                if enabled.strip().lower() in {"0", "false", "no", "off"}:
                    continue
            elif enabled is False:
                continue
            return True
        return False

    @field_validator(
        "manual_pilot_extensions",
        "manual_pilot_phones",
        "manual_pilot_external_ids",
        "bitrix24_target_department_ids",
        "call_processing_daily_upstream_manager_ids",
        mode="before",
    )
    @classmethod
    def split_csv_values(cls, value: Any) -> list[str]:
        """Normalize CSV-like env values into string lists."""
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]

    @model_validator(mode="after")
    def build_onlinepbx_base_url(self) -> Settings:
        """Populate OnlinePBX base URL from explicit override or normalized host."""
        if self.onlinepbx_api_base_url.strip():
            self.onlinepbx_base_url = self._normalize_url(self.onlinepbx_api_base_url)
            return self

        domain = self.onlinepbx_domain.strip()
        if not domain:
            self.onlinepbx_base_url = ""
            return self
        host = self._extract_host(domain)
        if host.endswith(".onlinepbx.ru") or host.endswith(".onpbx.ru"):
            self.onlinepbx_base_url = f"https://{host}/api"
            return self

        normalized_host = host.removesuffix(".")
        self.onlinepbx_base_url = f"https://{normalized_host}.onlinepbx.ru/api"
        return self

    @property
    def is_development(self) -> bool:
        """Return True when the application runs in development mode."""
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        """Return True when the application runs in production mode."""
        return self.app_env == "production"

    @property
    def has_telegram(self) -> bool:
        """Return True when Telegram delivery is configured."""
        return self.telegram_bot_token != ""

    @property
    def has_smtp(self) -> bool:
        """Return True when SMTP delivery is configured."""
        return self.smtp_user != ""

    @property
    def has_alert_email_delivery(self) -> bool:
        """Return True when production alert email delivery is configured."""
        return (
            self.alert_email_enabled
            and self.alert_email_to.strip() != ""
            and self.has_smtp
        )

    @property
    def has_alert_telegram_delivery(self) -> bool:
        """Return True when production alert Telegram delivery is configured."""
        return (
            self.alert_telegram_enabled
            and self.alert_telegram_chat_id.strip() != ""
            and self.has_telegram
        )

    @property
    def has_test_email_delivery(self) -> bool:
        """Return True when a dedicated test email recipient is configured."""
        return self.test_delivery_email_to != "" and self.has_smtp

    @property
    def has_test_telegram_delivery(self) -> bool:
        """Return True when a dedicated test Telegram recipient is configured."""
        return self.test_delivery_telegram_chat_id != "" and self.has_telegram

    @property
    def has_bitrix24_readonly(self) -> bool:
        """Return True when Bitrix24 read-only mapping should be attempted."""
        if not self.bitrix24_readonly_enabled:
            return False
        webhook = self.bitrix24_webhook_url.strip()
        if webhook == "":
            return False
        placeholder_markers = (
            "yourcompany.bitrix24",
            "yourcompany.",
            "<bitrix",
            "changeme",
        )
        lowered = webhook.lower()
        return not any(marker in lowered for marker in placeholder_markers)

    @property
    def effective_manual_live_stt_provider(self) -> str:
        """Return the STT provider to use for manual live validation."""
        return self.manual_live_stt_provider or self.stt_provider

    @staticmethod
    def _extract_host(value: str) -> str:
        """Extract host from a subdomain, host, or URL-like value."""
        candidate = value.strip()
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return urlparse(candidate).netloc.strip().lower()
        return candidate.strip().strip("/").lower()

    @staticmethod
    def _normalize_url(value: str) -> str:
        """Normalize an absolute URL-like value."""
        candidate = value.strip()
        if not candidate.startswith(("http://", "https://")):
            candidate = f"https://{candidate}"
        return candidate.rstrip("/")


settings = Settings()
