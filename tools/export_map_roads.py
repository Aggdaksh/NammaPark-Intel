#!/usr/bin/env python3
"""Export a compact road layer from the local Bengaluru OSM graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import osmnx as ox


ROAD_PRIORITY = {
    "motorway": 1,
    "trunk": 2,
    "primary": 3,
    "secondary": 4,
    "tertiary": 5,
    "unclassified": 6,
    "residential": 7,
    "service": 8,
    "living_street": 9,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", default="ml/data/bengaluru.graphml")
    parser.add_argument("--demo-data", default="public/fallback/demo_data.json")
    parser.add_argument("--out", default="public/fallback/map_roads.json")
    parser.add_argument("--max-segments", type=int, default=4200)
    parser.add_argument("--simplify-tolerance", type=float, default=0.000055)
    parser.add_argument("--pad", type=float, default=0.035)
    return parser.parse_args()


def first_highway(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, tuple) and value:
        return str(value[0])
    text = str(value or "road")
    if text.startswith("[") and "," in text:
        return text.strip("[]").split(",", 1)[0].strip(" '\"")
    return text.strip(" '\"")


def road_rank(value: Any) -> int:
    highway = first_highway(value)
    return ROAD_PRIORITY.get(highway, 10)


def road_tier(value: Any) -> str:
    rank = road_rank(value)
    if rank <= 3:
        return "arterial"
    if rank <= 5:
        return "collector"
    return "local"


def load_bbox(demo_data_path: Path, pad: float) -> tuple[float, float, float, float]:
    data = json.loads(demo_data_path.read_text())
    bbox = data.get("metadata", {}).get("bbox") or {}
    if bbox:
        min_lat = float(bbox["min_lat"])
        max_lat = float(bbox["max_lat"])
        min_lon = float(bbox["min_lon"])
        max_lon = float(bbox["max_lon"])
    else:
        points = data.get("hotspots", [])
        min_lat = min(float(point["centroid_lat"]) for point in points)
        max_lat = max(float(point["centroid_lat"]) for point in points)
        min_lon = min(float(point["centroid_lon"]) for point in points)
        max_lon = max(float(point["centroid_lon"]) for point in points)
    return min_lon - pad, min_lat - pad, max_lon + pad, max_lat + pad


def export_roads(args: argparse.Namespace) -> dict[str, Any]:
    graph_path = Path(args.graph)
    demo_data_path = Path(args.demo_data)
    out_path = Path(args.out)
    min_lon, min_lat, max_lon, max_lat = load_bbox(demo_data_path, args.pad)

    graph = ox.load_graphml(graph_path)
    edges = ox.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True)
    edges = edges.cx[min_lon:max_lon, min_lat:max_lat].copy()
    if edges.empty:
        raise RuntimeError("No roads matched the hotspot bounding box")

    edges["rank"] = edges["highway"].map(road_rank)
    edges["tier"] = edges["highway"].map(road_tier)
    if "length" not in edges:
        edges["length"] = edges.geometry.length

    edges = edges.sort_values(["rank", "length"], ascending=[True, False]).head(args.max_segments)

    segments: list[dict[str, Any]] = []
    for _, row in edges.iterrows():
        geometry = row.geometry.simplify(args.simplify_tolerance, preserve_topology=False)
        if geometry.is_empty:
            continue
        line_strings = list(geometry.geoms) if geometry.geom_type == "MultiLineString" else [geometry]
        for line in line_strings:
            coords = [[round(x, 6), round(y, 6)] for x, y in line.coords]
            if len(coords) < 2:
                continue
            segments.append(
                {
                    "tier": row["tier"],
                    "highway": first_highway(row.get("highway")),
                    "length_m": round(float(row.get("length", 0)), 1),
                    "coords": coords,
                }
            )

    payload = {
        "metadata": {
            "source": str(graph_path),
            "bbox": {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
            },
            "segment_count": len(segments),
            "max_segments": args.max_segments,
            "simplify_tolerance": args.simplify_tolerance,
        },
        "segments": segments,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, separators=(",", ":")))
    return payload["metadata"]


def main() -> None:
    metadata = export_roads(parse_args())
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
