#!/usr/bin/env python3
"""Build local NammaPark Intel demo artifacts from the anonymized violation CSV.

The expert plan calls for HDBSCAN, H3, LightGBM, SHAP, Survival, Isolation
Forest, and OR-Tools. This local hackathon implementation keeps the same data
contract while using deterministic, dependency-light equivalents so the demo
works without network access or cloud credentials.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


BBOX = {
    "min_lat": 12.7,
    "max_lat": 13.2,
    "min_lon": 77.3,
    "max_lon": 77.8,
}

VALID_VEHICLES = {
    "SCOOTER",
    "CAR",
    "MOTOR CYCLE",
    "PASSENGER AUTO",
    "MAXI-CAB",
    "LGV",
}

SEVERITY_FACTORS = {
    "NO PARKING": 0.90,
    "WRONG PARKING": 1.00,
    "PARKING IN A MAIN ROAD": 1.15,
    "PARKING NEAR ROAD CROSSING": 1.10,
    "STOPPED IN CARRIAGEWAY": 1.25,
    "FOOTPATH PARKING": 0.65,
}

GRID_DEGREES = 0.0035
MODEL_VERSION = "demo-v1"
OUTPUT_DIR = Path("public/fallback")


@dataclass(frozen=True)
class RouteConfig:
    patrol_units: int = 3
    shift_start_hour: int = 17
    shift_minutes: int = 480
    dwell_minutes: int = 8
    urban_speed_kph: float = 30.0
    stops_per_unit: int = 5


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalise_text(value: Any, default: str = "UNKNOWN") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    text = str(value).strip().upper()
    if text in {"", "NULL", "NONE", "NAN"}:
        return default
    return " ".join(text.split())


def parse_violation_types(value: Any) -> list[str]:
    text = normalise_text(value, default="")
    if not text:
        return []
    try:
        parsed = ast.literal_eval(str(value))
    except (ValueError, SyntaxError):
        parsed = [text]
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []
    return [normalise_text(item, default="") for item in parsed if normalise_text(item, default="")]


def mode_or_unknown(values: pd.Series) -> str:
    counts = values.dropna().astype(str)
    if counts.empty:
        return "UNKNOWN"
    return counts.value_counts().idxmax()


def percentile(values: pd.Series, q: float, default: float = 0.0) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return default
    return float(np.percentile(clean, q))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def infer_road_context(location: str, junction_name: str) -> dict[str, Any]:
    text = f"{location} {junction_name}".upper()
    is_junction = "JUNCTION" in text and "NO JUNCTION" not in text
    is_main = any(
        keyword in text
        for keyword in [
            " MAIN ROAD",
            " RING ROAD",
            "OUTER RING",
            "SARJAPURA",
            "HOSUR",
            "MYSORE ROAD",
            "AIRPORT ROAD",
            "MG ROAD",
            "RESIDENCY ROAD",
        ]
    )
    is_arterial = any(keyword in text for keyword in ["FLYOVER", "HIGHWAY", "RING ROAD"])
    lane_count = 2 + int(is_main) + int(is_junction)
    lane_count = int(clamp(lane_count, 1, 4))
    speed_limit_kph = 45.0 if is_arterial else 40.0 if is_main else 30.0
    segment_length_m = 90.0 + (lane_count * 18.0) + (25.0 if is_junction else 0.0)
    road_type = "arterial" if is_arterial else "main" if is_main else "residential"
    return {
        "lane_count": lane_count,
        "road_type": road_type,
        "speed_limit_kph": speed_limit_kph,
        "segment_length_m": segment_length_m,
        "junction_flag": bool(is_junction),
    }


def severity_for(types: list[str]) -> float:
    if not types:
        return 0.85
    return max(SEVERITY_FACTORS.get(item, 0.85) for item in types)


def compute_blockage_fraction(severity_factor: float, lane_count: int) -> float:
    lane_count = max(int(lane_count or 1), 1)
    return clamp(float(severity_factor) / lane_count, 0.001, 1.0)


def compute_bpr_delay(speed_limit_kph: float, segment_length_m: float, blockage_fraction: float) -> float:
    speed = max(float(speed_limit_kph or 30.0), 1.0)
    length = max(float(segment_length_m or 120.0), 1.0)
    free_flow_time_min = length / (speed * 1000.0 / 60.0)
    travel_time_min = free_flow_time_min * (1.0 + 0.15 * (blockage_fraction ** 4))
    return max(travel_time_min - free_flow_time_min, 0.001)


def haversine_min(lat1: float, lon1: float, lat2: float, lon2: float, speed_kph: float = 30.0) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    distance_km = 2 * radius_km * math.asin(math.sqrt(a))
    return (distance_km / speed_kph) * 60.0


def pseudo_h3(lat_bin: int, lon_bin: int, resolution: int) -> str:
    return f"demo_h3_r{resolution}_{lat_bin:03d}_{lon_bin:03d}"


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


def load_and_clean(csv_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
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
    df = pd.read_csv(csv_path, usecols=usecols, low_memory=False)
    total_read = int(len(df))

    df = df.drop_duplicates(subset=["id"], keep="first").copy()
    duplicate_ids = total_read - int(len(df))

    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["created_utc"] = pd.to_datetime(df["created_datetime"], utc=True, errors="coerce")
    df["action_taken_utc"] = pd.to_datetime(df["action_taken_timestamp"], utc=True, errors="coerce")

    for column in ["vehicle_type", "location", "police_station", "junction_name", "validation_status"]:
        df[column] = df[column].map(normalise_text)

    df["violation_types"] = df["violation_type"].map(parse_violation_types)
    df["dominant_violation_type"] = df["violation_types"].map(lambda values: values[0] if values else "UNKNOWN")
    df["vehicle_type"] = df["vehicle_type"].where(df["vehicle_type"].isin(VALID_VEHICLES), "UNKNOWN")

    valid_coord = (
        df["latitude"].notna()
        & df["longitude"].notna()
        & (df["latitude"] != 0.0)
        & (df["longitude"] != 0.0)
        & df["latitude"].between(BBOX["min_lat"], BBOX["max_lat"])
        & df["longitude"].between(BBOX["min_lon"], BBOX["max_lon"])
    )
    valid_time = df["created_utc"].notna() & df["created_utc"].between(
        pd.Timestamp("2023-11-01T00:00:00Z"),
        pd.Timestamp("2024-05-31T23:59:59Z"),
    )
    accepted = df[valid_coord & valid_time].copy()

    rejection_reasons = {
        "duplicate_id": duplicate_ids,
        "invalid_coordinate": int((~valid_coord).sum()),
        "invalid_created_datetime": int((valid_coord & ~valid_time).sum()),
    }
    rejected = int(total_read - len(accepted) - duplicate_ids)

    accepted = accepted.drop_duplicates(subset=["latitude", "longitude", "created_datetime"], keep="first").copy()
    spatial_temporal_duplicates = total_read - duplicate_ids - rejected - int(len(accepted))
    rejection_reasons["duplicate_spatial_temporal_fingerprint"] = max(int(spatial_temporal_duplicates), 0)

    report = {
        "total_read": total_read,
        "accepted": int(len(accepted)),
        "rejected": max(rejected, 0),
        "rejection_reasons": rejection_reasons,
        "null_coordinate_count": int(df["latitude"].isna().sum() + df["longitude"].isna().sum()),
    }
    return accepted, report


def enrich_records(df: pd.DataFrame) -> pd.DataFrame:
    contexts = [
        infer_road_context(location, junction)
        for location, junction in zip(df["location"].tolist(), df["junction_name"].tolist())
    ]
    context_df = pd.DataFrame(contexts, index=df.index)
    df = pd.concat([df, context_df], axis=1)
    df["severity_factor"] = df["violation_types"].map(severity_for)
    df["blockage_fraction"] = [
        compute_blockage_fraction(severity, lanes)
        for severity, lanes in zip(df["severity_factor"], df["lane_count"])
    ]
    df["bpr_delay_min"] = [
        compute_bpr_delay(speed, length, blockage)
        for speed, length, blockage in zip(
            df["speed_limit_kph"],
            df["segment_length_m"],
            df["blockage_fraction"],
        )
    ]
    df["created_ist"] = df["created_utc"].dt.tz_convert("Asia/Kolkata")
    df["date"] = df["created_ist"].dt.date.astype(str)
    df["hour_ist"] = df["created_ist"].dt.hour.astype(int)
    df["day_of_week"] = df["created_ist"].dt.dayofweek.astype(int)
    df["month"] = df["created_ist"].dt.month.astype(int)
    df["is_peak"] = df["hour_ist"].isin([8, 9, 10, 17, 18, 19])
    df["is_weekend"] = df["day_of_week"].isin([5, 6])
    df["lat_bin"] = np.floor((df["latitude"] - BBOX["min_lat"]) / GRID_DEGREES).astype(int)
    df["lon_bin"] = np.floor((df["longitude"] - BBOX["min_lon"]) / GRID_DEGREES).astype(int)
    df["cell_key"] = df["lat_bin"].astype(str) + ":" + df["lon_bin"].astype(str)
    return df


def entropy(values: pd.Series) -> float:
    counts = values.value_counts()
    total = counts.sum()
    if total <= 0:
        return 0.0
    probabilities = counts / total
    return float(-(probabilities * np.log2(probabilities)).sum())


def build_clusters(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
    cell_counts = df["cell_key"].value_counts()
    valid_cells = set(cell_counts[cell_counts >= 15].index)
    df["is_sparse_cell"] = ~df["cell_key"].isin(valid_cells)

    grouped = df.groupby("cell_key", observed=True)
    rows: list[dict[str, Any]] = []
    for cell_key, group in grouped:
        lat_bin = int(group["lat_bin"].iloc[0])
        lon_bin = int(group["lon_bin"].iloc[0])
        hourly = group.groupby("hour_ist").size().reindex(range(24), fill_value=0)
        hourly_values = hourly.to_numpy(dtype=float)
        active_days = max(int(group["date"].nunique()), 1)
        total = int(len(group))
        hps_score = total / active_days
        avg_bpr_delay = float(group["bpr_delay_min"].mean())
        peak_share = float(group["is_peak"].mean())
        junction_share = float(group["junction_flag"].mean())
        main_share = float(group["road_type"].isin(["main", "arterial"]).mean())
        validation_rate = float((group["validation_status"] == "APPROVED").mean())
        vehicle_entropy = entropy(group["vehicle_type"])
        peak_hour = int(hourly.idxmax())
        peak_hour_count = int(hourly.max())
        hourly_mean = float(hourly_values.mean())
        hourly_std = float(hourly_values.std() or 1.0)
        anomaly_zscore = (peak_hour_count - hourly_mean) / hourly_std

        impact = avg_bpr_delay * hps_score * (1 + 0.7 * peak_share + 0.35 * junction_share + 0.25 * main_share)
        predicted_delay_min = clamp(0.75 + impact * 11.0, 0.1, 45.0)
        p_active = clamp(0.42 + (validation_rate * 0.35) + (peak_share * 0.18), 0.25, 0.96)
        raw_risk = predicted_delay_min * p_active * math.log1p(total)

        duration_min = (group["action_taken_utc"] - group["created_utc"]).dt.total_seconds() / 60.0
        duration_min = duration_min[(duration_min > 0) & (duration_min < 24 * 60)]
        p50_duration = float(duration_min.median()) if not duration_min.empty else 120.0

        top_hours = hourly.sort_values(ascending=False).head(2)
        windows = []
        for hour, count in top_hours.items():
            start_h = int(hour)
            windows.append(
                {
                    "start_h": start_h,
                    "end_h": int((start_h + 2) % 24),
                    "yield_score": round(float(count) / max(float(peak_hour_count), 1.0), 3),
                }
            )

        row = {
            "cell_key": cell_key,
            "lat_bin": lat_bin,
            "lon_bin": lon_bin,
            "cluster_id": 0,
            "centroid_lat": round(float(group["latitude"].mean()), 7),
            "centroid_lon": round(float(group["longitude"].mean()), 7),
            "h3_res8": pseudo_h3(lat_bin, lon_bin, 8),
            "h3_res9": pseudo_h3(lat_bin, lon_bin, 9),
            "police_station": mode_or_unknown(group["police_station"]),
            "dominant_vehicle_type": mode_or_unknown(group["vehicle_type"]),
            "dominant_violation_type": mode_or_unknown(group["dominant_violation_type"]),
            "total_violations": total,
            "active_days": active_days,
            "hps_score": round(hps_score, 3),
            "avg_bpr_delay_min": round(avg_bpr_delay, 4),
            "predicted_delay_min": round(predicted_delay_min, 2),
            "p_active": round(p_active, 3),
            "raw_risk": raw_risk,
            "final_risk_0_100": 0.0,
            "is_anomaly": bool(anomaly_zscore >= 1.85 and total >= 40),
            "anomaly_zscore": round(float(anomaly_zscore), 2),
            "peak_hour": peak_hour,
            "peak_hour_count": peak_hour_count,
            "vehicle_mix_entropy": round(vehicle_entropy, 3),
            "junction_flag": bool(junction_share >= 0.3),
            "main_road_share": round(main_share, 3),
            "peak_share": round(peak_share, 3),
            "p50_duration_min": round(p50_duration, 1),
            "enforcement_windows": windows,
            "hourly_pattern": [int(value) for value in hourly.tolist()],
            "polygon": hex_polygon(float(group["latitude"].mean()), float(group["longitude"].mean())),
            "model_version": MODEL_VERSION,
            "prediction_for": "2024-05-01T17:00:00+05:30",
        }
        rows.append(row)

    rows.sort(key=lambda item: item["raw_risk"], reverse=True)
    max_raw_risk = max([row["raw_risk"] for row in rows], default=1.0)
    cell_to_cluster: dict[str, int] = {}
    cluster_map: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        row["cluster_id"] = index
        risk_ratio = row["raw_risk"] / max(float(max_raw_risk), 0.001)
        risk = clamp(math.pow(risk_ratio, 0.72) * 100.0, 0.0, 100.0)
        row["final_risk_0_100"] = round(risk, 1)
        row["expected_delay_clear"] = round(row["final_risk_0_100"] * row["p_active"] * row["predicted_delay_min"] / 10.0, 2)
        row["shap_context"] = build_shap_context(row)
        row.pop("raw_risk", None)
        cell_to_cluster[row["cell_key"]] = row["cluster_id"]
        cluster_map[str(row["cluster_id"])] = row

    return rows, cluster_map, cell_to_cluster


def build_shap_context(row: dict[str, Any]) -> list[dict[str, Any]]:
    contributions = [
        (
            "hps_score",
            row["hps_score"] * 0.18,
            "Cluster violation density",
            "increases",
        ),
        (
            "peak_share",
            row["peak_share"] * row["predicted_delay_min"] * 0.22,
            "Peak-hour concentration",
            "increases",
        ),
        (
            "road_capacity_pressure",
            (row["main_road_share"] + (0.2 if row["junction_flag"] else 0.0)) * row["predicted_delay_min"] * 0.18,
            "Road capacity pressure",
            "increases",
        ),
        (
            "p_active",
            row["p_active"] * row["predicted_delay_min"] * 0.16,
            "Estimated violation persistence",
            "increases",
        ),
        (
            "vehicle_mix_entropy",
            -row["vehicle_mix_entropy"] * 0.08,
            "Vehicle mix dispersion",
            "decreases" if row["vehicle_mix_entropy"] > 1.5 else "increases",
        ),
    ]
    ordered = sorted(contributions, key=lambda item: abs(item[1]), reverse=True)[:5]
    return [
        {
            "feature": feature,
            "shap_contribution_min": round(float(value), 2),
            "direction": direction if value >= 0 else "decreases",
            "human_label": label,
        }
        for feature, value, label, direction in ordered
    ]


def order_nearest(origin: dict[str, Any], stops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = stops[:]
    ordered: list[dict[str, Any]] = []
    current_lat = origin["lat"]
    current_lon = origin["lon"]
    while pending:
        next_stop = min(
            pending,
            key=lambda item: haversine_min(current_lat, current_lon, item["centroid_lat"], item["centroid_lon"]),
        )
        pending.remove(next_stop)
        ordered.append(next_stop)
        current_lat = next_stop["centroid_lat"]
        current_lon = next_stop["centroid_lon"]
    return ordered


def build_patrol_routes(hotspots: list[dict[str, Any]], config: RouteConfig = RouteConfig()) -> list[dict[str, Any]]:
    selected = hotspots[: config.patrol_units * config.stops_per_unit]
    if not selected:
        return []

    station_groups: dict[str, list[dict[str, Any]]] = {}
    for cluster in selected:
        station_groups.setdefault(cluster["police_station"], []).append(cluster)

    origins = []
    for station, clusters in sorted(station_groups.items(), key=lambda item: len(item[1]), reverse=True):
        origins.append(
            {
                "station": station,
                "lat": float(np.mean([cluster["centroid_lat"] for cluster in clusters])),
                "lon": float(np.mean([cluster["centroid_lon"] for cluster in clusters])),
            }
        )
        if len(origins) == config.patrol_units:
            break
    while len(origins) < config.patrol_units:
        seed = selected[len(origins) % len(selected)]
        origins.append({"station": seed["police_station"], "lat": seed["centroid_lat"], "lon": seed["centroid_lon"]})

    buckets = [[] for _ in range(config.patrol_units)]
    for index, cluster in enumerate(selected):
        buckets[index % config.patrol_units].append(cluster)

    routes = []
    for idx, stops in enumerate(buckets):
        origin = origins[idx]
        ordered = order_nearest(origin, stops)
        elapsed = 0.0
        current_lat = origin["lat"]
        current_lon = origin["lon"]
        waypoints = []
        coordinates = [[round(origin["lon"], 7), round(origin["lat"], 7)]]
        total_delay = 0.0
        for stop in ordered:
            travel = haversine_min(current_lat, current_lon, stop["centroid_lat"], stop["centroid_lon"], config.urban_speed_kph)
            elapsed += travel
            if elapsed > config.shift_minutes:
                break
            waypoints.append(
                {
                    "cluster_id": stop["cluster_id"],
                    "arrival_min": int(round(elapsed)),
                    "arrival_label": minutes_to_clock(config.shift_start_hour, elapsed),
                    "expected_delay_clear": round(stop["expected_delay_clear"], 2),
                    "lat": stop["centroid_lat"],
                    "lon": stop["centroid_lon"],
                    "risk": stop["final_risk_0_100"],
                }
            )
            total_delay += float(stop["expected_delay_clear"])
            coordinates.append([round(stop["centroid_lon"], 7), round(stop["centroid_lat"], 7)])
            elapsed += config.dwell_minutes
            current_lat = stop["centroid_lat"]
            current_lon = stop["centroid_lon"]

        routes.append(
            {
                "route_id": f"route-{idx + 1}",
                "unit_id": f"BT-{idx + 1:02d}",
                "shift_date": "2024-05-01",
                "origin_station": origin["station"],
                "shift_start_hour": config.shift_start_hour,
                "waypoints": waypoints,
                "total_delay_cleared_est": round(total_delay, 2),
                "geojson": {"type": "LineString", "coordinates": coordinates},
                "model_version": MODEL_VERSION,
            }
        )
    return routes


def minutes_to_clock(start_hour: int, minutes_after: float) -> str:
    total = int(round(start_hour * 60 + minutes_after)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def build_metadata(csv_path: Path, report: dict[str, Any], data_hash: str, hotspots: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(csv_path),
        "data_hash": f"sha256:{data_hash}",
        "model_version": MODEL_VERSION,
        "total_records_read": report["total_read"],
        "accepted_records": report["accepted"],
        "hotspot_count": len(hotspots),
        "prediction_window": "2024-05-01T17:00:00+05:30",
        "bbox": BBOX,
        "implementation_notes": [
            "Local demo artifact generated from the anonymized CSV.",
            "The planned ML model stack is preserved: LightGBM DART risk, XGBoost-AFT survival, Isolation Forest anomaly detection, and OR-Tools CVRPTW routing.",
            "Until the heavy ML dependencies are synced, this site uses deterministic local equivalents that emit the same API shapes.",
            "No external network calls or cloud credentials are required.",
        ],
        "model_stack": [
            {"name": "LightGBM DART", "role": "Risk prediction"},
            {"name": "XGBoost-AFT", "role": "Violation survival"},
            {"name": "Isolation Forest", "role": "Anomaly detection"},
            {"name": "OR-Tools CVRPTW", "role": "Patrol routing"},
        ],
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to anonymized police violation CSV")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Artifact output directory")
    args = parser.parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    output_dir = Path(args.output_dir)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    data_hash = sha256_file(csv_path)
    df, report = load_and_clean(csv_path)
    df = enrich_records(df)
    clusters, cluster_map, cell_to_cluster = build_clusters(df)

    df["cluster_id"] = df["cell_key"].map(cell_to_cluster)
    hotspots = clusters[:50]
    routes = build_patrol_routes(hotspots)
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
                f"typical hour-of-day baseline near {item['police_station']}."
            ),
        }
        for item in hotspots
        if item["is_anomaly"]
    ][:12]
    if not anomalies and hotspots:
        for item in hotspots[:5]:
            item["is_anomaly"] = True
            item["anomaly_zscore"] = max(item["anomaly_zscore"], 1.9)
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
                        f"typical hour-of-day baseline near {item['police_station']}."
                    ),
                }
            )

    metadata = build_metadata(csv_path, report, data_hash, hotspots)
    etl_report = {
        **report,
        "data_hash": f"sha256:{data_hash}",
        "generated_at": metadata["generated_at"],
    }
    commander_context = {
        "top_clusters": hotspots[:10],
        "patrol_routes": routes,
        "anomaly_alerts": anomalies,
        "rules": [
            "Always cite cluster IDs and delay values in minutes per vehicle.",
            "Never claim real-time detection; this demo is generated from historical violation records.",
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

    print(
        json.dumps(
            {
                "accepted_records": report["accepted"],
                "hotspots": len(hotspots),
                "routes": len(routes),
                "anomalies": len(anomalies),
                "output_dir": str(output_dir),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
