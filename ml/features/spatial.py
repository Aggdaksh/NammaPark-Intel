"""Spatial feature helpers for H3, HDBSCAN, OSMnx snap, and routing distance."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from ml.config.settings import load_config


@dataclass(frozen=True)
class OSMSnapResult:
    osm_way_id: int | None
    lane_count: int
    road_type: str
    speed_limit_kph: float
    junction_flag: bool
    segment_length_m: float
    snap_distance_m: float | None
    osm_snap_fallback: bool


def assign_h3(lat: float, lon: float, res: int) -> str:
    try:
        import h3  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise ImportError("h3 is required for assign_h3; run `uv sync` first") from exc

    if hasattr(h3, "latlng_to_cell"):
        return h3.latlng_to_cell(lat, lon, res)
    return h3.geo_to_h3(lat, lon, res)


def run_hdbscan(coords: np.ndarray, min_cluster_size: int = 15) -> np.ndarray:
    try:
        import hdbscan  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise ImportError("hdbscan is required for run_hdbscan; run `uv sync` first") from exc

    if len(coords) == 0:
        return np.array([], dtype=int)
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, metric="haversine")
    radians = np.radians(coords.astype(float))
    return clusterer.fit_predict(radians)


def _first_scalar(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, tuple, set)):
        return next(iter(value), default)
    return value


def _parse_lane_count(value: Any, default: int) -> int:
    raw = _first_scalar(value, default)
    try:
        text = str(raw).split(";")[0].split("|")[0].strip()
        return max(int(float(text)), 1)
    except (TypeError, ValueError):
        return default


def _parse_speed_limit(value: Any, default: float) -> float:
    raw = _first_scalar(value, default)
    try:
        text = str(raw).replace("kph", "").replace("km/h", "").split(";")[0].strip()
        speed = float(text)
        return speed if speed > 0 else default
    except (TypeError, ValueError):
        return default


def _fallback_snap_result(osm_cfg: dict[str, Any]) -> OSMSnapResult:
    return OSMSnapResult(
        osm_way_id=None,
        lane_count=int(osm_cfg["fallback_lane_count"]),
        road_type=str(osm_cfg["fallback_road_type"]),
        speed_limit_kph=float(osm_cfg["fallback_speed_limit_kph"]),
        junction_flag=False,
        segment_length_m=float(osm_cfg["fallback_segment_length_m"]),
        snap_distance_m=None,
        osm_snap_fallback=True,
    )


def _snap_result_from_edge(graph: Any, edge: Any, distance_m: Any, osm_cfg: dict[str, Any]) -> OSMSnapResult:
    fallback = _fallback_snap_result(osm_cfg)
    try:
        if distance_m is None or float(distance_m) > float(osm_cfg["snap_radius_m"]):
            return fallback
        u, v, key = tuple(edge)
    except (TypeError, ValueError):
        return fallback

    edge_data = graph.get_edge_data(u, v, key) or {}
    lane_count = _parse_lane_count(edge_data.get("lanes"), int(osm_cfg["fallback_lane_count"]))
    speed_limit = _parse_speed_limit(edge_data.get("maxspeed"), float(osm_cfg["fallback_speed_limit_kph"]))
    road_type = str(_first_scalar(edge_data.get("highway"), osm_cfg["fallback_road_type"]))
    segment_length = float(edge_data.get("length") or osm_cfg["fallback_segment_length_m"])
    osm_way_id = _first_scalar(edge_data.get("osmid"), None)
    try:
        osm_way_id = int(osm_way_id) if osm_way_id is not None else None
    except (TypeError, ValueError):
        osm_way_id = None

    return OSMSnapResult(
        osm_way_id=osm_way_id,
        lane_count=lane_count,
        road_type=road_type,
        speed_limit_kph=speed_limit,
        junction_flag=bool(graph.degree(u) > 2 or graph.degree(v) > 2),
        segment_length_m=segment_length,
        snap_distance_m=float(distance_m),
        osm_snap_fallback=False,
    )


def _as_list(value: Any, size: int) -> list[Any]:
    if size == 1:
        if isinstance(value, list):
            return value
        if isinstance(value, np.ndarray):
            return list(value)
        if isinstance(value, tuple) and len(value) == 3 and not isinstance(value[0], (list, tuple, np.ndarray)):
            return [value]
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def snap_points_to_osm(
    latitudes: list[float] | np.ndarray,
    longitudes: list[float] | np.ndarray,
    graph: Any,
    config: dict | None = None,
) -> list[OSMSnapResult]:
    cfg = config or load_config()
    osm_cfg = cfg["features"]["osmnx"]
    lat_values = [float(value) for value in latitudes]
    lon_values = [float(value) for value in longitudes]
    if len(lat_values) != len(lon_values):
        raise ValueError("latitudes and longitudes must have the same length")

    fallback = _fallback_snap_result(osm_cfg)
    if graph is None:
        return [fallback for _ in lat_values]

    try:
        import osmnx as ox  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise ImportError("osmnx is required for snap_points_to_osm with a graph; run `uv sync` first") from exc

    try:
        edges, distances = ox.distance.nearest_edges(graph, X=lon_values, Y=lat_values, return_dist=True)
    except Exception:
        return [fallback for _ in lat_values]

    edge_values = _as_list(edges, len(lat_values))
    distance_values = _as_list(distances, len(lat_values))
    return [
        _snap_result_from_edge(graph, edge, distance, osm_cfg)
        for edge, distance in zip(edge_values, distance_values)
    ]


def snap_to_osm(lat: float, lon: float, graph: Any, config: dict | None = None) -> OSMSnapResult:
    return snap_points_to_osm([lat], [lon], graph, config)[0]


def compute_kring_lag(h3_index: str, hex_risk_map: dict[str, float], k: int) -> float:
    try:
        import h3  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise ImportError("h3 is required for compute_kring_lag; run `uv sync` first") from exc

    if hasattr(h3, "grid_disk"):
        neighbors = set(h3.grid_disk(h3_index, k))
    else:
        neighbors = set(h3.k_ring(h3_index, k))
    neighbors.discard(h3_index)
    values = [float(hex_risk_map[neighbor]) for neighbor in neighbors if neighbor in hex_risk_map]
    return float(np.mean(values)) if values else 0.0


def haversine_min(lat1: float, lon1: float, lat2: float, lon2: float, speed_kph: float = 30.0) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    distance_km = 2.0 * radius_km * math.asin(math.sqrt(a))
    return distance_km / max(speed_kph, 1.0) * 60.0


def haversine_matrix(coords: list[tuple[float, float]], speed_kph: float = 30.0) -> np.ndarray:
    size = len(coords)
    matrix = np.zeros((size, size), dtype=float)
    for i, (lat1, lon1) in enumerate(coords):
        for j, (lat2, lon2) in enumerate(coords):
            if i != j:
                matrix[i, j] = haversine_min(lat1, lon1, lat2, lon2, speed_kph)
    return matrix
