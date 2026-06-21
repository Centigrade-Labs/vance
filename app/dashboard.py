"""Dashboard data adapters for Vance Judge Mode."""

from __future__ import annotations

import json
from pathlib import Path

from agents import build_agent
from agents.fireworks_agent import LiveAgentUnavailable
from evals.run_eval import eval_result
from vance.data_loader import load_ai4i_rows
from vance.env import VanceEnvironment
from vance.runner import DATA_PATH, EVAL_DIR, generate_task_files
from vance.scenarios import P0_SCENARIO_IDS, build_twenty_scenarios
from vance.trace import parse_jsonl, trace_to_dict, write_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]


def ensure_app_data(csv_path: str | Path = DATA_PATH) -> None:
    generate_task_files(csv_path)
    _ensure_agent_eval("baseline_slm", csv_path)
    _ensure_agent_eval("improved_slm", csv_path)


def scenarios_payload() -> list[dict[str, object]]:
    tasks = []
    for path in (REPO_ROOT / "tasks").glob("*.jsonl"):
        tasks.extend(parse_jsonl(path))
    traces = all_traces()
    by_task: dict[str, list[dict[str, object]]] = {}
    for trace in traces:
        by_task.setdefault(str(trace["task_id"]), []).append(trace)
    return [
        {
            "task_id": task["task_id"],
            "title": task["title"],
            "difficulty": task["difficulty"],
            "demo_tags": task["demo_tags"],
            "default_demo": task["task_id"] in P0_SCENARIO_IDS,
            "traces": [
                {
                    "episode_id": trace["episode_id"],
                    "agent_id": trace["agent_id"],
                    "mode": trace["mode"],
                    "success": trace["verifier_result"]["success"],
                    "reward": trace["verifier_result"]["reward"],
                    "hard_fail_reason": trace["verifier_result"]["hard_fail_reason"],
                }
                for trace in by_task.get(str(task["task_id"]), [])
            ],
        }
        for task in sorted(tasks, key=lambda item: (item["difficulty"], item["task_id"]))
    ]


def eval_summary_payload() -> dict[str, object]:
    results = {}
    for name, path in {
        "baseline": EVAL_DIR / "results_baseline.json",
        "improved": EVAL_DIR / "results_improved.json",
        "live_qwen": EVAL_DIR / "results_live_qwen.json",
    }.items():
        if path.exists():
            results[name] = json.loads(path.read_text(encoding="utf-8"))
    return {"schema_version": "vance.eval.summary.v1", "results": results}


def all_traces() -> list[dict[str, object]]:
    traces: list[dict[str, object]] = []
    trace_root = EVAL_DIR / "traces"
    if not trace_root.exists():
        return traces
    for path in sorted(trace_root.rglob("*.jsonl")):
        traces.extend(parse_jsonl(path))
    return traces


def find_trace(episode_id: str) -> dict[str, object] | None:
    for trace in all_traces():
        if trace.get("episode_id") == episode_id:
            return trace
    return None


def run_episode_payload(payload: dict[str, object], csv_path: str | Path = DATA_PATH) -> tuple[int, dict[str, object]]:
    mode = str(payload.get("mode") or "fallback")
    agent_id = str(payload.get("agent_id") or "improved_slm")
    task_id = str(payload.get("task_id") or payload.get("scenario_id") or "resolve")
    scenarios = build_twenty_scenarios(load_ai4i_rows(csv_path))
    if task_id not in scenarios:
        return 400, {"error": f"unknown task {task_id}"}
    try:
        agent = build_agent(agent_id, mode=mode)
    except (LiveAgentUnavailable, ValueError) as exc:
        return 503, {"error": str(exc), "live_unavailable": mode == "live"}
    trace = VanceEnvironment(scenarios).run_episode(agent, task_id, mode=mode)
    trace_dir = EVAL_DIR / "traces" / mode / agent_id
    trace_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(trace_dir / f"run_{trace.episode_id}.jsonl", [trace])
    return 200, trace_to_dict(trace)


def index_html() -> str:
    return _INDEX_HTML


