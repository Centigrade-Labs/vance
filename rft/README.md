# Vance Fireworks RFT Bridge

This directory contains the remote rollout bridge for Fireworks Reinforcement
Fine Tuning. It exposes `POST /init`, runs a Vance task with the model
configuration Fireworks sends, scores the trace with the Vance verifier, and
logs rollout completion when `eval-protocol` is installed.

## Baseline

The current base Qwen3 4B HUD eval result is:

```text
Model: accounts/dharunsivakumar/deployments/kyvagfny
Runs: 20
Mean reward: 0.500 +/- 0.500
Success rate: 50.0%
HUD job: https://hud.ai/jobs/27e66f888ff94f4aa900c738a4ddeefa
```

## Build Prompt Dataset

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m rft.build_rft_dataset
```

This writes:

```text
rft/vance_rft_prompts.jsonl
```

Upload/register this dataset for Fireworks RFT. The dataset contains public task
prompts only; hidden AI4I labels stay in the verifier-side scenario objects.

## Run The Remote Server Locally

```bash
set -a
source .env
set +a

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m rft.remote_server
```

Health check:

```bash
curl http://localhost:8080/health
```

Local rollout smoke:

```bash
curl -s http://localhost:8080/init \
  -H 'content-type: application/json' \
  -d '{
    "completion_params": {"model": "accounts/fireworks/models/qwen3-4b", "temperature": 0, "max_tokens": 2048},
    "messages": [{"role": "user", "content": "{\"task_id\":\"resolve\"}"}],
    "metadata": {"rollout_id": "local-smoke", "task_id": "resolve"}
  }'
```

## Deploy On Modal

```bash
modal serve modal_rft.py
```

Then deploy:

```bash
modal deploy modal_rft.py
```

Use the public Modal base URL as the Fireworks RFT remote environment URL.
Fireworks calls `POST /init` on that service. If the UI explicitly asks for the
full init endpoint, use `https://<your-modal-url>/init`; otherwise use the base
service URL.

## Fireworks RFT

Use:

```text
Base model: accounts/fireworks/models/qwen3-4b
Remote environment URL: https://<your-modal-url>
Dataset: rft/vance_rft_prompts.jsonl
```

After the RFT job finishes, deploy the tuned model and run the same HUD eval:

```bash
OPENAI_API_KEY="$FIREWORKS_API_KEY" PYTHONDONTWRITEBYTECODE=1 .venv/bin/hud eval hud_env.py openai_compatible \
  --model "<rft-model-or-deployment>" \
  --config openai_compatible.base_url="$FIREWORKS_BASE_URL" \
  --max-steps 8 \
  --all \
  -y
```
