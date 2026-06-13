#!/usr/bin/env python3
"""Host wrapper for the package-owned call-processing CLI."""

from app.agents.call_processing.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
