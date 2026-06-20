#!/usr/bin/env python3
"""Validate generated NammaPark Intel demo artifacts."""

from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "public/fallback/demo_data.json"


def assert_range(name: str, value: float, low: float, high: float) -> None:
    if not (low <= value <= high):
        raise AssertionError(f"{name}={value} outside [{low}, {high}]")


def main() -> None:
    if not DATA_PATH.exists():
        raise SystemExit(f"Missing {DATA_PATH}. Run npm run generate first.")

    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    hotspots = payload.get("hotspots", [])
    clusters = payload.get("clusters", {})
    routes = payload.get("patrol_routes", [])
    anomalies = payload.get("anomalies", [])

    if len(hotspots) < 10:
        raise AssertionError("Expected at least 10 hotspots")
    if len(clusters) < len(hotspots):
        raise AssertionError("Cluster map is smaller than hotspot list")
    if not routes:
        raise AssertionError("Expected at least one patrol route")

    risks = [item["final_risk_0_100"] for item in hotspots]
    if risks != sorted(risks, reverse=True):
        raise AssertionError("Hotspots must be sorted by descending risk")

    for item in hotspots:
        cid = str(item["cluster_id"])
        if cid not in clusters:
            raise AssertionError(f"Cluster {cid} missing from cluster map")
        assert_range("final_risk_0_100", item["final_risk_0_100"], 0.0, 100.0)
        assert_range("p_active", item["p_active"], 0.0, 1.0)
        if item["predicted_delay_min"] < 0.0:
            raise AssertionError("Predicted delay must be non-negative")
        if len(item.get("shap_context", [])) != 5:
            raise AssertionError(f"Cluster {cid} should have five SHAP-style drivers")
        if not item.get("h3_res8") or not item.get("h3_res9"):
            raise AssertionError(f"Cluster {cid} missing H3-compatible fields")

    for route in routes:
        total = sum(point["expected_delay_clear"] for point in route.get("waypoints", []))
        if not math.isclose(total, route["total_delay_cleared_est"], rel_tol=0.0, abs_tol=0.05):
            raise AssertionError(f"Route {route['route_id']} total does not match waypoints")
        for point in route.get("waypoints", []):
            if point["arrival_min"] > 480:
                raise AssertionError(f"Route {route['route_id']} exceeds shift duration")

    for anomaly in anomalies:
        if anomaly["cluster_id"] not in [item["cluster_id"] for item in hotspots]:
            raise AssertionError("Anomaly must reference a displayed hotspot")

    print(
        json.dumps(
            {
                "status": "ok",
                "hotspots": len(hotspots),
                "clusters": len(clusters),
                "routes": len(routes),
                "anomalies": len(anomalies),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
