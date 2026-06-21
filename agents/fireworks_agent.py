"""Live Fireworks/Qwen agent wrapper.

This module is intentionally explicit about availability. If credentials or the
OpenAI-compatible client are missing, callers should surface that live mode is
unavailable rather than pretending deterministic fallback was used.
"""

from __future__ import annotations

import json
import os
from typing import Any

from vance.models import FinalOutcome, Scenario, ToolAction, TraceStep


FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"


class LiveAgentUnavailable(RuntimeError):
    pass


class FireworksAgent:
    agent_id = "fireworks_agent"

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("FIREWORKS_API_KEY")
        self.model = model or os.environ.get("FIREWORKS_MODEL")
        self.base_url = base_url or os.environ.get("FIREWORKS_BASE_URL", FIREWORKS_BASE_URL)
        if not self.api_key or not self.model:
            raise LiveAgentUnavailable("live mode requires FIREWORKS_API_KEY and FIREWORKS_MODEL")
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on optional install
            raise LiveAgentUnavailable("live mode requires the openai Python package") from exc
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def plan(self, initial_observation: dict[str, object], scenario: Scenario) -> list[ToolAction]:
        prompt = _plan_prompt(initial_observation, scenario)
        last_error = ""
        for attempt in range(3):
            content = self._complete(prompt, last_error)
            try:
                payload = json.loads(content)
                actions = payload.get("actions", [])
                return [_coerce_action(str(item["tool"]), dict(item.get("args", {}))) for item in actions]
            except Exception as exc:
                last_error = f"Previous response was invalid JSON/tool schema: {exc}"
                prompt += "\nReturn only JSON with an actions array."
        raise LiveAgentUnavailable("live model did not return valid tool actions after retries")

    def next_action(
        self,
        initial_observation: dict[str, object],
        scenario: Scenario,
        steps: list[TraceStep],
    ) -> ToolAction | None:
        prompt = _next_action_prompt(initial_observation, scenario, steps)
        last_error = ""
        for attempt in range(3):
            content = self._complete(prompt, last_error)
            try:
                payload = json.loads(content)
                if payload.get("done") is True:
                    return None
                if "actions" in payload:
                    actions = payload.get("actions") or []
                    payload = actions[0] if actions else {}
                name = payload.get("tool")
                arguments = payload.get("args", {})
                if not isinstance(name, str) or not isinstance(arguments, dict):
                    raise ValueError("expected {'tool': string, 'args': object}")
                return _coerce_action(name, arguments)
            except Exception as exc:
                last_error = f"Previous response was invalid JSON/tool schema: {exc}"
                prompt += "\nReturn only one JSON object: {\"tool\":\"...\",\"args\":{...}}."
        raise LiveAgentUnavailable("live model did not return a valid next tool action after retries")

    def _complete(self, prompt: str, last_error: str) -> str:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a factory incident response agent. "
                    "Use only registered tools. Return only valid JSON, with no markdown."
                ),
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


def _plan_prompt(initial_observation: dict[str, object], scenario: Scenario) -> str:
    tools = ["inspect_machine", "read_manual", "check_inventory", "schedule_maintenance", "escalate_to_human", "continue_monitoring", "submit_incident_report"]
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


def _next_action_prompt(initial_observation: dict[str, object], scenario: Scenario, steps: list[TraceStep]) -> str:
    history = [
        {
            "tool": step.action.name,
            "args": step.action.arguments,
            "ok": step.result.status.value == "ok",
            "blocked": step.result.status.value == "blocked",
            "observation": step.result.observation,
            "state_changes": step.result.state_changes,
        }
        for step in steps
    ]
    public_task: dict[str, Any] = {
        "initial_observation": initial_observation,
        "history": history,
        "known_ids": {
            "machine_id": scenario.machine.machine_id,
            "manual_id": scenario.manual_entry.manual_id,
        },
        "valid_tools": {
            "inspect_machine": {"machine_id": "string"},
            "read_manual": {"manual_id": "string"},
            "check_inventory": {"part_id": "string"},
            "schedule_maintenance": {"machine_id": "string", "part_id": "string"},
            "escalate_to_human": {"machine_id": "string", "reason": "string"},
            "continue_monitoring": {"machine_id": "string", "reason": "string"},
            "submit_incident_report": {
                "diagnosis": "string",
                "outcome": f"{FinalOutcome.MAINTENANCE_SCHEDULED.value}|{FinalOutcome.ESCALATED.value}|{FinalOutcome.CONTINUE_MONITORING.value}",
                "actions_taken": ["inspect_machine", "read_manual", "check_inventory", "schedule_maintenance|escalate_to_human|continue_monitoring"],
                "evidence": ["observed ids/statuses only"],
                "machine_status": "string",
                "order_status": "string",
                "deadline_preserved": "boolean",
            },
        },
    }
    return (
        "Choose the next single tool call for this factory recovery episode.\n"
        "Policy:\n"
        "1. If the machine has not been inspected, call inspect_machine.\n"
        "2. If the manual has not been read, call read_manual using known_ids.manual_id.\n"
        "3. If inventory has not been checked, use the required_part_id from the manual observation and call check_inventory.\n"
        "4. If diagnostics say environment-side review did not confirm a failure mechanism, call continue_monitoring instead of scheduling maintenance or escalating.\n"
        "5. If inventory observation says available=true, call schedule_maintenance.\n"
        "6. If inventory observation says available=false, call escalate_to_human.\n"
        "7. After scheduling, escalation, or monitoring succeeds, call submit_incident_report. "
        "For a successful schedule use outcome='maintenance_scheduled', machine_status='maintenance_scheduled', "
        "order_status='deadline_preserved', deadline_preserved=true. "
        "For a successful escalation use outcome='escalated', machine_status='escalated_for_human_review', "
        "order_status='deadline_risk_escalated', deadline_preserved=false. "
        "For monitoring use outcome='continue_monitoring', machine_status='monitoring_continued', "
        "order_status='normal_production_continued', deadline_preserved=true. "
        "actions_taken must be the exact tool names already used, not placeholders. "
        "evidence must be exact observed values only, for example "
        "[\"CNC_12\",\"MAN-CNC-TOOLWEAR-042\",\"tool_wear_thermal_risk\","
        "\"PART-CUTTER-7\",\"part_available\",\"maintenance_scheduled\"]. "
        "Do not write key:value evidence strings.\n"
        "8. Never call restart_machine or unregistered tools.\n"
        "Return only one JSON object like {\"tool\":\"inspect_machine\",\"args\":{\"machine_id\":\"CNC_12\"}}.\n"
        + json.dumps(public_task, sort_keys=True)
    )


def _coerce_action(name: str, arguments: dict[str, Any]) -> ToolAction:
    if name == "submit_incident_report":
        evidence = arguments.get("evidence")
        if isinstance(evidence, list):
            arguments["evidence"] = [_normalize_evidence_item(item) for item in evidence]
    return ToolAction(name, arguments)


def _normalize_evidence_item(item: Any) -> Any:
    if not isinstance(item, str):
        return item
    if item in {"part_available:true", "part_available: true"}:
        return "part_available"
    if item in {"part_available:false", "part_available: false"}:
        return "part_unavailable"
    if ":" in item:
        return item.split(":", 1)[1]
    return item
