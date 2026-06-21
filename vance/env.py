from __future__ import annotations

from copy import deepcopy
from typing import Any

from vance.tools import ToolRegistry
from vance.trace import TRACE_SCHEMA_VERSION, new_episode_id, utc_now
from vance.verifier import verify_episode


class ForgeEnv:
    def __init__(self, task_store: dict[str, dict[str, Any]], manual_store: Any = None, seed: int | None = None):
        self.task_store = task_store
        self.manual_store = manual_store
        self.seed = seed
        self.task: dict[str, Any] | None = None
        self.state: dict[str, Any] | None = None
        self.trace: dict[str, Any] | None = None
        self.done = False

    def reset(self, task_id: str, agent_id: str, mode: str = "live") -> dict[str, Any]:
        if task_id not in self.task_store:
            raise KeyError(f"Unknown task_id: {task_id}")
        self.task = deepcopy(self.task_store[task_id])
        self.state = deepcopy(self.task["initial_state"])
        self.done = False
        episode_id = new_episode_id(task_id, agent_id)
        self.trace = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "episode_id": episode_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "mode": mode,
            "seed": self.task.get("seed", self.seed),
            "started_at": utc_now(),
            "ended_at": None,
            "steps": [],
            "final_state": None,
            "final_report": None,
            "verifier_result": None,
        }
        return {
            "episode_id": episode_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "mode": mode,
            "seed": self.task.get("seed", self.seed),
            "max_steps": self.task["max_steps"],
            "public_task": {
                "title": self.task["title"],
                "goal": self.task["goal"],
                "difficulty": self.task["difficulty"],
                "machines": list(self.state.get("machines", {}).keys()),
                "orders": [order.get("id") for order in self.state.get("orders", [])],
                "visible_safety_rules": [rule.get("description") for rule in self.state.get("safety_rules", [])],
                "public_context": self.task.get("public_context", {}),
            },
            "initial_observation": {
                "machines": self.state.get("machines", {}),
                "orders": self.state.get("orders", []),
                "available_tools": [
                    "inspect_machine",
                    "read_manual",
                    "check_inventory",
                    "schedule_maintenance",
                    "escalate_to_human",
                    "submit_incident_report",
                ],
            },
        }

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        if self.done:
            raise RuntimeError("Episode is already done.")
        if self.task is None or self.state is None or self.trace is None:
            raise RuntimeError("Environment must be reset before step.")
        if not isinstance(action, dict):
            action = {"tool": None, "args": {}, "rationale": "Invalid action payload."}

        tool = action.get("tool")
        args = action.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        registry = ToolRegistry(self.task, self.state, self.trace["steps"])
        result = registry.call(tool, args)
        index = len(self.trace["steps"]) + 1
        step_record = {
            "index": index,
            "tool": tool,
            "args": args,
            "rationale": action.get("rationale", ""),
            "ok": result["ok"],
            "blocked": result["blocked"],
            "block_reason": result["block_reason"],
            "observation": result["observation"],
            "state_delta": result["state_delta"],
            "verifier_notes": result["verifier_flags"],
            "reward_delta": 0,
            "hard_fail": result["hard_fail"],
            "latency_ms": int(action.get("latency_ms", 0) or 0),
        }
        self.trace["steps"].append(step_record)
        if tool == "submit_incident_report":
            self.trace["final_report"] = args

        if result["hard_fail"] or tool == "submit_incident_report" or index >= self.task["max_steps"]:
            self._close_episode()

        return {
            "step": index,
            "ok": result["ok"],
            "done": self.done,
            "hard_fail": result["hard_fail"],
            "reward_delta": 0,
            "observation": result["observation"],
            "state_delta": result["state_delta"],
            "verifier_notes": result["verifier_flags"],
        }

    def run_episode(self, agent: Any, task_id: str, mode: str = "live") -> dict[str, Any]:
        reset_payload = self.reset(task_id, agent.agent_id, mode=mode)
        agent.reset(reset_payload)
        observation = reset_payload["initial_observation"]
        while not self.done:
            action = agent.next_action(observation, deepcopy(self.trace["steps"]))
            response = self.step(action)
            observation = response["observation"]
        return deepcopy(self.trace)

    def _close_episode(self) -> None:
        if self.trace is None or self.task is None or self.state is None:
            raise RuntimeError("Cannot close an uninitialized episode.")
        self.done = True
        self.trace["ended_at"] = utc_now()
        self.trace["final_state"] = deepcopy(self.state)
        self.trace["verifier_result"] = verify_episode(self.task, self.trace)
