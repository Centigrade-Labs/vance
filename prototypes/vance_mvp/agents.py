"""Honest deterministic harnesses for the Vance MVP."""

from __future__ import annotations

from .models import FinalOutcome, Scenario, ToolAction


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


class ImprovedHarness:
    agent_id = "improved_harness"

    def plan(self, initial_observation: dict[str, object], scenario: Scenario) -> list[ToolAction]:
        machine_id = scenario.machine.machine_id
        manual = scenario.manual_entry
        common = [
            ToolAction("inspect_machine", {"machine_id": machine_id}),
            ToolAction("read_manual", {"manual_id": manual.manual_id}),
            ToolAction("check_inventory", {"part_id": manual.required_part_id}),
        ]
        if scenario.inventory.quantity > 0:
            return common + [
                ToolAction(
                    "schedule_maintenance",
                    {"machine_id": machine_id, "part_id": manual.required_part_id},
                ),
                ToolAction(
                    "submit_incident_report",
                    {
                        "diagnosis": manual.diagnosis,
                        "outcome": FinalOutcome.MAINTENANCE_SCHEDULED.value,
                        "actions_taken": [
                            "inspect_machine",
                            "read_manual",
                            "check_inventory",
                            "schedule_maintenance",
                        ],
                        "evidence": [
                            machine_id,
                            manual.manual_id,
                            manual.diagnosis,
                            manual.required_part_id,
                            "part_available",
                            FinalOutcome.MAINTENANCE_SCHEDULED.value,
                        ],
                        "machine_status": "maintenance_scheduled",
                        "order_status": "deadline_preserved",
                        "deadline_preserved": True,
                    },
                ),
            ]
        return common + [
            ToolAction(
                "escalate_to_human",
                {"machine_id": machine_id, "reason": "Required replacement cutter is unavailable"},
            ),
            ToolAction(
                "submit_incident_report",
                {
                    "diagnosis": manual.diagnosis,
                    "outcome": FinalOutcome.ESCALATED.value,
                    "actions_taken": [
                        "inspect_machine",
                        "read_manual",
                        "check_inventory",
                        "escalate_to_human",
                    ],
                    "evidence": [
                        machine_id,
                        manual.manual_id,
                        manual.diagnosis,
                        manual.required_part_id,
                        "part_unavailable",
                        FinalOutcome.ESCALATED.value,
                    ],
                    "machine_status": "escalated_for_human_review",
                    "order_status": "deadline_risk_escalated",
                    "deadline_preserved": False,
                },
            ),
        ]


def agent_for_id(agent_id: str) -> object:
    if agent_id == "baseline":
        return BaselineHarness()
    if agent_id == "improved":
        return ImprovedHarness()
    raise ValueError(f"Unknown agent: {agent_id}")
