"""Deterministic AI provider routing for STT and LLM layers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.core_shared.config.settings import Settings, settings
from app.core_shared.exceptions import ConfigurationError

AIRoutingLayer = Literal["stt", "llm1", "llm2"]
AIRoutingPolicy = Literal["fixed", "failover", "weighted_ab", "manual_force"]
AIExecutionMode = Literal["openai_compatible", "vendor_specific"]

SUPPORTED_ROUTING_POLICIES = {"fixed", "failover", "weighted_ab", "manual_force"}


@dataclass(frozen=True, slots=True)
class AIExecutionCapability:
    """Declared execution capability for one routed provider."""

    layer: AIRoutingLayer
    provider: str
    execution_mode: AIExecutionMode
    supports_api_base: bool
    supports_endpoint: bool
    supports_model: bool
    requires_openai_compatible_api: bool


EXECUTION_CAPABILITY_MAP: dict[tuple[AIRoutingLayer, str], AIExecutionCapability] = {
    (
        "stt",
        "assemblyai",
    ): AIExecutionCapability(
        layer="stt",
        provider="assemblyai",
        execution_mode="vendor_specific",
        supports_api_base=False,
        supports_endpoint=False,
        supports_model=True,
        requires_openai_compatible_api=False,
    ),
    (
        "stt",
        "openai",
    ): AIExecutionCapability(
        layer="stt",
        provider="openai",
        execution_mode="openai_compatible",
        supports_api_base=True,
        supports_endpoint=False,
        supports_model=True,
        requires_openai_compatible_api=True,
    ),
    (
        "llm1",
        "openai",
    ): AIExecutionCapability(
        layer="llm1",
        provider="openai",
        execution_mode="openai_compatible",
        supports_api_base=True,
        supports_endpoint=False,
        supports_model=True,
        requires_openai_compatible_api=True,
    ),
    (
        "llm2",
        "openai",
    ): AIExecutionCapability(
        layer="llm2",
        provider="openai",
        execution_mode="openai_compatible",
        supports_api_base=True,
        supports_endpoint=False,
        supports_model=True,
        requires_openai_compatible_api=True,
    ),
}


class AIProviderEntryConfig(BaseModel):
    """One provider/account entry inside a layer-specific pool."""

    provider: str
    account_alias: str | None = None
    account_id: str | None = None
    model: str
    api_base: str | None = None
    endpoint: str | None = None
    api_key_env: str
    enabled: bool = True
    priority: int = 100
    weight: int = 1
    timeout_sec: int | None = None
    max_retries_for_this_provider: int = 0
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("provider", "model", "api_key_env", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> str:
        """Normalize required text values."""
        text = str(value or "").strip()
        if text == "":
            raise ValueError("must not be empty")
        return text

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        """Normalize provider identifiers."""
        return value.strip().lower()

    @field_validator("account_alias", "account_id", "api_base", "endpoint", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        """Normalize optional text values."""
        text = str(value).strip() if value is not None else ""
        return text or None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> list[str]:
        """Normalize tags to a plain list of strings."""
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]

    @model_validator(mode="after")
    def finalize_alias(self) -> AIProviderEntryConfig:
        """Ensure an account alias is always present for audit logs."""
        resolved_alias = self.account_alias or self.account_id
        if not resolved_alias:
            raise ValueError("account_alias or account_id must be provided")
        self.account_alias = resolved_alias
        return self


class AIProviderPoolConfig(BaseModel):
    """Layer-specific provider pool and routing policy."""

    routing_policy: AIRoutingPolicy = "fixed"
    fixed_account_alias: str | None = None
    force_account_alias: str | None = None
    entries: list[AIProviderEntryConfig] = Field(default_factory=list)

    @field_validator("fixed_account_alias", "force_account_alias", mode="before")
    @classmethod
    def normalize_aliases(cls, value: Any) -> str | None:
        """Normalize configured aliases."""
        text = str(value).strip() if value is not None else ""
        return text or None


@dataclass(slots=True)
class AIProviderRouteCandidate:
    """Executable route candidate with resolved config."""

    layer: AIRoutingLayer
    provider: str
    account_alias: str
    model: str
    api_key_env: str
    api_base: str | None
    endpoint: str | None
    timeout_sec: int | None
    max_retries_for_this_provider: int
    priority: int
    weight: int
    execution_mode: AIExecutionMode | None = None
    supports_api_base: bool = False
    supports_endpoint: bool = False
    supports_model: bool = True
    requires_openai_compatible_api: bool = False
    tags: list[str] = field(default_factory=list)
    notes: str | None = None

    @classmethod
    def from_entry(
        cls,
        entry: AIProviderEntryConfig,
        *,
        layer: AIRoutingLayer,
    ) -> AIProviderRouteCandidate:
        """Build an executable route candidate from validated config."""
        capability = EXECUTION_CAPABILITY_MAP.get((layer, entry.provider))
        return cls(
            layer=layer,
            provider=entry.provider,
            account_alias=entry.account_alias or "",
            model=entry.model,
            api_key_env=entry.api_key_env,
            api_base=entry.api_base,
            endpoint=entry.endpoint,
            timeout_sec=entry.timeout_sec,
            max_retries_for_this_provider=entry.max_retries_for_this_provider,
            priority=entry.priority,
            weight=entry.weight,
            execution_mode=capability.execution_mode if capability else None,
            supports_api_base=capability.supports_api_base if capability else False,
            supports_endpoint=capability.supports_endpoint if capability else False,
            supports_model=capability.supports_model if capability else True,
            requires_openai_compatible_api=(
                capability.requires_openai_compatible_api if capability else False
            ),
            tags=list(entry.tags),
            notes=entry.notes,
        )

    def resolved_api_key(self) -> str:
        """Read the API key from the referenced environment variable."""
        value = os.getenv(self.api_key_env, "").strip()
        if value == "":
            raise ConfigurationError(
                f"AI provider account '{self.account_alias}' requires env '{self.api_key_env}', "
                "but it is empty or missing."
            )
        return value

    def matches_provider_override(self, provider_name: str) -> bool:
        """Return True when a legacy provider override should target this candidate."""
        normalized = provider_name.strip().lower()
        if normalized == self.provider:
            return True
        if normalized == "whisper" and self.provider == "openai":
            return "whisper" in self.model.lower()
        return False

    def to_metadata(self) -> dict[str, Any]:
        """Return audit-safe provider metadata."""
        return {
            "layer": self.layer,
            "provider": self.provider,
            "account_alias": self.account_alias,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "api_base": self.api_base,
            "endpoint": self.endpoint,
            "priority": self.priority,
            "weight": self.weight,
            "timeout_sec": self.timeout_sec,
            "max_retries_for_this_provider": self.max_retries_for_this_provider,
            "execution_mode": self.execution_mode,
            "supports_api_base": self.supports_api_base,
            "supports_endpoint": self.supports_endpoint,
            "supports_model": self.supports_model,
            "requires_openai_compatible_api": self.requires_openai_compatible_api,
            "tags": list(self.tags),
            "notes": self.notes,
        }


@dataclass(slots=True)
class AIProviderRoutePlan:
    """Deterministic route plan plus execution audit state."""

    layer: AIRoutingLayer
    policy: AIRoutingPolicy
    requested_policy: AIRoutingPolicy
    subject_key: str
    forced_override: bool
    force_reason: str | None
    configured_pool_size: int
    candidates: list[AIProviderRouteCandidate]
    attempted: list[dict[str, Any]] = field(default_factory=list)
    selected_index: int = 0
    fallback_used: bool = False

    def current_candidate(self) -> AIProviderRouteCandidate:
        """Return the currently selected candidate."""
        return self.candidates[self.selected_index]

    def mark_attempt_success(self) -> None:
        """Record a successful provider attempt."""
        candidate = self.current_candidate()
        self.attempted.append(
            {
                **candidate.to_metadata(),
                "status": "success",
                "attempt_index": len(self.attempted) + 1,
            }
        )

    def mark_attempt_failure(self, error: str) -> bool:
        """Record a failed attempt and advance to fallback when allowed."""
        candidate = self.current_candidate()
        self.attempted.append(
            {
                **candidate.to_metadata(),
                "status": "failed",
                "error": error,
                "attempt_index": len(self.attempted) + 1,
            }
        )
        if self.policy == "failover" and self.selected_index + 1 < len(self.candidates):
            self.selected_index += 1
            self.fallback_used = True
            return True
        return False

    def to_metadata(
        self,
        *,
        executed: bool = True,
        notes: str | None = None,
        skip_reason: str | None = None,
        usage: dict[str, Any] | None = None,
        request_kind: str | None = None,
        execution_status: str | None = None,
        executed_endpoint_path: str | None = None,
        provider_request_id: str | None = None,
    ) -> dict[str, Any]:
        """Render one audit-friendly routing snapshot."""
        selected = self.current_candidate()
        provider_failure = any(item.get("status") == "failed" for item in self.attempted)
        resolved_execution_status = execution_status
        if resolved_execution_status is None:
            if executed:
                resolved_execution_status = "executed"
            elif self.attempted:
                resolved_execution_status = "attempted_failed"
            elif skip_reason:
                resolved_execution_status = "skipped"
            else:
                resolved_execution_status = "planned"
        return {
            "layer": self.layer,
            "policy": self.policy,
            "requested_policy": self.requested_policy,
            "forced_override": self.forced_override,
            "force_reason": self.force_reason,
            "subject_key": self.subject_key,
            "configured_pool_size": self.configured_pool_size,
            "selected_provider": selected.provider,
            "selected_account_alias": selected.account_alias,
            "selected_api_key_env": selected.api_key_env,
            "selected_model": selected.model,
            "selected_api_base": selected.api_base,
            "selected_endpoint": selected.endpoint,
            "selected_timeout_sec": selected.timeout_sec,
            "selected_max_retries_for_this_provider": selected.max_retries_for_this_provider,
            "selected_execution_mode": selected.execution_mode,
            "selected_supports_api_base": selected.supports_api_base,
            "selected_supports_endpoint": selected.supports_endpoint,
            "selected_supports_model": selected.supports_model,
            "selected_requires_openai_compatible_api": selected.requires_openai_compatible_api,
            "fallback_used": self.fallback_used,
            "provider_failure": provider_failure,
            "executed": executed,
            "execution_status": resolved_execution_status,
            "skip_reason": skip_reason,
            "request_kind": request_kind,
            "executed_endpoint_path": executed_endpoint_path,
            "provider_request_id": provider_request_id,
            "notes": notes,
            "usage": usage,
            "attempted_count": len(self.attempted),
            "attempted": list(self.attempted),
        }


class AIProviderRouter:
    """Resolve deterministic provider selections for one AI layer."""

    def __init__(self, app_settings: Settings | None = None):
        self.settings = app_settings or settings

    def get_pool(self, layer: AIRoutingLayer) -> AIProviderPoolConfig:
        """Return one configured pool or a legacy-compatible fallback."""
        pool_json = getattr(self.settings, f"ai_{layer}_providers_json")
        routing_policy = getattr(self.settings, f"ai_{layer}_routing_policy")
        fixed_alias = getattr(self.settings, f"ai_{layer}_fixed_account_alias")
        force_alias = getattr(self.settings, f"ai_{layer}_force_account_alias")

        if pool_json.strip():
            try:
                raw_entries = json.loads(pool_json)
            except json.JSONDecodeError as exc:
                raise ConfigurationError(
                    f"Invalid JSON in AI_{layer.upper()}_PROVIDERS_JSON: {exc}"
                ) from exc
            if not isinstance(raw_entries, list):
                raise ConfigurationError(
                    f"AI_{layer.upper()}_PROVIDERS_JSON must decode to a list of provider entries."
                )
            try:
                return AIProviderPoolConfig(
                    routing_policy=routing_policy,
                    fixed_account_alias=fixed_alias,
                    force_account_alias=force_alias,
                    entries=raw_entries,
                )
            except ValidationError as exc:
                raise ConfigurationError(
                    f"Invalid AI provider config for layer '{layer}': {exc}"
                ) from exc

        return self._build_legacy_pool(layer=layer)

    def build_route_plan(
        self,
        *,
        layer: AIRoutingLayer,
        subject_key: str,
        provider_override: str | None = None,
    ) -> AIProviderRoutePlan:
        """Resolve a deterministic candidate plan for one AI layer."""
        pool = self.get_pool(layer)
        enabled_entries = [
            AIProviderRouteCandidate.from_entry(entry, layer=layer)
            for entry in pool.entries
            if entry.enabled
        ]
        if not enabled_entries:
            raise ConfigurationError(f"No enabled AI provider entries configured for layer '{layer}'.")

        ordered = sorted(enabled_entries, key=lambda item: (item.priority, item.account_alias))
        requested_policy = pool.routing_policy

        if provider_override:
            filtered = [item for item in ordered if item.matches_provider_override(provider_override)]
            if not filtered and layer == "stt":
                filtered = self._build_legacy_stt_override_candidates(provider_override)
            if not filtered:
                raise ConfigurationError(
                    f"Legacy provider override '{provider_override}' did not match any configured "
                    f"entries for layer '{layer}'."
                )
            return AIProviderRoutePlan(
                layer=layer,
                policy="manual_force",
                requested_policy=requested_policy,
                subject_key=subject_key,
                forced_override=True,
                force_reason="legacy_provider_override",
                configured_pool_size=len(ordered),
                candidates=[filtered[0]],
            )

        if pool.force_account_alias:
            forced = self._get_entry_by_alias(ordered, pool.force_account_alias, layer=layer)
            return AIProviderRoutePlan(
                layer=layer,
                policy="manual_force",
                requested_policy=requested_policy,
                subject_key=subject_key,
                forced_override=True,
                force_reason="force_account_alias",
                configured_pool_size=len(ordered),
                candidates=[forced],
            )

        if requested_policy == "fixed":
            selected = self._resolve_fixed_candidate(
                entries=ordered,
                fixed_alias=pool.fixed_account_alias,
                layer=layer,
            )
            return AIProviderRoutePlan(
                layer=layer,
                policy="fixed",
                requested_policy=requested_policy,
                subject_key=subject_key,
                forced_override=False,
                force_reason=None,
                configured_pool_size=len(ordered),
                candidates=[selected],
            )

        if requested_policy == "failover":
            if pool.fixed_account_alias:
                primary = self._get_entry_by_alias(ordered, pool.fixed_account_alias, layer=layer)
                remainder = [item for item in ordered if item.account_alias != primary.account_alias]
                ordered = [primary, *remainder]
            return AIProviderRoutePlan(
                layer=layer,
                policy="failover",
                requested_policy=requested_policy,
                subject_key=subject_key,
                forced_override=False,
                force_reason=None,
                configured_pool_size=len(ordered),
                candidates=ordered,
            )

        if requested_policy == "weighted_ab":
            weighted_entries = [item for item in ordered if item.weight > 0]
            if not weighted_entries:
                raise ConfigurationError(
                    f"weighted_ab routing for layer '{layer}' requires at least one entry with weight > 0."
                )
            selected = self._select_weighted_entry(
                layer=layer,
                subject_key=subject_key,
                entries=weighted_entries,
            )
            return AIProviderRoutePlan(
                layer=layer,
                policy="weighted_ab",
                requested_policy=requested_policy,
                subject_key=subject_key,
                forced_override=False,
                force_reason=None,
                configured_pool_size=len(ordered),
                candidates=[selected],
            )

        if requested_policy == "manual_force":
            if pool.fixed_account_alias:
                forced = self._get_entry_by_alias(ordered, pool.fixed_account_alias, layer=layer)
                return AIProviderRoutePlan(
                    layer=layer,
                    policy="manual_force",
                    requested_policy=requested_policy,
                    subject_key=subject_key,
                    forced_override=True,
                    force_reason="fixed_account_alias",
                    configured_pool_size=len(ordered),
                    candidates=[forced],
                )
            raise ConfigurationError(
                f"manual_force routing for layer '{layer}' requires AI_{layer.upper()}_FORCE_ACCOUNT_ALIAS "
                f"or AI_{layer.upper()}_FIXED_ACCOUNT_ALIAS."
            )

        raise ConfigurationError(f"Unsupported AI routing policy for layer '{layer}': {requested_policy}")

    def _build_legacy_pool(self, *, layer: AIRoutingLayer) -> AIProviderPoolConfig:
        """Build a single-entry pool from existing legacy settings."""
        if layer == "stt":
            entries = [self._build_legacy_stt_entry(provider_name=self.settings.stt_provider)]
        elif layer == "llm1":
            entries = [
                {
                    "provider": "openai",
                    "account_alias": "legacy_openai_llm1_primary",
                    "model": self.settings.openai_model_classify,
                    "api_key_env": "OPENAI_API_KEY",
                    "timeout_sec": self.settings.openai_timeout_sec,
                    "max_retries_for_this_provider": self.settings.openai_max_retries,
                    "priority": 1,
                    "weight": 1,
                    "tags": ["legacy", "single_provider", "llm1"],
                    "notes": "Prepared from legacy classification model settings.",
                }
            ]
        else:
            entries = [
                {
                    "provider": "openai",
                    "account_alias": "legacy_openai_llm2_primary",
                    "model": self.settings.openai_model_analyze,
                    "api_key_env": "OPENAI_API_KEY",
                    "timeout_sec": self.settings.openai_timeout_sec,
                    "max_retries_for_this_provider": self.settings.openai_max_retries,
                    "priority": 1,
                    "weight": 1,
                    "tags": ["legacy", "single_provider", "llm2"],
                    "notes": "Derived automatically from legacy analyzer settings.",
                }
            ]

        return AIProviderPoolConfig(entries=entries)

    def _build_legacy_stt_override_candidates(
        self,
        provider_override: str,
    ) -> list[AIProviderRouteCandidate]:
        """Allow legacy manual-live STT overrides without requiring JSON pool config."""
        normalized = provider_override.strip().lower()
        if normalized not in {"assemblyai", "whisper", "openai"}:
            return []
        entry = self._build_legacy_stt_entry(provider_name=normalized)
        return [
            AIProviderRouteCandidate.from_entry(
                AIProviderEntryConfig.model_validate(entry),
                layer="stt",
            )
        ]

    @staticmethod
    def get_execution_capability(
        *,
        layer: AIRoutingLayer,
        provider: str,
    ) -> AIExecutionCapability | None:
        """Return the declared execution capability for one layer/provider pair."""
        return EXECUTION_CAPABILITY_MAP.get((layer, provider.strip().lower()))

    @staticmethod
    def ensure_execution_compatibility(
        candidate: AIProviderRouteCandidate,
        *,
        executor_label: str,
        required_execution_mode: AIExecutionMode | None = None,
    ) -> None:
        """Fail fast when a routed candidate is not supported by the current executor path."""
        if candidate.execution_mode is None:
            raise ConfigurationError(
                f"Provider '{candidate.provider}' account '{candidate.account_alias}' is routing-valid "
                f"for layer '{candidate.layer}', but unsupported by current {executor_label}."
            )
        if required_execution_mode and candidate.execution_mode != required_execution_mode:
            raise ConfigurationError(
                f"Provider '{candidate.provider}' account '{candidate.account_alias}' uses "
                f"execution_mode='{candidate.execution_mode}', but current {executor_label} requires "
                f"'{required_execution_mode}'."
            )
        if candidate.api_base and not candidate.supports_api_base:
            raise ConfigurationError(
                f"Provider '{candidate.provider}' account '{candidate.account_alias}' configured "
                f"'api_base', but current {executor_label} does not support it."
            )
        if candidate.endpoint and not candidate.supports_endpoint:
            raise ConfigurationError(
                f"Provider '{candidate.provider}' account '{candidate.account_alias}' configured "
                f"'endpoint', but current {executor_label} does not support it."
            )

    def _build_legacy_stt_entry(self, *, provider_name: str) -> dict[str, Any]:
        """Build one legacy STT provider entry from the requested provider name."""
        normalized = provider_name.strip().lower()
        if normalized == "assemblyai":
            return {
                "provider": "assemblyai",
                "account_alias": "legacy_assemblyai_primary",
                "model": "assemblyai_default",
                "api_key_env": "ASSEMBLYAI_API_KEY",
                "timeout_sec": self.settings.openai_timeout_sec,
                "max_retries_for_this_provider": 0,
                "priority": 1,
                "weight": 1,
                "tags": ["legacy", "single_provider"],
                "notes": "Derived automatically from legacy STT settings.",
            }
        return {
            "provider": "openai",
            "account_alias": "legacy_openai_stt_primary",
            "model": self.settings.openai_model_stt,
            "api_key_env": "OPENAI_API_KEY",
            "timeout_sec": self.settings.openai_timeout_sec,
            "max_retries_for_this_provider": self.settings.openai_max_retries,
            "priority": 1,
            "weight": 1,
            "tags": ["legacy", "single_provider", normalized],
            "notes": "Derived automatically from legacy STT settings.",
        }

    @staticmethod
    def _get_entry_by_alias(
        entries: list[AIProviderRouteCandidate],
        alias: str,
        *,
        layer: AIRoutingLayer,
    ) -> AIProviderRouteCandidate:
        """Resolve one candidate by account alias."""
        for entry in entries:
            if entry.account_alias == alias:
                return entry
        raise ConfigurationError(
            f"Configured account alias '{alias}' was not found in AI provider pool for layer '{layer}'."
        )

    def _resolve_fixed_candidate(
        self,
        *,
        entries: list[AIProviderRouteCandidate],
        fixed_alias: str | None,
        layer: AIRoutingLayer,
    ) -> AIProviderRouteCandidate:
        """Resolve the single candidate for fixed routing."""
        if fixed_alias:
            return self._get_entry_by_alias(entries, fixed_alias, layer=layer)
        return entries[0]

    @staticmethod
    def _select_weighted_entry(
        *,
        layer: AIRoutingLayer,
        subject_key: str,
        entries: list[AIProviderRouteCandidate],
    ) -> AIProviderRouteCandidate:
        """Select one weighted entry deterministically from the subject key."""
        total_weight = sum(entry.weight for entry in entries)
        signature = "|".join(
            [layer, subject_key, *[f"{entry.account_alias}:{entry.weight}" for entry in entries]]
        )
        bucket = int(hashlib.sha256(signature.encode("utf-8")).hexdigest(), 16) % total_weight
        current = 0
        for entry in entries:
            current += entry.weight
            if bucket < current:
                return entry
        return entries[-1]
