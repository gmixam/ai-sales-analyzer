"""Database access package shared across all agents and services."""

from app.core_shared.db.base import Base
from app.core_shared.db.models import (
    Agreement,
    Analysis,
    Department,
    Insight,
    Interaction,
    Manager,
    ManagerProgress,
    Prompt,
    PromptSuggestion,
)
from app.core_shared.db.session import SessionLocal, engine, get_db

__all__ = [
    "Agreement",
    "Analysis",
    "Base",
    "Department",
    "Insight",
    "Interaction",
    "Manager",
    "ManagerProgress",
    "Prompt",
    "PromptSuggestion",
    "SessionLocal",
    "engine",
    "get_db",
]
