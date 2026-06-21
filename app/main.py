from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.service import DashboardService


try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional local dependency
    def load_dotenv() -> None:
        return None


load_dotenv()


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

app = FastAPI(title="Forge Judge Mode", version="0.1.0")
service = DashboardService(task_dir=TASK_DIR, trace_dir=TRACE_DIR)

BASE_DIR = Path(__file__).resolve().parent
PAGES_DIR = BASE_DIR / "templates"
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _render_page(filename: str) -> HTMLResponse:
    return HTMLResponse((PAGES_DIR / filename).read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
async def index():
    return _render_page("index.html")


@app.get("/evals", response_class=HTMLResponse)
async def evals_page():
    return _render_page("evals.html")


@app.get("/about", response_class=HTMLResponse)
async def about_page():
    return _render_page("about.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "loaded_scenarios": len(service.scenarios())}


@app.get("/api/scenarios")
async def scenarios() -> dict[str, Any]:
    items = service.scenarios()
    return {"count": len(items), "scenarios": items}


@app.post("/api/run")
async def run_episode(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = payload.get("task_id")
    agent_id = payload.get("agent_id", "improved_slm")
    mode = payload.get("mode", "fallback")
    if not task_id:
        scenarios_payload = service.scenarios()
        if not scenarios_payload:
            raise HTTPException(status_code=400, detail="No tasks are loaded. Add JSONL task records under tasks/.")
        task_id = scenarios_payload[0]["task_id"]
    try:
        trace = service.run_episode(task_id, agent_id, mode)
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


@app.get("/api/traces/{episode_id}")
async def get_trace(episode_id: str) -> dict[str, Any]:
    trace = service.get_trace(episode_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return trace


@app.get("/api/evals/summary")
async def eval_summary() -> dict[str, Any]:
    return service.eval_summary()


@app.get("/api/export/{episode_id}.jsonl")
async def export_trace(episode_id: str) -> Response:
    trace = service.get_trace(episode_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return Response(
        content=json.dumps(trace, sort_keys=True) + "\n",
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{episode_id}.jsonl"'},
    )


@app.post("/api/hud/reset")
async def hud_reset(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = payload.get("task_id")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required.")
    try:
        return service.hud().reset(task_id, payload.get("agent_id", "hud_agent"), payload.get("mode", "live"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/hud/step")
async def hud_step(payload: dict[str, Any]) -> dict[str, Any]:
    episode_id = payload.get("episode_id")
    action = payload.get("action")
    if not episode_id or not isinstance(action, dict):
        raise HTTPException(status_code=400, detail="episode_id and action are required.")
    try:
        return service.hud().step(episode_id, action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def main() -> None:
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
