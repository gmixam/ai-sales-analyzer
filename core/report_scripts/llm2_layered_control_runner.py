#!/usr/bin/env python3
"""Control runner for LLM2 layered proof artifacts.

The runner is intentionally limited to the analysis evidence layer:

baseline artifact + layered simulation -> adapter -> validate_report_evidence
-> Evidence Registry -> report block router -> JSON/Markdown summary.

It does not render report previews, PDFs, Telegram messages, or delivery output.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable


CORE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CORE_ROOT.parent
DEFAULT_PACKAGE_DIR = (
    CORE_ROOT
    / "review_packages"
    / "llm2_recalibration_control_sample_2026-05-18_2026-05-20"
)
DEFAULT_OUTPUT_DIR_NAME = "llm2_layered_control_runner_output"
DEFAULT_ADAPTER_MODULES = (
    "app.agents.calls.llm2_layered_analysis",
    "app.agents.calls.llm2_layered_proof_adapter",
    "app.agents.calls.llm2_layered_adapter",
    "app.agents.calls.llm2_proof_adapter",
)
DEFAULT_ADAPTER_FUNCTIONS = (
    "normalize_llm2_layered_scores_detail",
    "normalize_llm2_layered_analysis",
    "adapt_layered_proof_simulation",
    "adapt_layered_llm2_artifact",
    "adapt_layered_artifact",
    "adapt_to_scores_detail",
    "build_scores_detail",
    "to_scores_detail",
)


if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))


class RunnerError(Exception):
    """Expected runner failure that should be written as an artifact."""


class AdapterUnavailableError(RunnerError):
    """Raised when the layered adapter module/function is not available."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run LLM2 layered proof simulation artifacts through the adapter, "
            "report evidence validator, Evidence Registry, and report block router."
        ),
    )
    parser.add_argument(
        "--package-dir",
        type=Path,
        default=DEFAULT_PACKAGE_DIR,
        help="Review package directory with baseline_artifacts/ and layered proof simulation artifacts.",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help="Override baseline artifacts directory. Defaults to PACKAGE/baseline_artifacts.",
    )
    parser.add_argument(
        "--simulation-dir",
        type=Path,
        default=None,
        help="Override layered proof simulation directory. Defaults to latest PACKAGE/llm2_layered_proof_simulation_*.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Output directory. Defaults to PACKAGE/{DEFAULT_OUTPUT_DIR_NAME}.",
    )
    parser.add_argument(
        "--adapter-module",
        default=None,
        help=(
            "Adapter module to import. Defaults to trying known LLM2 layered adapter module names."
        ),
    )
    parser.add_argument(
        "--adapter-function",
        default=None,
        help=(
            "Adapter function to call. Defaults to trying common adapter function names."
        ),
    )
    parser.add_argument(
        "--allow-missing-adapter",
        action="store_true",
        help="Write adapter_unavailable artifacts and exit 0 instead of 2.",
    )
    return parser


