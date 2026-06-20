from __future__ import annotations

import pandas as pd

from ml.config.settings import load_config
from ml.features.temporal import add_temporal_features


def test_temporal_features_use_configured_lags_and_flags() -> None:
    config = load_config()
    frame = pd.DataFrame(
        {
            "cluster_id": [1, 1, 1],
            "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"]),
            "hour_ist": [8, 9, 10],
            "day_of_week": [0, 5, 6],
            "month": [1, 1, 1],
            "bpr_delay_sum_min": [1.0, 2.0, 4.0],
        }
    )

    out = add_temporal_features(frame, config)

    assert {"hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos"} <= set(out.columns)
    assert out["is_peak"].tolist() == [1, 1, 1]
    assert out["is_weekend"].tolist() == [0, 1, 1]
    assert out["delay_lag_1h"].tolist() == [0.0, 1.0, 2.0]
    assert "delay_roll24h_std" in out.columns
