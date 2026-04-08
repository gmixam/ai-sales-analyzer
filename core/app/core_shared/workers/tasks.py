"""Shared task placeholder module.

This module will later define background jobs for STT, LLM calls, delivery,
and periodic maintenance workflows.
"""

from collections.abc import Sequence


def get_registered_tasks() -> Sequence[str]:
    """Return placeholder task names."""
    return ()
