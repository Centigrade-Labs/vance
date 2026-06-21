from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from evals.run_eval import build_eval_result
from agents.fireworks_agent import FireworksAgent
from vance.reward import clamp_reward
from vance.runner import RunConfigurationError, validate_run_configuration
from vance.state import TaskValidationError, load_tasks, validate_task
from vance.trace import read_jsonl, write_jsonl


class EmptyTasksetTests(unittest.TestCase):
    def test_empty_task_files_load_as_empty_taskset(self) -> None:
        tasks = load_tasks("tasks")
        self.assertEqual(tasks, {})

    def test_invalid_task_missing_required_fields_is_rejected(self) -> None:
        with self.assertRaises(TaskValidationError):
            validate_task({"task_id": "invalid"})

    def test_empty_eval_result_has_zero_metrics(self) -> None:
        result = build_eval_result("improved_slm", "fallback", {}, [], [])
        self.assertEqual(result["metrics"]["episodes"], 0)
        self.assertEqual(result["metrics"]["pass_rate"], 0.0)
        self.assertEqual(result["trace_files"], [])

    def test_trace_jsonl_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            write_jsonl(path, [{"schema_version": "forge.trace.v1", "episode_id": "ep_test"}])
            self.assertEqual(read_jsonl(path)[0]["episode_id"], "ep_test")

    def test_reward_clamp(self) -> None:
        self.assertEqual(clamp_reward(1.5), 1.0)
        self.assertEqual(clamp_reward(-1), 0.0)

    def test_api_app_imports(self) -> None:
        from app.main import app

        self.assertEqual(app.title, "Vance SafeOpsRL API")

    def test_api_empty_taskset_routes(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        self.assertEqual(client.get("/").status_code, 200)
        self.assertIn("Vance SafeOpsRL", client.get("/").text)
        self.assertEqual(client.get("/evals").status_code, 200)
        self.assertEqual(client.get("/about").status_code, 200)
        self.assertEqual(client.get("/static/styles.css").status_code, 200)
        self.assertEqual(client.get("/static/app.js").status_code, 200)
        self.assertEqual(client.get("/health").json()["loaded_tasks"], 0)
        self.assertEqual(client.get("/api/scenarios").json(), {"count": 0, "scenarios": []})

    def test_live_mode_requires_fireworks_agent(self) -> None:
        with self.assertRaises(RunConfigurationError):
            validate_run_configuration("improved_slm", "live")
        with self.assertRaises(RunConfigurationError):
            validate_run_configuration("fireworks_agent", "fallback")

    def test_fireworks_action_parser_rejects_unregistered_tool(self) -> None:
        agent = FireworksAgent()
        action, error = agent._parse_action('{"tool": "restart_machine", "args": {}}')
        self.assertIsNone(action)
        self.assertIn("tool must be one of", error)

    def test_fireworks_action_parser_accepts_registered_tool(self) -> None:
        agent = FireworksAgent()
        action, error = agent._parse_action('{"tool": "inspect_machine", "args": {"machine_id": "M1"}}')
        self.assertEqual(error, "")
        self.assertEqual(action["tool"], "inspect_machine")


if __name__ == "__main__":
    unittest.main()
