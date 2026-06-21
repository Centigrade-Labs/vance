"""FastAPI Judge Mode dashboard entrypoint.

When FastAPI/Uvicorn are not installed, `python app/main.py` falls back to a
standard-library server with the same core routes so fallback demos still work.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

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

app = FastAPI(title="vance Judge Mode", version="0.1.0")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Vance Judge Mode dashboard.")
    parser.add_argument("--mode", choices=["fallback", "live"], default="fallback")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    ensure_app_data()
    try:
        import uvicorn
    except Exception:
        return _run_stdlib(args.host, args.port)
    uvicorn.run("app.main:create_app", factory=True, host=args.host, port=args.port, log_level="info")
    return 0


def _run_stdlib(host: str, port: int) -> int:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                self._send(index_html().encode("utf-8"), "text/html")
                return
            if self.path == "/api/scenarios":
                self._send_json(scenarios_payload())
                return
            if self.path == "/api/evals/summary":
                self._send_json(eval_summary_payload())
                return
            if self.path.startswith("/api/traces/"):
                episode_id = unquote(self.path.removeprefix("/api/traces/"))
                found = find_trace(episode_id)
                self._send_json(found if found else {"error": "trace not found"}, HTTPStatus.OK if found else HTTPStatus.NOT_FOUND)
                return
            if self.path.startswith("/api/export/") and self.path.endswith(".jsonl"):
                episode_id = unquote(self.path.removeprefix("/api/export/").removesuffix(".jsonl"))
                found = find_trace(episode_id)
                if not found:
                    self._send_json({"error": "trace not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._send((json.dumps(found, sort_keys=True) + "\n").encode("utf-8"), "application/jsonl")
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.path != "/api/run":
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(length) or b"{}")
            status, body = run_episode_payload(payload)
            self._send_json(body, HTTPStatus(status))

        def log_message(self, format: str, *args) -> None:
            return

        def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send(json.dumps(payload, sort_keys=True).encode("utf-8"), "application/json", status)

        def _send(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Vance Judge Mode: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def main() -> None:
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    raise SystemExit(main())
