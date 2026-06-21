from __future__ import annotations

from typing import Any


class ImprovedAgent:
    """Safety-first deterministic harness matching the PRD tool checklist."""

    agent_id = "improved_slm"

    def reset(self, task: dict[str, Any]) -> None:
        self.task = task
        self.machine_id = task["public_task"]["machines"][0]
        self.order_id = task["public_task"]["orders"][0] if task["public_task"]["orders"] else None

    def next_action(self, observation: dict[str, Any], trace_so_far: list[dict[str, Any]]) -> dict[str, Any]:
        if not trace_so_far:
            return {
                "tool": "inspect_machine",
                "args": {"machine_id": self.machine_id},
                "rationale": "Confirm machine state before recovery action.",
            }

        if not _used(trace_so_far, "read_manual"):
            error_code = _last_inspection(trace_so_far).get("error_code")
            return {
                "tool": "read_manual",
                "args": {"error_code": error_code},
                "rationale": "Read approved manual guidance before any action.",
            }

        manual = _last_manual(trace_so_far)
        part_id = manual.get("required_part_id")
        if part_id and not _used(trace_so_far, "check_inventory"):
            return {
                "tool": "check_inventory",
                "args": {"part_id": part_id},
                "rationale": "Verify required part availability before maintenance.",
            }

        inventory = _last_inventory(trace_so_far, part_id) if part_id else {"available": True}
        if _should_escalate(manual, inventory):
            if not _used(trace_so_far, "escalate_to_human"):
                return {
                    "tool": "escalate_to_human",
                    "args": {
                        "machine_id": self.machine_id,
                        "reason": _escalation_reason(manual, inventory),
                        "severity": "high",
                        "blocking_order_id": self.order_id,
                    },
                    "rationale": "Escalate because safe recovery cannot be completed with available resources.",
                }
            return self._report(trace_so_far, manual, escalated=True)

        if not _used(trace_so_far, "schedule_maintenance"):
            return {
                "tool": "schedule_maintenance",
                "args": {
                    "machine_id": self.machine_id,
                    "action": manual["safe_actions"][0],
                    "part_id": part_id,
                    "order_plan": {"order_id": self.order_id, "strategy": "preserve"},
                },
                "rationale": "Schedule the approved safe maintenance action.",
            }

        return self._report(trace_so_far, manual, escalated=False)

    def _report(self, trace_so_far: list[dict[str, Any]], manual: dict[str, Any], escalated: bool) -> dict[str, Any]:
        part_id = manual.get("required_part_id")
        actions = [step["tool"] for step in trace_so_far if step.get("ok")]
        if escalated:
            final_state = "correctly_escalated"
            order_impact = f"{self.order_id} escalated"
        else:
            final_state = "safe_recovered"
            order_impact = f"{self.order_id} preserved"
        evidence = [manual.get("error_code"), manual.get("manual_id"), manual.get("diagnosis_hint")]
        if part_id:
            inventory = _last_inventory(trace_so_far, part_id)
            evidence.append(part_id)
            evidence.append(str(inventory.get("available")))
        return {
            "tool": "submit_incident_report",
            "args": {
                "diagnosis": manual.get("diagnosis_hint"),
                "affected_machine_id": self.machine_id,
                "actions_taken": actions,
                "parts_used": [] if escalated or not part_id else [part_id],
                "escalation_required": escalated,
                "final_state": final_state,
                "order_impact": order_impact,
                "evidence": [item for item in evidence if item],
            },
            "rationale": "Submit a report grounded in the completed trace.",
        }


def _used(trace: list[dict[str, Any]], tool: str) -> bool:
    return any(step.get("tool") == tool and step.get("ok") for step in trace)


def _last_inspection(trace: list[dict[str, Any]]) -> dict[str, Any]:
    for step in reversed(trace):
        if step.get("tool") == "inspect_machine":
            return step.get("observation", {})
    return {}


def _last_manual(trace: list[dict[str, Any]]) -> dict[str, Any]:
    for step in reversed(trace):
        if step.get("tool") == "read_manual":
            return step.get("observation", {}).get("manual_entry") or {}
    return {}


def _last_inventory(trace: list[dict[str, Any]], part_id: str | None) -> dict[str, Any]:
    for step in reversed(trace):
        if step.get("tool") == "check_inventory" and step.get("observation", {}).get("part_id") == part_id:
            return step.get("observation", {})
    return {"available": False, "quantity": 0}


def _should_escalate(manual: dict[str, Any], inventory: dict[str, Any]) -> bool:
    if not manual.get("safe_actions"):
        return True
    if manual.get("required_part_id") and not inventory.get("available"):
        return True
    return False


def _escalation_reason(manual: dict[str, Any], inventory: dict[str, Any]) -> str:
    if not manual.get("safe_actions"):
        return "Manual requires human inspection and no safe tool action is available."
    if manual.get("required_part_id") and not inventory.get("available"):
        return f"Required part {manual['required_part_id']} is unavailable."
    return "Safe recovery cannot be completed with available tools."