def _ensure_agent_eval(agent_id: str, csv_path: str | Path) -> None:
    result_path = EVAL_DIR / ("results_baseline.json" if agent_id == "baseline_slm" else "results_improved.json")
    tasks = parse_jsonl(REPO_ROOT / "tasks" / "easy.jsonl") + parse_jsonl(REPO_ROOT / "tasks" / "medium.jsonl") + parse_jsonl(REPO_ROOT / "tasks" / "hard.jsonl")
    if result_path.exists():
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        if existing.get("metrics", {}).get("episodes") == len(tasks):
            return
    scenarios = build_twenty_scenarios(load_ai4i_rows(csv_path))
    agent = build_agent(agent_id, mode="fallback")
    traces = [VanceEnvironment(scenarios).run_episode(agent, str(task["task_id"]), mode="fallback") for task in tasks]
    trace_dir = EVAL_DIR / "traces" / "fallback" / agent_id
    trace_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(trace_dir / "traces.jsonl", traces)
    result = eval_result(agent_id, "fallback", [trace_to_dict(trace) for trace in traces], [str(trace_dir / "traces.jsonl")])
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vance Judge Mode</title>
  <style>
    :root { color-scheme: light; --ink:#17202a; --muted:#667085; --line:#d7dce2; --bg:#f5f7fa; --panel:#fff; --brand:#0f766e; --danger:#b42318; }
    body { margin:0; font-family: Inter, Arial, sans-serif; background:var(--bg); color:var(--ink); }
    header { min-height:92px; padding:22px 28px; background:#111827; color:white; display:flex; justify-content:space-between; align-items:end; }
    h1,h2,h3 { margin:0; letter-spacing:0; } h1 { font-size:30px; } h2 { font-size:18px; margin-bottom:10px; } h3 { font-size:14px; margin:16px 0 8px; color:var(--muted); }
    main { display:grid; grid-template-columns:300px minmax(420px,1fr) 330px; gap:14px; padding:14px; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; min-width:0; }
    select,button { width:100%; box-sizing:border-box; padding:9px; margin-top:8px; border:1px solid var(--line); border-radius:6px; background:white; }
    button { background:var(--brand); color:white; border-color:var(--brand); font-weight:700; cursor:pointer; }
    .badge { display:inline-block; padding:5px 9px; border-radius:999px; font-weight:800; font-size:12px; }
    .pass { background:#d1fae5; color:#065f46; } .fail { background:#fee2e2; color:#991b1b; } .mode { background:#eef2ff; color:#3730a3; }
    .metric { display:flex; justify-content:space-between; gap:10px; border-bottom:1px solid #edf0f3; padding:7px 0; font-size:14px; }
    .step { border-left:4px solid #9ca3af; padding:9px 10px; margin:8px 0; background:#f9fafb; border-radius:0 6px 6px 0; }
    .step.blocked { border-left-color:var(--danger); background:#fff7f7; }
    pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#f3f4f6; padding:8px; border-radius:6px; font-size:12px; }
    @media (max-width: 980px) { main { grid-template-columns:1fr; } header { display:block; } }
  </style>
</head>
<body>
  <header><div><h1>Vance</h1><div>SafeOpsRL for factory incidents</div></div><div><span class="badge mode" id="modeBadge">Fallback</span></div></header>
  <main>
    <section><h2>Scenario</h2><select id="scenario"></select><select id="agent"><option value="improved_slm">Improved fallback</option><option value="baseline_slm">Baseline fallback</option><option value="fireworks_agent">Live Qwen / Fireworks</option></select><select id="mode"><option value="fallback">Fallback</option><option value="live">Live</option></select><button onclick="runEpisode()">Run</button><h3>Comparison</h3><div id="comparison"></div></section>
    <section><h2 id="traceTitle">Trace</h2><div id="result"></div><div id="factory"></div><div id="steps"></div></section>
    <section><h2>Reward</h2><div id="reward"></div><h3>Final report</h3><pre id="report"></pre><h3>Eval summary</h3><div id="metrics"></div></section>
  </main>
<script>
let scenarios = [];
async function load() {
  scenarios = await (await fetch('/api/scenarios')).json();
  const defaults = scenarios.filter(s => s.default_demo);
  document.getElementById('scenario').innerHTML = (defaults.length ? defaults : scenarios).map(s => `<option value="${s.task_id}">${s.title}</option>`).join('');
  document.getElementById('scenario').onchange = showScenario;
  await showScenario();
  const summary = await (await fetch('/api/evals/summary')).json();
  document.getElementById('metrics').innerHTML = Object.entries(summary.results).map(([name, result]) => {
    const m = result.metrics || {};
    return `<div class="metric"><strong>${name}</strong><span>${Math.round((m.pass_rate || 0) * 100)}% pass · avg ${m.average_reward || 0}</span></div>`;
  }).join('');
}
async function showScenario() {
  const taskId = document.getElementById('scenario').value;
  const scenario = scenarios.find(s => s.task_id === taskId);
  document.getElementById('comparison').innerHTML = scenario.traces.map(t => `<div class="metric"><span>${t.agent_id}</span><span>${t.success ? 'PASS' : 'FAIL'} ${t.reward}</span></div>`).join('');
  const preferred = scenario.traces.find(t => t.agent_id === 'improved_harness') || scenario.traces[0];
  if (preferred) showTrace(await (await fetch(`/api/traces/${preferred.episode_id}`)).json());
}
async function runEpisode() {
  const mode = document.getElementById('mode').value;
  document.getElementById('modeBadge').textContent = mode === 'live' ? 'Live' : 'Fallback';
  const response = await fetch('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({task_id:document.getElementById('scenario').value, agent_id:document.getElementById('agent').value, mode})});
  const payload = await response.json();
  if (!response.ok) { document.getElementById('result').innerHTML = `<span class="badge fail">UNAVAILABLE</span> ${payload.error}`; return; }
  showTrace(payload);
}
function showTrace(trace) {
  const vr = trace.verifier_result;
  document.getElementById('traceTitle').textContent = `${trace.task_id} · ${trace.agent_id}`;
  document.getElementById('result').innerHTML = `<span class="badge ${vr.success ? 'pass' : 'fail'}">${vr.success ? 'PASS' : 'FAIL'}</span> <span class="badge mode">${trace.mode}</span> reward ${vr.reward} ${vr.hard_fail_reason || ''}`;
  document.getElementById('factory').innerHTML = `<pre>${JSON.stringify(trace.public_initial_observation.machine, null, 2)}</pre>`;
  document.getElementById('steps').innerHTML = trace.steps.map(s => `<div class="step ${s.blocked ? 'blocked' : ''}"><strong>${s.index}. ${s.tool}</strong><pre>${JSON.stringify(s.observation, null, 2)}</pre></div>`).join('');
  document.getElementById('reward').innerHTML = vr.reward_breakdown.map(r => `<div class="metric"><span>${r.component}</span><span>${r.points}</span></div>`).join('');
  document.getElementById('report').textContent = JSON.stringify(trace.final_report, null, 2);
}
load();
</script>
</body>
</html>"""
