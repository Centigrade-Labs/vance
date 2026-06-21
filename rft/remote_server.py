"""Remote rollout server for Fireworks RFT.

Fireworks RFT calls POST /init with a rollout request. This server runs the
Vance factory-recovery episode against the policy model in that request, scores
it with the normal Vance verifier, and logs rollout completion for Fireworks
tracing when eval-protocol is installed.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agents.fireworks_agent import FireworksAgent, LiveAgentUnavailable
from vance.data_loader import load_ai4i_rows
from vance.env import MAX_STEPS, VanceEnvironment
from vance.runner import DATA_PATH, REPO_ROOT
from vance.scenarios import build_100_scenarios, build_twenty_scenarios, public_initial_observation
from vance.trace import trace_to_dict, write_jsonl


try:  # Optional locally, required for production RFT tracing.
    from eval_protocol import FireworksTracingHttpHandler, RolloutIdFilter, Status
except Exception:  # pragma: no cover - depends on optional Fireworks package.
    FireworksTracingHttpHandler = None
    RolloutIdFilter = None
    Status = None


DEFAULT_BASE_MODEL = "accounts/fireworks/models/qwen3-4b"
DEFAULT_TRACE_DIR = REPO_ROOT / "evals" / "traces" / "rft" / "fireworks_agent"

LOGGER = logging.getLogger("vance.rft")
_TRACING_HANDLER_ATTACHED = False


class InitRequest(BaseModel):
    completion_params: dict[str, Any] = Field(default_factory=dict)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] | None = None
    model_base_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    api_key: str | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Vance Fireworks RFT Bridge")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "vance-rft-bridge",
            "tasks": len(_scenarios()),
            "max_steps": MAX_STEPS,
        }

    @app.get("/tasks")
    def tasks() -> list[dict[str, Any]]:
        return [
            {
                "task_id": scenario.scenario_id,
                "title": scenario.title,
                "difficulty": scenario.difficulty,
                "expected_outcome": scenario.expected_outcome.value,
                "initial_observation": public_initial_observation(scenario),
            }
            for scenario in _scenarios().values()
        ]

    @app.post("/init")
    def init(request: InitRequest) -> dict[str, Any]:
        rollout_id = _rollout_id(request)
        logger = _rollout_logger(rollout_id)
        try:
            task_id = _extract_task_id(request)
            scenarios = _scenarios()
            if task_id not in scenarios:
                raise HTTPException(status_code=400, detail=f"unknown Vance task_id: {task_id}")

            model = _resolve_model(request)
            base_url = _resolve_base_url(request, model)
            api_key = request.api_key or os.environ.get("FIREWORKS_API_KEY")
            if not api_key:
                raise HTTPException(status_code=400, detail="missing Fireworks api_key in request and FIREWORKS_API_KEY env")

            agent = FireworksAgent(api_key=api_key, model=model, base_url=base_url)
            trace = VanceEnvironment(scenarios).run_episode(agent, task_id, mode="rft")
            trace_path = _write_trace(trace, rollout_id)
            result = trace.verifier_result

            response = {
                "status": "success",
                "task_id": task_id,
                "rollout_id": rollout_id,
                "model": model,
                "reward": result.reward,
                "passed": result.passed,
                "hard_fail": result.hard_fail,
                "hard_fail_reason": result.hard_fail_reason,
                "fail_reasons": result.fail_reasons,
                "trace_path": str(trace_path),
                "trace": trace_to_dict(trace),
            }
            _log_finished(logger, response)
            return response
        except HTTPException as exc:
            _log_error(logger, str(exc.detail))
            raise
        except LiveAgentUnavailable as exc:
            _log_error(logger, str(exc))
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            _log_error(logger, str(exc))
            raise

    return app


app = create_app()


@lru_cache(maxsize=1)
def _scenarios():
    rows = load_ai4i_rows(_data_path())
    scenarios = build_twenty_scenarios(rows)
    scenarios.update(build_100_scenarios(rows))
    return scenarios


def _data_path() -> Path:
    configured = os.environ.get("VANCE_AI4I_CSV")
    if configured:
        return Path(configured)
    local = Path(DATA_PATH)
    if local.exists():
        return local
    container = Path("/app/data/ai4i2020.csv")
    if container.exists():
        return container
    return local


def _extract_task_id(request: InitRequest) -> str:
    for key in ("task_id", "scenario_id", "row_id"):
        value = request.metadata.get(key)
        if isinstance(value, str) and value in _scenarios():
            return value

    for message in request.messages:
        content = message.get("content")
        payload = _jsonish(content)
        if isinstance(payload, dict):
            for key in ("task_id", "scenario_id"):
                value = payload.get(key)
                if isinstance(value, str) and value in _scenarios():
                    return value
            nested = payload.get("metadata")
            if isinstance(nested, dict):
                value = nested.get("task_id")
                if isinstance(value, str) and value in _scenarios():
                    return value
    return "resolve"


def _resolve_model(request: InitRequest) -> str:
    requested = str(request.completion_params.get("model") or "").strip()
    if requested.startswith("fireworks_ai/"):
        requested = requested.removeprefix("fireworks_ai/")
    configured = os.environ.get("FIREWORKS_MODEL", "").strip()
    if configured and _is_base_or_missing_model(requested):
        return configured
    return requested or configured or DEFAULT_BASE_MODEL


def _resolve_base_url(request: InitRequest, model: str) -> str:
    configured = os.environ.get("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
    requested = (request.model_base_url or "").strip()
    if model.startswith("accounts/"):
        return configured
    return requested or configured


def _is_base_or_missing_model(model: str) -> bool:
    return not model or model == DEFAULT_BASE_MODEL or model.startswith("accounts/fireworks/models/")


def _jsonish(content: Any) -> Any:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        texts = [item.get("text", "") for item in content if isinstance(item, dict)]
        content = "\n".join(texts)
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _rollout_id(request: InitRequest) -> str:
    for key in ("rollout_id", "run_id", "row_id"):
        value = request.metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return "local-rollout"


def _trace_dir() -> Path:
    return Path(os.environ.get("VANCE_RFT_TRACE_DIR", str(DEFAULT_TRACE_DIR)))


def _write_trace(trace, rollout_id: str) -> Path:
    safe_rollout = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in rollout_id)
    path = _trace_dir() / f"{trace.task_id}.{safe_rollout}.jsonl"
    write_jsonl(path, [trace])
    return path


def _rollout_logger(rollout_id: str) -> logging.Logger:
    _ensure_tracing_handler()
    logger = logging.getLogger(f"vance.rft.{rollout_id}")
    logger.setLevel(logging.INFO)
    if RolloutIdFilter is not None:
        logger.addFilter(RolloutIdFilter(rollout_id))
    return logger


def _ensure_tracing_handler() -> None:
    global _TRACING_HANDLER_ATTACHED
    if _TRACING_HANDLER_ATTACHED or FireworksTracingHttpHandler is None:
        return
    logging.getLogger().addHandler(FireworksTracingHttpHandler())
    _TRACING_HANDLER_ATTACHED = True


def _log_finished(logger: logging.Logger, response: dict[str, Any]) -> None:
    if Status is not None:
        logger.info("Vance rollout completed", extra={"status": Status.rollout_finished(), "vance": response})
    else:
        logger.info("Vance rollout completed: reward=%s task=%s", response["reward"], response["task_id"])


def _log_error(logger: logging.Logger, message: str) -> None:
    if Status is not None:
        logger.error("Vance rollout failed: %s", message, extra={"status": Status.rollout_error(message)})
    else:
        logger.error("Vance rollout failed: %s", message)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("rft.remote_server:app", host="0.0.0.0", port=port, reload=False)
