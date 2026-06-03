"""Compatibility helpers for OpenAI-compatible chat completions."""

from __future__ import annotations

from typing import Any


def build_chat_completion_kwargs(
    *,
    model: str,
    messages: list[dict[str, str]],
    timeout: int | float | None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build chat completion kwargs, omitting unsupported knobs for reasoning models."""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "timeout": timeout,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    normalized_temperature = _normalized_temperature(model, temperature)
    if normalized_temperature is not None:
        kwargs["temperature"] = normalized_temperature
    if max_tokens is not None and _supports_legacy_max_tokens(model):
        kwargs["max_tokens"] = max_tokens
    return kwargs


def _normalized_temperature(model: str, temperature: float | None) -> float | None:
    normalized = str(model or "").strip().lower()
    if normalized in {"kimi-k2.5", "kimi-k2.6"}:
        return 1
    if temperature is None:
        return None
    if normalized.startswith(("gpt-5", "o1", "o3", "o4")):
        return None
    return temperature


def _supports_legacy_max_tokens(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return not normalized.startswith(("gpt-5", "o1", "o3", "o4"))
