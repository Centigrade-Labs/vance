# Task Authoring

Synthetic task data is intentionally not included in this repo.

Teammate 2 should add records to:

- `tasks/easy.jsonl`
- `tasks/medium.jsonl`
- `tasks/hard.jsonl`

Each line must be one `vance.task.v1` JSON object matching `prd.md` section 32.5.

Validation is automatic when tasks are loaded:

```bash
python -m vance.runner --list
```

Do not add hand-authored eval metrics. Run:

```bash
python evals/run_eval.py --agent baseline_slm --mode fallback
python evals/run_eval.py --agent improved_slm --mode fallback
```
