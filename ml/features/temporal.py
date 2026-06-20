"""Temporal feature helpers for cyclical time, lag, and rolling features."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def add_cyclical_features(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    temporal_cfg = config["features"]["temporal"]
    cycles = temporal_cfg["cycles"]
    out["hour_sin"] = np.sin(2 * np.pi * out["hour_ist"] / int(cycles["hour"]))
    out["hour_cos"] = np.cos(2 * np.pi * out["hour_ist"] / int(cycles["hour"]))
    out["dow_sin"] = np.sin(2 * np.pi * out["day_of_week"] / int(cycles["day_of_week"]))
    out["dow_cos"] = np.cos(2 * np.pi * out["day_of_week"] / int(cycles["day_of_week"]))
    out["month_sin"] = np.sin(2 * np.pi * out["month"] / int(cycles["month"]))
    out["month_cos"] = np.cos(2 * np.pi * out["month"] / int(cycles["month"]))
    return out


def add_calendar_flags(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    temporal_cfg = config["features"]["temporal"]
    out["is_peak"] = out["hour_ist"].isin(temporal_cfg["peak_hours"]).astype(int)
    out["is_weekend"] = out["day_of_week"].isin(temporal_cfg["weekend_days"]).astype(int)
    return out


def add_lag_features(
    frame: pd.DataFrame,
    config: dict[str, Any],
    *,
    group_col: str = "cluster_id",
    value_col: str = "bpr_delay_sum_min",
) -> pd.DataFrame:
    out = frame.sort_values([group_col, "date", "hour_ist"]).reset_index(drop=True).copy()
    for lag in config["features"]["temporal"]["lags_h"]:
        out[f"delay_lag_{lag}h"] = out.groupby(group_col)[value_col].shift(int(lag)).fillna(0.0)
    return out


def add_rolling_features(
    frame: pd.DataFrame,
    config: dict[str, Any],
    *,
    group_col: str = "cluster_id",
    value_col: str = "bpr_delay_sum_min",
) -> pd.DataFrame:
    out = frame.copy()
    temporal_cfg = config["features"]["temporal"]
    for window in temporal_cfg["rolling_windows_h"]:
        window = int(window)
        out[f"delay_roll{window}h_mean"] = (
            out.groupby(group_col)[value_col]
            .transform(lambda values: values.shift(1).rolling(window, min_periods=1).mean())
            .fillna(0.0)
        )
    std_window = int(temporal_cfg["rolling_std_window_h"])
    out[f"delay_roll{std_window}h_std"] = (
        out.groupby(group_col)[value_col]
        .transform(lambda values: values.shift(1).rolling(std_window, min_periods=1).std())
        .fillna(0.0)
    )
    return out


def add_temporal_features(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = add_cyclical_features(frame, config)
    out = add_calendar_flags(out, config)
    out = add_lag_features(out, config)
    return add_rolling_features(out, config)
