# Forge

Forge is a scaffold for a HUD-compatible RL-style environment and evaluation suite for safe factory incident agents.

This repository is intentionally scaffold-only right now. The PRD defines the implementation contract; teammates should fill the empty files according to the phase ownership in `prd.md`.

## Current Status

- PRD: enriched and build-phased.
- Project folders: scaffolded.
- Python implementation: empty placeholders.
- Synthetic task data: intentionally empty.
- Dashboard: empty placeholders.
- Env templates: present.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Fallback mode should eventually run without API keys. Live integrations require filling `.env`.

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

## Scaffold Layout

```text
forge/
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
