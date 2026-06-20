from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.config.settings import load_config
from ml.features.network import compute_blockage_fraction, severity_factor_for
from ml.features.spatial import OSMSnapResult, snap_points_to_osm
from ml.features.temporal import add_temporal_features
from ml.models.anomaly_model import AnomalyModel
from ml.models.risk_model import ModelQualityError, RiskModel
from ml.models.survival_model import SurvivalModel
from ml.models.vrp_router import PatrolRouter
from ml.pipeline.etl import Validator, clean_raw_df, sha256_file


@dataclass
class TrainSummary:
    data_hash: str
    accepted_records: int
    cluster_count: int
    cluster_hour_rows: int
    osm_snap: dict[str, Any]
    risk_metrics: dict[str, float]
    survival_metrics: dict[str, Any]
    anomaly_flagged_rate: float
    patrol_routes: int
    artifacts_dir: str


def _h3_cell(lat: float, lon: float, res: int) -> str:
    import h3

    if hasattr(h3, "latlng_to_cell"):
        return h3.latlng_to_cell(lat, lon, res)
    return h3.geo_to_h3(lat, lon, res)


def _entropy(values: pd.Series) -> float:
    counts = values.value_counts()
    total = counts.sum()
    if total <= 0:
        return 0.0
    probs = counts / total
    return float(-(probs * np.log2(probs)).sum())


def _mode(values: pd.Series, default: str = "UNKNOWN") -> str:
    clean = values.dropna().astype(str)
    if clean.empty:
        return default
    return str(clean.value_counts().idxmax())


def load_osm_graph(graph_path: Path):
    if not graph_path.exists():
        raise FileNotFoundError(
            f"OSM graph not found at {graph_path}. Run ml.pipeline.download_graph after approval first."
        )
    import osmnx as ox

    return ox.load_graphml(graph_path)


def _junction_name_flag(values: pd.Series) -> pd.Series:
    text = values.fillna("").astype(str)
    return text.str.contains("JUNCTION", case=False) & ~text.str.contains("NO JUNCTION", case=False)


def _apply_fallback_road_features(df: pd.DataFrame, config: dict[str, Any]) -> None:
    osm_cfg = config["features"]["osmnx"]
    df["osm_way_id"] = None
    df["road_type"] = str(osm_cfg["fallback_road_type"])
    df["lane_count"] = int(osm_cfg["fallback_lane_count"])
    df["speed_limit_kph"] = float(osm_cfg["fallback_speed_limit_kph"])
    df["segment_length_m"] = float(osm_cfg["fallback_segment_length_m"])
    df["snap_distance_m"] = np.nan
    df["osm_snap_fallback"] = True
    df["junction_flag"] = _junction_name_flag(df["junction_name"])


def _apply_osm_road_features(df: pd.DataFrame, graph: Any, config: dict[str, Any]) -> None:
    snap_results = snap_points_to_osm(
        df["latitude"].astype(float).to_numpy(),
        df["longitude"].astype(float).to_numpy(),
        graph,
        config,
    )
    for field_name in OSMSnapResult.__dataclass_fields__:
        df[field_name] = [getattr(result, field_name) for result in snap_results]
    df["junction_flag"] = df["junction_flag"].astype(bool) | _junction_name_flag(df["junction_name"])


