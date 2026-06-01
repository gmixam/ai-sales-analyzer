"""Top-level mirror for Report Evidence Registry tests."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_TEST_PATH = PROJECT_ROOT / "core" / "tests" / "test_report_evidence_registry.py"
SPEC = importlib.util.spec_from_file_location("core_test_report_evidence_registry", CORE_TEST_PATH)
assert SPEC is not None and SPEC.loader is not None
core_test_report_evidence_registry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = core_test_report_evidence_registry
SPEC.loader.exec_module(core_test_report_evidence_registry)

ReportEvidenceRegistryTests = core_test_report_evidence_registry.ReportEvidenceRegistryTests


if __name__ == "__main__":
    unittest.main()
