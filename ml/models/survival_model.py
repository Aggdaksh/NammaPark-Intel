from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb
from lifelines.utils import concordance_index
from sklearn.preprocessing import OrdinalEncoder


@dataclass
class SurvivalTrainResult:
    artifact_path: Path
    metrics: dict[str, float | bool]
    cluster_active_probability: pd.DataFrame


class SurvivalModel:
    feature_cols = [
        "vehicle_type",
        "dominant_violation_type",
        "police_station",
        "hour_ist",
        "day_of_week",
        "lane_count",
        "junction_flag",
        "blockage_fraction",
        "bpr_delay_min",
    ]

    categorical_cols = ["vehicle_type", "dominant_violation_type", "police_station"]

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.encoder: OrdinalEncoder | None = None
        self.booster: xgb.Booster | None = None
        self.use_heuristic = False

    def train(self, violations: pd.DataFrame, artifacts_dir: Path, version: str = "v1") -> SurvivalTrainResult:
        cfg = self.config["models"]["survival"]
        df = violations.copy()
        df["created_ist"] = pd.to_datetime(df["created_ist"])
        df = df.sort_values("created_ist")
        cutoff = df["created_ist"].quantile(0.8)
        train_df = df[df["created_ist"] <= cutoff].copy()
        val_df = df[df["created_ist"] > cutoff].copy()

        x_train = self._prepare_features(train_df, fit=True)
        x_val = self._prepare_features(val_df, fit=False)
        y_lower_train, y_upper_train, observed_train = self._duration_bounds(train_df)
        y_lower_val, _, observed_val = self._duration_bounds(val_df)

        dtrain = xgb.DMatrix(x_train)
        dtrain.set_float_info("label_lower_bound", y_lower_train)
        dtrain.set_float_info("label_upper_bound", y_upper_train)
        params = {
            "objective": cfg["objective"],
            "eval_metric": "aft-nloglik",
            "aft_loss_distribution": cfg["aft_loss_distribution"],
            "aft_loss_distribution_scale": cfg["aft_loss_distribution_scale"],
            "tree_method": cfg["tree_method"],
            "learning_rate": cfg["learning_rate"],
            "max_depth": cfg["max_depth"],
            "subsample": cfg["subsample"],
            "seed": 42,
        }
        self.booster = xgb.train(params, dtrain, num_boost_round=350, verbose_eval=False)

        median_pred = np.maximum(self.booster.predict(xgb.DMatrix(x_val)), 1.0)
        observed_mask = observed_val & np.isfinite(y_lower_val)
        if observed_mask.sum() >= 20:
            c_index = float(concordance_index(y_lower_val[observed_mask], -median_pred[observed_mask]))
        else:
            c_index = 0.0
        self.use_heuristic = c_index < float(cfg["gates"]["force_heuristic_below"])
        metrics = {"val_concordance_index": c_index, "heuristic_fallback": self.use_heuristic}

        cluster_probs = df.groupby("cluster_id", as_index=False).apply(self._cluster_active_probability, include_groups=False)
        cluster_probs = cluster_probs.rename(columns={None: "p_active_at_dispatch"})
        if "p_active_at_dispatch" not in cluster_probs:
            cluster_probs["p_active_at_dispatch"] = cluster_probs.iloc[:, -1]
        cluster_probs = cluster_probs[["cluster_id", "p_active_at_dispatch"]]

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifacts_dir / f"survival_model_{version}.json"
        payload = {
            "model_name": "survival_model",
            "version": version,
            "metrics": metrics,
            "feature_cols": self.feature_cols,
            "categorical_cols": self.categorical_cols,
        }
        artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if self.booster is not None:
            self.booster.save_model(str(artifacts_dir / f"survival_booster_{version}.json"))
        return SurvivalTrainResult(artifact_path, metrics, cluster_probs)

    def p_active_at_dispatch(self, violation_age_min: float, travel_time_min: float, median_duration: float = 120.0) -> float:
        if self.use_heuristic:
            return float(np.clip(math.exp(-violation_age_min / 120.0), 0.0, 1.0))
        t_arrival = max(violation_age_min + travel_time_min, 1e-6)
        median = max(median_duration, 1.0)
        u = math.log(t_arrival / median)
        return float(np.clip(1.0 / (1.0 + math.exp(u)), 0.0, 1.0))

    def _prepare_features(self, df: pd.DataFrame, fit: bool) -> pd.DataFrame:
        out = df[self.feature_cols].copy()
        out["junction_flag"] = out["junction_flag"].astype(int)
        for col in self.categorical_cols:
            out[col] = out[col].fillna("UNKNOWN").astype(str)
        if fit:
            self.encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
            out[self.categorical_cols] = self.encoder.fit_transform(out[self.categorical_cols])
        else:
            if self.encoder is None:
                raise RuntimeError("Encoder is not fitted")
            out[self.categorical_cols] = self.encoder.transform(out[self.categorical_cols])
        return out.fillna(0.0)

    def _duration_bounds(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        cfg = self.config["models"]["survival"]
        action = pd.to_datetime(df["action_taken_ist"], errors="coerce")
        created = pd.to_datetime(df["created_ist"], errors="coerce")
        duration = (action - created).dt.total_seconds() / 60.0
        observed = duration.notna() & (duration > 0)
        lower = np.where(observed, duration, 0.0).astype(float)
        upper = np.where(observed, duration, np.inf).astype(float)
        lower = np.where(observed, lower, float(cfg["censor_horizon_min"]))
        return lower, upper, observed.to_numpy()

    def _cluster_active_probability(self, group: pd.DataFrame) -> float:
        now = group["created_ist"].max()
        ages = (now - group["created_ist"]).dt.total_seconds() / 60.0
        recent_ages = np.clip(ages.tail(50), 0.0, 24 * 60)
        probs = [self.p_active_at_dispatch(float(age), 20.0) for age in recent_ages]
        return float(np.mean(probs)) if probs else 0.5
