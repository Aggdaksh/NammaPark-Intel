"""Runtime configuration for NammaPark Intel.

The canonical editable config is `ml/config/config.yaml`. The project does not
depend on PyYAML at import time so early pipeline utilities and tests can run
before `uv sync` has installed the full stack. When PyYAML is present, values
from the YAML file are merged over these defaults.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "project": {"name": "NammaPark Intel", "mode": "production_architecture", "model_version": "v1"},
    "data": {
        "bengaluru_bbox": {"min_lat": 12.7, "max_lat": 13.2, "min_lon": 77.3, "max_lon": 77.8},
        "valid_created_datetime": {
            "start": "2023-11-01T00:00:00Z",
            "end": "2024-04-30T23:59:59Z",
        },
        "valid_vehicle_types": ["SCOOTER", "CAR", "MOTOR CYCLE", "PASSENGER AUTO", "MAXI-CAB", "LGV"],
    },
    "features": {
        "hdbscan": {"min_cluster_size": 15},
        "h3": {"primary_resolution": 8, "secondary_resolution": 9},
        "osmnx": {
            "graph_path": "ml/data/bengaluru.graphml",
            "snap_radius_m": 50.0,
            "fallback_lane_count": 2,
            "fallback_road_type": "residential",
            "fallback_speed_limit_kph": 30.0,
            "fallback_segment_length_m": 120.0,
        },
        "bpr": {
            "alpha": 0.15,
            "beta": 4.0,
            "severity_factors": {
                "NO PARKING": 0.9,
                "WRONG PARKING": 1.0,
                "PARKING IN A MAIN ROAD": 1.15,
                "PARKING NEAR ROAD CROSSING": 1.1,
                "STOPPED IN CARRIAGEWAY": 1.25,
                "FOOTPATH PARKING": 0.65,
                "UNKNOWN": 0.85,
            },
        },
        "temporal": {
            "lags_h": [1, 2, 3, 6, 24, 48, 168],
            "rolling_windows_h": [3, 6, 24],
            "rolling_std_window_h": 24,
            "peak_hours": [8, 9, 10, 17, 18, 19],
            "weekend_days": [5, 6],
            "cycles": {"hour": 24, "day_of_week": 7, "month": 12},
        },
    },
    "models": {
        "risk": {
            "boosting_type": "dart",
            "n_estimators": 1000,
            "learning_rate": 0.05,
            "num_leaves": 63,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "min_child_samples": 20,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "early_stopping_rounds": 50,
            "random_state": 42,
            "gates": {"min_spearman": 0.75, "max_mae_min": 3.0, "min_topk10_precision": 0.70},
        },
        "survival": {
            "objective": "survival:aft",
            "aft_loss_distribution": "logistic",
            "aft_loss_distribution_scale": 1.0,
            "tree_method": "hist",
            "learning_rate": 0.05,
            "max_depth": 4,
            "subsample": 0.8,
            "censor_horizon_min": 240,
            "heuristic_median_duration_min": 120,
            "gates": {"min_concordance": 0.65, "force_heuristic_below": 0.60},
        },
        "anomaly": {"n_estimators": 200, "contamination": 0.05, "random_state": 42, "score_threshold": -0.1},
        "vrp": {
            "time_limit_seconds": 10,
            "shift_minutes": 480,
            "slack_minutes": 30,
            "dwell_minutes": 8,
            "urban_speed_kph": 30.0,
            "greedy_improvement_gate": 0.10,
            "default_units": 3,
            "candidate_multiplier_per_unit": 6,
            "min_candidate_clusters": 12,
        },
    },
    "cache": {
        "ttl_seconds": {
            "hotspots": 900,
            "cluster_detail": 1800,
            "patrol_routes": 3600,
            "anomaly_alerts": 900,
            "shap_context": 3600,
        }
    },
    "api": {"fallback_dir": "public/fallback", "default_shift_hour_ist": 17},
    "database": {"url_env": "DATABASE_URL", "engine": "postgresql", "postgis_required": True},
    "serving": {
        "redis": {
            "url_env": "UPSTASH_REDIS_URL",
            "fallback_url_env": "REDIS_URL",
            "key_prefix": "nammapark:intel",
        },
        "postgres": {"api_cache_table": "api_cache"},
    },
}


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    config_path = Path(path) if path else Path(__file__).with_name("config.yaml")
    if not config_path.exists():
        return config

    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return config

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a mapping: {config_path}")
    return deep_merge(config, loaded)
