"""CLI runner for the isolated Vance MVP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.vance_mvp.agents import agent_for_id
from prototypes.vance_mvp.data_loader import load_ai4i_rows
from prototypes.vance_mvp.environment import VanceEnvironment
from prototypes.vance_mvp.eval_summary import write_eval_summary
from prototypes.vance_mvp.scenarios import P0_SCENARIO_IDS, build_scenarios, build_twenty_task_records, task_record_from_scenario
from prototypes.vance_mvp.trace import parse_jsonl, write_jsonl, write_records_jsonl


OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the isolated Vance MVP demo.")
    parser.add_argument("--csv", required=True, help="Path to data/ai4i2020.csv")
    parser.add_argument("--scenario", help="Optional single scenario/task id")
    parser.add_argument("--agent", choices=["baseline", "improved"], help="Optional single agent")
    args = parser.parse_args(argv)

    rows = load_ai4i_rows(args.csv)
    scenarios = build_scenarios(rows)
    if args.scenario and args.scenario not in scenarios:
        raise ValueError(f"Unknown scenario: {args.scenario}")
    scenario_ids = [args.scenario] if args.scenario else list(P0_SCENARIO_IDS)
    agent_ids = [args.agent] if args.agent else ["baseline", "improved"]

    write_records_jsonl(OUTPUT_DIR / "p0_tasks.jsonl", [task_record_from_scenario(scenarios[item]) for item in P0_SCENARIO_IDS])
    write_records_jsonl(OUTPUT_DIR / "taskset_20.jsonl", build_twenty_task_records(rows))

    traces_by_agent: dict[str, list[object]] = {"baseline": [], "improved": []}
    summary_rows: list[tuple[str, str, str, str, str, str]] = []
    for agent_id in agent_ids:
        agent = agent_for_id(agent_id)
        for scenario_id in scenario_ids:
            env = VanceEnvironment(scenarios)
            trace = env.run_episode(agent, scenario_id)
            traces_by_agent[agent_id].append(trace)
            result = trace.verifier_result
            summary_rows.append(
                (
                    scenario_id,
                    trace.agent_id,
                    "PASS" if result.passed else "FAIL",
                    f"{result.reward:.2f}",
                    result.hard_fail_reason or "-",
                    str(trace.final_state.get("final_outcome", "-")),
                )
            )

    if traces_by_agent["baseline"]:
        write_jsonl(OUTPUT_DIR / "baseline.jsonl", traces_by_agent["baseline"])
    if traces_by_agent["improved"]:
        write_jsonl(OUTPUT_DIR / "improved.jsonl", traces_by_agent["improved"])
    write_eval_summary(OUTPUT_DIR)

    _print_table(summary_rows)

    for name in ("baseline.jsonl", "improved.jsonl"):
        path = OUTPUT_DIR / name
        if path.exists():
            parse_jsonl(path)
    return 0


def _print_table(rows: list[tuple[str, str, str, str, str, str]]) -> None:
    headers = ("scenario", "agent", "result", "reward", "hard_fail_reason", "final_outcome")
    table = [headers] + rows
    widths = [max(len(str(row[index])) for row in table) for index in range(len(headers))]
    print(" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


if __name__ == "__main__":
    raise SystemExit(main())
