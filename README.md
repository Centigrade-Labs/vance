# Vance / Forge SafeOpsRL

Vance is the non-UI implementation of the Forge PRD: a HUD-compatible RL-style environment and evaluation suite for safe factory incident agents.

This repository contains the backend/runtime pieces only. It intentionally excludes dashboard UI, synthetic task records, manuals, expected outcomes, fallback traces, screenshots, and demo video assets.

## What Is Implemented

- Deterministic environment runtime
- Task schema loading and validation
- Schema-constrained operational tools
- Trace-level verifier
- Reward calculation
- JSONL trace persistence
- Baseline and improved fallback agent harnesses
- Live Fireworks agent integration
- Eval runner
- API service for scenarios, runs, traces, eval summaries, exports, and HUD reset/step
- HUD reset/step adapter
- Dockerfile
- CI and tests

No pass rates, traces, or scenarios are faked.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

## Empty Taskset Behavior

The repository intentionally ships with empty task files:

- `tasks/easy.jsonl`
- `tasks/medium.jsonl`
- `tasks/hard.jsonl`

With no tasks loaded:

```bash
python -m vance.runner --list
python evals/run_eval.py --agent improved_slm --mode fallback
```

The first command returns `[]`. The second writes generated zero-episode metrics. This is intentional and honest until task data is added.

## Running Episodes

After task records are added:

```bash
python -m vance.runner --task cnc_spindle_001 --agent improved_slm --mode fallback
```

Live mode is only valid with the Fireworks agent:

```bash
python -m vance.runner --task cnc_spindle_001 --agent fireworks_agent --mode live
```

The runtime rejects `--mode live` with deterministic fallback agents so live results cannot be mislabeled.

## Eval

```bash
python evals/run_eval.py --agent baseline_slm --mode fallback
python evals/run_eval.py --agent improved_slm --mode fallback
```

Generated eval files are ignored by git:

- `evals/results_baseline.json`
- `evals/results_improved.json`

## API Service

Start the backend API:

```bash
python app/main.py
```

OpenAPI docs are available at:

```text
http://127.0.0.1:8000/docs
```

Routes:

- `GET /`
- `GET /health`
- `GET /api/scenarios`
- `POST /api/run`
- `GET /api/traces/{episode_id}`
- `GET /api/evals/summary`
- `GET /api/export/{episode_id}.jsonl`
- `POST /api/hud/reset`
- `POST /api/hud/step`

## Environment Variables

Required for local API defaults:

- `VANCE_HOST`
- `VANCE_PORT`
- `VANCE_TASK_DIR`
- `VANCE_TRACE_DIR`

Required only for live Fireworks inference:

- `FIREWORKS_API_KEY`
- `FIREWORKS_MODEL`
- `FIREWORKS_BASE_URL`

Fallback mode does not require API keys.

## Project Layout

```text
vance/
  env.py
  state.py
  tools.py
  verifier.py
  reward.py
  runner.py
  trace.py
  hud.py
tasks/
  easy.jsonl
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
  service.py
```

## Verification

```bash
python -m unittest discover -s tests
python -m vance.runner --list
python evals/run_eval.py --agent improved_slm --mode fallback
python -m compileall vance agents app evals tests
```