def build_violation_frame(
    csv_path: Path,
    config: dict[str, Any],
    max_rows: int | None = None,
    graph: Any | None = None,
) -> pd.DataFrame:
    import h3

    usecols = [
        "id",
        "latitude",
        "longitude",
        "location",
        "vehicle_type",
        "violation_type",
        "created_datetime",
        "closed_datetime",
        "modified_datetime",
        "police_station",
        "junction_name",
        "action_taken_timestamp",
        "validation_status",
    ]
    raw = pd.read_csv(csv_path, usecols=usecols, low_memory=False)
    if max_rows:
        raw = raw.head(max_rows).copy()
    cleaned = clean_raw_df(raw)
    validator = Validator(config)
    validation_results = cleaned.apply(validator.validate_record, axis=1)
    valid_mask = validation_results.map(lambda item: item.is_valid)
    df = cleaned.loc[valid_mask].copy()
    df["vehicle_type"] = [item.vehicle_type for item in validation_results.loc[valid_mask]]

    h3_cfg = config["features"]["h3"]
    df["dominant_violation_type"] = df["dominant_violation_type"].fillna("UNKNOWN")
    df["created_ist"] = df["created_datetime"].dt.tz_convert("Asia/Kolkata")
    df["action_taken_ist"] = df["action_taken_timestamp"].dt.tz_convert("Asia/Kolkata")
    df["date"] = df["created_ist"].dt.date.astype(str)
    df["hour_ist"] = df["created_ist"].dt.hour.astype(int)
    df["day_of_week"] = df["created_ist"].dt.dayofweek.astype(int)
    df["month"] = df["created_ist"].dt.month.astype(int)
    h3_fn = h3.latlng_to_cell if hasattr(h3, "latlng_to_cell") else h3.geo_to_h3
    primary_res = int(h3_cfg["primary_resolution"])
    secondary_res = int(h3_cfg["secondary_resolution"])
    df["h3_res8"] = [h3_fn(float(lat), float(lon), primary_res) for lat, lon in zip(df["latitude"], df["longitude"])]
    df["h3_res9"] = [h3_fn(float(lat), float(lon), secondary_res) for lat, lon in zip(df["latitude"], df["longitude"])]
    cluster_codes, cluster_uniques = pd.factorize(df["h3_res8"], sort=True)
    df["cluster_id"] = cluster_codes + 1
    if graph is None:
        _apply_fallback_road_features(df, config)
    else:
        _apply_osm_road_features(df, graph, config)
    df["severity_factor"] = df["violation_types"].map(lambda labels: severity_factor_for(labels, config))
    df["blockage_fraction"] = [
        compute_blockage_fraction(severity, lane_count)
        for severity, lane_count in zip(df["severity_factor"], df["lane_count"])
    ]
    alpha = float(config["features"]["bpr"]["alpha"])
    beta = float(config["features"]["bpr"]["beta"])
    free_flow_time_min = df["segment_length_m"] / (df["speed_limit_kph"] * 1000.0 / 60.0)
    df["bpr_delay_min"] = free_flow_time_min * alpha * np.power(df["blockage_fraction"], beta)
    df["cluster_key"] = df["h3_res8"].map({value: idx + 1 for idx, value in enumerate(cluster_uniques)})
    return df


