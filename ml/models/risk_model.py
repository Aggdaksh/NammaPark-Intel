from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error
from sklearn.preprocessing import OrdinalEncoder


class ModelQualityError(RuntimeError):
    pass


@dataclass
class RiskTrainResult:
    model_path: Path
    metadata_path: Path
    metrics: dict[str, float]
    predictions: pd.DataFrame


class RiskModel:
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
        self.preprocessor: ColumnTransformer | None = None
        self.model: lgb.LGBMRegressor | None = None
        self.calibrator: IsotonicRegression | None = None
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

    def train(self, df: pd.DataFrame, artifacts_dir: Path, data_hash: str, version: str = "v1") -> RiskTrainResult:
        cfg = self.config["models"]["risk"]
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        cutoff = frame["date"].quantile(0.8)
        train_df = frame[frame["date"] <= cutoff].copy()
        val_df = frame[frame["date"] > cutoff].copy()
        if train_df.empty or val_df.empty:
            raise ModelQualityError("Risk model needs non-empty temporal train and validation splits")

        features = self._feature_columns(frame)
        self.feature_names = features
        categorical = [col for col in self.categorical_features if col in features]
        numerical = [col for col in features if col not in categorical]
        self.preprocessor = ColumnTransformer(
            [
                (
                    "cat",
                    OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                    categorical,
                ),
                ("num", "passthrough", numerical),
            ],
            verbose_feature_names_out=False,
        )
        x_train = self.preprocessor.fit_transform(train_df[features])
        x_val = self.preprocessor.transform(val_df[features])

        self.model = lgb.LGBMRegressor(
            boosting_type=cfg["boosting_type"],
            n_estimators=cfg["n_estimators"],
            learning_rate=cfg["learning_rate"],
            num_leaves=cfg["num_leaves"],
            feature_fraction=cfg["feature_fraction"],
            bagging_fraction=cfg["bagging_fraction"],
            bagging_freq=cfg["bagging_freq"],
            min_child_samples=cfg["min_child_samples"],
            reg_alpha=cfg["reg_alpha"],
            reg_lambda=cfg["reg_lambda"],
            random_state=cfg["random_state"],
            n_jobs=-1,
            verbose=-1,
        )
        self.model.fit(x_train, train_df[self.target_col])

        val_pred = np.maximum(self.model.predict(x_val), 0.0)
        y_val = val_df[self.target_col].to_numpy()
        max_target = float(np.percentile(train_df[self.target_col], 99)) or 1.0
        scaled_target = np.clip(train_df[self.target_col].to_numpy() * 100.0 / max_target, 0.0, 100.0)
        train_pred = np.maximum(self.model.predict(x_train), 0.0)
        self.calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=100.0)
        self.calibrator.fit(train_pred, scaled_target)
        val_risk = self.calibrator.predict(val_pred)

        topk_precision = self._topk_precision(y_val, val_pred, k=10)
        spearman = float(spearmanr(y_val, val_pred).statistic)
        if np.isnan(spearman):
            spearman = 0.0
        metrics = {
            "val_MAE_delay_min": float(mean_absolute_error(y_val, val_pred)),
            "val_MAPE": float(mean_absolute_percentage_error(np.maximum(y_val, 1e-9), np.maximum(val_pred, 1e-9))),
            "val_SpearmanR": spearman,
            "val_TopK10_precision": topk_precision,
        }

        gates = cfg["gates"]
        if metrics["val_SpearmanR"] < gates["min_spearman"] or metrics["val_MAE_delay_min"] > gates["max_mae_min"]:
            raise ModelQualityError(f"Risk model failed quality gate: {metrics}")

        val_out = val_df[["cluster_id", "date", "hour_ist", "centroid_lat", "centroid_lon"]].copy()
        val_out["predicted_delay_min"] = val_pred
        val_out["final_risk_0_100"] = val_risk
        val_out["shap_context"] = self.compute_shap_context(x_val, val_df, limit=250)

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        model_path = artifacts_dir / f"risk_model_{version}.joblib"
        metadata_path = artifacts_dir / f"risk_model_metadata_{version}.json"
        joblib.dump(
            {
                "preprocessor": self.preprocessor,
                "model": self.model,
                "calibrator": self.calibrator,
                "features": features,
                "categorical_features": categorical,
                "target_col": self.target_col,
            },
            model_path,
        )
        metadata = {
            "model_name": "risk_model",
            "version": version,
            "data_hash": data_hash,
            "training_rows": int(len(train_df)),
            "validation_rows": int(len(val_df)),
            "features": features,
            "metrics": metrics,
            "lgbm_params": {key: cfg[key] for key in cfg if key != "gates"},
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return RiskTrainResult(model_path, metadata_path, metrics, val_out)

    def compute_shap_context(self, x_val: np.ndarray, val_df: pd.DataFrame, limit: int = 250) -> list[list[dict[str, Any]]]:
        if self.model is None or self.preprocessor is None:
            raise RuntimeError("RiskModel must be trained before SHAP computation")
        transformed_names = list(self.preprocessor.get_feature_names_out())
        sample_size = min(limit, x_val.shape[0])
        sample = x_val[:sample_size]
        explainer = shap.TreeExplainer(self.model)
        shap_values = explainer.shap_values(sample)
        contexts: list[list[dict[str, Any]]] = []
        for row_values in shap_values:
            order = np.argsort(np.abs(row_values))[::-1][:5]
            contexts.append(
                [
                    {
                        "feature": transformed_names[idx],
                        "shap_contribution_min": round(float(row_values[idx]), 3),
                        "direction": "increases" if row_values[idx] >= 0 else "decreases",
                        "human_label": transformed_names[idx].replace("_", " ").title(),
                    }
                    for idx in order
                ]
            )
        fallback = contexts[-1] if contexts else []
        while len(contexts) < len(val_df):
            contexts.append(fallback)
        return contexts

    @staticmethod
    def _topk_precision(y_true: np.ndarray, y_pred: np.ndarray, k: int) -> float:
        k = min(k, len(y_true))
        true_top = set(np.argsort(y_true)[-k:])
        pred_top = set(np.argsort(y_pred)[-k:])
        return len(true_top & pred_top) / max(k, 1)
