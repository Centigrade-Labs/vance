"""Agent factory for Vance."""

from __future__ import annotations

from agents.baseline_slm import BaselineHarness
from agents.fireworks_agent import FireworksAgent, LiveAgentUnavailable
from agents.improved_slm import ImprovedHarness


def build_agent(agent_id: str, mode: str = "fallback") -> object:
    if agent_id in {"baseline", "baseline_slm", "baseline_harness"}:
        return BaselineHarness()
    if agent_id in {"improved", "improved_slm", "improved_harness"}:
        return ImprovedHarness()
    if agent_id in {"fireworks", "fireworks_agent", "qwen"}:
        if mode != "live":
            raise LiveAgentUnavailable("fireworks_agent requires --mode live")
        return FireworksAgent()
    raise ValueError(f"unknown agent {agent_id}")
