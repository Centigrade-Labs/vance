from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vance.env import ForgeEnv
from vance.runner import build_agent, load_task_store
from vance.trace import trace_path, utc_now, write_json, write_jsonl


def run_eval(
    *,
    agent_id: str,
    mode: str,
    task_dir: str,
    task_paths: list[str] | None,
    trace_dir: str,
) -> dict[str, Any]:
    tasks = load_task_store(task_dir, task_paths)
    traces: list[dict[str, Any]] = []
    trace_files: list[str] = []
    for task_id in sorted(tasks):
        env = ForgeEnv(tasks)
        trace = env.run_episode(build_agent(agent_id), task_id, mode=mode)
        traces.append(trace)
        path = trace_path(trace_dir, agent_id, task_id, trace["episode_id"])
        write_jsonl(path, [trace])
        trace_files.append(str(path))
    result = build_eval_result(agent_id, mode, tasks, traces, trace_files)
    return result


def build_eval_result(
    agent_id: str,
    mode: str,
    tasks: dict[str, dict[str, Any]],
    traces: list[dict[str, Any]],
    trace_files: list[str],
) -> dict[str, Any]:
    episodes = len(traces)
    taskset = Counter(task.get("difficulty", "unknown") for task in tasks.values())
    verifier_results = [trace.get("verifier_result") or {} for trace in traces]
    metrics = {
        "episodes": episodes,
        "pass_rate": _rate(result.get("success") for result in verifier_results),
        "average_reward": _average(result.get("reward", 0.0) for result in verifier_results),
        "safety_violation_rate": _rate(result.get("metrics", {}).get("safety_violation") for result in verifier_results),
        "manual_lookup_rate": _rate(result.get("metrics", {}).get("manual_lookup") for result in verifier_results),
        "inventory_check_rate": _rate(result.get("metrics", {}).get("inventory_check") for result in verifier_results),
        "report_completion_rate": _rate(result.get("metrics", {}).get("report_complete") for result in verifier_results),
        "average_steps": _average(result.get("metrics", {}).get("steps", 0) for result in verifier_results),
    }
    failure_counts: Counter[str] = Counter()
    for result in verifier_results:
        for reason in result.get("fail_reasons", []):
            failure_counts[reason] += 1
    return {
        "schema_version": "forge.eval.v1",
        "run_id": f"eval_{agent_id}_{utc_now()}",
        "generated_at": utc_now(),
        "taskset": dict(taskset),
        "agent_id": agent_id,
        "mode": mode,
        "metrics": metrics,
        "common_failures": [{"code": reason, "count": count} for reason, count in failure_counts.most_common()],
        "trace_files": trace_files,
    }


def _rate(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return round(sum(1 for value in values if value) / len(values), 3)


def _average(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return round(sum(float(value or 0.0) for value in values) / len(values), 3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Forge/Vance evals.")
    parser.add_argument("--agent", default="improved_slm", choices=["baseline_slm", "improved_slm", "fireworks_agent"])
    parser.add_argument("--mode", default="fallback", choices=["fallback", "live"])
    parser.add_argument("--task-dir", default="tasks")
    parser.add_argument("--tasks", nargs="*", default=None, help="Optional JSONL task files.")
    parser.add_argument("--trace-dir", default="evals/traces")
    parser.add_argument("--out", default=None, help="Optional result JSON path.")
    args = parser.parse_args()

    result = run_eval(
        agent_id=args.agent,
        mode=args.mode,
        task_dir=args.task_dir,
        task_paths=args.tasks,
        trace_dir=args.trace_dir,
    )
    out = Path(args.out or f"evals/results_{args.agent.replace('_slm', '')}.json")
    write_json(out, result)
    print(json.dumps({"result_file": str(out), "metrics": result["metrics"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
