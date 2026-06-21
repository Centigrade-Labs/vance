from __future__ import annotations

from typing import Any


class BaselineAgent:
    """Intentionally weak deterministic baseline harness."""

    agent_id = "baseline_slm"

    def reset(self, task: dict[str, Any]) -> None:
        self.task = task
        self.machine_id = task["public_task"]["machines"][0]
        self.order_id = task["public_task"]["orders"][0] if task["public_task"]["orders"] else None
        self.error_code: str | None = None

    def next_action(self, observation: dict[str, Any], trace_so_far: list[dict[str, Any]]) -> dict[str, Any]:
        if not trace_so_far:
            return {
                "tool": "inspect_machine",
                "args": {"machine_id": self.machine_id},
                "rationale": "Check the affected machine.",
            }
        last = trace_so_far[-1]
        if last.get("tool") == "inspect_machine":
            self.error_code = last.get("observation", {}).get("error_code")
            if self.error_code == "SPINDLE_WARN_42":
                return {
                    "tool": "restart_machine",
                    "args": {"machine_id": self.machine_id},
                    "rationale": "Try a quick restart.",
                }
            return {
                "tool": "read_manual",
                "args": {"error_code": self.error_code},
                "rationale": "Look up the current error code.",
            }
        if last.get("tool") == "read_manual":
            manual = last.get("observation", {}).get("manual_entry") or {}
            return self._report(manual, ["inspect_machine", "read_manual"])
        return self._report({}, [step.get("tool") for step in trace_so_far if step.get("ok")])

    def _report(self, manual: dict[str, Any], actions: list[str]) -> dict[str, Any]:
        return {
            "tool": "submit_incident_report",
            "args": {
                "diagnosis": manual.get("diagnosis_hint", "unknown_fault"),
                "affected_machine_id": self.machine_id,
                "actions_taken": actions,
                "parts_used": [],
                "escalation_required": False,
                "final_state": "safe_recovered",
                "order_impact": f"{self.order_id or 'order'} preserved",
                "evidence": [item for item in [self.error_code, manual.get("manual_id")] if item],
            },
            "rationale": "Submit a short report.",
        }
