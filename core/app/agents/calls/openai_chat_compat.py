"""Compatibility helpers for OpenAI-compatible chat completions."""

from __future__ import annotations

from typing import Any


def build_chat_completion_kwargs(
    *,
    model: str,
    messages: list[dict[str, str]],
    timeout: int | float | None,
    temperature: float | None = None,
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
    if temperature is not None and _supports_custom_temperature(model):
        kwargs["temperature"] = temperature
    return kwargs


def _supports_custom_temperature(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return not normalized.startswith(("gpt-5", "o1", "o3", "o4"))
