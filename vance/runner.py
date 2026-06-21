from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agents.baseline_slm import BaselineAgent
from agents.fireworks_agent import FireworksAgent
from agents.improved_slm import ImprovedAgent
from vance.env import ForgeEnv
from vance.state import load_tasks, load_tasks_from_files, summarize_task
from vance.trace import trace_path, write_jsonl


AGENTS = {
    "baseline_slm": BaselineAgent,
    "improved_slm": ImprovedAgent,
    "fireworks_agent": FireworksAgent,
}


def build_agent(agent_id: str) -> Any:
    if agent_id not in AGENTS:
        raise KeyError(f"Unknown agent: {agent_id}")
    return AGENTS[agent_id]()


def load_task_store(task_dir: str = "tasks", task_paths: list[str] | None = None) -> dict[str, dict[str, Any]]:
    if task_paths:
        return load_tasks_from_files(task_paths)
    return load_tasks(task_dir)


def run_one(task_id: str, agent_id: str, mode: str = "fallback", task_dir: str = "tasks", task_paths: list[str] | None = None) -> dict[str, Any]:
    tasks = load_task_store(task_dir, task_paths)
    if task_id not in tasks:
        raise KeyError(f"Unknown task_id: {task_id}. Loaded tasks: {sorted(tasks)}")
    env = ForgeEnv(tasks)
    return env.run_episode(build_agent(agent_id), task_id, mode=mode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Forge/Vance episodes.")
    parser.add_argument("--task", help="Task ID to run.")
    parser.add_argument("--agent", default="improved_slm", choices=sorted(AGENTS))
    parser.add_argument("--mode", default="fallback", choices=["fallback", "live"])
    parser.add_argument("--task-dir", default="tasks")
    parser.add_argument("--tasks", nargs="*", default=None, help="Optional JSONL task files.")
    parser.add_argument("--trace-dir", default="evals/traces")
    parser.add_argument("--out", default=None, help="Optional JSONL output path.")
    parser.add_argument("--list", action="store_true", help="List loaded scenarios and exit.")
    args = parser.parse_args()

    task_store = load_task_store(args.task_dir, args.tasks)
    if args.list:
        print(json.dumps([summarize_task(task) for task in task_store.values()], indent=2, sort_keys=True))
        return
    if not args.task:
        raise SystemExit("--task is required unless --list is used")
    if args.task not in task_store:
        raise SystemExit(f"Unknown task_id {args.task}. Loaded {len(task_store)} tasks.")
    env = ForgeEnv(task_store)
    trace = env.run_episode(build_agent(args.agent), args.task, mode=args.mode)
    out = Path(args.out) if args.out else trace_path(args.trace_dir, args.agent, args.task, trace["episode_id"])
    write_jsonl(out, [trace])
    print(json.dumps({"trace_file": str(out), "verifier_result": trace["verifier_result"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