def _install_default_env() -> None:
    defaults = {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/test_db",
        "POSTGRES_DB": "test_db",
        "POSTGRES_USER": "user",
        "POSTGRES_PASSWORD": "pass",
        "REDIS_URL": "redis://:pass@localhost:6379/0",
        "REDIS_PASSWORD": "pass",
        "OPENAI_API_KEY": "test-key",
        "ASSEMBLYAI_API_KEY": "test-key",
        "ONLINEPBX_DOMAIN": "example.onpbx.ru",
        "ONLINEPBX_API_KEY": "test-key",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RunnerError(f"JSON artifact must be an object: {_rel(path)}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return _rel(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


def _resolve_simulation_dir(package_dir: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    candidates = [
        item
        for item in package_dir.glob("llm2_layered_proof_simulation_*")
        if item.is_dir()
    ]
    if not candidates:
        raise RunnerError(f"No llm2_layered_proof_simulation_* directory under {_rel(package_dir)}")
    return sorted(candidates)[-1]


def _load_baselines(baseline_dir: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    baselines: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for path in sorted(baseline_dir.glob("*.json")):
        try:
            payload = _load_json(path)
            call_id = _text(_path_get(payload, "interaction.id"))
            if not call_id:
                issues.append({"path": _rel(path), "reason": "missing_interaction_id"})
                continue
            baselines[call_id] = {"path": path, "payload": payload}
        except Exception as exc:
            issues.append({"path": _rel(path), "reason": "load_error", "error": str(exc)})
    return baselines, issues


def _load_simulations(simulation_dir: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    simulations: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for path in sorted(simulation_dir.glob("*_llm2_layered_proof_simulation.json")):
        try:
            payload = _load_json(path)
            call_id = _text(payload.get("call_id"))
            if not call_id:
                issues.append({"path": _rel(path), "reason": "missing_call_id"})
                continue
            simulations[call_id] = {"path": path, "payload": payload}
        except Exception as exc:
            issues.append({"path": _rel(path), "reason": "load_error", "error": str(exc)})
    return simulations, issues


def _build_pairs(
    baselines: dict[str, dict[str, Any]],
    simulations: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for call_id in sorted(set(baselines) & set(simulations)):
        baseline = baselines[call_id]
        simulation = simulations[call_id]
        day = _text(simulation["payload"].get("day")) or _text(baseline["payload"].get("day"))
        pairs.append(
            {
                "call_id": call_id,
                "day": day,
                "baseline_path": baseline["path"],
                "baseline": baseline["payload"],
                "simulation_path": simulation["path"],
                "simulation": simulation["payload"],
            }
        )
    for call_id in sorted(set(baselines) - set(simulations)):
        issues.append(
            {
                "call_id": call_id,
                "baseline_path": _rel(baselines[call_id]["path"]),
                "reason": "missing_simulation_artifact",
            }
        )
    for call_id in sorted(set(simulations) - set(baselines)):
        issues.append(
            {
                "call_id": call_id,
                "simulation_path": _rel(simulations[call_id]["path"]),
                "reason": "missing_baseline_artifact",
            }
        )
    return sorted(pairs, key=lambda item: (item.get("day") or "", item["call_id"])), issues


def _load_adapter(module_name: str | None, function_name: str | None) -> tuple[str, str, Callable[..., Any]]:
    module_names = (module_name,) if module_name else DEFAULT_ADAPTER_MODULES
    function_names = (function_name,) if function_name else DEFAULT_ADAPTER_FUNCTIONS
    import_errors: list[str] = []
    for candidate_module_name in module_names:
        local_path = _local_module_path(candidate_module_name)
        if local_path is not None and not local_path.exists():
            import_errors.append(
                f"{candidate_module_name}: module file not found at {_rel(local_path)}"
            )
            continue
        try:
            module = _import_module(candidate_module_name, local_path=local_path)
        except Exception as exc:
            import_errors.append(f"{candidate_module_name}: {type(exc).__name__}: {exc}")
            continue
        for candidate_function_name in function_names:
            fn = getattr(module, candidate_function_name, None)
            if callable(fn):
                return candidate_module_name, candidate_function_name, fn
        import_errors.append(
            f"{candidate_module_name}: missing adapter function; tried {', '.join(function_names)}"
        )
    raise AdapterUnavailableError("; ".join(import_errors))


def _local_module_path(module_name: str) -> Path | None:
    prefix = "app."
    if not module_name.startswith(prefix):
        return None
    path = CORE_ROOT / Path(*module_name.split(".")).with_suffix(".py")
    return path if path.exists() else None


def _import_module(module_name: str, *, local_path: Path | None) -> Any:
    if local_path is None:
        return importlib.import_module(module_name)
    synthetic_name = f"_llm2_layered_control_runner_{local_path.stem}"
    spec = importlib.util.spec_from_file_location(synthetic_name, local_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot build import spec for {_rel(local_path)}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[synthetic_name] = module
    spec.loader.exec_module(module)
    return module


def _invoke_adapter(
    adapter_fn: Callable[..., Any],
    *,
    baseline: dict[str, Any],
    simulation: dict[str, Any],
    baseline_path: Path,
    simulation_path: Path,
) -> dict[str, Any]:
    kwargs = {
        "artifact": simulation,
        "baseline": baseline,
        "baseline_artifact": baseline,
        "baseline_payload": baseline,
        "simulation": simulation,
        "simulation_artifact": simulation,
        "layered_artifact": simulation,
        "layered_proof_artifact": simulation,
        "baseline_path": baseline_path,
        "simulation_path": simulation_path,
        "transcript": _text(_path_get(baseline, "interaction.text")),
    }
    try:
        signature = inspect.signature(adapter_fn)
    except (TypeError, ValueError):
        result = adapter_fn(baseline, simulation)
    else:
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if accepts_kwargs:
            result = adapter_fn(**kwargs)
        else:
            accepted = {
                name: value
                for name, value in kwargs.items()
                if name in parameters
            }
            if accepted:
                result = adapter_fn(**accepted)
            else:
                positional_params = [
                    parameter
                    for parameter in parameters.values()
                    if parameter.kind
                    in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    )
                ]
                if len(positional_params) == 1:
                    result = adapter_fn(simulation)
                else:
                    result = adapter_fn(baseline, simulation)
    return _extract_scores_detail(result)


def _extract_scores_detail(adapter_result: Any) -> dict[str, Any]:
    result = _to_mapping(adapter_result)
    if not result:
        raise RunnerError("Adapter returned an empty or non-mapping result")
    scores_detail = _to_mapping(result.get("scores_detail"))
    if scores_detail:
        return scores_detail
    analysis_scores_detail = _to_mapping(_path_get(result, "analysis.scores_detail"))
    if analysis_scores_detail:
        return analysis_scores_detail
    if "report_evidence" in result or "report_evidence_version" in result:
        return result
    raise RunnerError(
        "Adapter result must be scores_detail-like or contain scores_detail/analysis.scores_detail"
    )


def _run_pipeline(
    pairs: list[dict[str, Any]],
    *,
    adapter_module: str,
    adapter_function: str,
    adapter_fn: Callable[..., Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.agents.calls.report_block_router import route_evidence_items
    from app.agents.calls.report_evidence import validate_report_evidence
    from app.agents.calls.report_evidence_registry import (
        build_report_evidence_registry,
        report_evidence_registry_as_dicts,
    )

    records: list[dict[str, Any]] = []
    aggregate: dict[str, Any] = {
        "validation": Counter(),
        "validation_error_codes": Counter(),
        "validation_warning_codes": Counter(),
        "registry_items": 0,
        "registry_proof_status": Counter(),
        "router_routed_by_block": Counter(),
        "records_by_day": defaultdict(int),
    }

    for pair in pairs:
        call_id = pair["call_id"]
        day = pair.get("day")
        record: dict[str, Any] = {
            "status": "ok",
            "day": day,
            "call_id": call_id,
            "baseline_path": _rel(pair["baseline_path"]),
            "simulation_path": _rel(pair["simulation_path"]),
            "adapter": {"module": adapter_module, "function": adapter_function},
        }
        try:
            scores_detail = _invoke_adapter(
                adapter_fn,
                baseline=pair["baseline"],
                simulation=pair["simulation"],
                baseline_path=pair["baseline_path"],
                simulation_path=pair["simulation_path"],
            )
            transcript = _text(_path_get(pair["baseline"], "interaction.text"))
            validation = validate_report_evidence(scores_detail, transcript)
            validation_payload = validation.model_dump(mode="json")
            registry_artifact = {"call_id": call_id, "scores_detail": scores_detail}
            registry_items = build_report_evidence_registry([registry_artifact])
            registry_dicts = report_evidence_registry_as_dicts(registry_items)
            routed = route_evidence_items(registry_items)
            router_summary = _to_mapping(_path_get(routed, "diagnostics.summary"))
            registry_proof_status = Counter(
                _text(_path_get(item, "diagnostics.proof_status")) or "unknown"
                for item in registry_dicts
            )
            routed_by_block = Counter(
                {
                    str(block): int(count)
                    for block, count in _to_mapping(
                        router_summary.get("routed_count_by_block")
                    ).items()
                }
            )

            errors = validation_payload.get("errors") or []
            warnings = validation_payload.get("warnings") or []
            aggregate["validation"]["valid" if validation.is_valid else "invalid"] += 1
            aggregate["registry_items"] += len(registry_dicts)
            aggregate["registry_proof_status"].update(registry_proof_status)
            aggregate["router_routed_by_block"].update(routed_by_block)
            aggregate["records_by_day"][day or "unknown"] += 1
            aggregate["validation_error_codes"].update(
                _text(item.get("code")) or "unknown" for item in errors
            )
            aggregate["validation_warning_codes"].update(
                _text(item.get("code")) or "unknown" for item in warnings
            )

            record.update(
                {
                    "validation": {
                        "is_valid": validation.is_valid,
                        "version": validation_payload.get("version"),
                        "error_count": len(errors),
                        "warning_count": len(warnings),
                        "errors": errors,
                        "warnings": warnings,
                    },
                    "registry": {
                        "item_count": len(registry_dicts),
                        "proof_status_counts": dict(sorted(registry_proof_status.items())),
                    },
                    "router": {
                        "routing_version": routed.get("routing_version"),
                        "routed_count_by_block": dict(sorted(routed_by_block.items())),
                        "rejected_count": router_summary.get("rejected_count"),
                    },
                }
            )
        except Exception as exc:
            record.update(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
        records.append(record)

    return records, _finalize_aggregate(aggregate)


def _finalize_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    return {
        "validation": dict(sorted(aggregate["validation"].items())),
        "validation_error_codes": dict(sorted(aggregate["validation_error_codes"].items())),
        "validation_warning_codes": dict(sorted(aggregate["validation_warning_codes"].items())),
        "registry_items": aggregate["registry_items"],
        "registry_proof_status": dict(sorted(aggregate["registry_proof_status"].items())),
        "router_routed_by_block": dict(sorted(aggregate["router_routed_by_block"].items())),
        "records_by_day": dict(sorted(aggregate["records_by_day"].items())),
    }


def _build_summary(
    *,
    status: str,
    args: argparse.Namespace,
    baseline_dir: Path,
    simulation_dir: Path,
    output_dir: Path,
    baselines: dict[str, dict[str, Any]],
    simulations: dict[str, dict[str, Any]],
    pairs: list[dict[str, Any]],
    load_issues: list[dict[str, Any]],
    match_issues: list[dict[str, Any]],
    records: list[dict[str, Any]] | None = None,
    aggregate: dict[str, Any] | None = None,
    adapter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = records or []
    record_status = Counter(_text(item.get("status")) or "unknown" for item in records)
    if status == "completed" and record_status.get("error"):
        status = "completed_with_record_errors"
    if status == "completed" and aggregate and aggregate.get("validation", {}).get("invalid"):
        status = "completed_with_validation_errors"
    return {
        "artifact_type": "llm2_layered_control_runner_summary",
        "artifact_version": "llm2_layered_control_runner_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "scope_guardrails": {
            "report_layer_pdf_telegram_delivery_run": False,
            "runner_scope": "LLM2 adapter, validate_report_evidence, evidence_registry, router",
        },
        "inputs": {
            "package_dir": _rel(args.package_dir),
            "baseline_dir": _rel(baseline_dir),
            "simulation_dir": _rel(simulation_dir),
        },
        "outputs": {
            "output_dir": _rel(output_dir),
            "summary_json": _rel(output_dir / "summary.json"),
            "summary_markdown": _rel(output_dir / "summary.md"),
        },
        "adapter": adapter or {},
        "counts": {
            "baseline_files": len(baselines),
            "simulation_files": len(simulations),
            "matched_pairs": len(pairs),
            "records": len(records),
            "record_status": dict(sorted(record_status.items())),
            "load_issues": len(load_issues),
            "match_issues": len(match_issues),
        },
        "aggregate": aggregate or {},
        "load_issues": load_issues,
        "match_issues": match_issues,
        "records": records,
    }


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# LLM2 layered control runner summary",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Generated at: `{summary.get('generated_at')}`",
        f"- Package: `{_to_mapping(summary.get('inputs')).get('package_dir')}`",
        f"- Baseline dir: `{_to_mapping(summary.get('inputs')).get('baseline_dir')}`",
        f"- Simulation dir: `{_to_mapping(summary.get('inputs')).get('simulation_dir')}`",
        f"- JSON summary: `{_to_mapping(summary.get('outputs')).get('summary_json')}`",
        f"- Markdown summary: `{_to_mapping(summary.get('outputs')).get('summary_markdown')}`",
        "",
        "Scope guardrail: no Report Layer preview/PDF/Telegram/delivery path was run.",
        "",
    ]
    adapter = _to_mapping(summary.get("adapter"))
    if adapter:
        lines.extend(
            [
                "## Adapter",
                "",
                f"- Module: `{adapter.get('module') or 'unavailable'}`",
                f"- Function: `{adapter.get('function') or 'unavailable'}`",
                f"- Status: `{adapter.get('status') or 'unknown'}`",
            ]
        )
        if adapter.get("error"):
            lines.append(f"- Error: `{_escape_md(str(adapter.get('error'))[:400])}`")
        lines.append("")

    counts = _to_mapping(summary.get("counts"))
    lines.extend(
        [
            "## Counts",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Baseline files | {counts.get('baseline_files', 0)} |",
            f"| Simulation files | {counts.get('simulation_files', 0)} |",
            f"| Matched pairs | {counts.get('matched_pairs', 0)} |",
            f"| Records | {counts.get('records', 0)} |",
            f"| Load issues | {counts.get('load_issues', 0)} |",
            f"| Match issues | {counts.get('match_issues', 0)} |",
            "",
        ]
    )

    aggregate = _to_mapping(summary.get("aggregate"))
    if aggregate:
        lines.extend(
            [
                "## Aggregate",
                "",
                f"- Validation: `{json.dumps(aggregate.get('validation', {}), ensure_ascii=False)}`",
                f"- Registry proof status: `{json.dumps(aggregate.get('registry_proof_status', {}), ensure_ascii=False)}`",
                f"- Router routed by block: `{json.dumps(aggregate.get('router_routed_by_block', {}), ensure_ascii=False)}`",
                "",
            ]
        )

    records = summary.get("records") or []
    if records:
        lines.extend(
            [
                "## Records",
                "",
                "| Day | Call ID | Status | Valid | Registry items | Routed blocks |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for record in records:
            validation = _to_mapping(record.get("validation"))
            registry = _to_mapping(record.get("registry"))
            router = _to_mapping(record.get("router"))
            routed = router.get("routed_count_by_block") or {}
            routed_short = ", ".join(
                f"{block}:{count}" for block, count in sorted(_to_mapping(routed).items()) if count
            )
            lines.append(
                "| {day} | `{call_id}` | `{status}` | {valid} | {items} | {routed} |".format(
                    day=_escape_md(record.get("day") or ""),
                    call_id=_escape_md(record.get("call_id") or ""),
                    status=_escape_md(record.get("status") or ""),
                    valid=str(validation.get("is_valid")) if validation else "",
                    items=registry.get("item_count", ""),
                    routed=_escape_md(routed_short),
                )
            )
        lines.append("")

    issues = (summary.get("load_issues") or []) + (summary.get("match_issues") or [])
    if issues:
        lines.extend(["## Input Issues", "", "| Reason | Path/Call |", "|---|---|"])
        for issue in issues[:50]:
            path_or_call = issue.get("path") or issue.get("baseline_path") or issue.get("simulation_path") or issue.get("call_id")
            lines.append(
                f"| `{_escape_md(issue.get('reason') or 'unknown')}` | `{_escape_md(path_or_call or '')}` |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return {}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    namespace = getattr(value, "__dict__", None)
    return dict(namespace) if isinstance(namespace, dict) else {}


def _path_get(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
            continue
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _escape_md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    _install_default_env()
    package_dir = args.package_dir
    baseline_dir = args.baseline_dir or package_dir / "baseline_artifacts"
    simulation_dir = _resolve_simulation_dir(package_dir, args.simulation_dir)
    output_dir = args.output_dir or package_dir / DEFAULT_OUTPUT_DIR_NAME

    baselines, baseline_issues = _load_baselines(baseline_dir)
    simulations, simulation_issues = _load_simulations(simulation_dir)
    pairs, match_issues = _build_pairs(baselines, simulations)
    load_issues = baseline_issues + simulation_issues

    if not pairs:
        summary = _build_summary(
            status="no_matched_pairs",
            args=args,
            baseline_dir=baseline_dir,
            simulation_dir=simulation_dir,
            output_dir=output_dir,
            baselines=baselines,
            simulations=simulations,
            pairs=pairs,
            load_issues=load_issues,
            match_issues=match_issues,
        )
        return 1, summary

    try:
        adapter_module, adapter_function, adapter_fn = _load_adapter(
            args.adapter_module,
            args.adapter_function,
        )
    except AdapterUnavailableError as exc:
        summary = _build_summary(
            status="adapter_unavailable",
            args=args,
            baseline_dir=baseline_dir,
            simulation_dir=simulation_dir,
            output_dir=output_dir,
            baselines=baselines,
            simulations=simulations,
            pairs=pairs,
            load_issues=load_issues,
            match_issues=match_issues,
            adapter={
                "status": "unavailable",
                "module": args.adapter_module,
                "function": args.adapter_function,
                "default_modules": list(DEFAULT_ADAPTER_MODULES),
                "default_functions": list(DEFAULT_ADAPTER_FUNCTIONS),
                "error": str(exc),
            },
        )
        return (0 if args.allow_missing_adapter else 2), summary

    records, aggregate = _run_pipeline(
        pairs,
        adapter_module=adapter_module,
        adapter_function=adapter_function,
        adapter_fn=adapter_fn,
    )
    summary = _build_summary(
        status="completed",
        args=args,
        baseline_dir=baseline_dir,
        simulation_dir=simulation_dir,
        output_dir=output_dir,
        baselines=baselines,
        simulations=simulations,
        pairs=pairs,
        load_issues=load_issues,
        match_issues=match_issues,
        records=records,
        aggregate=aggregate,
        adapter={
            "status": "loaded",
            "module": adapter_module,
            "function": adapter_function,
        },
    )
    return 0 if summary["status"] == "completed" else 1, summary


def main() -> int:
    args = build_parser().parse_args()
    output_dir = args.output_dir or args.package_dir / DEFAULT_OUTPUT_DIR_NAME
    try:
        exit_code, summary = run(args)
    except Exception as exc:
        summary = {
            "artifact_type": "llm2_layered_control_runner_summary",
            "artifact_version": "llm2_layered_control_runner_v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "runner_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "outputs": {
                "output_dir": _rel(output_dir),
                "summary_json": _rel(output_dir / "summary.json"),
                "summary_markdown": _rel(output_dir / "summary.md"),
            },
        }
        exit_code = 1
    _write_json(output_dir / "summary.json", summary)
    _write_text(output_dir / "summary.md", _markdown(summary))
    print(json.dumps({"status": summary.get("status"), **summary.get("outputs", {})}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
