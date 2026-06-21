from __future__ import annotations

from dataclasses import replace
from typing import Any

from vance.env import VanceEnvironment
from vance.models import ToolAction
from vance.trace import trace_to_dict
from vance.verifier import verify_trace


class HUDAdapter:
    """Small adapter exposing reset/step semantics for HUD-style runners."""

    def __init__(self, scenarios: dict[str, Any]):
        self.scenarios = scenarios
        self.sessions: dict[str, VanceEnvironment] = {}
        self.episodes: dict[str, str] = {}

    def reset(self, task_id: str, agent_id: str = "hud_agent", mode: str = "fallback") -> dict[str, Any]:
        env = VanceEnvironment(self.scenarios)
        observation = env.reset(task_id, agent_id, mode=mode)
        episode_id = f"hud_{task_id}_{agent_id}"
        self.sessions[episode_id] = env
        self.episodes[episode_id] = task_id
        return {
            "episode_id": episode_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "mode": mode,
            "initial_observation": observation,
        }

    def step(self, episode_id: str, action: dict[str, Any]) -> dict[str, Any]:
        if episode_id not in self.sessions:
            raise KeyError(f"Unknown episode_id: {episode_id}")
        env = self.sessions[episode_id]
        observation = env.step(ToolAction(str(action.get("tool", "")), dict(action.get("args", {}))))
        return {
            "episode_id": episode_id,
            "observation": observation,
            "done": bool(env.state.get("terminated")),
        }

    def trace(self, episode_id: str) -> dict[str, Any]:
        if episode_id not in self.sessions:
            raise KeyError(f"Unknown episode_id: {episode_id}")
        env = self.sessions[episode_id]
        trace = env._build_trace({})
        return trace_to_dict(replace(trace, verifier_result=verify_trace(trace, env.scenario_or_raise())))
