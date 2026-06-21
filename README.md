# Vance

Vance is a scaffold for a HUD-compatible RL-style environment and evaluation suite for safe factory incident agents.

This repository now contains a runnable MVP for the PRD's core loop: factory task -> tool trace -> deterministic verifier -> reward -> dashboard/eval output. Fallback mode works without API keys; live Qwen/Fireworks, HUD, and Modal are additive paths.

## Current Status

- 20 AI4I-seeded task records across `tasks/easy.jsonl`, `tasks/medium.jsonl`, and `tasks/hard.jsonl`.
- Deterministic Vance environment, tools, verifier, reward, trace export, and eval runner.
- Baseline and improved fallback harnesses.
- Live Fireworks/Qwen wrapper that clearly reports unavailable credentials/packages.
- Judge Mode dashboard with fallback data and JSONL export.
- HUD v6 and Modal adapter entrypoints.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Fallback mode runs without API keys:

```bash
python -m vance.runner --task resolve --agent improved_slm --mode fallback
python evals/run_eval.py --agent improved_slm --tasks tasks/easy.jsonl --mode fallback
python app/main.py --mode fallback --port 8765
```

Then open `http://127.0.0.1:8765`.

Live integrations require filling `.env`.

## Environment Variables

Required later for live Fireworks model calls:

- `FIREWORKS_API_KEY`
- `FIREWORKS_MODEL`

Required later for HUD setup:

- `HUD_API_KEY`
- `HUD_ENV_ID`
- `HUD_PROJECT`

Optional later integrations:

- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`
- `DAYTONA_API_KEY`
- `EXA_API_KEY`
- `MINIMAX_API_KEY`

## Live / Platform Commands

```bash
FIREWORKS_API_KEY=... FIREWORKS_MODEL=... python evals/run_eval.py --agent fireworks_agent --tasks tasks/easy.jsonl --mode live
hud eval hud_env.py <model> --max-steps 8
modal serve modal_app.py
modal deploy modal_app.py
```

## Scaffold Layout

```text
vance/
  env.py
  state.py
  tools.py
  verifier.py
  reward.py
  runner.py
  trace.py
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
  dashboard.py
  templates/
  static/
demo/
  script.md
  sample_traces/
  screenshots/
docs/
  architecture.md
  reward_design.md
```

## Ownership

- Sri: environment, verifier, reward, repo contracts.
- Teammate 1: HUD setup and environment adapter.
- Teammate 2: synthetic tasks, manuals, expected outcomes, fallback traces.
- Teammate 3: agent harness, eval runner, metrics.
- Teammate 4: dashboard, UI polish, demo video, README support.
