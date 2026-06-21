from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import uuid
from typing import Any


TRACE_SCHEMA_VERSION = "forge.trace.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_episode_id(task_id: str, agent_id: str) -> str:
    return f"ep_{task_id}_{agent_id}_{uuid.uuid4().hex[:8]}"


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(source.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source}:{line_no} contains invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{source}:{line_no} must contain a JSON object")
        rows.append(row)
    return rows


def trace_path(trace_dir: str | Path, agent_id: str, task_id: str, episode_id: str) -> Path:
    return Path(trace_dir) / agent_id / f"{task_id}_{episode_id}.jsonl"
