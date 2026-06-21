# Vance MVP Prototype

This isolated prototype proves the first Vance loop:

```text
AI4I CSV row -> factory task -> deterministic harness actions -> verifier -> pass/fail -> JSONL trace
```

It is intentionally standalone and uses only the Python standard library. It does not modify the existing application, package metadata, lockfiles, deployment files, or environment files.

## Data

`data/ai4i2020.csv` is synthetic predictive-maintenance data. The prototype selects one failure row, preferring `TWF`, then `HDF`, `OSF`, `PWF`, and finally any `Machine failure` row.

Public agent observations use only:

- `Type`
- `Air temperature [K]`
- `Process temperature [K]`
- `Rotational speed [rpm]`
- `Torque [Nm]`
- `Tool wear [min]`

These label columns are hidden verifier data and are never included in the agent's initial observation:

- `Machine failure`
- `TWF`
- `HDF`
- `PWF`
- `OSF`
- `RNF`

The machine ID, manual entry, required part, inventory, production order, safety rule, deadline, and expected outcome are synthetic scenario context added by this prototype.

## Scenarios

The demo runs five P0 scenarios:

- `resolve`: CNC spindle/tool-wear warning.
- `heat_dissipation_resolve`: heat dissipation failure with available cooling parts.
- `power_load_resolve`: power/load anomaly with available drive service kit.
- `overstrain_escalation`: overstrain issue where the required cutter is unavailable.
- `random_anomaly_escalation`: ambiguous anomaly that requires human review.

`baseline_harness` and `improved_harness` are deterministic harnesses, not LLMs. Live Qwen, HUD, and hosted dashboard integration come later.

## Run

From the repository root:

```bash
python3 prototypes/vance_mvp/run_demo.py --csv data/ai4i2020.csv
```

Run a single combination:

```bash
python3 prototypes/vance_mvp/run_demo.py --csv data/ai4i2020.csv --scenario resolve --agent improved
```

Traces are saved inside this isolated directory:

- `prototypes/vance_mvp/output/baseline.jsonl`
- `prototypes/vance_mvp/output/improved.jsonl`
- `prototypes/vance_mvp/output/eval_summary.json`
- `prototypes/vance_mvp/output/p0_tasks.jsonl`
- `prototypes/vance_mvp/output/taskset_20.jsonl`

## Dashboard

From the repository root:

```bash
python3 prototypes/vance_mvp/run_dashboard.py --csv data/ai4i2020.csv --port 8765
```

Open `http://127.0.0.1:8765`. The dashboard exposes:

- `GET /`
- `GET /api/scenarios`
- `POST /api/run`
- `GET /api/traces/{episode_id}`
- `GET /api/evals/summary`
- `GET /api/export/{episode_id}.jsonl`

## Test

From the repository root:

```bash
python3 -m unittest prototypes.vance_mvp.tests.test_vance_mvp
```
