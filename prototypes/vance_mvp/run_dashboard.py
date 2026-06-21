"""Standard-library Judge Mode dashboard for the isolated Vance MVP."""

from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.vance_mvp.agents import agent_for_id
from prototypes.vance_mvp.data_loader import load_ai4i_rows
from prototypes.vance_mvp.environment import VanceEnvironment
from prototypes.vance_mvp.eval_summary import write_eval_summary
from prototypes.vance_mvp.scenarios import P0_SCENARIO_IDS, build_scenarios, build_twenty_task_records, task_record_from_scenario
from prototypes.vance_mvp.trace import parse_jsonl, trace_to_dict, write_jsonl, write_records_jsonl


OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Vance MVP Judge Mode dashboard.")
    parser.add_argument("--csv", required=True, help="Path to data/ai4i2020.csv")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    ensure_dashboard_data(args.csv)
    handler = _handler_factory(args.csv)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Vance Judge Mode: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def ensure_dashboard_data(csv_path: str | Path) -> None:
    rows = load_ai4i_rows(csv_path)
    scenarios = build_scenarios(rows)
    write_records_jsonl(OUTPUT_DIR / "p0_tasks.jsonl", [task_record_from_scenario(scenarios[item]) for item in P0_SCENARIO_IDS])
    write_records_jsonl(OUTPUT_DIR / "taskset_20.jsonl", build_twenty_task_records(rows))
    for agent_id in ("baseline", "improved"):
        traces = []
        agent = agent_for_id(agent_id)
        for scenario_id in P0_SCENARIO_IDS:
            traces.append(VanceEnvironment(scenarios).run_episode(agent, scenario_id))
        write_jsonl(OUTPUT_DIR / f"{agent_id}.jsonl", traces)
    write_eval_summary(OUTPUT_DIR)


