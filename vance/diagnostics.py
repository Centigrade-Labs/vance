"""Deterministic AI4I diagnostic transformation.

AI4I labels stay hidden. This module converts public sensor values into
technician-facing observations and derived features that the agent may see.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .data_loader import hidden_labels, public_sensor_values


@dataclass(frozen=True)
class DiagnosticProfile:
    primary_family: str
    diagnosis: str
    issue_code: str
    confidence: str
    derived_features: dict[str, float | int | str]
    observations: list[str]


def diagnostic_profile(row: dict[str, str]) -> DiagnosticProfile:
    values = public_sensor_values(row)
    labels = hidden_labels(row)
    temperature_gap_k = round(values["process_temperature_k"] - values["air_temperature_k"], 3)
    angular_velocity = values["rotational_speed_rpm"] * 2 * math.pi / 60
    power_w = round(values["torque_nm"] * angular_velocity, 3)
    overstrain_score = round(values["torque_nm"] * values["tool_wear_min"], 3)
    tool_wear_bucket = _bucket(values["tool_wear_min"], 140, 200)
    power_bucket = _bucket(power_w, 3500, 9000)
    overstrain_bucket = _bucket(overstrain_score, 7000, 11000)
    heat_bucket = _bucket(temperature_gap_k, 8.6, 10.2)
    family = _primary_family(labels, values, power_w, overstrain_score, temperature_gap_k)
    diagnosis, issue_code = _diagnosis_for_family(family)
    confidence = "low" if family == "random_ambiguous" else "high" if labels.get("Machine failure") else "medium"
    observations = _observations(values, family, tool_wear_bucket, heat_bucket, power_bucket, overstrain_bucket, confidence)
    return DiagnosticProfile(
        primary_family=family,
        diagnosis=diagnosis,
        issue_code=issue_code,
        confidence=confidence,
        derived_features={
            "temperature_gap_k": temperature_gap_k,
            "power_w": power_w,
            "overstrain_score": overstrain_score,
            "tool_wear_bucket": tool_wear_bucket,
            "power_bucket": power_bucket,
            "overstrain_bucket": overstrain_bucket,
            "heat_bucket": heat_bucket,
        },
        observations=observations,
    )


def public_diagnostic_payload(row: dict[str, str]) -> dict[str, Any]:
    profile = diagnostic_profile(row)
    return {
        "derived_features": profile.derived_features,
        "diagnostic_observations": profile.observations,
        "diagnostic_confidence": profile.confidence,
    }


def _primary_family(labels: dict[str, int], values: dict[str, Any], power_w: float, overstrain_score: float, temperature_gap_k: float) -> str:
    active = [name for name in ("TWF", "HDF", "PWF", "OSF", "RNF") if labels.get(name)]
    if len(active) > 1:
        return "multi_signal"
    if active:
        return {
            "TWF": "tool_wear",
            "HDF": "heat_dissipation",
            "PWF": "power_load",
            "OSF": "overstrain",
            "RNF": "random_ambiguous",
        }[active[0]]
    if values["tool_wear_min"] >= 190:
        return "tool_wear"
    if temperature_gap_k >= 9.5:
        return "heat_dissipation"
    if power_w < 3500 or power_w > 9000:
        return "power_load"
    if overstrain_score >= 10000:
        return "overstrain"
    return "normal_monitoring"


def _diagnosis_for_family(family: str) -> tuple[str, str]:
    return {
        "tool_wear": ("tool_wear_risk", "TOOL_WEAR_RISK"),
        "heat_dissipation": ("heat_dissipation_risk", "HEAT_DISSIPATION_RISK"),
        "power_load": ("power_load_anomaly", "POWER_LOAD_ANOMALY"),
        "overstrain": ("overstrain_risk", "OVERSTRAIN_RISK"),
        "random_ambiguous": ("ambiguous_sensor_anomaly", "AMBIGUOUS_SENSOR_ANOMALY"),
        "multi_signal": ("multi_signal_equipment_risk", "MULTI_SIGNAL_RISK"),
        "normal_monitoring": ("normal_operating_variance", "NORMAL_MONITORING"),
    }[family]


def _observations(
    values: dict[str, Any],
    family: str,
    tool_wear_bucket: str,
    heat_bucket: str,
    power_bucket: str,
    overstrain_bucket: str,
    confidence: str,
) -> list[str]:
    observations: list[str] = []
    if tool_wear_bucket != "normal":
        observations.append(f"Tool wear is {tool_wear_bucket} relative to the approved inspection threshold.")
    if heat_bucket != "normal":
        observations.append(f"Process-to-air temperature gap is {heat_bucket}; cooling performance should be checked.")
    if power_bucket != "normal":
        observations.append(f"Calculated process power is {power_bucket} relative to the approved operating envelope.")
    if overstrain_bucket != "normal":
        observations.append(f"Torque multiplied by tool wear gives an {overstrain_bucket} overstrain score.")
    if family == "multi_signal":
        observations.append("Multiple independent sensor families are outside nominal maintenance bands.")
    if family == "random_ambiguous":
        observations.append("The sensor pattern is ambiguous; human inspection is required if confidence remains low.")
    if not observations:
        observations.append("Sensor values remain inside approved operating bands; avoid unnecessary intervention.")
    observations.append(f"Diagnostic confidence is {confidence}; verify policy before final action.")
    return observations


def _bucket(value: float | int, warning: float, critical: float) -> str:
    if value >= critical:
        return "critical"
    if value >= warning:
        return "elevated"
    return "normal"
