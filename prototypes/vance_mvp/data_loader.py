"""AI4I CSV loading and failure-row selection."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


PUBLIC_COLUMNS = (
    "Type",
    "Air temperature [K]",
    "Process temperature [K]",
    "Rotational speed [rpm]",
    "Torque [Nm]",
    "Tool wear [min]",
)

HIDDEN_LABEL_COLUMNS = (
    "Machine failure",
    "TWF",
    "HDF",
    "PWF",
    "OSF",
    "RNF",
)

REQUIRED_COLUMNS = PUBLIC_COLUMNS + HIDDEN_LABEL_COLUMNS
FAILURE_PREFERENCE = ("TWF", "HDF", "OSF", "PWF", "Machine failure")


def load_ai4i_rows(csv_path: str | Path) -> list[dict[str, str]]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
        rows = list(reader)

    if not rows:
        raise ValueError("CSV contains no data rows")
    return rows


def select_failure_row(rows: list[dict[str, str]]) -> dict[str, str]:
    for label in FAILURE_PREFERENCE:
        for row in rows:
            if _as_int(row.get(label)) == 1:
                return row
    raise ValueError("No suitable failure row found in AI4I CSV")


def row_identifier(row: dict[str, str], fallback_index: int = 0) -> str:
    return row.get("UDI") or row.get("Product ID") or f"row-{fallback_index}"


def hidden_labels(row: dict[str, str]) -> dict[str, int]:
    return {column: _as_int(row.get(column)) for column in HIDDEN_LABEL_COLUMNS}


def public_sensor_values(row: dict[str, str]) -> dict[str, Any]:
    return {
        "product_type": row["Type"],
        "air_temperature_k": float(row["Air temperature [K]"]),
        "process_temperature_k": float(row["Process temperature [K]"]),
        "rotational_speed_rpm": int(float(row["Rotational speed [rpm]"])),
        "torque_nm": float(row["Torque [Nm]"]),
        "tool_wear_min": int(float(row["Tool wear [min]"])),
    }


def _as_int(value: str | None) -> int:
    if value in (None, ""):
        return 0
    return int(float(value))

