"""Registry of deterministic project agents."""

from app.agents.base import BaseAgent

# Реестр агентов. Добавить агент = одна строка здесь.
# Scheduler вызывает: AGENT_REGISTRY["calls"].run_daily(dept_id)
AGENT_REGISTRY: dict[str, type[BaseAgent]] = {}

# CallsAgent добавляется после реализации в calls/agent.py
# from app.agents.calls.agent import CallsAgent
# AGENT_REGISTRY["calls"] = CallsAgent
