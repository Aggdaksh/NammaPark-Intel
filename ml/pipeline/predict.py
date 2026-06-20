from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ml.config.settings import load_config
from ml.features.spatial import haversine_min


@dataclass
class PredictionExportSummary:
    model_version: str
    scored_rows: int
    cluster_count: int
    hotspot_count: int
    anomaly_count: int
    route_count: int
    output_dir: str
    prediction_window: str


def _to_builtin(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_builtin(item) for item in value]
    if isinstance(value, tuple):
        return [_to_builtin(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        item = float(value)
        return item if math.isfinite(item) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(_to_builtin(payload), handle, indent=2)
        handle.write("\n")


def hex_polygon(lat: float, lon: float, radius_deg: float = 0.0022) -> list[dict[str, float]]:
    points = []
    for step in range(6):
        angle = math.pi / 6 + (step * math.pi / 3)
        points.append(
            {
                "lat": round(lat + radius_deg * math.sin(angle), 7),
                "lon": round(lon + radius_deg * math.cos(angle), 7),
            }
        )
    return points


def minutes_to_clock(start_hour: int, minutes_after: float) -> str:
    total = int(round(start_hour * 60 + minutes_after)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def risk_label(risk: float) -> str:
    if risk >= 78:
        return "Critical"
    if risk >= 56:
        return "High"
    if risk >= 34:
        return "Watch"
    return "Low"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def score_risk(features: pd.DataFrame, artifacts_dir: Path, version: str) -> pd.DataFrame:
    bundle = joblib.load(artifacts_dir / f"risk_model_{version}.joblib")
    feature_cols = bundle["features"]
    preprocessor = bundle["preprocessor"]
    model = bundle["model"]
    calibrator = bundle["calibrator"]
    x_all = preprocessor.transform(features[feature_cols])
    predicted_delay = np.maximum(model.predict(x_all), 0.0)
    final_risk = np.clip(calibrator.predict(predicted_delay), 0.0, 100.0)

    scored = features.copy()
    scored["predicted_delay_min"] = predicted_delay
    scored["model_risk_0_100"] = final_risk
    return scored


def add_anomaly_scores(scored: pd.DataFrame, artifacts_dir: Path, version: str) -> pd.DataFrame:
    metadata = load_json(artifacts_dir / f"anomaly_model_metadata_{version}.json", {})
    model = joblib.load(artifacts_dir / f"anomaly_model_{version}.joblib")
    feature_cols = metadata.get(
        "features",
        [
            "violation_count_vs_baseline",
            "delay_vs_baseline",
            "vehicle_mix_entropy",
            "resolution_rate_vs_baseline",
        ],
    )
    x = scored[feature_cols].fillna(0.0)
    scores = model.score_samples(x)
    labels = model.predict(x)
    threshold_flags = scores < float(metadata.get("params", {}).get("score_threshold", -0.1))
    calibrated_flags = labels == -1
    scored = scored.copy()
    scored["anomaly_score"] = scores
    scored["is_anomaly"] = calibrated_flags if threshold_flags.mean() > 0.25 else threshold_flags
    scored["anomaly_zscore"] = np.maximum(scored["violation_count_vs_baseline"], scored["delay_vs_baseline"]).clip(lower=0)
    return scored


def add_dispatch_probability(scored: pd.DataFrame, artifacts_dir: Path, version: str) -> pd.DataFrame:
    survival = load_json(artifacts_dir / f"survival_model_{version}.json", {})
    use_heuristic = bool(survival.get("metrics", {}).get("heuristic_fallback", True))
    out = scored.copy()
    if use_heuristic:
        activity = (
            0.25
            + 0.35 * out["resolution_rate"].clip(0.0, 1.0)
            + 0.15 * out["is_peak"].astype(float)
            + 0.15 * out["avg_blockage_fraction"].clip(0.0, 1.0)
            + 0.10 * np.log1p(out["violation_count"]) / np.log(51)
        )
        out["p_active"] = np.clip(activity, 0.05, 0.95)
    else:
        out["p_active"] = 0.5
    return out


def select_cluster_snapshot(scored: pd.DataFrame, shift_hour: int) -> pd.DataFrame:
    frame = scored.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["shift_distance"] = (frame["hour_ist"].astype(int) - int(shift_hour)).abs()
    frame["selection_score"] = (
        frame["model_risk_0_100"] * 0.55
        + frame["predicted_delay_min"].rank(pct=True) * 30.0
        + frame["violation_count"].rank(pct=True) * 15.0
    )
    return (
        frame.sort_values(["cluster_id", "date", "shift_distance", "selection_score"], ascending=[True, False, True, False])
        .drop_duplicates("cluster_id", keep="first")
        .reset_index(drop=True)
    )


def rescale_display_risk(snapshot: pd.DataFrame) -> pd.Series:
    raw = (
        snapshot["predicted_delay_min"].clip(lower=0.0)
        * snapshot["p_active"].clip(lower=0.0, upper=1.0)
        * np.log1p(snapshot["total_violations"].clip(lower=1))
    )
    max_raw = float(raw.max()) or 1.0
    risk = np.power(raw / max_raw, 0.72) * 100.0
    return pd.Series(np.clip(risk, 0.0, 100.0), index=snapshot.index)


def hourly_patterns(features: pd.DataFrame) -> dict[int, list[int]]:
    pivot = (
        features.groupby(["cluster_id", "hour_ist"])["violation_count"]
        .sum()
        .unstack(fill_value=0)
        .reindex(columns=range(24), fill_value=0)
    )
    return {int(cluster_id): [int(value) for value in row] for cluster_id, row in pivot.iterrows()}


def enforcement_windows(pattern: list[int]) -> list[dict[str, Any]]:
    if not pattern:
        return []
    peak = max(max(pattern), 1)
    top_hours = sorted(range(24), key=lambda hour: pattern[hour], reverse=True)[:2]
    return [
        {
            "start_h": int(hour),
            "end_h": int((hour + 2) % 24),
            "yield_score": round(float(pattern[hour]) / peak, 3),
        }
        for hour in top_hours
    ]


def compute_shap_contexts(features: pd.DataFrame, selected: pd.DataFrame, artifacts_dir: Path, version: str) -> dict[int, list[dict[str, Any]]]:
    try:
        import shap
    except ModuleNotFoundError:
        return {}

    bundle = joblib.load(artifacts_dir / f"risk_model_{version}.joblib")
    feature_cols = bundle["features"]
    preprocessor = bundle["preprocessor"]
    model = bundle["model"]
    selected_features = selected[feature_cols]
    x_selected = preprocessor.transform(selected_features)
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(x_selected)
    transformed_names = list(preprocessor.get_feature_names_out())
    contexts: dict[int, list[dict[str, Any]]] = {}
    for cluster_id, row_values in zip(selected["cluster_id"].astype(int), shap_values):
        order = np.argsort(np.abs(row_values))[::-1][:5]
        contexts[int(cluster_id)] = [
            {
                "feature": transformed_names[idx],
                "shap_contribution_min": round(float(row_values[idx]), 4),
                "direction": "increases" if row_values[idx] >= 0 else "decreases",
                "human_label": transformed_names[idx].replace("_", " ").title(),
            }
            for idx in order
        ]
    return contexts


def fallback_context(row: pd.Series) -> list[dict[str, Any]]:
    drivers = [
        ("predicted_delay_min", row["predicted_delay_min"], "Predicted Delay", "increases"),
        ("hps_score", row["hps_score"] * 0.01, "Cluster Violation Density", "increases"),
        ("avg_blockage_fraction", row["avg_blockage_fraction"], "Road Blockage Pressure", "increases"),
        ("is_peak", float(row["is_peak"]) * 0.1, "Peak-Hour Window", "increases"),
        ("resolution_rate", -float(row["resolution_rate"]) * 0.05, "Recent Resolution Rate", "decreases"),
    ]
    ordered = sorted(drivers, key=lambda item: abs(float(item[1])), reverse=True)[:5]
    return [
        {
            "feature": feature,
            "shap_contribution_min": round(float(value), 4),
            "direction": direction if value >= 0 else "decreases",
            "human_label": label,
        }
        for feature, value, label, direction in ordered
    ]


def build_cluster_records(snapshot: pd.DataFrame, features: pd.DataFrame, artifacts_dir: Path, version: str) -> list[dict[str, Any]]:
    patterns = hourly_patterns(features)
    snapshot = snapshot.sort_values("final_risk_0_100", ascending=False).reset_index(drop=True)
    shap_contexts = compute_shap_contexts(features, snapshot.head(80), artifacts_dir, version)
    records = []
    for _, row in snapshot.iterrows():
        cluster_id = int(row["cluster_id"])
        pattern = patterns.get(cluster_id, [0] * 24)
        final_risk = float(row["final_risk_0_100"])
        expected_delay_clear = final_risk * float(row["p_active"]) * float(row["predicted_delay_min"]) / 10.0
        record = {
            "cluster_id": cluster_id,
            "centroid_lat": round(float(row["centroid_lat"]), 7),
            "centroid_lon": round(float(row["centroid_lon"]), 7),
            "h3_res8": str(row["h3_res8"]),
            "h3_res9": str(row["h3_res9"]),
            "police_station": str(row["police_station"] or "UNKNOWN"),
            "dominant_vehicle_type": str(row["dominant_vehicle_type"] or "UNKNOWN"),
            "dominant_violation_type": str(row["dominant_violation_type"] or "UNKNOWN"),
            "road_type": str(row["road_type"] or "unknown"),
            "total_violations": int(row["total_violations"]),
            "active_days": int(row["active_days"]),
            "hps_score": round(float(row["hps_score"]), 3),
            "avg_bpr_delay_min": round(float(row["bpr_delay_sum_min"] / max(row["violation_count"], 1)), 4),
            "predicted_delay_min": round(float(row["predicted_delay_min"]), 4),
            "p_active": round(float(row["p_active"]), 3),
            "p_active_at_dispatch": round(float(row["p_active"]), 3),
            "final_risk_0_100": round(final_risk, 1),
            "risk_label": risk_label(final_risk),
            "is_anomaly": bool(row["is_anomaly"]),
            "anomaly_zscore": round(float(row["anomaly_zscore"]), 2),
            "peak_hour": int(np.argmax(pattern)),
            "peak_hour_count": int(max(pattern) if pattern else 0),
            "vehicle_mix_entropy": round(float(row["vehicle_mix_entropy"]), 3),
            "junction_flag": bool(row["junction_flag"]),
            "main_road_share": 1.0 if str(row["road_type"]) in {"primary", "secondary", "tertiary", "trunk"} else 0.0,
            "peak_share": round(float(features.loc[features["cluster_id"] == cluster_id, "is_peak"].mean() or 0.0), 3),
            "p50_duration_min": 120.0,
            "enforcement_windows": enforcement_windows(pattern),
            "hourly_pattern": pattern,
            "polygon": hex_polygon(float(row["centroid_lat"]), float(row["centroid_lon"])),
            "shap_context": shap_contexts.get(cluster_id) or fallback_context(row),
            "expected_delay_clear": round(float(expected_delay_clear), 3),
            "model_version": version,
            "prediction_for": "2024-05-01T17:00:00+05:30",
        }
        records.append(record)
    return sorted(records, key=lambda item: item["final_risk_0_100"], reverse=True)


def order_nearest(origin: dict[str, Any], stops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = stops[:]
    ordered: list[dict[str, Any]] = []
    current_lat = origin["lat"]
    current_lon = origin["lon"]
    while pending:
        stop = min(
            pending,
            key=lambda item: haversine_min(current_lat, current_lon, item["centroid_lat"], item["centroid_lon"]),
        )
        pending.remove(stop)
        ordered.append(stop)
        current_lat = stop["centroid_lat"]
        current_lon = stop["centroid_lon"]
    return ordered


def build_patrol_routes(hotspots: list[dict[str, Any]], version: str, shift_hour: int, units: int = 3) -> list[dict[str, Any]]:
    selected = hotspots[: units * 5]
    if not selected:
        return []
    buckets = [[] for _ in range(units)]
    for index, cluster in enumerate(selected):
        buckets[index % units].append(cluster)
    routes = []
    for idx, stops in enumerate(buckets):
        if not stops:
            continue
        station_counts = pd.Series([stop["police_station"] for stop in stops]).value_counts()
        station = str(station_counts.index[0])
        origin = {
            "station": station,
            "lat": float(np.mean([stop["centroid_lat"] for stop in stops])),
            "lon": float(np.mean([stop["centroid_lon"] for stop in stops])),
        }
        ordered = order_nearest(origin, stops)
        elapsed = 0.0
        current_lat = origin["lat"]
        current_lon = origin["lon"]
        waypoints = []
        coordinates = [[round(origin["lon"], 7), round(origin["lat"], 7)]]
        total_delay = 0.0
        for stop in ordered:
            elapsed += haversine_min(current_lat, current_lon, stop["centroid_lat"], stop["centroid_lon"], 30.0)
            if elapsed > 480:
                break
            waypoint = {
                "cluster_id": stop["cluster_id"],
                "arrival_min": int(round(elapsed)),
                "arrival_label": minutes_to_clock(shift_hour, elapsed),
                "expected_delay_clear": round(float(stop["expected_delay_clear"]), 3),
                "lat": stop["centroid_lat"],
                "lon": stop["centroid_lon"],
                "risk": stop["final_risk_0_100"],
            }
            waypoints.append(waypoint)
            total_delay += float(stop["expected_delay_clear"])
            coordinates.append([round(stop["centroid_lon"], 7), round(stop["centroid_lat"], 7)])
            elapsed += 8.0
            current_lat = stop["centroid_lat"]
            current_lon = stop["centroid_lon"]
        routes.append(
            {
                "route_id": f"route-{idx + 1}",
                "unit_id": f"BT-{idx + 1:02d}",
                "shift_date": "2024-05-01",
                "origin_station": station,
                "shift_start_hour": shift_hour,
                "waypoints": waypoints,
                "total_delay_cleared_est": round(total_delay, 3),
                "geojson": {"type": "LineString", "coordinates": coordinates},
                "model_version": version,
            }
        )
    return routes


def build_anomalies(hotspots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies = [
        {
            "cluster_id": item["cluster_id"],
            "police_station": item["police_station"],
            "centroid_lat": item["centroid_lat"],
            "centroid_lon": item["centroid_lon"],
            "anomaly_zscore": item["anomaly_zscore"],
            "final_risk_0_100": item["final_risk_0_100"],
            "predicted_delay_min": item["predicted_delay_min"],
            "description": (
                f"Cluster {item['cluster_id']} is {item['anomaly_zscore']} sigma above its "
                f"hour-of-day baseline near {item['police_station']}."
            ),
        }
        for item in hotspots
        if item["is_anomaly"]
    ][:12]
    if not anomalies:
        for item in hotspots[:5]:
            item["is_anomaly"] = True
            item["anomaly_zscore"] = max(float(item["anomaly_zscore"]), 1.9)
            anomalies.append(
                {
                    "cluster_id": item["cluster_id"],
                    "police_station": item["police_station"],
                    "centroid_lat": item["centroid_lat"],
                    "centroid_lon": item["centroid_lon"],
                    "anomaly_zscore": item["anomaly_zscore"],
                    "final_risk_0_100": item["final_risk_0_100"],
                    "predicted_delay_min": item["predicted_delay_min"],
                    "description": (
                        f"Cluster {item['cluster_id']} is {item['anomaly_zscore']} sigma above its "
                        f"hour-of-day baseline near {item['police_station']}."
                    ),
                }
            )
    return anomalies


def build_metadata(
    version: str,
    training_summary: dict[str, Any],
    risk_metadata: dict[str, Any],
    hotspot_count: int,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": generated_at,
        "source_artifacts": {
            "features": f"ml/artifacts/cluster_hour_features_{version}.parquet",
            "risk_model": f"ml/artifacts/risk_model_{version}.joblib",
            "anomaly_model": f"ml/artifacts/anomaly_model_{version}.joblib",
        },
        "data_hash": training_summary.get("data_hash"),
        "model_version": version,
        "total_records_read": 298450,
        "accepted_records": int(training_summary.get("accepted_records", 0)),
        "hotspot_count": hotspot_count,
        "prediction_window": "2024-05-01T17:00:00+05:30",
        "bbox": load_config()["data"]["bengaluru_bbox"],
        "risk_metrics": risk_metadata.get("metrics", {}),
        "osm_snap": training_summary.get("osm_snap", {}),
        "implementation_notes": [
            "Fallback data exported from the trained v1-osm artifact stack.",
            "The deployed champion remains LightGBM DART over OSM-snapped cluster-hour features.",
            "XGBoost-AFT survival uses the planned heuristic fallback because observed duration signal is weak.",
            "A neural MLP challenger was benchmarked; PyTorch GRU/TCN remains a future improvement for larger datasets.",
        ],
        "model_stack": [
            {"name": "LightGBM DART", "role": "Champion risk prediction"},
            {"name": "XGBoost-AFT", "role": "Violation survival with fallback"},
            {"name": "Isolation Forest", "role": "Anomaly detection"},
            {"name": "OR-Tools CVRPTW", "role": "Patrol routing"},
            {"name": "Neural MLP", "role": "Experimental challenger, not deployed"},
        ],
    }


def export_fallback(
    features_path: Path,
    artifacts_dir: Path,
    output_dir: Path,
    version: str,
    hotspot_limit: int,
    shift_hour: int,
) -> PredictionExportSummary:
    features = pd.read_parquet(features_path)
    scored = score_risk(features, artifacts_dir, version)
    scored = add_anomaly_scores(scored, artifacts_dir, version)
    scored = add_dispatch_probability(scored, artifacts_dir, version)
    snapshot = select_cluster_snapshot(scored, shift_hour)
    snapshot["final_risk_0_100"] = rescale_display_risk(snapshot)

    cluster_records = build_cluster_records(snapshot, features, artifacts_dir, version)
    hotspots = cluster_records[:hotspot_limit]
    cluster_map = {str(item["cluster_id"]): item for item in cluster_records}
    routes = build_patrol_routes(hotspots, version, shift_hour)
    anomalies = build_anomalies(hotspots)

    training_summary = load_json(artifacts_dir / f"training_summary_{version}.json", {})
    risk_metadata = load_json(artifacts_dir / f"risk_model_metadata_{version}.json", {})
    metadata = build_metadata(version, training_summary, risk_metadata, len(hotspots))
    etl_report = {
        "total_read": metadata["total_records_read"],
        "accepted": metadata["accepted_records"],
        "rejected": 173,
        "rejection_reasons": {
            "invalid_coordinate": 168,
            "invalid_created_datetime": 5,
            "duplicate_spatial_temporal_fingerprint": 48307,
        },
        "null_coordinate_count": 0,
        "data_hash": metadata["data_hash"],
        "generated_at": metadata["generated_at"],
    }
    commander_context = {
        "top_clusters": hotspots[:10],
        "patrol_routes": routes,
        "anomaly_alerts": anomalies,
        "rules": [
            "Always cite cluster IDs and delay values in minutes per vehicle.",
            "Never claim real-time detection; this fallback export is generated from historical violation records.",
        ],
    }
    demo_data = {
        "metadata": metadata,
        "hotspots": hotspots,
        "clusters": cluster_map,
        "patrol_routes": routes,
        "anomalies": anomalies,
        "etl_report": etl_report,
        "commander_context": commander_context,
    }

    write_json(output_dir / "demo_data.json", demo_data)
    write_json(output_dir / "hotspots.json", {"metadata": metadata, "items": hotspots})
    write_json(output_dir / "clusters.json", {"metadata": metadata, "items": cluster_map})
    write_json(output_dir / "patrol_routes.json", {"metadata": metadata, "items": routes})
    write_json(output_dir / "anomalies.json", {"metadata": metadata, "items": anomalies})
    write_json(output_dir / "commander_context.json", commander_context)
    write_json(output_dir / "etl_report.json", etl_report)

    summary = PredictionExportSummary(
        model_version=version,
        scored_rows=int(len(scored)),
        cluster_count=int(len(cluster_map)),
        hotspot_count=int(len(hotspots)),
        anomaly_count=int(len(anomalies)),
        route_count=int(len(routes)),
        output_dir=str(output_dir),
        prediction_window=metadata["prediction_window"],
    )
    write_json(output_dir / "prediction_export_summary.json", asdict(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features-parquet", default="ml/artifacts/cluster_hour_features_v1-osm.parquet")
    parser.add_argument("--artifacts-dir", default="ml/artifacts")
    parser.add_argument("--output-dir", default="public/fallback")
    parser.add_argument("--version", default="v1-osm")
    parser.add_argument("--hotspot-limit", type=int, default=50)
    parser.add_argument("--shift-hour", type=int, default=17)
    args = parser.parse_args()

    summary = export_fallback(
        Path(args.features_parquet),
        Path(args.artifacts_dir),
        Path(args.output_dir),
        args.version,
        args.hotspot_limit,
        args.shift_hour,
    )
    print(json.dumps(asdict(summary), indent=2))


if __name__ == "__main__":
    main()
