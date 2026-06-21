from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
from typing import Any


TASK_FILES = ("easy.jsonl", "medium.jsonl", "hard.jsonl")
TASK_SCHEMA_VERSION = "vance.task.v1"


class TaskValidationError(ValueError):
    """Raised when a task does not satisfy the v1 contract."""


def clone(value: Any) -> Any:
    return deepcopy(value)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    records: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(source.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TaskValidationError(f"{source}:{line_no} contains invalid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise TaskValidationError(f"{source}:{line_no} must be a JSON object")
        records.append(record)
    return records


def load_tasks(task_dir: str | Path = "tasks", task_files: tuple[str, ...] = TASK_FILES) -> dict[str, dict[str, Any]]:
    root = Path(task_dir)
    tasks: dict[str, dict[str, Any]] = {}
    for filename in task_files:
        path = root / filename
        if not path.exists():
            continue
        for task in load_jsonl(path):
            task_id = task.get("task_id")
            if not task_id:
                raise TaskValidationError(f"{path} contains a task without task_id")
            if task_id in tasks:
                raise TaskValidationError(f"Duplicate task_id: {task_id}")
            validate_task(task)
            tasks[task_id] = task
    return tasks


def load_tasks_from_files(paths: list[str | Path]) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    for path in paths:
        for task in load_jsonl(path):
            task_id = task.get("task_id")
            if not task_id:
                raise TaskValidationError(f"{path} contains a task without task_id")
            if task_id in tasks:
                raise TaskValidationError(f"Duplicate task_id: {task_id}")
            validate_task(task)
            tasks[task_id] = task
    return tasks


def validate_task(task: dict[str, Any]) -> None:
    required = {
        "schema_version": str,
        "task_id": str,
        "title": str,
        "difficulty": str,
        "seed": int,
        "max_steps": int,
        "goal": str,
        "public_context": dict,
        "initial_state": dict,
        "manuals": list,
        "expected_outcome": dict,
        "scoring": dict,
        "demo_tags": list,
    }
    for field, expected_type in required.items():
        if field not in task:
            raise TaskValidationError(f"{task.get('task_id', '<unknown>')} missing required field: {field}")
        if not isinstance(task[field], expected_type):
            raise TaskValidationError(f"{task.get('task_id', '<unknown>')} field {field} must be {expected_type.__name__}")
    if task["schema_version"] != TASK_SCHEMA_VERSION:
        raise TaskValidationError(f"{task['task_id']} must use schema_version {TASK_SCHEMA_VERSION}")
    if task["difficulty"] not in {"easy", "medium", "hard"}:
        raise TaskValidationError(f"{task['task_id']} has invalid difficulty {task['difficulty']}")
    if task["max_steps"] < 1 or task["max_steps"] > 12:
        raise TaskValidationError(f"{task['task_id']} max_steps must be between 1 and 12")
    _validate_state(task)
    _validate_manuals(task)
    _validate_expected_outcome(task)


def summarize_task(task: dict[str, Any]) -> dict[str, Any]:
    state = task["initial_state"]
    return {
        "task_id": task["task_id"],
        "title": task["title"],
        "difficulty": task["difficulty"],
        "goal": task["goal"],
        "demo_tags": task["demo_tags"],
        "machines": list(state.get("machines", {}).keys()),
        "orders": [order.get("id") for order in state.get("orders", [])],
        "safety_rules": [rule.get("description") for rule in state.get("safety_rules", [])],
    }


def _validate_state(task: dict[str, Any]) -> None:
    state = task["initial_state"]
    for field in ("machines", "inventory", "orders", "safety_rules", "event_log"):
        if field not in state:
            raise TaskValidationError(f"{task['task_id']} initial_state missing {field}")
    if not isinstance(state["machines"], dict) or not state["machines"]:
        raise TaskValidationError(f"{task['task_id']} must define at least one machine")
    if not isinstance(state["orders"], list):
        raise TaskValidationError(f"{task['task_id']} orders must be a list")
    if not isinstance(state["event_log"], list):
        raise TaskValidationError(f"{task['task_id']} event_log must be a list")


def _validate_manuals(task: dict[str, Any]) -> None:
    if not task["manuals"]:
        raise TaskValidationError(f"{task['task_id']} must include at least one manual entry")
    required = {
        "manual_id",
        "error_code",
        "symptoms",
        "diagnosis_hint",
        "required_steps",
        "required_part_id",
        "safe_actions",
        "unsafe_actions",
        "warnings",
        "escalation_rules",
        "estimated_recovery_hours",
    }
    for manual in task["manuals"]:
        if not isinstance(manual, dict):
            raise TaskValidationError(f"{task['task_id']} manual entries must be objects")
        missing = sorted(required - set(manual))
        if missing:
            raise TaskValidationError(f"{task['task_id']} manual missing fields: {missing}")


def _validate_expected_outcome(task: dict[str, Any]) -> None:
    outcome = task["expected_outcome"]
    required = {
        "affected_machine_id",
        "diagnosis",
        "required_tools",
        "required_manual_ids",
        "required_part_ids",
        "safe_actions",
        "allowed_final_states",
        "must_escalate",
        "unsafe_tool_attempts",
        "deadline_assertion",
        "report_required_fields",
    }
    missing = sorted(required - set(outcome))
    if missing:
        raise TaskValidationError(f"{task['task_id']} expected_outcome missing fields: {missing}")
    if outcome["affected_machine_id"] not in task["initial_state"]["machines"]:
        raise TaskValidationError(f"{task['task_id']} expected machine is not in initial_state")
