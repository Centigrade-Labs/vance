"""Dataclass models for the isolated Vance MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ScenarioKind(str, Enum):
    RESOLVE = "resolve"
    ESCALATION = "escalation"
    MONITORING = "monitoring"


class ToolStatus(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"
    ERROR = "error"


class FinalOutcome(str, Enum):
    UNRESOLVED = "unresolved"
    MAINTENANCE_SCHEDULED = "maintenance_scheduled"
    ESCALATED = "escalated"
    CONTINUE_MONITORING = "continue_monitoring"
    HARD_FAILED = "hard_failed"


@dataclass(frozen=True)
class MachineState:
    machine_id: str
    product_type: str
    air_temperature_k: float
    process_temperature_k: float
    rotational_speed_rpm: int
    torque_nm: float
    tool_wear_min: int
    status: str = "needs_diagnosis"


@dataclass(frozen=True)
class InventoryItem:
    part_id: str
    name: str
    quantity: int


@dataclass(frozen=True)
class ProductionOrder:
    order_id: str
    product_type: str
    deadline: str
    status: str


@dataclass(frozen=True)
class ManualEntry:
    manual_id: str
    issue_code: str
    diagnosis: str
    symptom: str
    required_part_id: str
    required_part_name: str
    safety_rule: str
    safe_action: str = "schedule approved maintenance"


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    difficulty: str
    seed: int
    kind: ScenarioKind
    source_csv_row_identifier: str
    machine: MachineState
    manual_entry: ManualEntry
    inventory: InventoryItem
    production_order: ProductionOrder
    expected_outcome: FinalOutcome
    hidden_failure_labels: dict[str, int]
    operational_rationale: str
    demo_tags: list[str] = field(default_factory=list)
    diagnostic_observations: list[str] = field(default_factory=list)
    derived_features: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolAction:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    observation: dict[str, Any]
    state_changes: dict[str, Any] = field(default_factory=dict)
    verifier_note: str = ""


@dataclass(frozen=True)
class TraceStep:
    index: int
    action: ToolAction
    result: ToolResult
    operational_rationale: str = ""


@dataclass(frozen=True)
class IncidentReport:
    diagnosis: str
    outcome: str
    actions_taken: list[str]
    evidence: list[str]
    machine_status: str
    order_status: str
    deadline_preserved: bool


@dataclass(frozen=True)
class VerifierResult:
    passed: bool
    reward: float
    hard_fail: bool
    hard_fail_reason: str
    reward_breakdown: dict[str, float]
    notes: list[str]
    success_reasons: list[str] = field(default_factory=list)
    fail_reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeTrace:
    schema_version: str
    episode_id: str
    task_id: str
    scenario_id: str
    agent_id: str
    mode: str
    seed: int
    source_csv_row_identifier: str
    public_initial_observation: dict[str, Any]
    steps: list[TraceStep]
    attempted_invalid_actions: list[str]
    final_state: dict[str, Any]
    final_report: IncidentReport | None
    verifier_result: VerifierResult
