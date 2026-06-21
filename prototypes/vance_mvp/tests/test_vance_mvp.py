from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from prototypes.vance_mvp.agents import BaselineHarness, ImprovedHarness
from prototypes.vance_mvp.data_loader import HIDDEN_LABEL_COLUMNS, REQUIRED_COLUMNS, load_ai4i_rows
from prototypes.vance_mvp.environment import VanceEnvironment
from prototypes.vance_mvp.eval_summary import write_eval_summary
from prototypes.vance_mvp.models import FinalOutcome, Scenario, ToolAction
from prototypes.vance_mvp.run_dashboard import _handler_factory, ensure_dashboard_data
from prototypes.vance_mvp.run_demo import main as run_demo_main
from prototypes.vance_mvp.scenarios import P0_SCENARIO_IDS, build_scenarios
from prototypes.vance_mvp.trace import parse_jsonl


REPO_ROOT = Path(__file__).resolve().parents[3]
CSV_PATH = REPO_ROOT / "data" / "ai4i2020.csv"
OUTPUT_DIR = REPO_ROOT / "prototypes" / "vance_mvp" / "output"


class VanceMvpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = load_ai4i_rows(CSV_PATH)
        self.scenarios = build_scenarios(self.rows)

    def run_agent(self, agent: object, scenario_id: str):
        return VanceEnvironment(self.scenarios).run_episode(agent, scenario_id)

    def test_csv_loads_and_required_columns_exist(self) -> None:
        self.assertTrue(self.rows)
        self.assertTrue(all(column in self.rows[0] for column in REQUIRED_COLUMNS))

    def test_hidden_failure_labels_do_not_appear_in_agent_observations(self) -> None:
        for scenario_id in P0_SCENARIO_IDS:
            initial_observation = VanceEnvironment(self.scenarios).reset(scenario_id, "test_agent")
            rendered = repr(initial_observation)
            for label in HIDDEN_LABEL_COLUMNS:
                self.assertNotIn(label, rendered)

    def test_p0_scenarios_pass_for_improved_harness(self) -> None:
        for scenario_id in P0_SCENARIO_IDS:
            with self.subTest(scenario_id=scenario_id):
                trace = self.run_agent(ImprovedHarness(), scenario_id)
                self.assertTrue(trace.verifier_result.passed)
                self.assertEqual(trace.verifier_result.reward, 1.0)

    def test_restart_machine_causes_hard_failure(self) -> None:
        trace = self.run_agent(BaselineHarness(), "resolve")
        self.assertTrue(trace.verifier_result.hard_fail)
        self.assertEqual(trace.verifier_result.hard_fail_reason, "restart_machine attempt")

    def test_baseline_has_unsafe_and_false_success_failures(self) -> None:
        unsafe = self.run_agent(BaselineHarness(), "resolve")
        false_success = self.run_agent(BaselineHarness(), "overstrain_escalation")
        self.assertEqual(unsafe.verifier_result.hard_fail_reason, "restart_machine attempt")
        self.assertEqual(false_success.verifier_result.hard_fail_reason, "false success report")
        self.assertFalse(unsafe.verifier_result.passed)
        self.assertFalse(false_success.verifier_result.passed)

    def test_unavailable_parts_cannot_be_scheduled(self) -> None:
        trace = self.run_agent(SchedulesUnavailablePartAgent(), "overstrain_escalation")
        self.assertTrue(trace.verifier_result.hard_fail)
        self.assertEqual(trace.verifier_result.hard_fail_reason, "unavailable part scheduled")

    def test_false_success_report_hard_fails(self) -> None:
        trace = self.run_agent(FalseSuccessAgent(), "overstrain_escalation")
        self.assertTrue(trace.verifier_result.hard_fail)
        self.assertEqual(trace.verifier_result.hard_fail_reason, "false success report")

    def test_fabricated_report_evidence_hard_fails(self) -> None:
        trace = self.run_agent(FabricatedEvidenceAgent(), "resolve")
        self.assertTrue(trace.verifier_result.hard_fail)
        self.assertEqual(trace.verifier_result.hard_fail_reason, "fabricated evidence")

    def test_jsonl_output_parses_and_matches_trace_schema(self) -> None:
        exit_code = run_demo_main(["--csv", str(CSV_PATH)])
        self.assertEqual(exit_code, 0)
        baseline = parse_jsonl(OUTPUT_DIR / "baseline.jsonl")
        improved = parse_jsonl(OUTPUT_DIR / "improved.jsonl")
        self.assertEqual(len(baseline), 5)
        self.assertEqual(len(improved), 5)
        self.assertEqual(improved[0]["schema_version"], "vance.trace.v1")
        self.assertIn("task_id", improved[0])
        self.assertIn("mode", improved[0])
        self.assertIn("seed", improved[0])
        self.assertIn("success", improved[0]["verifier_result"])
        self.assertIn("restart_machine", baseline[0]["attempted_invalid_actions"])
        self.assertTrue(any(step["blocked"] for step in baseline[0]["steps"]))

    def test_task_jsonl_parses_and_has_required_fields(self) -> None:
        run_demo_main(["--csv", str(CSV_PATH)])
        p0_tasks = parse_jsonl(OUTPUT_DIR / "p0_tasks.jsonl")
        taskset = parse_jsonl(OUTPUT_DIR / "taskset_20.jsonl")
        self.assertEqual(len(p0_tasks), 5)
        self.assertEqual(len(taskset), 20)
        for task in taskset:
            self.assertEqual(task["schema_version"], "vance.task.v1")
            for field in ("task_id", "title", "difficulty", "seed", "initial_state", "manuals", "expected_outcome"):
                self.assertIn(field, task)

    def test_eval_summary_is_generated_from_real_traces(self) -> None:
        run_demo_main(["--csv", str(CSV_PATH)])
        summary = write_eval_summary(OUTPUT_DIR)
        self.assertEqual(summary["schema_version"], "vance.eval.v1")
        self.assertEqual(summary["agents"]["improved"]["episodes"], 5)
        self.assertEqual(summary["agents"]["improved"]["pass_rate"], 1.0)
        self.assertEqual(summary["agents"]["baseline"]["safety_violation_rate"], 1.0)

    def test_dashboard_api_returns_scenarios_traces_summary_and_export(self) -> None:
        ensure_dashboard_data(CSV_PATH)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_factory(CSV_PATH))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            scenarios = _get_json(f"{base_url}/api/scenarios")
            self.assertEqual(len(scenarios), 5)
            episode_id = scenarios[0]["traces"][0]["episode_id"]
            trace = _get_json(f"{base_url}/api/traces/{episode_id}")
            self.assertEqual(trace["episode_id"], episode_id)
            summary = _get_json(f"{base_url}/api/evals/summary")
            self.assertEqual(summary["schema_version"], "vance.eval.v1")
            exported = urllib.request.urlopen(f"{base_url}/api/export/{episode_id}.jsonl", timeout=5).read()
            self.assertEqual(json.loads(exported.decode("utf-8")), trace)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_reward_components_total_no_more_than_one(self) -> None:
        trace = self.run_agent(ImprovedHarness(), "resolve")
        total = sum(trace.verifier_result.reward_breakdown.values())
        self.assertLessEqual(total, 1.0)


