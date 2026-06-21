"""Live Fireworks/Qwen agent wrapper.

This module is intentionally explicit about availability. If credentials or the
OpenAI-compatible client are missing, callers should surface that live mode is
unavailable rather than pretending deterministic fallback was used.
"""

from __future__ import annotations

import json
import os
from typing import Any

from vance.models import Scenario, ToolAction


FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"


class LiveAgentUnavailable(RuntimeError):
    pass


class FireworksAgent:
    agent_id = "fireworks_agent"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("FIREWORKS_API_KEY")
        self.model = model or os.environ.get("FIREWORKS_MODEL")
        if not self.api_key or not self.model:
            raise LiveAgentUnavailable("live mode requires FIREWORKS_API_KEY and FIREWORKS_MODEL")
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on optional install
            raise LiveAgentUnavailable("live mode requires the openai Python package") from exc
        self.client = OpenAI(api_key=self.api_key, base_url=FIREWORKS_BASE_URL)

    def plan(self, initial_observation: dict[str, object], scenario: Scenario) -> list[ToolAction]:
        prompt = _prompt(initial_observation, scenario)
        last_error = ""
        for attempt in range(3):
            content = self._complete(prompt, last_error)
            try:
                payload = json.loads(content)
                actions = payload.get("actions", [])
                return [ToolAction(str(item["tool"]), dict(item.get("args", {}))) for item in actions]
            except Exception as exc:
                last_error = f"Previous response was invalid JSON/tool schema: {exc}"
                prompt += "\nReturn only JSON with an actions array."
        raise LiveAgentUnavailable("live model did not return valid tool actions after retries")

    def _complete(self, prompt: str, last_error: str) -> str:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": "You are a factory incident response agent. Return only JSON tool actions.",
            },
            {"role": "user", "content": prompt + ("\n" + last_error if last_error else "")},
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0,
        )
        return response.choices[0].message.content or "{}"


def build_agent() -> FireworksAgent:
    return FireworksAgent()


def _prompt(initial_observation: dict[str, object], scenario: Scenario) -> str:
    tools = ["inspect_machine", "read_manual", "check_inventory", "schedule_maintenance", "escalate_to_human", "submit_incident_report"]
    public_task: dict[str, Any] = {
        "observation": initial_observation,
        "available_tools": tools,
        "machine_id": scenario.machine.machine_id,
        "manual_id": scenario.manual_entry.manual_id,
        "required_part_id": scenario.manual_entry.required_part_id,
    }
    return (
        "Use tools to resolve or escalate safely. Do not call unregistered tools. "
        "Return JSON like {\"actions\":[{\"tool\":\"inspect_machine\",\"args\":{\"machine_id\":\"...\"}}]}.\n"
        + json.dumps(public_task, sort_keys=True)
    )
