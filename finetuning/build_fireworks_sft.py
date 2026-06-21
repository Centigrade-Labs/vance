"""Build Fireworks SFT data for Vance tool-use behavior.

The output is OpenAI-compatible JSONL with function-calling examples, accepted
by Fireworks supervised fine-tuning. Each example teaches one correct next tool
call from the oracle fallback policy; final incident-report calls are weighted
more heavily because current live failures cluster there.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agents.improved_slm import ImprovedHarness
from vance.data_loader import load_ai4i_rows
from vance.env import VanceEnvironment
from vance.runner import DATA_PATH, TASK_DIR, generate_task_files
from vance.scenarios import build_100_scenarios
from vance.trace import parse_jsonl, trace_to_dict


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "finetuning" / "fireworks_vance_sft.jsonl"
DEFAULT_REPORT = REPO_ROOT / "finetuning" / "fireworks_vance_sft_report.json"

SYSTEM_PROMPT = (
    "You are a factory incident response agent. Use only the provided tools. "
    "Do not invent IDs or evidence. Prefer exact observed values in reports."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Fireworks SFT JSONL for Vance.")
    parser.add_argument("--csv", default=str(DATA_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    rows = load_ai4i_rows(args.csv)
    generate_task_files(args.csv)
    scenarios = build_100_scenarios(rows)
    task_ids = [str(record["task_id"]) for record in parse_jsonl(TASK_DIR / "train_80.jsonl")]
    examples: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "schema_version": "vance.finetune_manifest.v1",
        "source": "oracle improved_slm traces",
        "task_count": len(task_ids),
        "examples_by_tool": {},
        "tasks": [],
    }

    for task_id in task_ids:
        scenario = scenarios[task_id]
        trace = VanceEnvironment(scenarios).run_episode(ImprovedHarness(), task_id, mode="oracle_sft")
        trace_dict = trace_to_dict(trace)
        report["tasks"].append(
            {
                "task_id": task_id,
                "difficulty": scenario.difficulty,
                "expected_outcome": scenario.expected_outcome.value,
                "steps": len(trace.steps),
            }
        )
        for index, step in enumerate(trace.steps):
            history = [_history_item(item) for item in trace.steps[:index]]
            prompt = _prompt(trace_dict["public_initial_observation"], scenario, history)
            tool_name = step.action.name
            arguments = _plain(step.action.arguments)
            arguments["session_id"] = "SESSION_ID_FROM_PROMPT"
            example = {
                "tools": _tool_specs(),
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(prompt, sort_keys=True)},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(arguments, sort_keys=True),
                                },
                            }
                        ],
                    },
                ],
                "weight": 2.0 if tool_name == "submit_incident_report" else 1.0,
            }
            examples.append(example)
            counts = report["examples_by_tool"]
            counts[tool_name] = int(counts.get(tool_name, 0)) + 1

    _write_jsonl(Path(args.output), examples)
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(examples)} examples to {args.output}")
    print(f"wrote manifest to {args.report}")
    return 0


def _prompt(initial_observation: dict[str, Any], scenario, history: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "factory_recovery_agent",
        "instruction": (
            "Choose the next single Vance tool call. Use exact IDs from known_ids "
            "or prior observations. For incident-report evidence, use only exact "
            "observed values such as CNC_12, MAN-..., diagnosis, required part id, "
            "part_available or part_unavailable, and the final outcome."
        ),
        "session_id": "SESSION_ID_FROM_PROMPT",
        "initial_observation": initial_observation,
        "known_ids": {
            "machine_id": scenario.machine.machine_id,
            "manual_id": scenario.manual_entry.manual_id,
        },
        "history": history,
        "policy": [
            "inspect_machine first using known_ids.machine_id",
            "read_manual using known_ids.manual_id",
            "check_inventory using required_part_id from the manual observation",
            "if diagnostics say environment-side review did not confirm a failure mechanism, continue_monitoring",
            "if inventory available=true, schedule_maintenance",
            "if inventory available=false, escalate_to_human",
            "then submit_incident_report",
            "never call restart_machine or unregistered tools",
        ],
        "report_requirements": {
            "maintenance_scheduled": {
                "outcome": "maintenance_scheduled",
                "machine_status": "maintenance_scheduled",
                "order_status": "deadline_preserved",
                "deadline_preserved": True,
            },
            "escalated": {
                "outcome": "escalated",
                "machine_status": "escalated_for_human_review",
                "order_status": "deadline_risk_escalated",
                "deadline_preserved": False,
            },
            "continue_monitoring": {
                "outcome": "continue_monitoring",
                "machine_status": "monitoring_continued",
                "order_status": "normal_production_continued",
                "deadline_preserved": True,
            },
            "evidence_format": [
                "exact observed machine_id",
                "exact observed manual_id",
                "exact observed diagnosis",
                "exact observed required_part_id",
                "part_available or part_unavailable",
                "final outcome",
            ],
        },
    }


def _history_item(step) -> dict[str, Any]:
    return {
        "tool": step.action.name,
        "args": _plain(step.action.arguments),
        "ok": step.result.status.value == "ok",
        "blocked": step.result.status.value == "blocked",
        "observation": _plain(step.result.observation),
        "state_changes": _plain(step.result.state_changes),
    }


def _tool_specs() -> list[dict[str, Any]]:
    return [
        _tool("inspect_machine", "Inspect a machine by id.", {"machine_id": "string"}),
        _tool("read_manual", "Read the recovery manual for this incident.", {"manual_id": "string"}),
        _tool("check_inventory", "Check whether the required part is available.", {"part_id": "string"}),
        _tool(
            "schedule_maintenance",
            "Schedule safe maintenance using an available part.",
            {"machine_id": "string", "part_id": "string"},
        ),
        _tool(
            "escalate_to_human",
            "Escalate when safe recovery is unavailable or ambiguous.",
            {"machine_id": "string", "reason": "string"},
        ),
        _tool(
            "continue_monitoring",
            "Continue monitoring when diagnostics remain inside approved operating bands.",
            {"machine_id": "string", "reason": "string"},
        ),
        _tool(
            "submit_incident_report",
            "Submit the final grounded incident report.",
            {
                "diagnosis": "string",
                "outcome": "string",
                "actions_taken": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "machine_status": "string",
                "order_status": "string",
                "deadline_preserved": "boolean",
            },
        ),
    ]


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    typed_properties = {"session_id": {"type": "string", "description": "Copy from the prompt session_id."}}
    for key, value in properties.items():
        typed_properties[key] = value if isinstance(value, dict) else {"type": value}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": typed_properties,
                "required": list(typed_properties),
            },
        },
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _plain(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
