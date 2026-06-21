from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from vance.env import VanceEnv
from vance.hud import HUDAdapter
from vance.runner import build_agent, validate_run_configuration
from vance.state import load_tasks, summarize_task
from vance.trace import read_jsonl, trace_path, write_jsonl


class ApiService:
    def __init__(self, task_dir: str = "tasks", trace_dir: str = "evals/traces"):
        self.task_dir = task_dir
        self.trace_dir = trace_dir
        self._traces: dict[str, dict[str, Any]] = {}
        self._hud: HUDAdapter | None = None

    def tasks(self) -> dict[str, dict[str, Any]]:
        return load_tasks(self.task_dir)

    def scenarios(self) -> list[dict[str, Any]]:
        return [summarize_task(task) for task in self.tasks().values()]

    def run_episode(self, task_id: str, agent_id: str, mode: str) -> dict[str, Any]:
        validate_run_configuration(agent_id, mode)
        tasks = self.tasks()
        if task_id not in tasks:
            raise KeyError(f"Unknown task_id: {task_id}")
        env = VanceEnv(tasks)
        trace = env.run_episode(build_agent(agent_id), task_id, mode=mode)
        self._traces[trace["episode_id"]] = trace
        path = trace_path(self.trace_dir, agent_id, task_id, trace["episode_id"])
        write_jsonl(path, [trace])
        return trace

    def get_trace(self, episode_id: str) -> dict[str, Any] | None:
        if episode_id in self._traces:
            return self._traces[episode_id]
        for path in Path(self.trace_dir).glob(f"*/*{episode_id}*.jsonl"):
            rows = read_jsonl(path)
            if rows:
                self._traces[episode_id] = rows[0]
                return rows[0]
        return None

    def eval_summary(self) -> dict[str, Any]:
        return {
            "baseline": _read_json(Path("evals/results_baseline.json")),
            "improved": _read_json(Path("evals/results_improved.json")),
        }

    def hud(self) -> HUDAdapter:
        if self._hud is None:
            self._hud = HUDAdapter(self.tasks())
        return self._hud


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())
