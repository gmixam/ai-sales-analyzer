"""Typed application settings loaded from environment variables."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core_shared.exceptions import ConfigurationError


class Settings(BaseSettings):
    """Centralized application settings for AI Sales Analyzer."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_env: str = Field(default="production")
    log_level: str = Field(default="INFO")
    compose_project_name: str = Field(default="asa")

    # Database
    database_url: PostgresDsn
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # Redis
    redis_url: RedisDsn
    redis_password: str

    # OpenAI
    openai_api_key: str
    openai_model_classify: str = Field(default="gpt-4o-mini")
    openai_model_analyze: str = Field(default="gpt-4o")
    openai_model_stt: str = Field(default="whisper-1")
    openai_max_retries: int = Field(default=3, ge=1)
    openai_timeout_sec: int = Field(default=120, ge=1)

    # Speech-to-text
    stt_provider: str = Field(default="assemblyai")
    manual_live_stt_provider: str = Field(default="")
    stt_language: str = Field(default="ru")

    # AssemblyAI
    assemblyai_api_key: str
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

    # OnlinePBX
    onlinepbx_domain: str
    onlinepbx_api_key: str
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

    @field_validator("stt_provider", "manual_live_stt_provider")
    @classmethod
    def normalize_stt_provider(cls, value: str) -> str:
        """Normalize STT provider names."""
        return value.strip().lower()

    @field_validator(
        "ai_stt_routing_policy",
        "ai_llm1_routing_policy",
        "ai_llm2_routing_policy",
    )
    @classmethod
    def normalize_ai_routing_policy(cls, value: str) -> str:
        """Normalize configured AI routing policy names."""
        return value.strip().lower()

    @field_validator(
        "manual_pilot_extensions",
        "manual_pilot_phones",
        "manual_pilot_external_ids",
        "bitrix24_target_department_ids",
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
