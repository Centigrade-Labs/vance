"""FastAPI Judge Mode dashboard entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.dashboard import (
    build_training_data_payload,
    connections_payload,
    dashboard_payload,
    ensure_app_data,
    eval_job_payload,
    finetune_job_payload,
    launch_finetune_payload,
    models_payload,
    run_eval_payload,
    run_logs_payload,
    runs_payload,
    start_eval_payload,
    start_finetune_payload,
    testsets_payload,
    trace_payload,
)
from app.service import DashboardService


BASE_DIR = Path(__file__).resolve().parent
PAGES_DIR = BASE_DIR / "templates"


def _env(*names: str, default: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


TASK_DIR = _env("FORGE_TASK_DIR", "VANCE_TASK_DIR", default="tasks")
TRACE_DIR = _env("FORGE_TRACE_DIR", "VANCE_TRACE_DIR", default="evals/traces")
HOST = _env("FORGE_HOST", "VANCE_HOST", default="127.0.0.1")
PORT = int(_env("FORGE_PORT", "VANCE_PORT", default="8000"))

service = DashboardService(task_dir=TASK_DIR, trace_dir=TRACE_DIR)


def _render_page(filename: str) -> HTMLResponse:
    return HTMLResponse((PAGES_DIR / filename).read_text(encoding="utf-8"))


def _raise_for_payload(status: int, body: dict[str, Any]) -> None:
    if status >= 400:
        raise HTTPException(status_code=status, detail=body)


def create_app() -> FastAPI:
    app = FastAPI(title="Vance Judge Mode", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.on_event("startup")
    def _startup() -> None:
        ensure_app_data()

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _render_page("index.html")

    @app.get("/evals", response_class=HTMLResponse)
    def evals_page():
        return _render_page("evals.html")

    @app.get("/about", response_class=HTMLResponse)
    def about_page():
        return _render_page("about.html")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "loaded_scenarios": len(service.scenarios())}

    @app.get("/api/dashboard")
    def dashboard():
        return dashboard_payload()

    @app.get("/api/connections")
    def connections():
        return connections_payload()

    @app.get("/api/testsets")
    def testsets():
        return testsets_payload()

    @app.get("/api/models")
    def models():
        return models_payload()

    @app.get("/api/runs")
    def runs():
        return runs_payload()

    @app.get("/api/runs/{run_id}/logs")
    def run_logs(run_id: str):
        found = run_logs_payload(run_id)
        if not found:
            raise HTTPException(status_code=404, detail="run not found")
        return found

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, Any]:
        items = service.scenarios()
        return {"count": len(items), "scenarios": items}

    @app.post("/api/run")
    def run_episode(payload: dict[str, Any]) -> dict[str, Any]:
        task_id = payload.get("task_id")
        agent_id = payload.get("agent_id", "improved_slm")
        mode = payload.get("mode", "fallback")
        if not task_id:
            scenarios_payload = service.scenarios()
            if not scenarios_payload:
                raise HTTPException(status_code=400, detail="No tasks are loaded. Add JSONL task records under tasks/.")
            task_id = scenarios_payload[0]["task_id"]
        try:
            trace = service.run_episode(str(task_id), str(agent_id), str(mode))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "episode_id": trace["episode_id"],
            "task_id": trace["task_id"],
            "agent_id": trace["agent_id"],
            "mode": trace["mode"],
            "verifier_result": trace["verifier_result"],
            "trace": trace,
        }

    @app.post("/api/evals/run")
    def run_eval(payload: dict[str, Any]):
        status, body = run_eval_payload(payload)
        _raise_for_payload(status, body)
        return body

    @app.post("/api/evals/start")
    def start_eval(payload: dict[str, Any]):
        status, body = start_eval_payload(payload)
        _raise_for_payload(status, body)
        return body

    @app.get("/api/evals/jobs/{run_id}")
    def eval_job(run_id: str):
        found = eval_job_payload(run_id)
        if not found:
            raise HTTPException(status_code=404, detail="run not found")
        return found

    @app.post("/api/training-data/build")
    def build_training_data(payload: dict[str, Any]):
        status, body = build_training_data_payload(payload)
        _raise_for_payload(status, body)
        return body

    @app.post("/api/fine-tunes/launch")
    def launch_finetune(payload: dict[str, Any]):
        status, body = launch_finetune_payload(payload)
        _raise_for_payload(status, body)
        return body

    @app.post("/api/fine-tunes/start")
    def start_finetune(payload: dict[str, Any]):
        status, body = start_finetune_payload(payload)
        _raise_for_payload(status, body)
        return body

    @app.get("/api/fine-tunes/jobs/{job_id}")
    def fine_tune_job(job_id: str):
        found = finetune_job_payload(job_id)
        if not found:
            raise HTTPException(status_code=404, detail="fine-tune job not found")
        return found

    @app.get("/api/traces/{episode_id}")
    def trace(episode_id: str):
        found = service.get_trace(episode_id) or trace_payload(episode_id)
        if not found:
            raise HTTPException(status_code=404, detail="trace not found")
        return found

    @app.get("/api/evals/summary")
    def evals_summary():
        return service.eval_summary()

    @app.get("/api/export/{episode_id}.jsonl", response_class=PlainTextResponse)
    def export_trace(episode_id: str):
        found = service.get_trace(episode_id)
        if found:
            return json.dumps(found, sort_keys=True) + "\n"
        exported = trace_payload(episode_id)
        if not exported:
            raise HTTPException(status_code=404, detail="trace not found")
        return json.dumps(exported, sort_keys=True) + "\n"

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Vance Judge Mode dashboard.")
    parser.add_argument("--mode", choices=["fallback", "live"], default="fallback")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    ensure_app_data()
    import uvicorn

    uvicorn.run("app.main:create_app", factory=True, host=args.host, port=args.port, log_level="info")
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
