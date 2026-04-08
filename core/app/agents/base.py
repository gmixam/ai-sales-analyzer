"""Base class for deterministic project agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

import structlog


class BaseAgent(ABC):
    """
    Базовый класс агента.
    Агент = изолированный детерминированный pipeline для одного типа данных.
    НЕ является AI-агентом — это Python-модуль с фиксированными шагами.
    """

    def __init__(self, department_id: str):
        self.department_id = UUID(department_id)
        self.logger = structlog.get_logger().bind(
            agent=self.__class__.__name__,
            department_id=department_id,
        )

    @abstractmethod
    async def run_daily(self, date: str | None = None) -> dict:
        """Ежедневный прогон: получить → проанализировать → доставить."""

    @abstractmethod
    async def run_weekly(self) -> dict:
        """Еженедельный coaching pack для РОПа."""
