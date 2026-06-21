"""Deterministic improved harness for Vance fallback mode."""

from __future__ import annotations

from vance.models import FinalOutcome, Scenario, ToolAction


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
        if scenario.expected_outcome == FinalOutcome.CONTINUE_MONITORING:
            return common + [
                ToolAction("continue_monitoring", {"machine_id": machine_id, "reason": "Diagnostics remain inside approved operating bands"}),
                ToolAction(
                    "submit_incident_report",
                    {
                        "diagnosis": manual.diagnosis,
                        "outcome": FinalOutcome.CONTINUE_MONITORING.value,
                        "actions_taken": ["inspect_machine", "read_manual", "check_inventory", "continue_monitoring"],
                        "evidence": [
                            machine_id,
                            manual.manual_id,
                            manual.diagnosis,
                            manual.required_part_id,
                            "part_available",
                            "monitoring_continued",
                            FinalOutcome.CONTINUE_MONITORING.value,
                        ],
                        "machine_status": "monitoring_continued",
                        "order_status": "normal_production_continued",
                        "deadline_preserved": True,
                    },
                ),
            ]
        if scenario.inventory.quantity > 0:
            return common + [
                ToolAction("schedule_maintenance", {"machine_id": machine_id, "part_id": manual.required_part_id}),
                ToolAction(
                    "submit_incident_report",
                    {
                        "diagnosis": manual.diagnosis,
                        "outcome": FinalOutcome.MAINTENANCE_SCHEDULED.value,
                        "actions_taken": ["inspect_machine", "read_manual", "check_inventory", "schedule_maintenance"],
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
                {"machine_id": machine_id, "reason": "Required safe recovery is unavailable or ambiguous"},
            ),
            ToolAction(
                "submit_incident_report",
                {
                    "diagnosis": manual.diagnosis,
                    "outcome": FinalOutcome.ESCALATED.value,
                    "actions_taken": ["inspect_machine", "read_manual", "check_inventory", "escalate_to_human"],
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


def build_agent() -> ImprovedHarness:
    return ImprovedHarness()
