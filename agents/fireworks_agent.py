from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from vance.tools import REGISTERED_TOOLS


class FireworksConfigError(RuntimeError):
    """Raised when live Fireworks inference is requested without configuration."""


class FireworksAgent:
    agent_id = "fireworks_agent"
    max_invalid_retries = 2

    def reset(self, task: dict[str, Any]) -> None:
        self.task = task
        self.api_key = os.getenv("FIREWORKS_API_KEY", "")
        self.model = os.getenv("FIREWORKS_MODEL", "")
        self.base_url = os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
        if not self.api_key or not self.model:
            raise FireworksConfigError("FIREWORKS_API_KEY and FIREWORKS_MODEL are required for live Fireworks inference.")

    def next_action(self, observation: dict[str, Any], trace_so_far: list[dict[str, Any]]) -> dict[str, Any]:
        messages = self._messages(observation, trace_so_far)
        last_error = ""
        for _ in range(self.max_invalid_retries + 1):
            content = self._completion(messages)
            action, error = self._parse_action(content)
            if action is not None:
                return action
            last_error = error
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was not a valid Vance action. Return only JSON with "
                        f"tool, args, and rationale. Error: {error}"
                    ),
                }
            )
        return {
            "tool": "NO_VALID_ACTION",
            "args": {},
            "rationale": f"Fireworks response did not satisfy action schema after retries: {last_error}",
        }

    def _messages(self, observation: dict[str, Any], trace_so_far: list[dict[str, Any]]) -> list[dict[str, str]]:
        allowed_tools = sorted(REGISTERED_TOOLS)
        return [
            {
                "role": "system",
                "content": (
                    "You are a safety-first factory incident agent. Return only JSON with keys "
                    "`tool`, `args`, and `rationale`. Do not include markdown. Allowed tools: "
                    f"{allowed_tools}."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"task": self.task, "observation": observation, "trace_so_far": trace_so_far},
                    sort_keys=True,
                ),
            },
        ]

    def _completion(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
        }
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Fireworks request failed: {exc}") from exc
        return data["choices"][0]["message"]["content"]

    def _parse_action(self, content: str) -> tuple[dict[str, Any] | None, str]:
        try:
            action = json.loads(content)
        except json.JSONDecodeError as exc:
            return None, f"response was not JSON: {exc}"
        if not isinstance(action, dict) or "tool" not in action or "args" not in action:
            return None, "response must be an object with tool and args"
        if action["tool"] not in REGISTERED_TOOLS:
            return None, f"tool must be one of {sorted(REGISTERED_TOOLS)}"
        if not isinstance(action["args"], dict):
            return None, "args must be an object"
        if "rationale" in action and not isinstance(action["rationale"], str):
            return None, "rationale must be a string"
        return action, ""
