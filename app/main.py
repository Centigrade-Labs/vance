"""FastAPI Judge Mode dashboard entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dashboard import (
    build_training_data_payload,
    connections_payload,
    dashboard_payload,
    ensure_app_data,
    eval_job_payload,
    eval_summary_payload,
    finetune_job_payload,
    export_trace_payload,
    index_html,
    launch_finetune_payload,
    models_payload,
    run_logs_payload,
    run_episode_payload,
    run_eval_payload,
    runs_payload,
    scenarios_payload,
    start_eval_payload,
    start_finetune_payload,
    testsets_payload,
    trace_payload,
)


def create_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, PlainTextResponse

    app = FastAPI(title="Vance Judge Mode")

    @app.on_event("startup")
    def _startup() -> None:
        ensure_app_data()

    @app.get("/", response_class=HTMLResponse)
    def index():
        return index_html()

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
    def scenarios():
        return scenarios_payload()

    @app.post("/api/run")
    def run(payload: dict[str, object]):
        status, body = run_episode_payload(payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=body)
        return body

    @app.post("/api/evals/run")
    def run_eval(payload: dict[str, object]):
        status, body = run_eval_payload(payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=body)
        return body

    @app.post("/api/evals/start")
    def start_eval(payload: dict[str, object]):
        status, body = start_eval_payload(payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=body)
        return body

    @app.get("/api/evals/jobs/{run_id}")
    def eval_job(run_id: str):
        found = eval_job_payload(run_id)
        if not found:
            raise HTTPException(status_code=404, detail="run not found")
        return found

    @app.post("/api/training-data/build")
    def build_training_data(payload: dict[str, object]):
        status, body = build_training_data_payload(payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=body)
        return body

    @app.post("/api/fine-tunes/launch")
    def launch_finetune(payload: dict[str, object]):
        status, body = launch_finetune_payload(payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=body)
        return body

    @app.post("/api/fine-tunes/start")
    def start_finetune(payload: dict[str, object]):
        status, body = start_finetune_payload(payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=body)
        return body

    @app.get("/api/fine-tunes/jobs/{job_id}")
    def fine_tune_job(job_id: str):
        found = finetune_job_payload(job_id)
        if not found:
            raise HTTPException(status_code=404, detail="fine-tune job not found")
        return found

    @app.get("/api/traces/{episode_id}")
    def trace(episode_id: str):
        found = trace_payload(episode_id)
        if not found:
            raise HTTPException(status_code=404, detail="trace not found")
        return found

    @app.get("/api/evals/summary")
    def evals_summary():
        return eval_summary_payload()

    @app.get("/api/export/{episode_id}.jsonl", response_class=PlainTextResponse)
    def export_trace(episode_id: str):
        exported = export_trace_payload(episode_id)
        if not exported:
            raise HTTPException(status_code=404, detail="trace not found")
        return exported

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Vance Judge Mode dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    ensure_app_data()
    import uvicorn

    uvicorn.run("app.main:create_app", factory=True, host=args.host, port=args.port, log_level="info")
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
