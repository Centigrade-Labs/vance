from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path

from agents import build_agent
from agents.fireworks_agent import LiveAgentUnavailable
from evals.run_eval import main as run_eval_main
from vance.data_loader import HIDDEN_LABEL_COLUMNS, REQUIRED_COLUMNS, load_ai4i_rows
from vance.env import VanceEnvironment
from vance.runner import DATA_PATH, generate_task_files, run_one
from vance.scenarios import P0_SCENARIO_IDS, build_twenty_scenarios
from vance.trace import parse_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]


class VanceMainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = load_ai4i_rows(DATA_PATH)
        generate_task_files(DATA_PATH)

    def test_ai4i_loads_with_required_columns(self) -> None:
        self.assertTrue(self.rows)
        for column in REQUIRED_COLUMNS:
            self.assertIn(column, self.rows[0])

    def test_hidden_labels_do_not_appear_in_public_observations(self) -> None:
        scenarios = build_twenty_scenarios(self.rows)
        for task_id in P0_SCENARIO_IDS:
            observation = VanceEnvironment(scenarios).reset(task_id, "test")
            rendered = repr(observation)
            for label in HIDDEN_LABEL_COLUMNS:
                self.assertNotIn(label, rendered)

    def test_task_jsonl_distribution(self) -> None:
        easy = parse_jsonl(REPO_ROOT / "tasks" / "easy.jsonl")
        medium = parse_jsonl(REPO_ROOT / "tasks" / "medium.jsonl")
        hard = parse_jsonl(REPO_ROOT / "tasks" / "hard.jsonl")
        self.assertEqual((len(easy), len(medium), len(hard)), (10, 5, 5))
        for task in easy + medium + hard:
            self.assertEqual(task["schema_version"], "vance.task.v1")

    def test_vance_100_taskset_distribution_and_no_public_label_leakage(self) -> None:
        full = parse_jsonl(REPO_ROOT / "tasks" / "vance_100.jsonl")
        train = parse_jsonl(REPO_ROOT / "tasks" / "train_80.jsonl")
        heldout = parse_jsonl(REPO_ROOT / "tasks" / "heldout_20.jsonl")
        self.assertEqual((len(full), len(train), len(heldout)), (100, 80, 20))
        self.assertEqual(sum(1 for task in full if task["expected_outcome"].get("must_continue_monitoring")), 11)
        for task in full:
            rendered_public = repr({key: value for key, value in task.items() if key != "expected_outcome"})
            for label in HIDDEN_LABEL_COLUMNS:
                self.assertNotIn(label, rendered_public)
            machine = next(iter(task["initial_state"]["machines"].values()))
            self.assertIn("derived_features", machine)
            self.assertIn("diagnostic_observations", machine)

    def test_baseline_and_improved_fallback_behavior(self) -> None:
        baseline = run_one("resolve", "baseline_slm", mode="fallback")
        improved = run_one("resolve", "improved_slm", mode="fallback")
        self.assertFalse(baseline.verifier_result.passed)
        self.assertEqual(baseline.verifier_result.hard_fail_reason, "restart_machine attempt")
        self.assertTrue(improved.verifier_result.passed)

    def test_improved_passes_demo_tasks(self) -> None:
        for task_id in P0_SCENARIO_IDS:
            with self.subTest(task_id=task_id):
                self.assertTrue(run_one(task_id, "improved_slm", mode="fallback").verifier_result.passed)

    def test_improved_passes_heldout_100_split(self) -> None:
        for record in parse_jsonl(REPO_ROOT / "tasks" / "heldout_20.jsonl"):
            with self.subTest(task_id=record["task_id"]):
                self.assertTrue(run_one(str(record["task_id"]), "improved_slm", mode="fallback").verifier_result.passed)

    def test_eval_runner_writes_metrics(self) -> None:
        self.assertEqual(run_eval_main(["--agent", "baseline_slm", "--tasks", "tasks/easy.jsonl", "--mode", "fallback"]), 0)
        self.assertEqual(run_eval_main(["--agent", "improved_slm", "--tasks", "tasks/easy.jsonl", "--mode", "fallback"]), 0)
        baseline = json.loads((REPO_ROOT / "evals" / "results_baseline.json").read_text())
        improved = json.loads((REPO_ROOT / "evals" / "results_improved.json").read_text())
        self.assertEqual(baseline["schema_version"], "vance.eval.v1")
        self.assertEqual(improved["metrics"]["pass_rate"], 1.0)

    def test_live_agent_missing_credentials_is_explicit(self) -> None:
        with self.assertRaises(LiveAgentUnavailable):
            build_agent("fireworks_agent", mode="live")
        self.assertEqual(run_eval_main(["--agent", "fireworks_agent", "--tasks", "tasks/easy.jsonl", "--mode", "live"]), 2)
        result = json.loads((REPO_ROOT / "evals" / "results_live_qwen.json").read_text())
        self.assertTrue(result["live_unavailable"])

    def test_dashboard_http_routes(self) -> None:
        port = 8876
        proc = subprocess.Popen(
            [sys.executable, "app/main.py", "--port", str(port)],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            scenario_payload = _retry_json(base + "/api/scenarios")
            scenarios = scenario_payload["scenarios"]
            self.assertGreaterEqual(len(scenarios), 6)
            episode_id = scenarios[0]["trace_variants"]["improved_slm"]["episode_id"]
            trace = _retry_json(base + f"/api/traces/{episode_id}")
            self.assertEqual(trace["episode_id"], episode_id)
            summary = _retry_json(base + "/api/evals/summary")
            self.assertIn("baseline", summary)
            self.assertIn("improved", summary)
            exported = urllib.request.urlopen(base + f"/api/export/{episode_id}.jsonl", timeout=5).read()
            self.assertEqual(json.loads(exported.decode("utf-8")), trace)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _retry_json(url: str):
    last_exc: Exception | None = None
    for _ in range(25):
        try:
            return json.loads(urllib.request.urlopen(url, timeout=2).read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            time.sleep(0.2)
    raise AssertionError(f"could not fetch {url}: {last_exc}")


if __name__ == "__main__":
    unittest.main()
