from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder, StandardScaler


@dataclass
class NeuralRiskTrainResult:
    model_path: Path
    metadata_path: Path
    predictions_path: Path
    metrics: dict[str, float]
    predictions: pd.DataFrame


class NeuralRiskModel:
    """Experimental deep MLP challenger for the LightGBM risk model.

    This is intentionally separate from the champion model stack. It lets us
    benchmark a neural network without replacing the planned LightGBM model.
    """

    categorical_features = [
        "h3_res8",
        "h3_res9",
        "road_type",
        "dominant_vehicle_type",
        "dominant_violation_type",
        "police_station",
    ]

    target_col = "bpr_delay_sum_min"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.pipeline: Pipeline | None = None
        self.feature_names: list[str] = []

    def _feature_columns(self, df: pd.DataFrame) -> list[str]:
        excluded = {
            self.target_col,
            "date",
            "cluster_id",
            "prediction_for",
            "created_at",
        }
        return [col for col in df.columns if col not in excluded]

    def train(
        self,
        df: pd.DataFrame,
        artifacts_dir: Path,
        *,
        data_hash: str,
        version: str,
        max_iter: int | None = None,
    ) -> NeuralRiskTrainResult:
        cfg = self.config["models"]["neural_risk"]
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["date", "cluster_id", "hour_ist"]).reset_index(drop=True)
        cutoff = frame["date"].quantile(0.8)
        train_df = frame[frame["date"] <= cutoff].copy()
        val_df = frame[frame["date"] > cutoff].copy()
        if train_df.empty or val_df.empty:
            raise ValueError("Neural risk model needs non-empty temporal train and validation splits")

        features = self._feature_columns(frame)
        self.feature_names = features
        categorical = [col for col in self.categorical_features if col in features]
        numerical = [col for col in features if col not in categorical]
        preprocessor = ColumnTransformer(
            [
                (
                    "cat",
                    OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                    categorical,
                ),
                ("num", StandardScaler(), numerical),
            ],
            verbose_feature_names_out=False,
        )
        regressor = MLPRegressor(
            hidden_layer_sizes=tuple(int(size) for size in cfg["hidden_layer_sizes"]),
            activation=cfg["activation"],
            solver=cfg["solver"],
            alpha=float(cfg["alpha"]),
            learning_rate_init=float(cfg["learning_rate_init"]),
            max_iter=int(max_iter or cfg["max_iter"]),
            early_stopping=bool(cfg["early_stopping"]),
            validation_fraction=float(cfg["validation_fraction"]),
            n_iter_no_change=int(cfg["n_iter_no_change"]),
            random_state=int(cfg["random_state"]),
            verbose=False,
        )
        self.pipeline = Pipeline(
            [
                ("preprocessor", preprocessor),
                ("model", regressor),
            ]
        )
        y_train_log = np.log1p(np.maximum(train_df[self.target_col].to_numpy(dtype=float), 0.0))
        self.pipeline.fit(train_df[features], y_train_log)

        val_pred = np.expm1(self.pipeline.predict(val_df[features]))
        val_pred = np.maximum(val_pred, 0.0)
        y_val = val_df[self.target_col].to_numpy(dtype=float)
        spearman = float(spearmanr(y_val, val_pred).statistic)
        if np.isnan(spearman):
            spearman = 0.0
        metrics = {
            "val_MAE_delay_min": float(mean_absolute_error(y_val, val_pred)),
            "val_MAPE": float(mean_absolute_percentage_error(np.maximum(y_val, 1e-9), np.maximum(val_pred, 1e-9))),
            "val_SpearmanR": spearman,
            "val_TopK10_precision": self._topk_precision(y_val, val_pred, k=10),
            "train_rows": float(len(train_df)),
            "validation_rows": float(len(val_df)),
            "actual_iterations": float(getattr(regressor, "n_iter_", 0)),
        }

        predictions = val_df[["cluster_id", "date", "hour_ist", "centroid_lat", "centroid_lon"]].copy()
        predictions["neural_predicted_delay_min"] = val_pred
        predictions["actual_delay_min"] = y_val

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        model_path = artifacts_dir / f"neural_risk_model_{version}.joblib"
        metadata_path = artifacts_dir / f"neural_risk_model_metadata_{version}.json"
        predictions_path = artifacts_dir / f"neural_risk_predictions_{version}.parquet"
        joblib.dump(
            {
                "pipeline": self.pipeline,
                "features": features,
                "categorical_features": categorical,
                "target_col": self.target_col,
            },
            model_path,
        )
        predictions.to_parquet(predictions_path, index=False)
        metadata = {
            "model_name": "neural_risk_model",
            "role": "experimental_challenger",
            "champion_model": "risk_model_v1-osm",
            "version": version,
            "data_hash": data_hash,
            "features": features,
            "metrics": metrics,
            "mlp_params": {
                **cfg,
                "max_iter": int(max_iter or cfg["max_iter"]),
            },
            "target_transform": "log1p",
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return NeuralRiskTrainResult(model_path, metadata_path, predictions_path, metrics, predictions)

    @staticmethod
    def _topk_precision(y_true: np.ndarray, y_pred: np.ndarray, k: int) -> float:
        k = min(k, len(y_true))
        true_top = set(np.argsort(y_true)[-k:])
        pred_top = set(np.argsort(y_pred)[-k:])
        return len(true_top & pred_top) / max(k, 1)
