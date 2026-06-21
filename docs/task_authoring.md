# Task Authoring

Synthetic task data is included and can be regenerated from `data/ai4i2020.csv`.

Generated records live in:

- `tasks/easy.jsonl`
- `tasks/medium.jsonl`
- `tasks/hard.jsonl`

Each line is one `vance.task.v1` JSON object matching `prd.md` section 32.5.

Regenerate task records with:

```bash
python -m vance.runner --generate-tasks --task resolve --agent improved_slm --mode fallback
```

Do not add hand-authored eval metrics. Run:

```bash
python evals/run_eval.py --agent baseline_slm --tasks tasks/easy.jsonl --mode fallback
python evals/run_eval.py --agent improved_slm --tasks tasks/easy.jsonl --mode fallback
```

