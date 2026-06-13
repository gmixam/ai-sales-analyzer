from __future__ import annotations

from app.agents.calls.manual_reporting_runner import build_parser


def test_manual_reporting_runner_accepts_force_rebuild_analyses_flag() -> None:
    args = build_parser().parse_args(
        [
            "--department-id",
            "472cda28-ce71-494c-9068-25d3ffbf7399",
            "--preset",
            "manager_daily",
            "--mode",
            "build_missing_and_report",
            "--date-from",
            "2026-06-03",
            "--manager-extension",
            "322",
            "--force-rebuild-analyses",
            "--no-delivery",
        ]
    )

    assert args.force_rebuild_analyses is True
    assert args.no_delivery is True