def _handler_factory(csv_path: str | Path):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                self._send_html(_INDEX_HTML)
                return
            if self.path == "/api/scenarios":
                self._send_json(_scenarios_payload())
                return
            if self.path == "/api/evals/summary":
                self._send_json(_read_json(OUTPUT_DIR / "eval_summary.json"))
                return
            if self.path.startswith("/api/traces/"):
                episode_id = unquote(self.path.removeprefix("/api/traces/"))
                trace = _find_trace(episode_id)
                self._send_json(trace if trace else {"error": "trace not found"}, HTTPStatus.OK if trace else HTTPStatus.NOT_FOUND)
                return
            if self.path.startswith("/api/export/") and self.path.endswith(".jsonl"):
                episode_id = unquote(self.path.removeprefix("/api/export/").removesuffix(".jsonl"))
                trace = _find_trace(episode_id)
                if not trace:
                    self._send_json({"error": "trace not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_bytes((json.dumps(trace, sort_keys=True) + "\n").encode("utf-8"), "application/jsonl")
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.path != "/api/run":
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(length) or b"{}")
            rows = load_ai4i_rows(csv_path)
            scenarios = build_scenarios(rows)
            scenario_id = payload.get("scenario_id") or payload.get("task_id") or "resolve"
            agent_id = payload.get("agent_id") or "improved"
            if scenario_id not in scenarios:
                self._send_json({"error": f"unknown scenario {scenario_id}"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                agent = agent_for_id(agent_id)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            trace = VanceEnvironment(scenarios).run_episode(agent, scenario_id)
            path = OUTPUT_DIR / f"run_{trace.episode_id}.jsonl"
            write_jsonl(path, [trace])
            self._send_json(trace_to_dict(trace))

        def log_message(self, format: str, *args) -> None:
            return

        def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_bytes(json.dumps(payload, sort_keys=True).encode("utf-8"), "application/json", status)

        def _send_html(self, html: str) -> None:
            self._send_bytes(html.encode("utf-8"), "text/html")

        def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def _scenarios_payload() -> list[dict[str, object]]:
    tasks = parse_jsonl(OUTPUT_DIR / "p0_tasks.jsonl")
    traces = _all_traces()
    by_task: dict[str, list[dict[str, object]]] = {}
    for trace in traces:
        by_task.setdefault(trace["task_id"], []).append(trace)
    return [
        {
            "task_id": task["task_id"],
            "title": task["title"],
            "difficulty": task["difficulty"],
            "demo_tags": task["demo_tags"],
            "traces": [
                {
                    "episode_id": trace["episode_id"],
                    "agent_id": trace["agent_id"],
                    "success": trace["verifier_result"]["success"],
                    "reward": trace["verifier_result"]["reward"],
                    "hard_fail_reason": trace["verifier_result"]["hard_fail_reason"],
                }
                for trace in by_task.get(task["task_id"], [])
            ],
        }
        for task in tasks
    ]


def _all_traces() -> list[dict[str, object]]:
    traces: list[dict[str, object]] = []
    for path in sorted(OUTPUT_DIR.glob("*.jsonl")):
        if path.name.endswith("tasks.jsonl") or path.name.startswith("taskset"):
            continue
        traces.extend(parse_jsonl(path))
    return traces


def _find_trace(episode_id: str) -> dict[str, object] | None:
    for trace in _all_traces():
        if trace.get("episode_id") == episode_id:
            return trace
    return None


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vance Judge Mode</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; background: #f6f7f9; color: #17202a; }
    header { padding: 20px 28px; background: #111827; color: white; }
    main { display: grid; grid-template-columns: 320px 1fr 320px; gap: 16px; padding: 16px; }
    section { background: white; border: 1px solid #d7dce2; border-radius: 8px; padding: 14px; }
    h1, h2, h3 { margin: 0 0 10px; }
    button, select { width: 100%; padding: 9px; margin-top: 8px; }
    .badge { display: inline-block; padding: 4px 8px; border-radius: 999px; font-weight: 700; }
    .pass { background: #d1fae5; color: #065f46; }
    .fail { background: #fee2e2; color: #991b1b; }
    .step { border-left: 4px solid #9ca3af; padding: 8px 10px; margin: 8px 0; background: #f9fafb; }
    .step.blocked { border-left-color: #dc2626; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f3f4f6; padding: 8px; border-radius: 6px; }
    .metric { display: flex; justify-content: space-between; border-bottom: 1px solid #edf0f3; padding: 6px 0; }
  </style>
</head>
<body>
  <header><h1>Vance Judge Mode</h1><div>Factory incident traces, deterministic verifier, generated metrics.</div></header>
  <main>
    <section>
      <h2>Scenario</h2>
      <select id="scenario"></select>
      <select id="agent"><option value="improved">improved</option><option value="baseline">baseline</option></select>
      <button onclick="runEpisode()">Run selected</button>
      <h3>Comparison</h3>
      <div id="comparison"></div>
    </section>
    <section>
      <h2 id="traceTitle">Trace</h2>
      <div id="result"></div>
      <div id="steps"></div>
    </section>
    <section>
      <h2>Reward</h2>
      <div id="reward"></div>
      <h3>Final report</h3>
      <pre id="report"></pre>
      <h3>Eval summary</h3>
      <div id="metrics"></div>
    </section>
  </main>
<script>
let scenarios = [];
let activeTrace = null;
async function load() {
  scenarios = await (await fetch('/api/scenarios')).json();
  const select = document.getElementById('scenario');
  select.innerHTML = scenarios.map(s => `<option value="${s.task_id}">${s.title}</option>`).join('');
  select.onchange = showScenario;
  await showScenario();
  const summary = await (await fetch('/api/evals/summary')).json();
  document.getElementById('metrics').innerHTML = Object.entries(summary.agents).map(([agent, metrics]) =>
    `<div class="metric"><strong>${agent}</strong><span>${Math.round(metrics.pass_rate * 100)}% pass, avg ${metrics.average_reward}</span></div>`
  ).join('');
}
async function showScenario() {
  const scenario = scenarios.find(s => s.task_id === document.getElementById('scenario').value);
  document.getElementById('comparison').innerHTML = scenario.traces.map(t =>
    `<div class="metric"><span>${t.agent_id}</span><span>${t.success ? 'PASS' : 'FAIL'} ${t.reward}</span></div>`
  ).join('');
  const preferred = scenario.traces.find(t => t.agent_id === 'improved_harness') || scenario.traces[0];
  if (preferred) showTrace(await (await fetch(`/api/traces/${preferred.episode_id}`)).json());
}
async function runEpisode() {
  const trace = await (await fetch('/api/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({task_id: document.getElementById('scenario').value, agent_id: document.getElementById('agent').value})
  })).json();
  showTrace(trace);
}
function showTrace(trace) {
  activeTrace = trace;
  const vr = trace.verifier_result;
  document.getElementById('traceTitle').textContent = `${trace.task_id} · ${trace.agent_id}`;
  document.getElementById('result').innerHTML = `<span class="badge ${vr.success ? 'pass' : 'fail'}">${vr.success ? 'PASS' : 'FAIL'}</span> reward ${vr.reward} ${vr.hard_fail_reason || ''}`;
  document.getElementById('steps').innerHTML = trace.steps.map(s =>
    `<div class="step ${s.blocked ? 'blocked' : ''}"><strong>${s.index}. ${s.tool}</strong><pre>${JSON.stringify(s.observation, null, 2)}</pre></div>`
  ).join('');
  document.getElementById('reward').innerHTML = vr.reward_breakdown.map(r =>
    `<div class="metric"><span>${r.component}</span><span>${r.points}</span></div>`
  ).join('');
  document.getElementById('report').textContent = JSON.stringify(trace.final_report, null, 2);
}
load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
