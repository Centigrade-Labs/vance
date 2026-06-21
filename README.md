# Vance / Forge SafeOpsRL

Vance is the implementation scaffold for the Forge PRD: a HUD-compatible RL-style environment and evaluation suite for safe factory incident agents.

This repo now contains the full non-data implementation surface: environment runtime, tools, verifier, rewards, agent harnesses, eval runner, HUD adapter, dashboard, docs, and CI. It intentionally contains no synthetic task records or demo traces. Teammate 2 owns filling `tasks/*.jsonl` and `demo/sample_traces/` according to `prd.md`.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

List scenarios:

```bash
python -m vance.runner --list
```

Run one episode after tasks are added:

```bash
python -m vance.runner --task cnc_spindle_001 --agent improved_slm --mode fallback
```

Run evals after tasks are added:

```bash
python evals/run_eval.py --agent baseline_slm --mode fallback
python evals/run_eval.py --agent improved_slm --mode fallback
```

Start Judge Mode:

```bash
python app/main.py
```

Open `http://127.0.0.1:8000`.

## Empty Taskset Behavior

The repository intentionally ships with empty task files:

- `tasks/easy.jsonl`
- `tasks/medium.jsonl`
- `tasks/hard.jsonl`

With no tasks loaded:

- `python -m vance.runner --list` returns an empty list.
- `python evals/run_eval.py --agent improved_slm` writes generated zero-episode metrics.
- The dashboard loads and shows that task data is pending.

No pass rates, traces, or scenarios are faked.

## Required Environment Variables

Fallback mode does not require API keys.

Live Fireworks inference requires:

- `FIREWORKS_API_KEY`
- `FIREWORKS_MODEL`
- `FIREWORKS_BASE_URL`

HUD setup uses:

- `HUD_API_KEY`
- `HUD_ENV_ID`
- `HUD_PROJECT`

Optional sponsor integrations:

- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`
- `DAYTONA_API_KEY`
- `EXA_API_KEY`
- `MINIMAX_API_KEY`

## Project Layout

```text
vance/
  env.py          # deterministic environment loop
  state.py        # task loading and validation
  tools.py        # schema-constrained operational tools
  verifier.py     # trace-level deterministic verifier
  reward.py       # reward components and penalties
  runner.py       # single-episode CLI
  trace.py        # JSON/JSONL trace persistence
  hud.py          # reset/step adapter for HUD-style runners
tasks/
  easy.jsonl      # intentionally empty until synthetic data owner fills it
  medium.jsonl
  hard.jsonl
agents/
  baseline_slm.py
  improved_slm.py
  fireworks_agent.py
evals/
  run_eval.py
app/
  main.py
  dashboard.py
  templates/
  static/
```

## Ownership

- Sri: environment, verifier, reward, repo contracts.
- Teammate 1: HUD setup and environment adapter validation.
- Teammate 2: synthetic tasks, manuals, expected outcomes, fallback traces.
- Teammate 3: agent harness, eval runner, metrics.
- Teammate 4: dashboard, UI polish, demo video, README support.

## Verification

```bash
python -m unittest
python -m vance.runner --list
python evals/run_eval.py --agent improved_slm --mode fallback
python -m compileall vance agents app evals
```
