from __future__ import annotations

from typing import Any

from vance.env import ForgeEnv


class HUDAdapter:
    """Small adapter exposing reset/step semantics for HUD-style runners."""

    def __init__(self, task_store: dict[str, dict[str, Any]]):
        self.task_store = task_store
        self.sessions: dict[str, ForgeEnv] = {}

    def reset(self, task_id: str, agent_id: str = "hud_agent", mode: str = "live") -> dict[str, Any]:
        env = ForgeEnv(self.task_store)
        payload = env.reset(task_id, agent_id, mode=mode)
        self.sessions[payload["episode_id"]] = env
        return payload

    def step(self, episode_id: str, action: dict[str, Any]) -> dict[str, Any]:
        if episode_id not in self.sessions:
            raise KeyError(f"Unknown episode_id: {episode_id}")
        env = self.sessions[episode_id]
        response = env.step(action)
        if response["done"]:
            response["trace"] = env.trace
        return response

    def trace(self, episode_id: str) -> dict[str, Any]:
        if episode_id not in self.sessions:
            raise KeyError(f"Unknown episode_id: {episode_id}")
        return self.sessions[episode_id].trace
