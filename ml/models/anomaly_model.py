from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


@dataclass
class AnomalyTrainResult:
    model_path: Path
    metadata_path: Path
    scored_features: pd.DataFrame


class AnomalyModel:
    feature_cols = [
        "violation_count_vs_baseline",
        "delay_vs_baseline",
        "vehicle_mix_entropy",
        "resolution_rate_vs_baseline",
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.model: IsolationForest | None = None

    def train(self, features: pd.DataFrame, artifacts_dir: Path, version: str = "v1") -> AnomalyTrainResult:
        cfg = self.config["models"]["anomaly"]
        frame = features.copy()
        x = frame[self.feature_cols].fillna(0.0)
        self.model = IsolationForest(
            n_estimators=cfg["n_estimators"],
            contamination=cfg["contamination"],
            random_state=cfg["random_state"],
            n_jobs=-1,
        )
        self.model.fit(x)
        scores = self.model.score_samples(x)
        labels = self.model.predict(x)
        frame["anomaly_score"] = scores
        threshold_flags = scores < float(cfg["score_threshold"])
        calibrated_flags = labels == -1
        frame["is_anomaly"] = calibrated_flags if threshold_flags.mean() > 0.25 else threshold_flags
        frame["anomaly_zscore"] = np.maximum(frame["violation_count_vs_baseline"], frame["delay_vs_baseline"]).clip(lower=0)

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        model_path = artifacts_dir / f"anomaly_model_{version}.joblib"
        metadata_path = artifacts_dir / f"anomaly_model_metadata_{version}.json"
        joblib.dump(self.model, model_path)
        metadata_path.write_text(
            json.dumps(
                {
                    "model_name": "anomaly_model",
                    "version": version,
                    "features": self.feature_cols,
                    "flagged_rate": float(frame["is_anomaly"].mean()),
                    "params": cfg,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return AnomalyTrainResult(model_path, metadata_path, frame)
