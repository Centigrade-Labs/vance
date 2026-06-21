# Demo Script

Use this with the fallback dashboard or hosted app.

Current repo state:

- Dashboard opens directly into Judge Mode.
- Eval runner generates metrics from real `tasks/*.jsonl` task records.
- 20 AI4I-seeded task records are included.
- Fallback traces are generated locally from deterministic harnesses.

Suggested flow:

1. Open the dashboard.
2. Show baseline failing on unsafe restart.
3. Show improved fallback resolving safely.
4. Show escalation when the required part is unavailable.
5. Export a JSONL trace and explain the trace-to-training-data path.

