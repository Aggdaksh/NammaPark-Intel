"""Road-network and BPR delay feature helpers."""

from __future__ import annotations

import math
from typing import Iterable

from ml.config.settings import load_config


def normalise_violation_label(label: object) -> str:
    if label is None:
        return "UNKNOWN"
    text = " ".join(str(label).strip().upper().split())
    if text in {"", "NULL", "NONE", "NAN"}:
        return "UNKNOWN"
    return text


def severity_factor_for(violation_types: str | Iterable[str], config: dict | None = None) -> float:
    cfg = config or load_config()
    severity_map = cfg["features"]["bpr"]["severity_factors"]
    if isinstance(violation_types, str):
        labels = [violation_types]
    else:
        labels = list(violation_types)
    if not labels:
        labels = ["UNKNOWN"]
    return max(float(severity_map.get(normalise_violation_label(label), severity_map["UNKNOWN"])) for label in labels)


def compute_blockage_fraction(severity_factor: float, lane_count: int | float) -> float:
    """Return lane blockage share, always in (0, 1]."""

    if severity_factor <= 0:
        raise ValueError("severity_factor must be positive")
    lanes = int(lane_count)
    if lanes < 1:
        raise ValueError("lane_count must be >= 1")
    return max(0.001, min(float(severity_factor) / lanes, 1.0))


def compute_bpr_delay(
    speed_limit_kph: float | int | None,
    segment_length_m: float | int | None,
    blockage_fraction: float,
    *,
    alpha: float | None = None,
    beta: float | None = None,
) -> float:
    """Compute BPR-style incremental delay in minutes per vehicle.

    Requirement 2.5 gives the travel-time equation:
    free_flow_time * (1 + alpha * blockage_fraction ** beta).

    The useful risk feature is the incremental delay over free-flow time,
    measured in minutes per vehicle. This keeps the feature non-negative and
    comparable across road segments.
    """

    cfg = load_config()
    alpha = float(alpha if alpha is not None else cfg["features"]["bpr"]["alpha"])
    beta = float(beta if beta is not None else cfg["features"]["bpr"]["beta"])
    speed = float(speed_limit_kph or cfg["features"]["osmnx"]["fallback_speed_limit_kph"])
    length = float(segment_length_m or cfg["features"]["osmnx"]["fallback_segment_length_m"])
    if speed <= 0:
        speed = float(cfg["features"]["osmnx"]["fallback_speed_limit_kph"])
    if length <= 0:
        raise ValueError("segment_length_m must be positive")
    if not 0 < blockage_fraction <= 1:
        raise ValueError("blockage_fraction must be in (0, 1]")

    free_flow_time_min = length / (speed * 1000.0 / 60.0)
    congested_time_min = free_flow_time_min * (1.0 + alpha * math.pow(blockage_fraction, beta))
    return max(congested_time_min - free_flow_time_min, 0.0)
