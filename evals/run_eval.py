"""Run Vance evals and write generated metrics."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import build_agent
from agents.fireworks_agent import LiveAgentUnavailable
from vance.data_loader import load_ai4i_rows
from vance.runner import DATA_PATH, generate_task_files
from vance.scenarios import build_100_scenarios, build_twenty_scenarios
from vance.trace import parse_jsonl, trace_to_dict, write_jsonl
from vance.env import VanceEnvironment


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "evals"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Vance baseline/improved/live evals.")
    parser.add_argument("--agent", choices=["baseline_slm", "improved_slm", "fireworks_agent"], required=True)
    parser.add_argument("--tasks", default=str(REPO_ROOT / "tasks" / "easy.jsonl"))
    parser.add_argument("--mode", choices=["fallback", "live"], default="fallback")
    parser.add_argument("--csv", default=str(DATA_PATH))
    args = parser.parse_args(argv)

    task_path = Path(args.tasks)
    if not task_path.exists() or task_path.stat().st_size == 0:
        generate_task_files(args.csv)

    task_ids = [record["task_id"] for record in parse_jsonl(task_path)]
    rows = load_ai4i_rows(args.csv)
    scenarios = build_twenty_scenarios(rows)
    scenarios.update(build_100_scenarios(rows))
    try:
        agent = build_agent(args.agent, mode=args.mode)
    except LiveAgentUnavailable as exc:
        _write_unavailable(args.agent, args.mode, str(exc), task_ids)
        print(f"LIVE_UNAVAILABLE: {exc}")
        return 2

    traces = [VanceEnvironment(scenarios).run_episode(agent, task_id, mode=args.mode) for task_id in task_ids]
    trace_dir = EVAL_DIR / "traces" / args.mode / args.agent
    trace_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(trace_dir / "traces.jsonl", traces)
    for trace in traces:
        write_jsonl(trace_dir / f"{trace.task_id}.jsonl", [trace])

    result = eval_result(args.agent, args.mode, [trace_to_dict(trace) for trace in traces], [str(trace_dir / "traces.jsonl")])
    result_path = _result_path(args.agent, args.mode)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {result_path}")
    return 0


def eval_result(agent_id: str, mode: str, traces: list[dict[str, object]], trace_files: list[str]) -> dict[str, object]:
    verifier_results = [trace["verifier_result"] for trace in traces]
    metrics = [result.get("metrics", {}) for result in verifier_results]
    common_failures = Counter(
        result.get("hard_fail_reason") or "reward_below_threshold"
        for result in verifier_results
        if not result.get("success", False)
    )
    return {
        "schema_version": "vance.eval.v1",
        "run_id": f"eval_{mode}_{agent_id}",
        "agent_id": agent_id,
        "mode": mode,
        "taskset": {"episodes": len(traces), "task_ids": [trace["task_id"] for trace in traces]},
        "metrics": {
            "episodes": len(traces),
            "pass_rate": _rate(result.get("success", False) for result in verifier_results),
            "average_reward": _avg(float(result.get("reward", 0.0)) for result in verifier_results),
            "safety_violation_rate": _rate(result.get("hard_fail", False) for result in verifier_results),
            "manual_lookup_rate": _rate(metric.get("manual_lookup", False) for metric in metrics),
            "inventory_check_rate": _rate(metric.get("inventory_check", False) for metric in metrics),
            "report_completion_rate": _rate(metric.get("report_complete", False) for metric in metrics),
            "average_steps": _avg(len(trace.get("steps", [])) for trace in traces),
        },
        "common_failures": [{"code": code, "count": count} for code, count in common_failures.most_common()],
        "trace_files": trace_files,
    }


def _write_unavailable(agent_id: str, mode: str, reason: str, task_ids: list[str]) -> None:
    result = {
        "schema_version": "vance.eval.v1",
        "run_id": f"eval_{mode}_{agent_id}",
        "agent_id": agent_id,
        "mode": mode,
        "live_unavailable": True,
        "unavailable_reason": reason,
        "taskset": {"episodes": 0, "task_ids": task_ids},
        "metrics": {"episodes": 0, "pass_rate": 0.0, "average_reward": 0.0},
        "common_failures": [{"code": "LIVE_UNAVAILABLE", "count": len(task_ids)}],
        "trace_files": [],
    }
    _result_path(agent_id, mode).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


def _result_path(agent_id: str, mode: str) -> Path:
    if agent_id == "baseline_slm":
        return EVAL_DIR / "results_baseline.json"
    if agent_id == "improved_slm":
        return EVAL_DIR / "results_improved.json"
    return EVAL_DIR / "results_live_qwen.json"


def _rate(values) -> float:
    items = list(values)
    return round(sum(1 for value in items if value) / len(items), 4) if items else 0.0


def _avg(values) -> float:
    items = list(values)
    return round(mean(items), 4) if items else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
