"""Build the prompt dataset used to trigger Fireworks RFT rollouts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from vance.data_loader import load_ai4i_rows
from vance.runner import DATA_PATH, TASK_DIR, generate_task_files
from vance.scenarios import build_100_scenarios, public_initial_observation
from vance.trace import parse_jsonl


DEFAULT_OUTPUT = Path(__file__).resolve().parent / "vance_rft_prompts.jsonl"


def build_records(csv_path: str | Path = DATA_PATH) -> list[dict[str, Any]]:
    generate_task_files(csv_path)
    scenarios = build_100_scenarios(load_ai4i_rows(csv_path))
    task_ids = [str(record["task_id"]) for record in parse_jsonl(TASK_DIR / "train_80.jsonl")]
    records = []
    for task_id in task_ids:
        scenario = scenarios[task_id]
        payload = {
            "task_id": scenario.scenario_id,
            "scenario_id": scenario.scenario_id,
            "difficulty": scenario.difficulty,
            "max_steps": 8,
            "initial_observation": public_initial_observation(scenario),
        }
        records.append(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": json.dumps(payload, sort_keys=True),
                    }
                ],
                "metadata": {
                    "task_id": scenario.scenario_id,
                    "difficulty": scenario.difficulty,
                },
            }
        )
    return records


def write_dataset(path: str | Path = DEFAULT_OUTPUT, csv_path: str | Path = DATA_PATH) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in build_records(csv_path):
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Vance Fireworks RFT prompt dataset.")
    parser.add_argument("--csv", default=str(DATA_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    path = write_dataset(args.out, args.csv)
    print(f"wrote {len(build_records(args.csv))} RFT prompt rows to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
