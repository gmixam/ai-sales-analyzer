"""Analysis purpose markers used by reporting and controlled verification runs."""

from __future__ import annotations

from typing import Any

ANALYSIS_PURPOSE_PRODUCTION = "production"
ANALYSIS_PURPOSE_CONTROLLED_SAMPLE = "controlled_sample"
ANALYSIS_PURPOSE_VERIFICATION = "verification"

CONTROLLED_ANALYSIS_PURPOSES = {
    ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
    ANALYSIS_PURPOSE_VERIFICATION,
}
VALID_ANALYSIS_PURPOSES = {
    ANALYSIS_PURPOSE_PRODUCTION,
    *CONTROLLED_ANALYSIS_PURPOSES,
}


def normalize_analysis_purpose(value: Any) -> str | None:
    """Return a canonical analysis purpose or None when the value is unknown."""
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "prod": ANALYSIS_PURPOSE_PRODUCTION,
        "stable": ANALYSIS_PURPOSE_PRODUCTION,
        "sample": ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        "controlled": ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        "controlled_sample": ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        "verification": ANALYSIS_PURPOSE_VERIFICATION,
        "verification_only": ANALYSIS_PURPOSE_VERIFICATION,
        "manual_verification_fixture": ANALYSIS_PURPOSE_VERIFICATION,
    }
    normalized = aliases.get(text, text)
    return normalized if normalized in VALID_ANALYSIS_PURPOSES else None


def analysis_purpose_from_scores_detail(
    scores_detail: Any,
    *,
    instruction_version: Any = None,
) -> str:
    """Resolve purpose from persisted JSON, treating old unmarked rows as production."""
    detail = scores_detail if isinstance(scores_detail, dict) else {}
    meta = detail.get("meta") if isinstance(detail.get("meta"), dict) else {}
    purpose = normalize_analysis_purpose(
        detail.get("analysis_purpose")
        or meta.get("analysis_purpose")
        or detail.get("purpose")
        or meta.get("purpose")
    )
    if purpose:
        return purpose

    provenance = str(detail.get("provenance") or meta.get("provenance") or "").strip().lower()
    instruction = str(instruction_version or "").strip().lower()
    if "verification" in provenance or instruction.startswith("verification"):
        return ANALYSIS_PURPOSE_VERIFICATION

    return ANALYSIS_PURPOSE_PRODUCTION


def analysis_purpose_from_analysis(analysis: Any) -> str:
    """Resolve the purpose for an Analysis-like row."""
    return analysis_purpose_from_scores_detail(
        getattr(analysis, "scores_detail", None),
        instruction_version=getattr(analysis, "instruction_version", None),
    )


def is_controlled_analysis_purpose(purpose: Any) -> bool:
    """Return whether the purpose belongs to a non-production verification/sample run."""
    return normalize_analysis_purpose(purpose) in CONTROLLED_ANALYSIS_PURPOSES


def is_controlled_analysis(analysis: Any) -> bool:
    """Return whether an Analysis-like row should be excluded from normal reports."""
    return analysis_purpose_from_analysis(analysis) in CONTROLLED_ANALYSIS_PURPOSES


def mark_scores_detail_analysis_purpose(
    result: dict[str, Any],
    *,
    analysis_purpose: Any = None,
    write_default: bool = True,
) -> dict[str, Any]:
    """Return a shallow-copied analysis contract with a canonical purpose marker."""
    normalized = normalize_analysis_purpose(analysis_purpose)
    detail = dict(result or {})
    meta = dict(detail.get("meta") or {}) if isinstance(detail.get("meta"), dict) else {}
    existing = analysis_purpose_from_scores_detail(detail)
    purpose = normalized or existing or ANALYSIS_PURPOSE_PRODUCTION
    if not write_default and purpose == ANALYSIS_PURPOSE_PRODUCTION and not analysis_purpose:
        return detail
    meta["analysis_purpose"] = purpose
    detail["meta"] = meta
    detail["analysis_purpose"] = purpose
    return detail
