from __future__ import annotations

import pandas as pd

from ml.config.settings import load_config
from ml.models.neural_risk_model import NeuralRiskModel
from ml.pipeline.train_neural import compare_to_champion


def _synthetic_features() -> pd.DataFrame:
    rows = []
    for idx in range(80):
        hour = idx % 24
        cluster_id = idx % 5 + 1
        delay = 0.05 + 0.01 * cluster_id + (0.02 if hour in {8, 9, 17, 18} else 0.0)
        rows.append(
            {
                "cluster_id": cluster_id,
                "date": f"2024-01-{idx % 20 + 1:02d}",
                "hour_ist": hour,
                "violation_count": idx % 7 + 1,
                "bpr_delay_sum_min": delay,
                "avg_blockage_fraction": 0.1 + 0.01 * cluster_id,
                "vehicle_mix_entropy": 0.5,
                "resolution_rate": 0.7,
                "centroid_lat": 12.9 + cluster_id * 0.001,
                "centroid_lon": 77.5 + cluster_id * 0.001,
                "h3_res8": f"cell8-{cluster_id}",
                "h3_res9": f"cell9-{cluster_id}",
                "police_station": "TEST",
                "dominant_vehicle_type": "SCOOTER",
                "dominant_violation_type": "NO PARKING",
                "road_type": "residential",
                "total_violations": 100,
                "active_days": 20,
                "junction_flag": False,
                "hps_score": 5.0,
                "day_of_week": idx % 7,
                "month": 1,
                "hour_sin": 0.0,
                "hour_cos": 1.0,
                "dow_sin": 0.0,
                "dow_cos": 1.0,
                "month_sin": 0.0,
                "month_cos": 1.0,
                "is_peak": int(hour in {8, 9, 17, 18}),
                "is_weekend": int(idx % 7 in {5, 6}),
                "delay_lag_1h": delay * 0.8,
                "delay_lag_2h": delay * 0.7,
                "delay_lag_3h": delay * 0.6,
                "delay_lag_6h": delay * 0.5,
                "delay_lag_24h": delay * 0.4,
                "delay_lag_48h": delay * 0.3,
                "delay_lag_168h": delay * 0.2,
                "delay_roll3h_mean": delay * 0.8,
                "delay_roll6h_mean": delay * 0.7,
                "delay_roll24h_mean": delay * 0.6,
                "delay_roll24h_std": 0.01,
                "count_mean": 3.0,
                "count_std": 1.0,
                "delay_mean": delay * 0.7,
                "delay_std": 0.01,
                "resolution_mean": 0.7,
                "resolution_std": 0.1,
                "violation_count_vs_baseline": 0.1,
                "delay_vs_baseline": 0.2,
                "resolution_rate_vs_baseline": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_neural_risk_model_trains_on_synthetic_frame(tmp_path) -> None:
    model = NeuralRiskModel(load_config())
    result = model.train(_synthetic_features(), tmp_path, data_hash="sha256:test", version="unit", max_iter=2)

    assert result.model_path.exists()
    assert result.metadata_path.exists()
    assert result.predictions_path.exists()
    assert 0.0 <= result.metrics["val_TopK10_precision"] <= 1.0


def test_neural_comparison_flags_champion_wins() -> None:
    neural_metrics = {
        "val_MAE_delay_min": 0.5,
        "val_SpearmanR": 0.7,
        "val_TopK10_precision": 0.4,
    }
    champion = {
        "metrics": {
            "val_MAE_delay_min": 0.1,
            "val_SpearmanR": 0.9,
            "val_TopK10_precision": 0.8,
        }
    }

    comparison = compare_to_champion(neural_metrics, champion)

    assert comparison["champion_available"] is True
    assert comparison["beats_champion_mae"] is False
    assert comparison["beats_champion_spearman"] is False
    assert comparison["beats_champion_topk10"] is False
