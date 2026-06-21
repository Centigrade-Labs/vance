from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from evals.run_eval import build_eval_result
from vance.reward import clamp_reward
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

    def test_dashboard_app_imports(self) -> None:
        from app.main import app

        self.assertEqual(app.title, "Forge Judge Mode")


if __name__ == "__main__":
    unittest.main()
