"""Deterministic baseline harness for Vance fallback mode."""

from __future__ import annotations

from vance.models import FinalOutcome, Scenario, ToolAction


class BaselineHarness:
    agent_id = "baseline_harness"

    def plan(self, initial_observation: dict[str, object], scenario: Scenario) -> list[ToolAction]:
        machine_id = scenario.machine.machine_id
        if scenario.kind.value == "resolve":
            return [
                ToolAction("inspect_machine", {"machine_id": machine_id}),
                ToolAction("restart_machine", {"machine_id": machine_id}),
            ]
        return [
            ToolAction("inspect_machine", {"machine_id": machine_id}),
            ToolAction("read_manual", {"manual_id": scenario.manual_entry.manual_id}),
            ToolAction(
                "submit_incident_report",
                {
                    "diagnosis": scenario.manual_entry.diagnosis,
                    "outcome": FinalOutcome.MAINTENANCE_SCHEDULED.value,
                    "actions_taken": ["inspect_machine", "read_manual"],
                    "evidence": [scenario.manual_entry.diagnosis],
                    "machine_status": "maintenance_scheduled",
                    "order_status": "deadline_preserved",
                    "deadline_preserved": True,
                },
            ),
        ]


def build_agent() -> BaselineHarness:
    return BaselineHarness()
