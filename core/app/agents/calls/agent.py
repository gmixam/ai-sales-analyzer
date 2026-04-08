"""Composition root for the calls agent.

The calls agent will orchestrate intake, extraction, analysis, and delivery
using deterministic Python modules and shared infrastructure services.
"""

from . import analyzer, delivery, extractor, intake

__all__ = ["analyzer", "delivery", "extractor", "intake"]
