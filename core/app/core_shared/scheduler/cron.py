"""Cron scheduling placeholder.

This module will later define periodic task schedules for polling telephony
sources, cleanup jobs, and reporting routines.
"""

from collections.abc import Mapping


def get_schedule() -> Mapping[str, str]:
    """Return a placeholder periodic schedule definition."""
    return {}
