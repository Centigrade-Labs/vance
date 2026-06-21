"""Deterministic step-based Vance MVP environment."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from .models import EpisodeTrace, FinalOutcome, Scenario, ToolAction, TraceStep, VerifierResult
from .scenarios import public_initial_observation
from .tools import REGISTERED_TOOLS, ToolRegistry
from .verifier import verify_trace


MAX_STEPS = 8
SCHEMA_VERSION = "vance.trace.v1"


class VanceEnvironment:
    def __init__(self, scenarios: dict[str, Scenario]) -> None:
        self.scenarios = scenarios
        self.scenario: Scenario | None = None
        self.agent_id = ""
        self.steps: list[TraceStep] = []
        self.attempted_invalid_actions: list[str] = []
        self.state: dict[str, object] = {}
        self.registry: ToolRegistry | None = None

    def reset(self, scenario_id: str, agent_id: str, mode: str = "fallback") -> dict[str, object]:
        if scenario_id not in self.scenarios:
            raise ValueError(f"Unknown scenario: {scenario_id}")
        self.scenario = self.scenarios[scenario_id]
        self.agent_id = agent_id
        self.steps = []
        self.attempted_invalid_actions = []
        self.state = {
            "inspected": False,
            "manual_read": False,
            "inventory_checked": False,
            "maintenance_scheduled": False,
            "escalated": False,
            "continued_monitoring": False,
            "part_available": None,
            "terminated": False,
            "hard_fail": False,
            "hard_fail_reason": "",
            "final_outcome": FinalOutcome.UNRESOLVED.value,
            "machine_status": self.scenario.machine.status,
            "order_status": self.scenario.production_order.status,
            "final_report": None,
            "mode": mode,
        }
        self.registry = ToolRegistry(self.scenario)
        return public_initial_observation(self.scenario)

    def step(self, action: ToolAction) -> dict[str, object]:
        self._require_reset()
        assert self.registry is not None
        assert self.scenario is not None

        if action.name not in REGISTERED_TOOLS:
            self.attempted_invalid_actions.append(action.name)

        result = self.registry.call(action.name, action.arguments, self.state)
        self.steps.append(
            TraceStep(
                index=len(self.steps) + 1,
                action=action,
                result=result,
                operational_rationale=self.scenario.operational_rationale,
            )
        )
        if len(self.steps) >= MAX_STEPS and not self.state["terminated"]:
            self.state["terminated"] = True
        return result.observation

    def run_episode(self, agent: object, scenario_id: str, mode: str = "fallback") -> EpisodeTrace:
        initial_observation = self.reset(scenario_id, getattr(agent, "agent_id", "unknown_agent"), mode=mode)
        if hasattr(agent, "next_action"):
            while not self.state.get("terminated") and len(self.steps) < MAX_STEPS:
                action = agent.next_action(
                    initial_observation=initial_observation,
                    scenario=self.scenarios[scenario_id],
                    steps=list(self.steps),
                )
                if action is None:
                    break
                self.step(action)
        else:
            for action in agent.plan(initial_observation, self.scenarios[scenario_id]):
                if self.state.get("terminated"):
                    break
                self.step(action)
                if len(self.steps) >= MAX_STEPS:
                    break

        trace = self._build_trace(initial_observation)
        verifier_result = verify_trace(trace, self.scenario_or_raise())
        return replace(trace, verifier_result=verifier_result)

    def _build_trace(self, initial_observation: dict[str, object]) -> EpisodeTrace:
        scenario = self.scenario_or_raise()
        placeholder_result = VerifierResult(False, 0.0, False, str(self.state.get("hard_fail_reason", "")), {}, [])
        return EpisodeTrace(
            schema_version=SCHEMA_VERSION,
            episode_id=str(uuid4()),
            task_id=scenario.scenario_id,
            scenario_id=scenario.scenario_id,
            agent_id=self.agent_id,
            mode=str(self.state.get("mode", "fallback")),
            seed=scenario.seed,
            source_csv_row_identifier=scenario.source_csv_row_identifier,
            public_initial_observation=initial_observation,
            steps=list(self.steps),
            attempted_invalid_actions=list(self.attempted_invalid_actions),
            final_state={
                "final_outcome": self.state.get("final_outcome"),
                "machine_status": self.state.get("machine_status"),
                "order_status": self.state.get("order_status"),
                "terminated": self.state.get("terminated"),
            },
            final_report=self.state.get("final_report"),
            verifier_result=placeholder_result,
        )

    def scenario_or_raise(self) -> Scenario:
        self._require_reset()
        assert self.scenario is not None
        return self.scenario

    def _require_reset(self) -> None:
        if self.scenario is None:
            raise RuntimeError("Environment must be reset before stepping")
