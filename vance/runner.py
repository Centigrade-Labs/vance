"""Command-line runner and task generation for Vance."""

from __future__ import annotations

import argparse
from pathlib import Path

from agents import build_agent
from agents.fireworks_agent import LiveAgentUnavailable

from .data_loader import load_ai4i_rows
from .env import VanceEnvironment
from .eval_summary import write_eval_summary
from .scenarios import (
    P0_SCENARIO_IDS,
    build_100_scenarios,
    build_100_task_records,
    build_p0_scenarios,
    build_twenty_scenarios,
    build_twenty_task_records,
    split_100_task_records,
)
from .trace import parse_jsonl, write_jsonl, write_records_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = REPO_ROOT / "data" / "ai4i2020.csv"
TASK_DIR = REPO_ROOT / "tasks"
EVAL_DIR = REPO_ROOT / "evals"
TRACE_ROOT = EVAL_DIR / "traces"


def generate_task_files(csv_path: str | Path = DATA_PATH) -> list[dict[str, object]]:
    rows = load_ai4i_rows(csv_path)
    tasks = build_twenty_task_records(rows)
    vance_100 = build_100_task_records(rows)
    train_80, heldout_20 = split_100_task_records(vance_100)
    by_difficulty = {"easy": [], "medium": [], "hard": []}
    for task in tasks:
        by_difficulty[str(task["difficulty"])].append(task)
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    for difficulty, records in by_difficulty.items():
        write_records_jsonl(TASK_DIR / f"{difficulty}.jsonl", records)
    write_records_jsonl(TASK_DIR / "vance_100.jsonl", vance_100)
    write_records_jsonl(TASK_DIR / "train_80.jsonl", train_80)
    write_records_jsonl(TASK_DIR / "heldout_20.jsonl", heldout_20)
    return tasks


def load_task_ids(task_path: str | Path | None = None) -> list[str]:
    if task_path is None:
        return [task["task_id"] for task in generate_task_files()]
    return [task["task_id"] for task in parse_jsonl(task_path)]


def run_one(task_id: str, agent_id: str, mode: str = "fallback", csv_path: str | Path = DATA_PATH):
    rows = load_ai4i_rows(csv_path)
    scenarios = _all_scenarios(rows)
    if task_id not in scenarios:
        raise ValueError(f"unknown task {task_id}")
    agent = build_agent(agent_id, mode=mode)
    return VanceEnvironment(scenarios).run_episode(agent, task_id, mode=mode)


def _all_scenarios(rows: list[dict[str, str]]) -> dict[str, object]:
    scenarios = build_twenty_scenarios(rows)
    scenarios.update(build_100_scenarios(rows))
    return scenarios


def run_p0_fallback(csv_path: str | Path = DATA_PATH) -> dict[str, list[object]]:
    rows = load_ai4i_rows(csv_path)
    scenarios = {scenario.scenario_id: scenario for scenario in build_p0_scenarios(rows)}
    traces_by_agent: dict[str, list[object]] = {"baseline": [], "improved": []}
    for agent_id in ("baseline", "improved"):
        agent = build_agent(agent_id)
        for task_id in P0_SCENARIO_IDS:
            traces_by_agent[agent_id].append(VanceEnvironment(scenarios).run_episode(agent, task_id, mode="fallback"))
    return traces_by_agent


def write_trace_outputs(traces_by_agent: dict[str, list[object]], mode: str = "fallback") -> None:
    for agent_id, traces in traces_by_agent.items():
        out_dir = TRACE_ROOT / mode / agent_id
        out_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(out_dir / "traces.jsonl", traces)
    write_eval_summary(TRACE_ROOT / mode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Vance episode.")
    parser.add_argument("--task", default="resolve")
    parser.add_argument("--agent", default="improved_slm")
    parser.add_argument("--mode", choices=["fallback", "live"], default="fallback")
    parser.add_argument("--csv", default=str(DATA_PATH))
    parser.add_argument("--generate-tasks", action="store_true")
    args = parser.parse_args(argv)

    if args.generate_tasks:
        tasks = generate_task_files(args.csv)
        print(f"wrote {len(tasks)} task records to {TASK_DIR}")

    try:
        trace = run_one(args.task, args.agent, mode=args.mode, csv_path=args.csv)
    except LiveAgentUnavailable as exc:
        print(f"LIVE_UNAVAILABLE: {exc}")
        return 2

    out_dir = TRACE_ROOT / args.mode / args.agent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{trace.task_id}.jsonl"
    write_jsonl(out_path, [trace])
    result = trace.verifier_result
    print(f"{trace.task_id} {trace.agent_id} {'PASS' if result.passed else 'FAIL'} reward={result.reward:.2f} trace={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
