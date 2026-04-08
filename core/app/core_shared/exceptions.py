"""Custom exceptions for AI Sales Analyzer."""

from __future__ import annotations


class ASAError(Exception):
    """Базовое исключение проекта AI Sales Analyzer."""


class ConfigurationError(ASAError):
    """Ошибка конфигурации."""


class IntakeError(ASAError):
    """Ошибка получения данных из источника."""

    def __init__(self, message: str, source: str, original: Exception | None = None):
        self.source = source
        self.original = original
        super().__init__(message)


class ExtractionError(ASAError):
    """Ошибка извлечения/транскрипции."""


class AnalysisError(ASAError):
    """Ошибка LLM-анализа."""

    def __init__(self, message: str, interaction_id: str, original: Exception | None = None):
        self.interaction_id = interaction_id
        self.original = original
        super().__init__(message)


class DeliveryError(ASAError):
    """Ошибка доставки отчёта."""


class DatabaseError(ASAError):
    """Ошибка работы с БД."""


class LLMResponseError(AnalysisError):
    """LLM вернул невалидный JSON или не прошёл Pydantic-валидацию."""

    def __init__(self, message: str, interaction_id: str, raw_response: str = ""):
        self.raw_response = raw_response
        super().__init__(message=message, interaction_id=interaction_id, original=None)


class SemanticAnalysisError(LLMResponseError):
    """LLM вернул shape-valid, но семантически пустой или непригодный анализ."""

    def __init__(
        self,
        message: str,
        interaction_id: str,
        raw_response: str = "",
        normalized_result: dict | None = None,
        reason_code: str = "",
    ):
        self.normalized_result = normalized_result or {}
        self.reason_code = reason_code
        super().__init__(message=message, interaction_id=interaction_id, raw_response=raw_response)
