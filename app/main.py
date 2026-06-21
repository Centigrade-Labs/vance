"""FastAPI Judge Mode dashboard entrypoint.

When FastAPI/Uvicorn are not installed, `python app/main.py` falls back to a
standard-library server with the same core routes so fallback demos still work.
"""

from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dashboard import ensure_app_data, eval_summary_payload, find_trace, index_html, run_episode_payload, scenarios_payload


def create_app():
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse, PlainTextResponse
    except Exception as exc:  # pragma: no cover - optional dependency branch
        raise RuntimeError("FastAPI is not installed") from exc

    app = FastAPI(title="Vance Judge Mode")

    @app.on_event("startup")
    def _startup() -> None:
        ensure_app_data()

    @app.get("/", response_class=HTMLResponse)
    def index():
        return index_html()

    @app.get("/api/scenarios")
    def scenarios():
        return scenarios_payload()

    @app.post("/api/run")
    def run(payload: dict[str, object]):
        status, body = run_episode_payload(payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=body)
        return body

    @app.get("/api/traces/{episode_id}")
    def trace(episode_id: str):
        found = find_trace(episode_id)
        if not found:
            raise HTTPException(status_code=404, detail="trace not found")
        return found

    @app.get("/api/evals/summary")
    def evals_summary():
        return eval_summary_payload()

    @app.get("/api/export/{episode_id}.jsonl", response_class=PlainTextResponse)
    def export_trace(episode_id: str):
        found = find_trace(episode_id)
        if not found:
            raise HTTPException(status_code=404, detail="trace not found")
        return json.dumps(found, sort_keys=True) + "\n"

    return app


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


app = None
try:
    app = create_app()
except RuntimeError:
    app = None


if __name__ == "__main__":
    raise SystemExit(main())
