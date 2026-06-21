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

- `vance.state` loads and validates task JSONL.
- `vance.env` owns reset, step, episode closure, and trace construction.
- `vance.tools` owns registered tool execution and state mutation.
- `vance.verifier` inspects the full trace and final state.
- `vance.reward` defines reward components and penalties.
- `vance.trace` persists JSON and JSONL artifacts.
- `vance.hud` exposes reset/step session semantics for HUD integration.

## Data Boundary

Task records and fallback traces are intentionally absent from this repo until the synthetic data owner fills them. The implementation treats an empty taskset as valid pending state.

## Dashboard And API Boundary

The FastAPI app serves a dashboard shell and JSON runtime routes:

- `GET /`
- `GET /evals`
- `GET /about`
- `GET /health`
- `GET /api/scenarios`
- `POST /api/run`
- `GET /api/traces/{episode_id}`
- `GET /api/evals/summary`
- `GET /api/export/{episode_id}.jsonl`
- `POST /api/hud/reset`
- `POST /api/hud/step`

Screenshots, demo video, task data, and fallback trace data are outside this implementation pass.
