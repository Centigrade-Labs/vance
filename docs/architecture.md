# Architecture

Vance implements the PRD as a deterministic, trace-verifiable environment.

```text
Dashboard / API / HUD / CLI
  -> Episode Runner
  -> Vance Environment
  -> Agent Harness
  -> Tool Registry
  -> State Simulator
  -> Verifier + Reward
  -> Trace Store + Eval Summary
```

## Runtime Boundaries

- `vance.scenarios` generates AI4I-seeded `vance.task.v1` records.
- `vance.env` owns reset, step, episode closure, and trace construction.
- `vance.tools` owns registered tool execution and state mutation.
- `vance.verifier` inspects the full trace and final state.
- `vance.reward` exposes reward weights.
- `vance.trace` persists JSON and JSONL artifacts.
- `hud_env.py` and `vance.hud` expose HUD-facing adapter paths.

## Data Boundary

Task records are generated from `data/ai4i2020.csv` plus synthetic operational context. Hidden AI4I labels remain verifier-only and do not appear in public observations.

## Dashboard And API Boundary

The dashboard serves Judge Mode and JSON runtime routes:

- `GET /`
- `GET /api/scenarios`
- `POST /api/run`
- `GET /api/traces/{episode_id}`
- `GET /api/evals/summary`
- `GET /api/export/{episode_id}.jsonl`

The app uses FastAPI/Uvicorn when installed and a standard-library fallback server otherwise.

