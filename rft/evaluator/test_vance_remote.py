"""Fireworks Eval Protocol wrapper for Vance remote RFT.

The Vance reward is produced by the deployed remote rollout server. This
evaluator exists so Fireworks can register a normal evaluator resource and then
connect it to the remote rollout processor.
"""

from pathlib import Path
from typing import Any
import os
import asyncio

import aiohttp
from dotenv import load_dotenv
from eval_protocol.models import EvaluateResult, EvaluationRow, Status
from eval_protocol.pytest import evaluation_test
from eval_protocol.pytest.rollout_processor import RolloutProcessor
from eval_protocol.pytest.tracing_utils import build_init_request
from eval_protocol.pytest.types import RolloutProcessorConfig


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)
DATASET = ROOT / "rft" / "vance_rft_prompts.jsonl"
REMOTE_URL = "https://dharunsivakumar002--vance-rft-bridge-fastapi-app.modal.run"
VALIDATION_MODEL = os.environ.get("FIREWORKS_MODEL", "accounts/fireworks/models/qwen3-4b")


class DirectVanceRemoteProcessor(RolloutProcessor):
    def __init__(self, remote_base_url: str) -> None:
        self.remote_base_url = remote_base_url.rstrip("/")
        self.session: aiohttp.ClientSession | None = None

    def _session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0))
        return self.session

    def __call__(self, rows: list[EvaluationRow], config: RolloutProcessorConfig) -> list[asyncio.Task[EvaluationRow]]:
        return [asyncio.create_task(self._process(row, config)) for row in rows]

    async def _process(self, row: EvaluationRow, config: RolloutProcessorConfig) -> EvaluationRow:
        payload = build_init_request(row, config, "https://tracing.fireworks.ai").model_dump()
        async with self._session().post(f"{self.remote_base_url}/init", json=payload, timeout=aiohttp.ClientTimeout(total=600)) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"Vance remote /init failed ({response.status}): {text}")
            vance = await response.json()
        row.rollout_status = Status.rollout_finished()
        if row.execution_metadata.extra:
            row.execution_metadata.extra["vance"] = vance
        else:
            row.execution_metadata.extra = {"vance": vance}
        return row

    async def acleanup(self) -> None:
        if self.session is not None and not self.session.closed:
            await self.session.close()


@evaluation_test(
    input_dataset=[str(DATASET)],
    completion_params=[
        {
            "model": f"fireworks_ai/{VALIDATION_MODEL}",
            "temperature": 0.8,
            "max_tokens": 2048,
        }
    ],
    rollout_processor=DirectVanceRemoteProcessor(remote_base_url=REMOTE_URL),
    passed_threshold=0.0,
    max_dataset_rows=20,
    num_runs=1,
    mode="pointwise",
)
async def test_vance_remote_rollout(row: EvaluationRow) -> EvaluationRow:
    """Use the Vance verifier score emitted by the remote rollout server."""
    extra: dict[str, Any] = row.execution_metadata.extra or {}
    vance = extra.get("vance")
    if not isinstance(vance, dict):
        row.evaluation_result = EvaluateResult(
            score=0.0,
            reason="Vance rollout did not attach reward metadata.",
            is_score_valid=False,
        )
        return row

    reward = float(vance.get("reward", 0.0))
    fail_reasons = vance.get("fail_reasons") or []
    hard_fail_reason = str(vance.get("hard_fail_reason") or "")
    reason = hard_fail_reason or ", ".join(str(item) for item in fail_reasons) or "Vance verifier reward."
    row.evaluation_result = EvaluateResult(
        score=max(0.0, min(1.0, reward)),
        reason=reason,
        trajectory_info={
            "task_id": vance.get("task_id"),
            "passed": vance.get("passed"),
            "hard_fail": vance.get("hard_fail"),
            "trace_path": vance.get("trace_path"),
        },
    )
    return row