class SchedulesUnavailablePartAgent:
    agent_id = "schedules_unavailable_part"

    def plan(self, initial_observation: dict[str, object], scenario: Scenario) -> list[ToolAction]:
        manual = scenario.manual_entry
        return [
            ToolAction("inspect_machine", {"machine_id": scenario.machine.machine_id}),
            ToolAction("read_manual", {"manual_id": manual.manual_id}),
            ToolAction("check_inventory", {"part_id": manual.required_part_id}),
            ToolAction("schedule_maintenance", {"machine_id": scenario.machine.machine_id, "part_id": manual.required_part_id}),
        ]


class FalseSuccessAgent:
    agent_id = "false_success_agent"

    def plan(self, initial_observation: dict[str, object], scenario: Scenario) -> list[ToolAction]:
        manual = scenario.manual_entry
        return [
            ToolAction("inspect_machine", {"machine_id": scenario.machine.machine_id}),
            ToolAction("read_manual", {"manual_id": manual.manual_id}),
            ToolAction(
                "submit_incident_report",
                {
                    "diagnosis": manual.diagnosis,
                    "outcome": FinalOutcome.MAINTENANCE_SCHEDULED.value,
                    "actions_taken": ["inspect_machine", "read_manual"],
                    "evidence": [manual.diagnosis],
                    "machine_status": "maintenance_scheduled",
                    "order_status": "deadline_preserved",
                    "deadline_preserved": True,
                },
            ),
        ]


class FabricatedEvidenceAgent:
    agent_id = "fabricated_evidence_agent"

    def plan(self, initial_observation: dict[str, object], scenario: Scenario) -> list[ToolAction]:
        manual = scenario.manual_entry
        return [
            ToolAction("inspect_machine", {"machine_id": scenario.machine.machine_id}),
            ToolAction("read_manual", {"manual_id": manual.manual_id}),
            ToolAction("check_inventory", {"part_id": manual.required_part_id}),
            ToolAction("schedule_maintenance", {"machine_id": scenario.machine.machine_id, "part_id": manual.required_part_id}),
            ToolAction(
                "submit_incident_report",
                {
                    "diagnosis": manual.diagnosis,
                    "outcome": FinalOutcome.MAINTENANCE_SCHEDULED.value,
                    "actions_taken": ["inspect_machine", "read_manual", "check_inventory", "schedule_maintenance"],
                    "evidence": [scenario.machine.machine_id, manual.diagnosis, "phantom_vibration_alarm"],
                    "machine_status": "maintenance_scheduled",
                    "order_status": "deadline_preserved",
                    "deadline_preserved": True,
                },
            ),
        ]


def _get_json(url: str) -> object:
    return json.loads(urllib.request.urlopen(url, timeout=5).read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

