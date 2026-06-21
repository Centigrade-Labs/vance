"""Dashboard data adapters for Vance SafeOpsRL."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from agents.baseline_slm import BaselineHarness
from agents.fireworks_agent import FireworksAgent, LiveAgentUnavailable
from agents.improved_slm import ImprovedHarness
from evals.run_eval import eval_result
from finetuning.build_fireworks_sft import DEFAULT_OUTPUT as SFT_OUTPUT
from finetuning.build_fireworks_sft import DEFAULT_REPORT as SFT_REPORT
from finetuning.build_fireworks_sft import main as build_sft_main
from rft.build_rft_dataset import DEFAULT_OUTPUT as RFT_OUTPUT
from rft.build_rft_dataset import write_dataset as write_rft_dataset
from vance.data_loader import load_ai4i_rows
from vance.env import MAX_STEPS, VanceEnvironment
from vance.runner import DATA_PATH, EVAL_DIR, generate_task_files
from vance.scenarios import P0_SCENARIO_IDS, build_100_scenarios, build_twenty_scenarios
from vance.trace import parse_jsonl, trace_to_dict, write_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = REPO_ROOT / "tasks"
DASHBOARD_RUN_DIR = EVAL_DIR / "dashboard_runs"
DASHBOARD_LOG_DIR = DASHBOARD_RUN_DIR / "logs"
FINETUNE_JOB_DIR = EVAL_DIR / "fine_tune_jobs"
FINETUNE_LOG_DIR = FINETUNE_JOB_DIR / "logs"
FIREWORKS_API_BASE = "https://api.fireworks.ai"
RFT_REMOTE_URL = os.environ.get(
    "VANCE_RFT_REMOTE_URL",
    "https://dharunsivakumar002--vance-rft-bridge-fastapi-app.modal.run",
)
_FIREWORKS_MODELS_CACHE: dict[str, Any] = {"loaded_at": 0.0, "models": [], "error": ""}
_RUN_LOCK = threading.Lock()


def _load_env_file() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(REPO_ROOT / ".env", override=False)


def ensure_app_data(csv_path: str | Path = DATA_PATH) -> None:
    _load_env_file()
    generate_task_files(csv_path)
    DASHBOARD_RUN_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_LOG_DIR.mkdir(parents=True, exist_ok=True)
    FINETUNE_JOB_DIR.mkdir(parents=True, exist_ok=True)
    FINETUNE_LOG_DIR.mkdir(parents=True, exist_ok=True)


def connections_payload() -> dict[str, Any]:
    _load_env_file()
    return {
        "hud": _command_exists(REPO_ROOT / ".venv" / "bin" / "hud") or _command_exists("hud"),
        "fireworks": bool(os.environ.get("FIREWORKS_API_KEY") and os.environ.get("FIREWORKS_BASE_URL")),
        "modal": _modal_health(),
        "verifier": True,
        "last_run": _last_run_time(),
    }


def testsets_payload() -> list[dict[str, Any]]:
    tasks = _twenty_tasks()
    task_ids = [str(task["task_id"]) for task in tasks]
    vance_100 = _tasks_from_file("vance_100.jsonl")
    train_80 = _tasks_from_file("train_80.jsonl")
    heldout_20 = _tasks_from_file("heldout_20.jsonl")
    p0_ids = [task_id for task_id in P0_SCENARIO_IDS if task_id in task_ids]
    safety_ids = [
        str(task["task_id"])
        for task in tasks
        if task["difficulty"] == "hard" or _expected_action(task) == "Escalate"
    ]
    return [
        _testset("vance-20-safeops", "Vance 20-task SafeOps", task_ids, "Balanced resolve/escalate scenarios across difficulties."),
        _testset("vance-100-full", "Vance 100-task AI4I Diagnostics", [str(task["task_id"]) for task in vance_100], "Stratified AI4I diagnostic taskset with false positives and heldout-ready variety."),
        _testset("vance-train-80", "Vance 80-task RFT Train", [str(task["task_id"]) for task in train_80], "Training split for SFT/RFT data generation."),
        _testset("vance-heldout-20", "Vance 20-task Heldout Eval", [str(task["task_id"]) for task in heldout_20], "Heldout comparison split for base vs tuned model evaluation."),
        _testset("vance-p0-demo", "Vance P0 Demo Set", p0_ids, "Core five-scenario judge demo loop."),
        _testset("vance-safety-critical", "Vance Safety Critical", safety_ids, "Escalation and high-risk recovery scenarios."),
    ]


def models_payload() -> list[dict[str, Any]]:
    _load_env_file()
    return _fireworks_deployment_models()


def dashboard_payload() -> dict[str, Any]:
    return {
        "connections": connections_payload(),
        "testsets": testsets_payload(),
        "models": models_payload(),
        "runs": runs_payload(),
        "model_error": str(_FIREWORKS_MODELS_CACHE.get("error") or ""),
    }


def run_eval_payload(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    testset_id = str(payload.get("testset_id") or "vance-20-safeops")
    model_id = str(payload.get("model_id") or "env_fireworks")
    run_mode = str(payload.get("run_mode") or "direct")
    max_steps = int(payload.get("max_steps") or MAX_STEPS)
    max_concurrent = int(payload.get("max_concurrent") or 3)
    testset = _find_testset(testset_id)
    model = _find_model(model_id, payload)
    if not testset:
        return 400, {"error": f"Unknown testset: {testset_id}"}
    if not model:
        return 400, {"error": f"Unknown model: {model_id}"}
    if run_mode == "hud":
        return _run_hud_eval(model, testset, max_steps, max_concurrent)
    return _run_direct_eval(model, testset, max_steps, max_concurrent)


def start_eval_payload(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    testset_id = str(payload.get("testset_id") or "vance-20-safeops")
    model_id = str(payload.get("model_id") or "env_fireworks")
    run_mode = str(payload.get("run_mode") or "direct")
    max_steps = int(payload.get("max_steps") or MAX_STEPS)
    max_concurrent = int(payload.get("max_concurrent") or 3)
    testset = _find_testset(testset_id)
    model = _find_model(model_id, payload)
    if not testset:
        return 400, {"error": f"Unknown testset: {testset_id}"}
    if not model:
        return 400, {"error": f"Unknown model: {model_id}"}
    if run_mode == "hud" and not model.get("path"):
        return 400, {"error": "HUD eval requires a Fireworks model path."}
    run_id = _new_run_id(run_mode)
    execution = {
        "kind": run_mode,
        "command": [],
        "returncode": None,
        "duration_seconds": 0,
        "max_concurrent": max_concurrent,
        "taskset_env": str(testset["id"]) if run_mode == "hud" else "",
        "hud_job_url": "",
        "stdout": "",
        "stderr": "",
        "log_files": {},
        "runtime_errors": [],
        "started_at": int(time.time()),
    }
    record = _running_run_record(run_id, model, testset, max_steps, execution)
    _write_run(record)
    thread = threading.Thread(
        target=_eval_worker,
        args=(run_id, run_mode, model, testset, max_steps, max_concurrent),
        daemon=True,
    )
    thread.start()
    return 202, record


def eval_job_payload(run_id: str) -> dict[str, Any] | None:
    return _load_run(run_id)


def runs_payload() -> list[dict[str, Any]]:
    runs = []
    for path in sorted(DASHBOARD_RUN_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            runs.append(_normalize_run_record(json.loads(path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
    return runs


def run_logs_payload(run_id: str) -> dict[str, Any] | None:
    run = _load_run(run_id)
    if not run:
        return None
    execution = dict(run.get("execution", {}))
    log_files = execution.get("log_files", {})
    logs = {}
    for key in ("stdout", "stderr"):
        path = log_files.get(key)
        if path and Path(path).exists():
            logs[key] = Path(path).read_text(encoding="utf-8", errors="replace")
        else:
            logs[key] = execution.get(key, "")
    return {
        "run_id": run_id,
        "status": run.get("status", "unknown"),
        "diagnostics": run.get("diagnostics", []),
        "trace_health": run.get("trace_health", {}),
        "execution": {**execution, **logs},
    }


def build_training_data_payload(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    run_id = str(payload.get("run_id") or "")
    run = _load_run(run_id) if run_id else None
    build_sft_main(["--output", str(SFT_OUTPUT), "--report", str(SFT_REPORT)])
    rft_path = write_rft_dataset(RFT_OUTPUT)
    sft_count = _line_count(SFT_OUTPUT)
    rft_count = _line_count(rft_path)
    failures = _failure_summary(run) if run else []
    manifest = {
        "schema_version": "vance.training_data.ui.v1",
        "source_run_id": run_id,
        "sft": {"path": str(SFT_OUTPUT), "examples": sft_count, "report": str(SFT_REPORT)},
        "rft": {"path": str(rft_path), "prompts": rft_count, "remote_url": RFT_REMOTE_URL},
        "failures": failures,
        "created_at": int(time.time()),
    }
    path = REPO_ROOT / "finetuning" / "dashboard_training_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return 200, manifest


def launch_finetune_payload(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    training_type = str(payload.get("training_type") or "rft")
    if training_type != "rft":
        return 400, {"error": "Dashboard launch currently supports Fireworks RFT only."}
    try:
        cmd, output_model = _finetune_command(payload)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    env = os.environ.copy()
    env.pop("MODAL_TOKEN_ID", None)
    env.pop("MODAL_TOKEN_SECRET", None)
    completed = subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True, timeout=900)
    body = {
        "command": _redact_command(cmd),
        "returncode": completed.returncode,
        "stdout": completed.stdout[-6000:],
        "stderr": completed.stderr[-6000:],
        "output_model": output_model,
    }
    return (200 if completed.returncode == 0 else 500), body


def start_finetune_payload(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    training_type = str(payload.get("training_type") or "rft")
    if training_type != "rft":
        return 400, {"error": "Dashboard launch currently supports Fireworks RFT only."}
    try:
        cmd, output_model = _finetune_command(payload)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    job_id = f"ft_{time.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
    stdout_path, stderr_path = _write_finetune_logs(job_id, "", "")
    job = {
        "schema_version": "vance.finetune.job.v1",
        "job_id": job_id,
        "status": "running",
        "created_at": int(time.time()),
        "created_label": time.strftime("%b %d, %Y %I:%M %p"),
        "output_model": output_model,
        "command": _redact_command(cmd),
        "returncode": None,
        "duration_seconds": 0,
        "stdout": "",
        "stderr": "",
        "fireworks_job": {},
        "log_files": {"stdout": str(stdout_path), "stderr": str(stderr_path)},
    }
    _write_finetune_job(job)
    thread = threading.Thread(target=_finetune_worker, args=(job_id, cmd, output_model, stdout_path, stderr_path), daemon=True)
    thread.start()
    return 202, job


def finetune_job_payload(job_id: str) -> dict[str, Any] | None:
    job = _load_finetune_job(job_id)
    if not job:
        return None
    logs = {}
    for key in ("stdout", "stderr"):
        path = job.get("log_files", {}).get(key)
        if path and Path(path).exists():
            logs[key] = Path(path).read_text(encoding="utf-8", errors="replace")
        else:
            logs[key] = job.get(key, "")
    fireworks_job = job.get("fireworks_job") or _extract_fireworks_rft_job(logs.get("stdout", ""))
    return {**job, **logs, "fireworks_job": fireworks_job}


def _finetune_command(payload: dict[str, Any]) -> tuple[list[str], str]:
    output_model = _normalize_fireworks_output_model(str(payload.get("output_model") or "vance-qwen3-4b-rft"))
    base_model = str(payload.get("base_model") or "accounts/fireworks/models/qwen3-4b")
    dataset = str(payload.get("dataset") or "vance-rft-prompts")
    evaluator = str(payload.get("evaluator") or "test-vance-remote-test-vance-remote-rollout")
    cmd = [
        str(REPO_ROOT / ".venv" / "bin" / "eval-protocol"),
        "create",
        "rft",
        "--dataset",
        dataset,
        "--evaluator",
        evaluator,
        "--base-model",
        base_model,
        "--output-model",
        output_model,
        "--response-candidates-count",
        str(payload.get("response_candidates_count") or 8),
        "--temperature",
        str(payload.get("temperature") or 1.2),
        "--epochs",
        str(payload.get("epochs") or 1),
        "--yes",
    ]
    return cmd, output_model


def _normalize_fireworks_output_model(output_model: str) -> str:
    _load_env_file()
    model = output_model.strip().strip("/")
    if not model:
        raise ValueError("Output model is required.")
    parts = model.split("/")
    if len(parts) == 4 and parts[0] == "accounts" and parts[2] == "models" and all(parts):
        return model
    if model.startswith("accounts/"):
        raise ValueError('Output model must use the format "accounts/<account-id>/models/<model-id>".')
    if "/" in model:
        raise ValueError("Output model can be a short model id or a full accounts/<account-id>/models/<model-id> path.")
    account_id = _fireworks_account_id()
    if not account_id:
        raise ValueError("Set FIREWORKS_ACCOUNT_ID or FIREWORKS_MODEL so Vance can build the Fireworks output model path.")
    return f"accounts/{account_id}/models/{model}"


def _finetune_worker(job_id: str, cmd: list[str], output_model: str, stdout_path: Path, stderr_path: Path) -> None:
    started = time.time()
    env = os.environ.copy()
    env.pop("MODAL_TOKEN_ID", None)
    env.pop("MODAL_TOKEN_SECRET", None)
    try:
        process = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
    except Exception as exc:
        stderr_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        _write_finetune_job(
            {
                "schema_version": "vance.finetune.job.v1",
                "job_id": job_id,
                "status": "failed",
                "created_at": int(started),
                "created_label": time.strftime("%b %d, %Y %I:%M %p", time.localtime(started)),
                "output_model": output_model,
                "command": _redact_command(cmd),
                "returncode": 1,
                "duration_seconds": round(time.time() - started, 3),
                "stdout": "",
                "stderr": stderr_path.read_text(encoding="utf-8", errors="replace"),
                "fireworks_job": {},
                "log_files": {"stdout": str(stdout_path), "stderr": str(stderr_path)},
            }
        )
        return
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_thread = threading.Thread(target=_stream_pipe, args=(process.stdout, stdout_path, stdout_chunks), daemon=True)
    stderr_thread = threading.Thread(target=_stream_pipe, args=(process.stderr, stderr_path, stderr_chunks), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    try:
        process.wait(timeout=1200)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
        with stderr_path.open("a", encoding="utf-8") as handle:
            handle.write("\nFine-tune launch timed out after 1200 seconds.\n")
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    returncode = 124 if timed_out else process.returncode
    job = {
        "schema_version": "vance.finetune.job.v1",
        "job_id": job_id,
        "status": "completed" if returncode == 0 else "failed",
        "created_at": int(started),
        "created_label": time.strftime("%b %d, %Y %I:%M %p", time.localtime(started)),
        "output_model": output_model,
        "command": _redact_command(cmd),
        "returncode": returncode,
        "duration_seconds": round(time.time() - started, 3),
        "stdout": stdout[-12000:],
        "stderr": stderr[-12000:],
        "fireworks_job": _extract_fireworks_rft_job(stdout),
        "log_files": {"stdout": str(stdout_path), "stderr": str(stderr_path)},
    }
    _write_finetune_job(job)


def _write_finetune_logs(job_id: str, stdout: str, stderr: str) -> tuple[Path, Path]:
    FINETUNE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = FINETUNE_LOG_DIR / f"{job_id}.stdout.log"
    stderr_path = FINETUNE_LOG_DIR / f"{job_id}.stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return stdout_path, stderr_path


def _write_finetune_job(job: dict[str, Any]) -> None:
    FINETUNE_JOB_DIR.mkdir(parents=True, exist_ok=True)
    data = json.dumps(job, indent=2, sort_keys=True)
    with _RUN_LOCK:
        (FINETUNE_JOB_DIR / f"{job['job_id']}.json").write_text(data, encoding="utf-8")


def _load_finetune_job(job_id: str) -> dict[str, Any] | None:
    path = FINETUNE_JOB_DIR / f"{job_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _extract_fireworks_rft_job(stdout: str) -> dict[str, str]:
    job_name = ""
    job_url = ""
    for line in stdout.splitlines():
        stripped = line.strip()
        if "Created Reinforcement Fine-tuning Job:" in stripped:
            job_name = stripped.rsplit(":", 1)[-1].strip()
        if "https://app.fireworks.ai/dashboard/fine-tuning/reinforcement/" in stripped:
            job_url = stripped.split()[-1].strip()
    return {"name": job_name, "url": job_url} if job_name or job_url else {}


def trace_payload(episode_id: str) -> dict[str, Any] | None:
    for trace in _all_traces():
        if trace.get("episode_id") == episode_id:
            return trace
    return None


def export_trace_payload(episode_id: str) -> str | None:
    trace = trace_payload(episode_id)
    return json.dumps(trace, sort_keys=True) + "\n" if trace else None


def scenarios_payload() -> list[dict[str, object]]:
    traces_by_task: dict[str, list[dict[str, Any]]] = {}
    for trace in _all_traces():
        traces_by_task.setdefault(str(trace.get("task_id")), []).append(trace)
    return [
        {
            "task_id": task["task_id"],
            "title": task["title"],
            "difficulty": task["difficulty"],
            "expected_action": _expected_action(task),
            "machine_id": next(iter(task["initial_state"]["machines"])),
            "traces": traces_by_task.get(str(task["task_id"]), []),
        }
        for task in _all_task_records()
    ]


def eval_summary_payload() -> dict[str, object]:
    runs = runs_payload()
    results = {}
    for path in sorted(EVAL_DIR.glob("results_*.json")):
        try:
            results[path.stem.removeprefix("results_")] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return {"schema_version": "vance.eval.summary.v1", "runs": runs, "latest": runs[0] if runs else None, "results": results}


def find_trace(episode_id: str) -> dict[str, object] | None:
    return trace_payload(episode_id)


def run_episode_payload(payload: dict[str, object], csv_path: str | Path = DATA_PATH) -> tuple[int, dict[str, object]]:
    task_id = str(payload.get("task_id") or payload.get("scenario_id") or "resolve")
    model = _find_model(str(payload.get("model_id") or "env_fireworks"), dict(payload))
    testset = _testset("single", "Single task", [task_id], "Single selected task")
    if not model:
        return 400, {"error": "model not found"}
    return _run_direct_eval(model, testset, MAX_STEPS, 1, csv_path=csv_path, single_trace=True)


def index_html() -> str:
    return _INDEX_HTML


def _eval_worker(
    run_id: str,
    run_mode: str,
    model: dict[str, Any],
    testset: dict[str, Any],
    max_steps: int,
    max_concurrent: int,
) -> None:
    try:
        if run_mode == "hud":
            status, body = _run_hud_eval(model, testset, max_steps, max_concurrent, run_id=run_id)
        else:
            status, body = _run_direct_eval(model, testset, max_steps, max_concurrent, run_id=run_id)
        if status >= 400:
            current = _load_run(run_id)
            if not current:
                return
            execution = dict(current.get("execution", {}))
            execution["returncode"] = 1
            execution["stderr"] = str(body.get("error") or body)
            execution["runtime_errors"] = _runtime_errors(execution["stderr"])
            current["execution"] = execution
            current["status"] = "failed"
            current["diagnostics"] = [{"severity": "error", "code": "EVAL_START_FAILED", "message": execution["stderr"]}]
            _write_run(current)
    except Exception as exc:
        current = _load_run(run_id)
        if not current:
            return
        execution = dict(current.get("execution", {}))
        execution["returncode"] = 1
        execution["stderr"] = (str(execution.get("stderr") or "") + f"\n{type(exc).__name__}: {exc}").strip()
        execution["runtime_errors"] = _runtime_errors(execution["stderr"])
        current["execution"] = execution
        current["status"] = "failed"
        current["diagnostics"] = [
            {"severity": "error", "code": "DASHBOARD_WORKER_FAILED", "message": f"{type(exc).__name__}: {exc}"}
        ]
        _write_run(current)


def _run_direct_eval(
    model: dict[str, Any],
    testset: dict[str, Any],
    max_steps: int,
    max_concurrent: int,
    csv_path: str | Path = DATA_PATH,
    single_trace: bool = False,
    run_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    run_id = run_id or _new_run_id("direct")
    started = time.time()
    rows = load_ai4i_rows(csv_path)
    scenarios = build_twenty_scenarios(rows)
    scenarios.update(build_100_scenarios(rows))
    task_ids = [task_id for task_id in testset["task_ids"] if task_id in scenarios]
    try:
        agent = _agent_for_model(model)
    except LiveAgentUnavailable as exc:
        return 503, {"error": str(exc)}
    traces = [VanceEnvironment(scenarios).run_episode(agent, task_id, mode=str(model["mode"])) for task_id in task_ids]
    trace_dicts = [trace_to_dict(trace) for trace in traces]
    trace_dir = EVAL_DIR / "traces" / "dashboard" / run_id
    trace_dir.mkdir(parents=True, exist_ok=True)
    for trace in traces:
        write_jsonl(trace_dir / f"{trace.task_id}.jsonl", [trace])
    execution = {
        "kind": "direct",
        "command": ["internal", "VanceEnvironment.run_episode"],
        "returncode": 0,
        "duration_seconds": round(time.time() - started, 3),
        "max_concurrent": max_concurrent,
        "stdout": "",
        "stderr": "",
        "log_files": {},
    }
    result = _run_record(run_id, model, testset, max_steps, trace_dicts, [str(trace_dir)], execution=execution)
    _write_run(result)
    if single_trace:
        return 200, trace_dicts[0] if trace_dicts else {"error": "no trace"}
    return 200, result


def _run_hud_eval(
    model: dict[str, Any],
    testset: dict[str, Any],
    max_steps: int,
    max_concurrent: int,
    run_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    if not model.get("path"):
        return 400, {"error": "HUD eval requires a Fireworks model path."}
    run_id = run_id or _new_run_id("hud")
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = env.get("FIREWORKS_API_KEY", "")
    env["VANCE_HUD_TASKSET"] = str(testset["id"])
    env.pop("MODAL_TOKEN_ID", None)
    env.pop("MODAL_TOKEN_SECRET", None)
    hud_bin = REPO_ROOT / ".venv" / "bin" / "hud"
    cmd = [
        str(hud_bin),
        "eval",
        "hud_env.py",
        "openai_compatible",
        "--model",
        str(model["path"]),
        "--config",
        f"openai_compatible.base_url={env.get('FIREWORKS_BASE_URL', 'https://api.fireworks.ai/inference/v1')}",
        "--max-steps",
        str(max_steps),
        "--max-concurrent",
        str(max_concurrent),
        "--all",
        "-y",
    ]
    started = time.time()
    stdout_path, stderr_path = _write_run_logs(run_id, "", "")
    execution = {
        "kind": "hud",
        "command": _redact_command(cmd),
        "returncode": None,
        "duration_seconds": 0,
        "max_concurrent": max_concurrent,
        "taskset_env": str(testset["id"]),
        "hud_job_url": "",
        "stdout": "",
        "stderr": "",
        "log_files": {"stdout": str(stdout_path), "stderr": str(stderr_path)},
        "runtime_errors": [],
        "started_at": int(started),
    }
    _write_run(_running_run_record(run_id, model, testset, max_steps, execution))
    process = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_thread = threading.Thread(target=_stream_pipe, args=(process.stdout, stdout_path, stdout_chunks), daemon=True)
    stderr_thread = threading.Thread(target=_stream_pipe, args=(process.stderr, stderr_path, stderr_chunks), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    try:
        process.wait(timeout=900)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
        with stderr_path.open("a", encoding="utf-8") as handle:
            handle.write("\nHUD eval timed out after 900 seconds.\n")
        stderr_chunks.append("\nHUD eval timed out after 900 seconds.\n")
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    duration = round(time.time() - started, 3)
    returncode = 124 if timed_out else process.returncode
    combined_output = stdout + "\n" + stderr
    execution.update(
        {
            "returncode": returncode,
            "duration_seconds": duration,
            "hud_job_url": _extract_hud_job_url(combined_output),
            "stdout": stdout[-12000:],
            "stderr": stderr[-12000:],
            "runtime_errors": _runtime_errors(combined_output),
        }
    )
    if returncode != 0:
        result = _run_record(run_id, model, testset, max_steps, [], [], execution=execution)
        result["status"] = "failed"
        result["diagnostics"].insert(0, {"severity": "error", "code": "HUD_COMMAND_FAILED", "message": "HUD eval command returned non-zero."})
        _write_run(result)
        return 200, result
    trace_dir = EVAL_DIR / "traces" / "hud" / "hud_agent"
    traces = _latest_traces_from_dir(trace_dir, set(testset["task_ids"]))
    result = _run_record(run_id, model, testset, max_steps, traces, [str(trace_dir)], execution=execution)
    _write_run(result)
    return 200, result


def _run_record(
    run_id: str,
    model: dict[str, Any],
    testset: dict[str, Any],
    max_steps: int,
    traces: list[dict[str, Any]],
    trace_files: list[str],
    execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = eval_result(str(model["id"]), str(model["mode"]), traces, trace_files)
    metrics = result["metrics"]
    trace_health = _trace_health(testset, traces)
    diagnostics = _run_diagnostics(execution or {}, trace_health, metrics)
    return {
        "schema_version": "vance.dashboard.run.v1",
        "run_id": run_id,
        "status": _run_status(execution or {}, trace_health, metrics),
        "model": model,
        "testset": {"id": testset["id"], "name": testset["name"], "tasks": len(testset["task_ids"]), "task_ids": testset["task_ids"]},
        "max_steps": max_steps,
        "created_at": int(time.time()),
        "created_label": time.strftime("%b %d, %Y %I:%M %p"),
        "metrics": metrics,
        "common_failures": result["common_failures"],
        "diagnostics": diagnostics,
        "trace_health": trace_health,
        "execution": execution or {},
        "traces": traces,
        "trace_files": trace_files,
    }


def _write_run(run: dict[str, Any]) -> None:
    DASHBOARD_RUN_DIR.mkdir(parents=True, exist_ok=True)
    data = json.dumps(run, indent=2, sort_keys=True)
    with _RUN_LOCK:
        (DASHBOARD_RUN_DIR / f"{run['run_id']}.json").write_text(data, encoding="utf-8")


def _new_run_id(run_mode: str) -> str:
    prefix = "hud" if run_mode == "hud" else "run"
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"


def _running_run_record(
    run_id: str,
    model: dict[str, Any],
    testset: dict[str, Any],
    max_steps: int,
    execution: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "vance.dashboard.run.v1",
        "run_id": run_id,
        "status": "running",
        "model": model,
        "testset": {"id": testset["id"], "name": testset["name"], "tasks": len(testset["task_ids"]), "task_ids": testset["task_ids"]},
        "max_steps": max_steps,
        "created_at": int(time.time()),
        "created_label": time.strftime("%b %d, %Y %I:%M %p"),
        "metrics": _empty_metrics(),
        "common_failures": [],
        "diagnostics": [{"severity": "info", "code": "RUNNING", "message": "Evaluation process is running. Live stdout/stderr is streaming below."}],
        "trace_health": _trace_health(testset, []),
        "execution": execution,
        "traces": [],
        "trace_files": [],
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "episodes": 0,
        "pass_rate": 0,
        "average_reward": 0,
        "safety_violation_rate": 0,
        "manual_lookup_rate": 0,
        "inventory_check_rate": 0,
        "report_completion_rate": 0,
        "average_steps": 0,
    }


def _stream_pipe(pipe: Any, path: Path, chunks: list[str]) -> None:
    if pipe is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        for line in pipe:
            chunks.append(line)
            handle.write(line)
            handle.flush()


def _load_run(run_id: str) -> dict[str, Any] | None:
    path = DASHBOARD_RUN_DIR / f"{run_id}.json"
    return _normalize_run_record(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


def _normalize_run_record(run: dict[str, Any]) -> dict[str, Any]:
    execution = run.get("execution")
    if not isinstance(execution, dict):
        execution = {
            "kind": "hud" if str(run.get("run_id", "")).startswith("hud_") else "direct",
            "command": [],
            "returncode": 0,
            "duration_seconds": None,
            "stdout": run.get("stdout", ""),
            "stderr": "",
            "log_files": {},
            "runtime_errors": _runtime_errors(str(run.get("stdout", ""))),
        }
        run["execution"] = execution
    if "trace_health" not in run:
        run["trace_health"] = _trace_health(run.get("testset", {"task_ids": []}), run.get("traces", []))
    if "diagnostics" not in run:
        run["diagnostics"] = _run_diagnostics(execution, run["trace_health"], run.get("metrics", {}))
    if "status" not in run:
        run["status"] = _run_status(execution, run["trace_health"], run.get("metrics", {}))
    return run


def _write_run_logs(run_id: str, stdout: str, stderr: str) -> tuple[Path, Path]:
    DASHBOARD_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = DASHBOARD_LOG_DIR / f"{run_id}.stdout.log"
    stderr_path = DASHBOARD_LOG_DIR / f"{run_id}.stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return stdout_path, stderr_path


def _trace_health(testset: dict[str, Any], traces: list[dict[str, Any]]) -> dict[str, Any]:
    expected = [str(task_id) for task_id in testset["task_ids"]]
    by_task = {str(trace.get("task_id")): trace for trace in traces}
    zero_step = [task_id for task_id, trace in by_task.items() if len(trace.get("steps", [])) == 0]
    failed = [str(trace.get("task_id")) for trace in traces if not trace.get("verifier_result", {}).get("success")]
    missing = [task_id for task_id in expected if task_id not in by_task]
    return {
        "expected_tasks": len(expected),
        "traces_found": len(traces),
        "missing_traces": missing,
        "missing_trace_count": len(missing),
        "zero_step_traces": zero_step,
        "zero_step_count": len(zero_step),
        "failed_traces": failed,
        "failed_trace_count": len(failed),
        "average_steps": round(sum(len(trace.get("steps", [])) for trace in traces) / len(traces), 4) if traces else 0.0,
    }


def _run_status(execution: dict[str, Any], trace_health: dict[str, Any], metrics: dict[str, Any]) -> str:
    if execution.get("returncode") not in (None, 0):
        return "command_failed"
    if execution.get("runtime_errors"):
        return "model_error"
    if trace_health.get("traces_found") and trace_health.get("zero_step_count") == trace_health.get("traces_found"):
        return "no_tool_calls"
    if trace_health.get("missing_trace_count"):
        return "incomplete"
    return "passed" if metrics.get("pass_rate") == 1.0 else "completed"


def _run_diagnostics(execution: dict[str, Any], trace_health: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    for error in execution.get("runtime_errors", []):
        diagnostics.append({"severity": "error", "code": str(error["code"]), "message": str(error["message"])})
    if execution.get("returncode") not in (None, 0):
        diagnostics.append({"severity": "error", "code": "COMMAND_RETURNED_NONZERO", "message": f"Command returned {execution.get('returncode')}."})
    if trace_health.get("missing_trace_count"):
        diagnostics.append({"severity": "error", "code": "MISSING_TRACES", "message": f"{trace_health['missing_trace_count']} expected task traces were not written."})
    if trace_health.get("traces_found") and trace_health.get("zero_step_count") == trace_health.get("traces_found"):
        diagnostics.append({"severity": "error", "code": "NO_TOOL_CALLS", "message": "Every trace has zero tool steps. The agent likely never reached or used the HUD MCP tools."})
    elif trace_health.get("zero_step_count"):
        diagnostics.append({"severity": "warning", "code": "ZERO_STEP_TRACES", "message": f"{trace_health['zero_step_count']} traces have no tool calls."})
    if metrics.get("episodes") and metrics.get("pass_rate") == 0 and not diagnostics:
        diagnostics.append({"severity": "warning", "code": "ALL_TASKS_FAILED", "message": "All verifier rewards are zero; inspect trace timeline and model outputs."})
    if not diagnostics:
        diagnostics.append({"severity": "info", "code": "RUN_COMPLETED", "message": "No runtime log errors were detected."})
    return diagnostics


def _runtime_errors(text: str) -> list[dict[str, str]]:
    errors = []
    seen: set[str] = set()
    patterns = {
        "DEPLOYMENT_SCALING_UP": "Fireworks deployment is scaled to zero and still waking up. Retry after warmup or lower max concurrency.",
        "Error getting response": "HUD agent request failed before producing an answer.",
        "Rate limit": "Provider rate limit encountered.",
        "Connection error": "Provider or MCP connection error encountered.",
    }
    for line in text.splitlines():
        for token, message in patterns.items():
            if token in line and token not in seen:
                errors.append({"code": token, "message": message, "line": line.strip()})
                seen.add(token)
    return errors


def _extract_hud_job_url(text: str) -> str:
    for item in text.split():
        if item.startswith("https://hud.ai/jobs/"):
            return item.strip()
    return ""


def _twenty_tasks() -> list[dict[str, Any]]:
    if not TASK_DIR.exists():
        generate_task_files()
    tasks: list[dict[str, Any]] = []
    for name in ("easy.jsonl", "medium.jsonl", "hard.jsonl"):
        path = TASK_DIR / name
        if path.exists():
            tasks.extend(parse_jsonl(path))
    return tasks


def _all_task_records() -> list[dict[str, Any]]:
    records = _twenty_tasks()
    seen = {str(record["task_id"]) for record in records}
    for name in ("vance_100.jsonl", "train_80.jsonl", "heldout_20.jsonl"):
        for record in _tasks_from_file(name):
            task_id = str(record["task_id"])
            if task_id not in seen:
                records.append(record)
                seen.add(task_id)
    return records


def _tasks_from_file(name: str) -> list[dict[str, Any]]:
    path = TASK_DIR / name
    if not path.exists():
        generate_task_files()
    return parse_jsonl(path) if path.exists() else []


def _testset(testset_id: str, name: str, task_ids: list[str], description: str) -> dict[str, Any]:
    tasks = [task for task in _all_task_records() if task["task_id"] in task_ids]
    return {
        "id": testset_id,
        "name": name,
        "task_ids": task_ids,
        "tasks": len(task_ids),
        "created": "Generated from AI4I sensor substrate",
        "description": description,
        "distribution": _distribution(tasks),
        "task_rows": [_task_row(task) for task in tasks],
    }


def _find_testset(testset_id: str) -> dict[str, Any] | None:
    return next((item for item in testsets_payload() if item["id"] == testset_id), None)


def _find_model(model_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    payload = payload or {}
    if model_id == "custom":
        path = str(payload.get("custom_model_path") or "")
        if not path:
            return None
        return {
            "id": "custom",
            "name": "Custom Fireworks Model",
            "provider": "Fireworks",
            "path": path,
            "base_model": "Custom",
            "type": "Custom",
            "created": "",
            "last_eval": None,
            "agent": "fireworks_agent",
            "mode": "live",
        }
    if model_id == "baseline_slm":
        return _local_model("baseline_slm", "Baseline Deterministic Agent", "Baseline")
    if model_id == "improved_slm":
        return _local_model("improved_slm", "Improved Deterministic Oracle", "Oracle")
    return next((item for item in models_payload() if item["id"] == model_id), None)


def _agent_for_model(model: dict[str, Any]):
    if model["id"] == "baseline_slm":
        return BaselineHarness()
    if model["id"] == "improved_slm":
        return ImprovedHarness()
    return FireworksAgent(model=str(model["path"]))


def _local_model(model_id: str, name: str, model_type: str) -> dict[str, Any]:
    return {
        "id": model_id,
        "name": name,
        "provider": "Local",
        "path": f"agents/{model_id}.py",
        "base_model": "Rule policy",
        "type": model_type,
        "created": "",
        "last_eval": _last_eval_for_model(model_id),
        "agent": model_id,
        "mode": "fallback",
    }


def _fireworks_deployment_models() -> list[dict[str, Any]]:
    now = time.time()
    if now - float(_FIREWORKS_MODELS_CACHE["loaded_at"]) < 20:
        return list(_FIREWORKS_MODELS_CACHE["models"])
    account_id = _fireworks_account_id()
    api_key = os.environ.get("FIREWORKS_API_KEY")
    if not account_id or not api_key:
        _FIREWORKS_MODELS_CACHE.update({"loaded_at": now, "models": [], "error": "Missing FIREWORKS_API_KEY or Fireworks account id."})
        return []
    try:
        deployments = _list_fireworks_deployments(account_id, api_key)
    except Exception as exc:
        _FIREWORKS_MODELS_CACHE.update({"loaded_at": now, "models": [], "error": str(exc)})
        return []
    current = os.environ.get("FIREWORKS_MODEL", "")
    deployments.sort(
        key=lambda item: (
            item.get("name") != current,
            -int(item.get("desiredReplicaCount") or 0),
            str(item.get("createTime") or ""),
        )
    )
    models = [_fireworks_model_entry(item) for item in deployments if item.get("name")]
    _FIREWORKS_MODELS_CACHE.update({"loaded_at": now, "models": models, "error": ""})
    return models


def _fireworks_account_id() -> str:
    for key in ("FIREWORKS_ACCOUNT_ID", "FIREWORKS_ACCOUNT"):
        if os.environ.get(key):
            return str(os.environ[key])
    for key in ("FIREWORKS_MODEL", "VANCE_SFT_MODEL", "VANCE_RFT_MODEL"):
        value = os.environ.get(key, "")
        if value.startswith("accounts/"):
            parts = value.split("/")
            if len(parts) > 1:
                return parts[1]
    return ""


def _list_fireworks_deployments(account_id: str, api_key: str) -> list[dict[str, Any]]:
    deployments: list[dict[str, Any]] = []
    page_token = ""
    while True:
        query = "pageSize=100"
        if page_token:
            query += f"&pageToken={page_token}"
        payload = _fireworks_get(f"/v1/accounts/{account_id}/deployments?{query}", api_key)
        deployments.extend(payload.get("deployments", []))
        page_token = str(payload.get("nextPageToken") or "")
        if not page_token:
            return deployments


def _fireworks_get(path: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        FIREWORKS_API_BASE + path,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "curl/8.5.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read(300).decode("utf-8", "replace").strip()
        raise RuntimeError(f"Fireworks deployment list failed with HTTP {exc.code}: {message}") from exc


def _fireworks_model_entry(deployment: dict[str, Any]) -> dict[str, Any]:
    path = str(deployment["name"])
    base_model = str(deployment.get("baseModel") or "")
    label = str(deployment.get("displayName") or path.rsplit("/", 1)[-1])
    state = str(deployment.get("state") or "unknown")
    replicas = f"{deployment.get('replicaCount', 0)}/{deployment.get('desiredReplicaCount', 0)}"
    model_type = "SFT Deployment" if "/models/" in base_model and not base_model.startswith("accounts/fireworks/") else "Base Deployment"
    return {
        "id": f"fireworks:{path}",
        "name": label,
        "provider": "Fireworks",
        "path": path,
        "base_model": base_model,
        "type": model_type,
        "created": str(deployment.get("createTime") or ""),
        "state": state,
        "replicas": replicas,
        "last_eval": _last_eval_for_model(path),
        "agent": "fireworks_agent",
        "mode": "live",
    }


def _task_row(task: dict[str, Any]) -> dict[str, Any]:
    machine_id = next(iter(task["initial_state"]["machines"]))
    manual = task["manuals"][0]
    inventory = task["initial_state"]["inventory"][manual["required_part_id"]]
    return {
        "task_id": task["task_id"],
        "title": task["title"],
        "difficulty": task["difficulty"],
        "expected_action": _expected_action(task),
        "machine_id": machine_id,
        "manual_id": manual["manual_id"],
        "part_id": manual["required_part_id"],
        "inventory": inventory["quantity"],
    }


def _distribution(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    difficulty = Counter(str(task["difficulty"]) for task in tasks)
    outcome = Counter(_expected_action(task) for task in tasks)
    failure_modes = Counter(_failure_mode(task) for task in tasks)
    total = len(tasks) or 1
    return {
        "difficulty": [{"label": key.title(), "count": difficulty[key], "percent": round(difficulty[key] / total * 100)} for key in ("easy", "medium", "hard")],
        "outcome": [
            {"label": key, "count": outcome[key], "percent": round(outcome[key] / total * 100)}
            for key in ("Resolve", "Escalate", "Monitor")
            if outcome[key]
        ],
        "failure_modes": [{"label": key, "count": count, "percent": round(count / total * 100)} for key, count in failure_modes.most_common()],
    }


def _expected_action(task: dict[str, Any]) -> str:
    if task.get("expected_outcome", {}).get("must_continue_monitoring"):
        return "Monitor"
    return "Escalate" if task.get("expected_outcome", {}).get("must_escalate") else "Resolve"


def _failure_mode(task: dict[str, Any]) -> str:
    diagnosis = str(task.get("expected_outcome", {}).get("diagnosis", "unknown")).replace("_", " ")
    if "normal" in diagnosis or task.get("expected_outcome", {}).get("must_continue_monitoring"):
        return "False positive / monitoring"
    if "multi" in diagnosis:
        return "Multi-signal"
    if "tool" in diagnosis:
        return "Tool wear"
    if "heat" in diagnosis:
        return "Heat dissipation"
    if "power" in diagnosis:
        return "Power / load"
    if "overstrain" in diagnosis:
        return "Overstrain"
    return "Random / ambiguous"


def _all_traces() -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for run in runs_payload():
        traces.extend(run.get("traces", []))
    trace_root = EVAL_DIR / "traces"
    if trace_root.exists():
        for path in sorted(trace_root.rglob("*.jsonl")):
            try:
                traces.extend(parse_jsonl(path))
            except Exception:
                continue
    return traces


def _latest_traces_from_dir(path: Path, task_ids: set[str]) -> list[dict[str, Any]]:
    traces = []
    for item in sorted(path.glob("*.jsonl"), key=lambda file: file.stat().st_mtime, reverse=True):
        parsed = parse_jsonl(item)
        if parsed and str(parsed[-1].get("task_id")) in task_ids:
            traces.append(parsed[-1])
    by_task = {}
    for trace in traces:
        by_task.setdefault(str(trace["task_id"]), trace)
    return list(by_task.values())


def _failure_summary(run: dict[str, Any]) -> list[dict[str, Any]]:
    failures = Counter()
    for trace in run.get("traces", []):
        result = trace.get("verifier_result", {})
        if result.get("success"):
            continue
        reason = result.get("hard_fail_reason") or ", ".join(result.get("fail_reasons", [])) or "reward_below_threshold"
        failures[str(reason)] += 1
    return [{"reason": reason, "count": count} for reason, count in failures.most_common()]


def _last_eval_for_model(model_path: str) -> float | None:
    for run in runs_payload():
        model = run.get("model", {})
        if model.get("path") == model_path or model.get("id") == model_path:
            return run.get("metrics", {}).get("pass_rate")
    return None


def _last_run_time() -> str:
    runs = runs_payload()
    return str(runs[0]["created_label"]) if runs else ""


def _line_count(path: str | Path) -> int:
    file_path = Path(path)
    return sum(1 for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()) if file_path.exists() else 0


def _modal_health() -> bool:
    try:
        with urllib.request.urlopen(f"{RFT_REMOTE_URL}/health", timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def _command_exists(command: str | Path) -> bool:
    if isinstance(command, Path):
        return command.exists()
    return any((Path(part) / command).exists() for part in os.environ.get("PATH", "").split(os.pathsep))


def _redact_command(cmd: list[str]) -> list[str]:
    return ["<redacted>" if "key" in part.lower() else part for part in cmd]


_INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vance SafeOpsRL</title>
  <style>
    :root { --bg:#fff; --panel:#fff; --ink:#08090a; --muted:#69707a; --line:#e5e7eb; --soft:#f7f7f8; --black:#050505; --green:#178a25; --red:#d92d20; --amber:#b7791f; --blue:#2563eb; --shadow:0 8px 28px rgba(15,23,42,.06); }
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;letter-spacing:0}
    button,input,select{font:inherit} button{cursor:pointer} button:disabled{cursor:not-allowed;opacity:.62}.shell{display:grid;grid-template-columns:164px 1fr;min-height:100vh}
    aside{border-right:1px solid var(--line);padding:24px 14px;display:flex;flex-direction:column;gap:28px;position:sticky;top:0;height:100vh;background:#fff}
    .brand{font-size:31px;font-weight:900;letter-spacing:-.03em}.nav{display:flex;flex-direction:column;gap:8px}.nav button{display:flex;gap:10px;align-items:center;border:0;border-radius:8px;background:transparent;padding:12px 14px;text-align:left;color:#34383f}.nav button.active{background:#f1f1f2;color:#000;font-weight:800}.theme{margin-top:auto;border:1px solid var(--line);border-radius:8px;padding:8px;display:flex;justify-content:space-between;color:#3f4650}
    header{height:80px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 22px 0 34px;box-shadow:var(--shadow);position:sticky;top:0;background:#fff;z-index:2}
    h1{font-size:19px;margin:0;font-weight:850}.conn{display:flex;align-items:center;gap:20px;border:1px solid var(--line);border-radius:8px;padding:12px 18px;background:#fff}.dot{width:9px;height:9px;border-radius:50%;background:#a3a3a3;display:inline-block;margin-right:8px}.dot.on{background:var(--green)}.top-actions{display:flex;align-items:center;gap:18px}.docs{background:#050505;color:#fff;border:0;border-radius:8px;padding:14px 20px;font-weight:800}.last{color:#34383f;line-height:1.45}
    main{padding:26px}.steps{display:grid;grid-template-columns:1.4fr repeat(5,1fr);border:1px solid var(--line);border-radius:10px;margin-bottom:26px;box-shadow:var(--shadow);overflow:hidden}.step-card{padding:18px 20px;display:flex;gap:16px;align-items:center;min-height:84px}.step-card.active{border:1px solid #111;border-radius:9px;margin:-1px;background:#fff}.num{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;background:#e7e7e8;font-weight:900}.active .num{background:#050505;color:white}.step-title{font-weight:850;font-size:15px}.step-sub{font-size:12px;color:var(--muted);margin-top:5px}
    .grid{display:grid;grid-template-columns:minmax(640px,1.4fr) minmax(420px,0.95fr);gap:26px}.card{border:1px solid var(--line);border-radius:10px;background:#fff;box-shadow:var(--shadow);padding:20px}.section-title{font-size:22px;font-weight:900;margin:0 0 8px}.section-sub{color:#242830;margin:0 0 20px}.card h3{font-size:17px;margin:0 0 18px}.table{width:100%;border-collapse:collapse}.table th{font-size:12px;text-align:left;color:#1d222a;font-weight:850;padding:12px 8px;border-bottom:1px solid var(--line)}.table td{padding:16px 8px;border-bottom:1px solid var(--line);vertical-align:middle}.radio{width:18px;height:18px;border:1px solid #8f949c;border-radius:50%;display:inline-block}.radio.on{border:6px solid #050505}.small-btn{border:1px solid var(--line);background:#fff;border-radius:7px;padding:9px 15px}.dist{display:grid;grid-template-columns:1fr 1fr 1.35fr;gap:28px;border:1px solid var(--line);border-radius:8px;margin-top:22px;padding:22px 28px}.dist h4{margin:0 0 14px}.legend{display:grid;gap:10px}.legend-row{display:grid;grid-template-columns:16px 1fr auto;gap:8px;align-items:center}.pilldot{width:10px;height:10px;border-radius:50%;background:#999}.green{background:#2cb34a}.yellow{background:#e9ad31}.red{background:#ef2b2d}.blue{background:#3c6df0}.purple{background:#7c4bd8}.gray{background:#6b7280}
    label{font-weight:850;display:block;margin:0 0 9px}.select,input{width:100%;border:1px solid var(--line);border-radius:7px;padding:12px 14px;background:#fff}.details{display:grid;grid-template-columns:120px 1fr;gap:10px 18px;margin:18px 0;color:#252a32}.details b{font-weight:850}.seg{display:flex}.seg button{border:1px solid var(--line);background:#fff;padding:11px 18px}.seg button.active{background:#050505;color:#fff}.seg button:first-child{border-radius:7px 0 0 7px}.seg button:last-child{border-radius:0 7px 7px 0}.actions-row{display:grid;grid-template-columns:1fr 1fr;gap:18px}.primary{background:#050505;color:#fff;border:0;border-radius:7px;padding:14px 18px;font-weight:900}.secondary{background:#fff;color:#050505;border:1px solid var(--line);border-radius:7px;padding:14px 18px;font-weight:800}
    .runs{margin-top:18px}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.metric{border:1px solid var(--line);border-radius:7px;text-align:center;padding:16px 8px}.metric .label{font-size:12px;font-weight:850}.metric .value{font-size:25px;font-weight:950;margin:10px 0 4px}.metric .sub{color:#4b5563}.results{display:none}.results.show{display:block}.trace{display:grid;gap:10px;max-height:470px;overflow:auto;padding-right:4px}.trace-step{border-left:4px solid #9ca3af;background:#fafafa;border-radius:0 7px 7px 0;padding:11px}.trace-step.bad{border-left-color:var(--red);background:#fff7f7}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:850}.pass{background:#dcfce7;color:#166534}.fail{background:#fee2e2;color:#991b1b}.warn{background:#fef3c7;color:#92400e}.info{background:#e0f2fe;color:#075985}.running{background:#dbeafe;color:#1d4ed8}.log-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.log-box{max-height:260px;overflow:auto}.diag-list{display:grid;gap:8px;margin-bottom:14px}.diag-item{border:1px solid var(--line);border-left:4px solid #64748b;border-radius:7px;padding:10px;background:#fafafa}.diag-item.error{border-left-color:var(--red);background:#fff7f7}.diag-item.warning{border-left-color:#d97706;background:#fffbeb}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f7f8;border:1px solid var(--line);border-radius:7px;padding:10px}.modal{position:fixed;inset:0;background:rgba(0,0,0,.28);display:none;align-items:center;justify-content:center;z-index:5}.modal.show{display:flex}.modal-card{background:#fff;border-radius:10px;box-shadow:0 24px 80px rgba(0,0,0,.24);width:min(720px,calc(100vw - 40px));padding:22px}.modal-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.x{border:0;background:#fff;font-size:22px}.toast{position:fixed;right:24px;bottom:24px;background:#111;color:white;padding:13px 16px;border-radius:8px;display:none;z-index:8}.toast.show{display:block}
    @media(max-width:1100px){.shell{grid-template-columns:1fr}aside{display:none}.grid{grid-template-columns:1fr}.steps{grid-template-columns:1fr 1fr}.summary-grid{grid-template-columns:1fr 1fr}header{position:static;height:auto;padding:18px;gap:16px;flex-wrap:wrap}.conn{flex-wrap:wrap}.dist{grid-template-columns:1fr}}
  </style>
</head>
<body>
<div class="shell">
  <aside><div class="brand">vance</div><div class="nav">
    <button class="active">⌂ Dashboard</button><button>⌘ Evaluations</button><button>▣ Training Data</button><button>⌁ Fine-Tuning</button><button>◎ Models</button><button>◌ Comparisons</button><button>⚙ Settings</button>
  </div><div class="theme">☼ Light <span>☾</span></div></aside>
  <div>
    <header><h1>Vance SafeOpsRL</h1><div class="conn" id="connections"></div><div class="top-actions"><div class="last">Last run<br><span id="lastRun">-</span></div><button class="secondary" onclick="toggleTrain(true)">Train</button><button class="docs">▰ View Docs</button></div></header>
    <main>
      <div class="steps">
        <div class="step-card active"><div class="num">1</div><div><div class="step-title">Testsets</div><div class="step-sub">View and select HUD testsets</div></div></div>
        <div class="step-card"><div class="num">2</div><div><div class="step-title">Run Eval</div><div class="step-sub">Run selected model</div></div></div>
        <div class="step-card"><div class="num">3</div><div><div class="step-title">Verifier Output</div><div class="step-sub">Review failures</div></div></div>
        <div class="step-card"><div class="num">4</div><div><div class="step-title">Build Training Data</div><div class="step-sub">Create data from failures</div></div></div>
        <div class="step-card"><div class="num">5</div><div><div class="step-title">Fine-Tune</div><div class="step-sub">Launch job</div></div></div>
        <div class="step-card"><div class="num">6</div><div><div class="step-title">Compare</div><div class="step-sub">Compare models</div></div></div>
      </div>
      <div class="grid">
        <div>
          <h2 class="section-title">1. Testsets (HUD Eval)</h2><p class="section-sub">Select a testset to evaluate your model.</p>
          <section class="card"><h3>Available Testsets</h3><table class="table"><thead><tr><th></th><th>Testset Name</th><th>Tasks</th><th>Created</th><th>Description</th><th>Actions</th></tr></thead><tbody id="testsets"></tbody></table><div class="dist" id="distribution"></div></section>
          <section class="card runs"><h3>Previous Runs</h3><table class="table"><thead><tr><th>Run ID</th><th>Status</th><th>Model</th><th>Testset</th><th>Tasks</th><th>Success Rate</th><th>Mean Reward</th><th>Run At</th><th>Actions</th></tr></thead><tbody id="runs"></tbody></table></section>
        </div>
        <div>
          <section class="card"><label>Select Model</label><select id="modelSelect" class="select"></select><div class="details" id="modelDetails"></div></section>
          <section class="card runs"><h3>Run Evaluation</h3><div class="details"><b>Testset</b><span id="runTestset">-</span><b>Tasks</b><span id="runTasks">-</span><b>Max Steps</b><input id="maxSteps" value="8"><b>Max Concurrent</b><input id="maxConcurrent" value="3"><b>Run Mode</b><div class="seg"><button id="modeHud" class="active" onclick="setRunMode('hud')">HUD Eval</button><button id="modeDirect" onclick="setRunMode('direct')">Direct Vance Eval</button></div></div><div class="actions-row"><button id="runButton" class="primary" onclick="runEval()">▶ Run Evaluation</button><button class="secondary" onclick="resetView()">Reset</button></div></section>
          <section class="card runs"><h3>Last Run Summary <span id="runIdLabel" style="font-weight:500;color:var(--muted)"></span></h3><div class="summary-grid" id="summary"></div><button class="secondary" style="margin-top:18px;width:100%" onclick="showResults()">View Full Results →</button></section>
        </div>
      </div>
      <section class="card runs results" id="resultsPanel"><h3>Verifier Output</h3><div id="runDiagnostics"></div><div class="grid"><div><table class="table"><thead><tr><th>Task</th><th>Steps</th><th>Result</th><th>Reward</th><th>Reason</th></tr></thead><tbody id="traceRows"></tbody></table></div><div><h3 id="traceTitle">Trace</h3><div id="traceDetail"></div></div></div></section>
    </main>
  </div>
</div>
<div class="modal" id="trainModal"><div class="modal-card"><div class="modal-head"><h3>Build Training Data / Fine-Tune</h3><button class="x" onclick="toggleTrain(false)">×</button></div><div class="details"><b>Source Run</b><span id="trainRun">-</span><b>SFT Data</b><span id="sftPath">Not built</span><b>RFT Prompts</b><span id="rftPath">Not built</span><b>Evaluator</b><input id="evaluator" value="test-vance-remote-test-vance-remote-rollout"><b>Dataset</b><input id="dataset" value="vance-rft-prompts"><b>Output Model</b><input id="outputModel" value="vance-qwen3-4b-rft"></div><div class="actions-row"><button class="primary" onclick="buildTrainingData()">Build Training Data</button><button id="fineTuneButton" class="secondary" onclick="launchFineTune()">Start Fine-Tune</button></div><pre class="mono" id="trainLog"></pre></div></div>
<div class="toast" id="toast"></div>
<script>
let state={testsets:[],models:[],runs:[],selectedTestset:null,selectedRun:null,runMode:'hud',poller:null,runningRunId:null,finetunePoller:null};
const pct=v=>`${Math.round((Number(v)||0)*100)}%`; const num=v=>(Number(v)||0).toFixed(2);
async function api(path,opts){const r=await fetch(path,opts);const j=await r.json();if(!r.ok){const d=j.detail;throw new Error(j.error||(typeof d==='string'?d:d&&d.error?d.error:JSON.stringify(d||j))||'Request failed')}return j}
async function init(){const data=await api('/api/dashboard');state={...state,...data,selectedTestset:data.testsets[0]};renderConnections(data.connections);renderModels(data.model_error);renderTestsets();renderRuns();renderSelectedTestset();if(data.runs[0])renderRun(data.runs[0])}
function renderConnections(c){lastRun.textContent=c.last_run||'-';connections.innerHTML=['hud','fireworks','modal','verifier'].map(k=>`<span><i class="dot ${c[k]?'on':''}"></i>${k[0].toUpperCase()+k.slice(1)}</span>`).join('')}
function renderModels(error){if(!state.models.length){modelSelect.innerHTML='<option value="">No Fireworks deployments found</option>';modelSelect.disabled=true;modelDetails.innerHTML=`<b>Status</b><span class="badge fail">${error||'No deployments returned by Fireworks'}</span>`;return}modelSelect.disabled=false;modelSelect.innerHTML=state.models.map(m=>`<option value="${m.id}">${m.name}</option>`).join('');modelSelect.onchange=renderModelDetails;renderModelDetails()}
function currentModel(){return state.models.find(m=>m.id===modelSelect.value)||state.models[0]||null}
function renderModelDetails(){const m=currentModel();if(!m){modelDetails.innerHTML='<b>Status</b><span>No model selected</span>';return}modelDetails.innerHTML=`<b>Provider</b><span>${m.provider}</span><b>Model Path</b><span class="mono">${m.path}</span><b>Base Model</b><span class="mono">${m.base_model||'-'}</span><b>State</b><span>${m.state||'-'}</span><b>Replicas</b><span>${m.replicas||'-'}</span><b>Type</b><span>${m.type}</span><b>Last Eval</b><span>${m.last_eval==null?'-':pct(m.last_eval)}</span>`}
function renderTestsets(){testsets.innerHTML=state.testsets.map((t,i)=>`<tr><td><span class="radio ${i===0?'on':''}" data-radio="${t.id}"></span></td><td><b>${t.name}</b></td><td>${t.tasks}</td><td>${t.created}</td><td>${t.description}</td><td><button class="small-btn" onclick="viewTasks('${t.id}')">View Tasks</button></td></tr>`).join('');document.querySelectorAll('[data-radio]').forEach(el=>el.onclick=()=>selectTestset(el.dataset.radio))}
function selectTestset(id){state.selectedTestset=state.testsets.find(t=>t.id===id);document.querySelectorAll('[data-radio]').forEach(el=>el.classList.toggle('on',el.dataset.radio===id));renderSelectedTestset()}
function renderSelectedTestset(){const t=state.selectedTestset;if(!t)return;runTestset.textContent=t.name;runTasks.textContent=t.tasks;distribution.innerHTML=distBlock('Difficulty Distribution',t.distribution.difficulty,['green','yellow','red'])+distBlock('Outcome Distribution',t.distribution.outcome,['blue','purple'])+distBlock('Failure Mode Distribution',t.distribution.failure_modes,['gray','gray','gray','gray','gray'])}
function distBlock(title,rows,colors){return `<div><h4>${title}</h4><div class="legend">${rows.map((r,i)=>`<div class="legend-row"><i class="pilldot ${colors[i]||'gray'}"></i><span>${r.label}</span><b>${r.count} (${r.percent}%)</b></div>`).join('')}</div></div>`}
function renderRuns(){runs.innerHTML=(state.runs||[]).slice(0,5).map(r=>`<tr><td>${r.run_id}</td><td>${statusBadge(r.status)}</td><td>${r.model.name}</td><td>${r.testset.name}</td><td>${r.testset.tasks}</td><td>${pct(r.metrics.pass_rate)}</td><td>${num(r.metrics.average_reward)}</td><td>${r.created_label}</td><td><button class="small-btn" onclick="selectRun('${r.run_id}')">View</button></td></tr>`).join('')||'<tr><td colspan="9">No runs yet</td></tr>'}
function setRunMode(mode){state.runMode=mode;modeHud.classList.toggle('active',mode==='hud');modeDirect.classList.toggle('active',mode==='direct')}
async function runEval(){if(!currentModel())return toast('No Fireworks deployment selected');const body={testset_id:state.selectedTestset.id,model_id:modelSelect.value,run_mode:state.runMode,max_steps:Number(maxSteps.value)||8,max_concurrent:Number(maxConcurrent.value)||3};runButton.disabled=true;runButton.textContent='Running...';const run=await api('/api/evals/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});upsertRun(run);renderRuns();renderRun(run);showResults();toast('Evaluation started');pollRun(run.run_id)}
function upsertRun(run){state.runs=[run,...(state.runs||[]).filter(r=>r.run_id!==run.run_id)]}
function isRunning(run){return run&&run.status==='running'}
async function pollRun(id){if(state.poller)clearInterval(state.poller);state.runningRunId=id;const tick=async()=>{try{const run=await api(`/api/evals/jobs/${id}`);upsertRun(run);renderRuns();renderRun(run);await loadRunLogs(run);if(!isRunning(run)){clearInterval(state.poller);state.poller=null;state.runningRunId=null;runButton.disabled=false;runButton.textContent='▶ Run Evaluation';toast('Evaluation complete')}}catch(e){clearInterval(state.poller);state.poller=null;state.runningRunId=null;runButton.disabled=false;runButton.textContent='▶ Run Evaluation';toast(e.message)}};await tick();if(state.runningRunId)state.poller=setInterval(tick,2000)}
function renderRun(run){state.selectedRun=run;runIdLabel.textContent=`(${run.run_id})`;const m=run.metrics||{};summary.innerHTML=metric('Status',statusText(run.status),'')+metric('Success Rate',pct(m.pass_rate),`${m.episodes||0} tasks`)+metric('Mean Reward',num(m.average_reward),'')+metric('Zero-Step Traces',String((run.trace_health||{}).zero_step_count||0),'')+metric('Manual Lookup Rate',pct(m.manual_lookup_rate),'')+metric('Inventory Check Rate',pct(m.inventory_check_rate),'')+metric('Report Completion Rate',pct(m.report_completion_rate),'')+metric('Avg Steps',num(m.average_steps),'');renderDiagnostics(run);renderTraceRows(run)}
function metric(label,value,sub){return `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`}
function renderTraceRows(run){traceRows.innerHTML=(run.traces||[]).map((t,i)=>{const v=t.verifier_result;return `<tr onclick="selectTrace(${i})"><td>${t.task_id}</td><td>${(t.steps||[]).length}</td><td><span class="badge ${v.success?'pass':'fail'}">${v.success?'PASS':'FAIL'}</span></td><td>${v.reward}</td><td>${v.hard_fail_reason||v.fail_reasons.join(', ')||'-'}</td></tr>`}).join('')||`<tr><td colspan="5">${isRunning(run)?'Evaluation is running. Logs will update here until traces are written.':'No traces found for this run.'}</td></tr>`;if(run.traces&&run.traces[0])selectTrace(0);else traceDetail.innerHTML=''}
async function selectRun(id){const run=state.runs.find(r=>r.run_id===id);if(run){renderRun(run);showResults();await loadRunLogs(run)}}
function selectTrace(i){const t=state.selectedRun.traces[i];traceTitle.textContent=`${t.task_id} · ${t.agent_id}`;traceDetail.innerHTML=`<div style="margin-bottom:10px"><span class="badge ${t.verifier_result.success?'pass':'fail'}">${t.verifier_result.success?'PASS':'FAIL'}</span> reward ${t.verifier_result.reward}</div><div class="trace">${t.steps.map(s=>`<div class="trace-step ${s.blocked||s.hard_fail?'bad':''}"><b>${s.index}. ${s.tool}</b><div class="mono">${JSON.stringify(s.args)}\n${JSON.stringify(s.observation,null,2)}</div></div>`).join('')}</div><h3>Final Report</h3><div class="mono">${JSON.stringify(t.final_report,null,2)}</div>`}
function showResults(){resultsPanel.classList.add('show');resultsPanel.scrollIntoView({behavior:'smooth'})}
function viewTasks(id){selectTestset(id);showResults();traceRows.innerHTML=state.selectedTestset.task_rows.map(t=>`<tr><td>${t.task_id}</td><td>${t.difficulty}</td><td>${t.expected_action}</td><td>${t.machine_id}</td></tr>`).join('')}
function resetView(){resultsPanel.classList.remove('show')}
function suggestedOutputModel(){const m=currentModel();const path=(m&&m.path)||'';const parts=path.split('/');const account=parts[0]==='accounts'&&parts[1]?parts[1]:'';const stamp=new Date().toISOString().slice(0,10).replaceAll('-','');return account?`accounts/${account}/models/vance-qwen3-4b-rft-${stamp}`:'vance-qwen3-4b-rft'}
function toggleTrain(show){trainModal.classList.toggle('show',show);trainRun.textContent=state.selectedRun?state.selectedRun.run_id:'No run selected';if(show&&(!outputModel.value||!outputModel.value.startsWith('accounts/')))outputModel.value=suggestedOutputModel()}
async function buildTrainingData(){if(!state.selectedRun)return toast('Run an eval first');trainLog.textContent='Building training data...';const data=await api('/api/training-data/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:state.selectedRun.run_id})});sftPath.textContent=`${data.sft.path} (${data.sft.examples})`;rftPath.textContent=`${data.rft.path} (${data.rft.prompts})`;trainLog.textContent=JSON.stringify(data.failures,null,2)}
async function launchFineTune(){fineTuneButton.disabled=true;fineTuneButton.textContent='Launching...';trainLog.textContent='Starting Fireworks RFT launch...';try{const job=await api('/api/fine-tunes/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({evaluator:evaluator.value,dataset:dataset.value,output_model:outputModel.value})});outputModel.value=job.output_model;renderFineTuneJob(job);pollFineTune(job.job_id)}catch(e){fineTuneButton.disabled=false;fineTuneButton.textContent='Start Fine-Tune';trainLog.textContent=e.message;toast('Fine-tune launch failed')}}
async function pollFineTune(id){if(state.finetunePoller)clearInterval(state.finetunePoller);const tick=async()=>{try{const job=await api(`/api/fine-tunes/jobs/${id}`);renderFineTuneJob(job);if(job.status!=='running'){clearInterval(state.finetunePoller);state.finetunePoller=null;fineTuneButton.disabled=false;fineTuneButton.textContent='Start Fine-Tune';toast(job.status==='completed'?'Fine-tune launched':'Fine-tune launch failed')}}catch(e){clearInterval(state.finetunePoller);state.finetunePoller=null;fineTuneButton.disabled=false;fineTuneButton.textContent='Start Fine-Tune';trainLog.textContent=e.message;toast('Fine-tune status failed')}};await tick();state.finetunePoller=setInterval(tick,2000)}
function renderFineTuneJob(job){const out=job.stdout||'';const err=job.stderr||'';const fw=job.fireworks_job||{};trainLog.textContent=`Status: ${job.status}\nJob: ${job.job_id}\nOutput model: ${job.output_model}\nFireworks RFT job: ${fw.name||'-'}\nFireworks URL: ${fw.url||'-'}\nReturn code: ${job.returncode??'-'}\nDuration: ${job.duration_seconds??0}s\nCommand: ${(job.command||[]).join(' ')}\n\nSTDOUT\n${out}\n\nSTDERR\n${err}`;trainLog.scrollTop=trainLog.scrollHeight}
function toast(msg){const el=document.getElementById('toast');el.textContent=msg;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),3000)}
function statusText(status){return (status||'unknown').replaceAll('_',' ')}
function statusBadge(status){const s=status||'unknown';const cls=s==='running'?'running':['passed','completed'].includes(s)?'pass':['model_error','no_tool_calls','command_failed','failed'].includes(s)?'fail':'warn';return `<span class="badge ${cls}">${statusText(s).toUpperCase()}</span>`}
function renderDiagnostics(run, logs){const h=run.trace_health||{};const exec=run.execution||{};const diagnostics=run.diagnostics||[];runDiagnostics.innerHTML=`<div class="card" style="box-shadow:none;margin-bottom:16px"><h3>Run Diagnostics ${statusBadge(run.status)}</h3><div class="details"><b>Command</b><span class="mono">${(exec.command||[]).join(' ')||'-'}</span><b>Return Code</b><span>${exec.returncode??'-'}</span><b>Duration</b><span>${exec.duration_seconds??'-'}s</span><b>Max Concurrent</b><span>${exec.max_concurrent??'-'}</span><b>HUD Job</b><span>${exec.hud_job_url?`<a href="${exec.hud_job_url}" target="_blank">${exec.hud_job_url}</a>`:'-'}</span><b>Trace Health</b><span>${h.traces_found||0}/${h.expected_tasks||0} traces · ${h.zero_step_count||0} zero-step · ${h.missing_trace_count||0} missing</span></div><div class="diag-list">${diagnostics.map(d=>`<div class="diag-item ${d.severity||'info'}"><b>${d.code}</b><br>${d.message}</div>`).join('')}</div><div id="runtimeLogs">${logs?logHtml(logs):'<div class="mono">Open a run to load full HUD stdout/stderr.</div>'}</div></div>`}
async function loadRunLogs(run){try{const logs=await api(`/api/runs/${run.run_id}/logs`);renderDiagnostics(run,logs)}catch(e){toast(e.message)}}
function logHtml(logs){const e=logs.execution||{};return `<h3>Runtime Logs</h3><div class="log-grid"><div><b>stdout</b><pre class="mono log-box">${escapeHtml(e.stdout||'')}</pre></div><div><b>stderr</b><pre class="mono log-box">${escapeHtml(e.stderr||'')}</pre></div></div>`}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
document.addEventListener('keydown',e=>{if(e.key==='t')toggleTrain(true)});init().catch(e=>toast(e.message));
</script>
</body>
</html>"""
