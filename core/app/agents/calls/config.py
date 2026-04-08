"""Configuration for the calls agent."""

from dataclasses import dataclass

from app.core_shared.config.settings import settings


@dataclass
class CallsAgentConfig:
    """Настройки агента анализа звонков."""

    min_duration_sec: int = settings.calls_min_duration_sec
    max_daily_per_manager: int = settings.calls_max_daily_per_manager
    weekly_pack_size: int = settings.calls_weekly_pack_size
    allowed_statuses: tuple = ("answered",)
    allowed_directions: tuple = ("in", "out")


calls_config = CallsAgentConfig()
