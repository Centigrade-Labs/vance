# Vance Fireworks Fine-Tuning

This directory contains supervised fine-tuning data for the Vance tool-use loop.

The dataset is generated from the deterministic oracle policy over the 20-task
Vance taskset. It targets the current failure mode from HUD evals: correct tool
sequence, but brittle incident-report evidence formatting.

## Build Dataset

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python finetuning/build_fireworks_sft.py
```

Outputs:

```text
finetuning/fireworks_vance_sft.jsonl
finetuning/fireworks_vance_sft_report.json
```

## Fireworks SFT

Fireworks accepts OpenAI-compatible chat JSONL for SFT, including function
calling examples.

Use the Fireworks UI or `firectl`. If using `firectl`:

```bash
firectl dataset create vance-safeopsrl-sft-v1 finetuning/fireworks_vance_sft.jsonl

firectl sftj create \
  --base-model accounts/fireworks/models/qwen2p5-7b-instruct \
  --dataset vance-safeopsrl-sft-v1 \
  --output-model vance-qwen25-7b-safeops-sft-v1

firectl sftj get vance-safeopsrl-sft-v1
firectl model list
```

After the job completes, deploy the fine-tuned model:

```bash
firectl deployment create vance-qwen25-7b-safeops-sft-v1
```

Set `.env` to the returned deployment path:

```bash
FIREWORKS_MODEL=accounts/<account>/deployments/<fine-tuned-deployment>
```

Then rerun the same eval:

```bash
set -a
source .env
set +a

OPENAI_API_KEY="$FIREWORKS_API_KEY" PYTHONDONTWRITEBYTECODE=1 .venv/bin/hud eval hud_env.py openai_compatible \
  --model "$FIREWORKS_MODEL" \
  --config openai_compatible.base_url="$FIREWORKS_BASE_URL" \
  --max-steps 8 \
  --all \
  -y
```

Baseline before SFT: 20 runs, 70% success, mean reward around 0.70.
