#!/usr/bin/env python3
"""Host wrapper for the package-owned call-processing CLI."""

from pathlib import Path
import sys

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.call_processing.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
