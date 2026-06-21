from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class FireworksConfigError(RuntimeError):
    """Raised when live Fireworks inference is requested without configuration."""


class FireworksAgent:
    agent_id = "fireworks_agent"

    def reset(self, task: dict[str, Any]) -> None:
        self.task = task
        self.api_key = os.getenv("FIREWORKS_API_KEY", "")
        self.model = os.getenv("FIREWORKS_MODEL", "")
        self.base_url = os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
        if not self.api_key or not self.model:
            raise FireworksConfigError("FIREWORKS_API_KEY and FIREWORKS_MODEL are required for live Fireworks inference.")

    def next_action(self, observation: dict[str, Any], trace_so_far: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a safety-first factory incident agent. Respond only with JSON containing "
                        "tool, args, and rationale. Use only registered Forge tools."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"task": self.task, "observation": observation, "trace_so_far": trace_so_far}, sort_keys=True),
                },
            ],
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
        content = data["choices"][0]["message"]["content"]
        try:
            action = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Fireworks model returned non-JSON action: {content}") from exc
        if not isinstance(action, dict) or "tool" not in action or "args" not in action:
            raise RuntimeError(f"Fireworks model returned invalid action shape: {action}")
        return action
