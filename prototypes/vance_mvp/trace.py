"""JSONL trace serialization for the Vance MVP."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .models import EpisodeTrace


def trace_to_dict(trace: EpisodeTrace) -> dict[str, Any]:
    result = trace.verifier_result
    return {
        "schema_version": trace.schema_version,
        "episode_id": trace.episode_id,
        "task_id": trace.task_id,
        "scenario_id": trace.scenario_id,
        "agent_id": trace.agent_id,
        "mode": trace.mode,
        "seed": trace.seed,
        "source_csv_row_identifier": trace.source_csv_row_identifier,
        "public_initial_observation": _plain(trace.public_initial_observation),
        "attempted_invalid_actions": list(trace.attempted_invalid_actions),
        "steps": [
            {
                "index": step.index,
                "tool": step.action.name,
                "args": _plain(step.action.arguments),
                "rationale": step.operational_rationale,
                "ok": step.result.status.value == "ok",
                "blocked": step.result.status.value == "blocked",
                "observation": _plain(step.result.observation),
                "state_delta": _plain(step.result.state_changes),
                "verifier_notes": [{"severity": "info", "message": step.result.verifier_note}],
                "reward_delta": 0,
                "hard_fail": step.result.status.value == "blocked" and step.action.name not in {"submit_incident_report"},
            }
            for step in trace.steps
        ],
        "final_state": _plain(trace.final_state),
        "final_report": _plain(trace.final_report),
        "verifier_result": {
            "success": result.passed,
            "passed": result.passed,
            "reward": result.reward,
            "hard_fail": result.hard_fail,
            "hard_fail_reason": result.hard_fail_reason,
            "reward_breakdown": [
                {"component": component, "points": points, "earned": points > 0}
                for component, points in result.reward_breakdown.items()
            ],
            "fail_reasons": list(result.fail_reasons),
            "success_reasons": list(result.success_reasons),
            "metrics": dict(result.metrics),
            "notes": list(result.notes),
        },
    }


def write_jsonl(path: str | Path, traces: list[EpisodeTrace]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace_to_dict(trace), sort_keys=True) + "\n")


def write_records_jsonl(path: str | Path, records: list[dict[str, Any]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(_plain(record), sort_keys=True) + "\n")


def parse_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
