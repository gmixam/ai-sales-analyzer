"""Minimal diagnostics CLI for OnlinePBX live CDR and audio fetch."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

from app.agents.calls.extractor import CallsExtractor
from app.agents.calls.intake import OnlinePBXIntake
from app.core_shared.config.settings import settings


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for one live OnlinePBX probe."""
    parser = argparse.ArgumentParser(description="Probe OnlinePBX CDR and recording download.")
    parser.add_argument("--date", required=True, help="Call date in YYYY-MM-DD")
    parser.add_argument("--call-id", help="Specific OnlinePBX uuid to probe")
    parser.add_argument(
        "--min-talk-duration",
        type=int,
        default=settings.calls_min_duration_sec,
        help="Minimum talk duration when auto-picking one record",
    )
    parser.add_argument(
        "--skip-audio",
        action="store_true",
        help="Stop after CDR validation and recording URL lookup.",
    )
    return parser


def main() -> None:
    """Run the probe and print a compact JSON report."""
    department_id = "00000000-0000-0000-0000-000000000001"
    intake = OnlinePBXIntake(department_id=department_id, db=None)
    extractor = CallsExtractor(department_id=department_id, db=None)

    args = build_parser().parse_args()
    records = intake.get_cdr_list(args.date)
    selected = _pick_record(records=records, call_id=args.call_id, min_talk_duration=args.min_talk_duration)
    recording_url = intake.get_recording_url(selected.call_id)

    result: dict[str, object] = {
        "config": {
            "domain": settings.onlinepbx_domain,
            "base_url": settings.onlinepbx_base_url,
            "cdr_url": intake._safe_url(intake.cdr_url),
            "auth_url": intake._safe_url(intake.auth_url or ""),
            "stt_provider": settings.stt_provider,
            "manual_live_stt_provider": settings.effective_manual_live_stt_provider,
        },
        "cdr": {
            "date": args.date,
            "fetched": len(records),
            "selected_call_id": selected.call_id,
            "selected_extension": selected.extension,
            "selected_phone": selected.phone,
            "selected_talk_duration": selected.talk_duration,
            "selected_direction": selected.direction,
        },
        "recording": {
            "url": extractor._safe_url(recording_url),
        },
    }

    if not args.skip_audio:
        artifact = extractor.download_and_extract(
            SimpleNamespace(
                id="probe",
                external_id=selected.call_id,
                raw_ref=recording_url,
            )
        )
        result["audio"] = {
            "path": str(artifact),
            "size_bytes": artifact.stat().st_size,
            "suffix": artifact.suffix,
        }
        artifact.unlink(missing_ok=True)

    print(json.dumps(result, ensure_ascii=False, indent=2))


def _pick_record(*, records, call_id: str | None, min_talk_duration: int):
    """Pick one record for the live probe."""
    if call_id:
        for record in records:
            if record.call_id == call_id:
                return record
        raise SystemExit(f"Call id {call_id} was not found in the fetched CDR list.")

    eligible = [record for record in records if record.talk_duration >= min_talk_duration]
    if not eligible:
        raise SystemExit(
            f"No call matched min talk duration {min_talk_duration} seconds for this date."
        )
    return sorted(eligible, key=lambda item: item.talk_duration, reverse=True)[0]


if __name__ == "__main__":
    main()
