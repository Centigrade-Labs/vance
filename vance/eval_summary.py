"""Generate vance.eval.v1 summaries from trace JSONL files."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from .trace import parse_jsonl


def generate_eval_summary(output_dir: str | Path) -> dict[str, Any]:
    base = Path(output_dir)
    agents: dict[str, dict[str, Any]] = {}
    all_trace_files: list[str] = []
    for name in ("baseline", "improved"):
        path = base / f"{name}.jsonl"
        if not path.exists():
            continue
        traces = parse_jsonl(path)
        all_trace_files.append(str(path))
        agents[name] = _agent_metrics(traces)

    task_ids = sorted({trace["task_id"] for name in ("baseline", "improved") for trace in _load_if_exists(base / f"{name}.jsonl")})
    return {
        "schema_version": "vance.eval.v1",
        "run_id": "eval_local_fallback",
        "mode": "fallback",
        "taskset": {"total": len(task_ids), "task_ids": task_ids},
        "agents": agents,
        "trace_files": all_trace_files,
    }


def write_eval_summary(output_dir: str | Path) -> dict[str, Any]:
    summary = generate_eval_summary(output_dir)
    path = Path(output_dir) / "eval_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _load_if_exists(path: Path) -> list[dict[str, Any]]:
    return parse_jsonl(path) if path.exists() else []


def _agent_metrics(traces: list[dict[str, Any]]) -> dict[str, Any]:
    if not traces:
        return {
            "episodes": 0,
            "pass_rate": 0.0,
            "average_reward": 0.0,
            "safety_violation_rate": 0.0,
            "manual_lookup_rate": 0.0,
            "inventory_check_rate": 0.0,
            "report_completion_rate": 0.0,
            "average_steps": 0.0,
        }

    verifier_results = [trace["verifier_result"] for trace in traces]
    metrics = [result.get("metrics", {}) for result in verifier_results]
    return {
        "episodes": len(traces),
        "pass_rate": _rate(result.get("success", False) for result in verifier_results),
        "average_reward": round(mean(float(result.get("reward", 0.0)) for result in verifier_results), 4),
        "safety_violation_rate": _rate(result.get("hard_fail", False) for result in verifier_results),
        "manual_lookup_rate": _rate(metric.get("manual_lookup", False) for metric in metrics),
        "inventory_check_rate": _rate(metric.get("inventory_check", False) for metric in metrics),
        "report_completion_rate": _rate(metric.get("report_complete", False) for metric in metrics),
        "average_steps": round(mean(len(trace.get("steps", [])) for trace in traces), 2),
    }


def _rate(values) -> float:
    items = list(values)
    if not items:
        return 0.0
    return round(sum(1 for value in items if value) / len(items), 4)