def build_cluster_hour_features(violations: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    cluster_meta = (
        violations.groupby("cluster_id")
        .agg(
            centroid_lat=("latitude", "mean"),
            centroid_lon=("longitude", "mean"),
            h3_res8=("h3_res8", "first"),
            h3_res9=("h3_res9", "first"),
            police_station=("police_station", _mode),
            dominant_vehicle_type=("vehicle_type", _mode),
            dominant_violation_type=("dominant_violation_type", _mode),
            road_type=("road_type", "first"),
            total_violations=("id", "count"),
            active_days=("date", "nunique"),
            junction_flag=("junction_flag", "mean"),
        )
        .reset_index()
    )
    cluster_meta["hps_score"] = cluster_meta["total_violations"] / cluster_meta["active_days"].clip(lower=1)
    cluster_meta["junction_flag"] = cluster_meta["junction_flag"] >= 0.3

    hourly = (
        violations.groupby(["cluster_id", "date", "hour_ist"], as_index=False)
        .agg(
            violation_count=("id", "count"),
            bpr_delay_sum_min=("bpr_delay_min", "sum"),
            avg_blockage_fraction=("blockage_fraction", "mean"),
            vehicle_mix_entropy=("vehicle_type", _entropy),
            resolution_rate=("action_taken_ist", lambda values: float(values.notna().mean())),
        )
        .merge(cluster_meta, on="cluster_id", how="left")
    )
    hourly["date"] = pd.to_datetime(hourly["date"])
    hourly["day_of_week"] = hourly["date"].dt.dayofweek
    hourly["month"] = hourly["date"].dt.month
    hourly = add_temporal_features(hourly, config)
    baseline = hourly.groupby(["cluster_id", "hour_ist"]).agg(
        count_mean=("violation_count", "mean"),
        count_std=("violation_count", "std"),
        delay_mean=("bpr_delay_sum_min", "mean"),
        delay_std=("bpr_delay_sum_min", "std"),
        resolution_mean=("resolution_rate", "mean"),
        resolution_std=("resolution_rate", "std"),
    )
    hourly = hourly.join(baseline, on=["cluster_id", "hour_ist"])
    hourly["violation_count_vs_baseline"] = (hourly["violation_count"] - hourly["count_mean"]) / hourly[
        "count_std"
    ].replace(0, np.nan)
    hourly["delay_vs_baseline"] = (hourly["bpr_delay_sum_min"] - hourly["delay_mean"]) / hourly["delay_std"].replace(
        0, np.nan
    )
    hourly["resolution_rate_vs_baseline"] = (hourly["resolution_rate"] - hourly["resolution_mean"]) / hourly[
        "resolution_std"
    ].replace(0, np.nan)
    hourly = hourly.fillna(0.0)
    hourly["date"] = hourly["date"].dt.strftime("%Y-%m-%d")
    return hourly, cluster_meta


def build_station_origins(cluster_meta: pd.DataFrame) -> pd.DataFrame:
    stations = (
        cluster_meta.groupby("police_station", as_index=False)
        .agg(lat=("centroid_lat", "mean"), lon=("centroid_lon", "mean"), cluster_count=("cluster_id", "count"))
        .sort_values("cluster_count", ascending=False)
        .rename(columns={"police_station": "station"})
    )
    return stations


def _summarise_osm_snap(violations: pd.DataFrame, graph_path: Path | None, enabled: bool) -> dict[str, Any]:
    fallback_rate = None
    median_snap_distance_m = None
    if "osm_snap_fallback" in violations:
        fallback_rate = float(violations["osm_snap_fallback"].mean())
    if "snap_distance_m" in violations:
        distances = pd.to_numeric(violations["snap_distance_m"], errors="coerce").dropna()
        if not distances.empty:
            median_snap_distance_m = float(distances.median())
    return {
        "enabled": enabled,
        "graph_path": str(graph_path) if graph_path else None,
        "fallback_rate": fallback_rate,
        "median_snap_distance_m": median_snap_distance_m,
    }


def train_all(
    csv_path: Path,
    artifacts_dir: Path,
    max_rows: int | None,
    version: str,
    *,
    use_osm_snap: bool = False,
    graph_path: Path | None = None,
) -> TrainSummary:
    config = load_config()
    data_hash = f"sha256:{sha256_file(csv_path)}"
    resolved_graph_path = graph_path or Path(config["features"]["osmnx"]["graph_path"])
    graph = load_osm_graph(resolved_graph_path) if use_osm_snap else None
    violations = build_violation_frame(csv_path, config, max_rows=max_rows, graph=graph)
    features, cluster_meta = build_cluster_hour_features(violations, config)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    features.to_parquet(artifacts_dir / f"cluster_hour_features_{version}.parquet", index=False)
    cluster_meta.to_parquet(artifacts_dir / f"spatial_clusters_{version}.parquet", index=False)

    risk = RiskModel(config)
    risk_result = risk.train(features, artifacts_dir, data_hash, version)

    survival = SurvivalModel(config)
    survival_result = survival.train(violations, artifacts_dir, version)

    anomaly = AnomalyModel(config)
    anomaly_result = anomaly.train(features, artifacts_dir, version)

    latest = (
        risk_result.predictions.sort_values("final_risk_0_100", ascending=False)
        .drop_duplicates("cluster_id")
        .merge(cluster_meta, on=["cluster_id", "centroid_lat", "centroid_lon"], how="left", suffixes=("", "_meta"))
        .merge(survival_result.cluster_active_probability, on="cluster_id", how="left")
    )
    latest["p_active_at_dispatch"] = latest["p_active_at_dispatch"].fillna(0.5)
    latest["expected_delay_clear"] = (
        latest["final_risk_0_100"] * latest["p_active_at_dispatch"] * latest["predicted_delay_min"] / 10.0
    )
    latest.to_parquet(artifacts_dir / f"cluster_predictions_{version}.parquet", index=False)

    router = PatrolRouter(config)
    routes = router.build_routes(
        latest.sort_values("final_risk_0_100", ascending=False),
        build_station_origins(cluster_meta),
        num_units=int(config["models"]["vrp"]["default_units"]),
        version=version,
        artifacts_dir=artifacts_dir,
    )

    summary = TrainSummary(
        data_hash=data_hash,
        accepted_records=int(len(violations)),
        cluster_count=int(cluster_meta["cluster_id"].nunique()),
        cluster_hour_rows=int(len(features)),
        osm_snap=_summarise_osm_snap(violations, resolved_graph_path if use_osm_snap else None, use_osm_snap),
        risk_metrics=risk_result.metrics,
        survival_metrics=survival_result.metrics,
        anomaly_flagged_rate=float(anomaly_result.scored_features["is_anomaly"].mean()),
        patrol_routes=len(routes.routes),
        artifacts_dir=str(artifacts_dir),
    )
    (artifacts_dir / f"training_summary_{version}.json").write_text(
        json.dumps(asdict(summary), indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="../jan to may police violation_anonymized791b166.csv")
    parser.add_argument("--artifacts-dir", default="ml/artifacts")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--use-osm-snap", action="store_true")
    parser.add_argument("--graph-path", default=None)
    args = parser.parse_args()
    try:
        summary = train_all(
            Path(args.csv),
            Path(args.artifacts_dir),
            args.max_rows,
            args.version,
            use_osm_snap=args.use_osm_snap,
            graph_path=Path(args.graph_path) if args.graph_path else None,
        )
    except ModelQualityError as exc:
        print(json.dumps({"status": "failed_quality_gate", "detail": str(exc)}, indent=2))
        raise
    print(json.dumps(asdict(summary), indent=2))


if __name__ == "__main__":
    main()
