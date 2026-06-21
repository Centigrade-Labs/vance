from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.demo_data import DEMO_SCENARIOS, demo_eval_summary


class DashboardService:
    def __init__(self, task_dir: str = "tasks", trace_dir: str = "evals/traces"):
        self.task_dir = Path(task_dir)
        self.trace_dir = Path(trace_dir)
        self._traces: dict[str, dict[str, Any]] = {}
        self._scenario_index = {scenario["task_id"]: scenario for scenario in DEMO_SCENARIOS}
        self._hud = _HUDAdapter(self)
        self._seed_demo_traces()

    def scenarios(self) -> list[dict[str, Any]]:
        return deepcopy(DEMO_SCENARIOS)

    def run_episode(self, task_id: str, agent_id: str, mode: str) -> dict[str, Any]:
        scenario = self._scenario_index.get(task_id)
        if scenario is None:
            raise KeyError(f"Unknown task_id: {task_id}")

        variant_key = "baseline_slm" if agent_id == "baseline_slm" else "improved_slm"
        template = deepcopy(scenario["trace_variants"][variant_key])
        trace = self._stamp_trace(template, agent_id=agent_id, mode=mode)
        self._store_trace(trace)
        return trace

    def get_trace(self, episode_id: str) -> dict[str, Any] | None:
        if episode_id in self._traces:
            return deepcopy(self._traces[episode_id])

        if self.trace_dir.exists():
            for path in self.trace_dir.rglob(f"{episode_id}.jsonl"):
                rows = _read_jsonl(path)
                if rows:
                    self._traces[episode_id] = rows[0]
                    return deepcopy(rows[0])

        return None

    def eval_summary(self) -> dict[str, Any]:
        baseline = _read_json_file(Path("evals/results_baseline.json"))
        improved = _read_json_file(Path("evals/results_improved.json"))
        if baseline is not None or improved is not None:
            return {
                "baseline": baseline or demo_eval_summary()["baseline"],
                "improved": improved or demo_eval_summary()["improved"],
            }
        return demo_eval_summary()

    def hud(self) -> "_HUDAdapter":
        return self._hud

    def _seed_demo_traces(self) -> None:
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        for scenario in DEMO_SCENARIOS:
            for variant in scenario["trace_variants"].values():
                trace = deepcopy(variant)
                self._store_trace(trace, persist=False)

    def _stamp_trace(self, trace: dict[str, Any], *, agent_id: str, mode: str) -> dict[str, Any]:
        episode_id = f"ep_{trace['task_id']}_{agent_id}_{_timestamp_key()}"
        now = datetime.now(timezone.utc)
        trace["episode_id"] = episode_id
        trace["agent_id"] = agent_id
        trace["mode"] = mode
        trace["started_at"] = now.isoformat().replace("+00:00", "Z")
        trace["ended_at"] = (now + timedelta(seconds=max(4, len(trace.get("steps", [])) * 2))).isoformat().replace(
            "+00:00", "Z"
        )
        return trace

    def _store_trace(self, trace: dict[str, Any], *, persist: bool = True) -> None:
        self._traces[trace["episode_id"]] = deepcopy(trace)
        if not persist:
            return

        path = self.trace_dir / trace["agent_id"] / trace["task_id"] / f"{trace['episode_id']}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trace, sort_keys=True) + "\n", encoding="utf-8")


def _timestamp_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


class _HUDAdapter:
    def __init__(self, service: DashboardService):
        self._service = service
        self._episodes: dict[str, dict[str, Any]] = {}

    def reset(self, task_id: str, agent_id: str, mode: str) -> dict[str, Any]:
        scenario = self._service._scenario_index.get(task_id)
        if scenario is None:
            raise KeyError(f"Unknown task_id: {task_id}")

        episode_id = f"hud_{task_id}_{agent_id}_{_timestamp_key()}"
        payload = {
            "episode_id": episode_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "mode": mode,
            "step": 0,
            "scenario": scenario["title"],
        }
        self._episodes[episode_id] = deepcopy(payload)
        return deepcopy(payload)

    def step(self, episode_id: str, action: dict[str, Any]) -> dict[str, Any]:
        payload = self._episodes.get(episode_id)
        if payload is None:
            raise KeyError(f"Unknown episode_id: {episode_id}")

        payload["step"] += 1
        payload["last_action"] = deepcopy(action)
        payload["observation"] = {
            "status": "ok",
            "accepted": True,
            "step": payload["step"],
        }
        return deepcopy(payload)


ApiService = DashboardService
