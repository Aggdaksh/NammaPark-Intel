from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from ml.features.spatial import haversine_matrix


@dataclass
class VRPResult:
    artifact_path: Path
    routes: list[dict[str, Any]]


class PatrolRouter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def build_routes(
        self,
        clusters_df: pd.DataFrame,
        stations_df: pd.DataFrame,
        num_units: int = 3,
        version: str = "v1",
        artifacts_dir: Path | None = None,
    ) -> VRPResult:
        cfg = self.config["models"]["vrp"]
        if clusters_df.empty:
            routes: list[dict[str, Any]] = []
            path = (artifacts_dir or Path("ml/artifacts")) / f"patrol_routes_{version}.json"
            path.write_text(json.dumps(routes, indent=2), encoding="utf-8")
            return VRPResult(path, routes)

        candidate_count = max(
            num_units * int(cfg["candidate_multiplier_per_unit"]),
            int(cfg["min_candidate_clusters"]),
        )
        clusters = clusters_df.head(candidate_count).reset_index(drop=True)
        stations = stations_df.head(max(1, min(len(stations_df), num_units))).reset_index(drop=True)
        nodes = pd.concat(
            [
                stations.rename(columns={"station": "label", "lat": "centroid_lat", "lon": "centroid_lon"}),
                clusters.assign(label=clusters["cluster_id"].map(lambda value: f"cluster-{value}")),
            ],
            ignore_index=True,
            sort=False,
        )
        station_count = len(stations)
        coords = list(zip(nodes["centroid_lat"].astype(float), nodes["centroid_lon"].astype(float)))
        dist = np.rint(haversine_matrix(coords, speed_kph=float(cfg["urban_speed_kph"]))).astype(int)
        starts = [idx % station_count for idx in range(num_units)]
        manager = pywrapcp.RoutingIndexManager(len(nodes), num_units, starts, starts)
        routing = pywrapcp.RoutingModel(manager)

        def time_callback(from_idx: int, to_idx: int) -> int:
            return int(dist[manager.IndexToNode(from_idx), manager.IndexToNode(to_idx)])

        transit_cb = routing.RegisterTransitCallback(time_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)
        routing.AddDimension(transit_cb, int(cfg["slack_minutes"]), int(cfg["shift_minutes"]), True, "Time")

        for node in range(station_count, len(nodes)):
            risk = float(nodes.iloc[node].get("final_risk_0_100", 1.0))
            penalty = max(100, int(risk * 100))
            routing.AddDisjunction([manager.NodeToIndex(node)], penalty)

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.seconds = int(cfg["time_limit_seconds"])
        solution = routing.SolveWithParameters(params)
        routes = self._extract_routes(manager, routing, solution, nodes, station_count, cfg, starts) if solution else []

        artifacts = artifacts_dir or Path("ml/artifacts")
        artifacts.mkdir(parents=True, exist_ok=True)
        artifact_path = artifacts / f"patrol_routes_{version}.json"
        artifact_path.write_text(json.dumps(routes, indent=2), encoding="utf-8")
        return VRPResult(artifact_path, routes)

    def _extract_routes(
        self,
        manager: pywrapcp.RoutingIndexManager,
        routing: pywrapcp.RoutingModel,
        solution: pywrapcp.Assignment,
        nodes: pd.DataFrame,
        station_count: int,
        cfg: dict[str, Any],
        starts: list[int],
    ) -> list[dict[str, Any]]:
        routes = []
        time_dimension = routing.GetDimensionOrDie("Time")
        for vehicle_id in range(len(starts)):
            index = routing.Start(vehicle_id)
            waypoints = []
            coordinates = [
                [
                    float(nodes.iloc[starts[vehicle_id]]["centroid_lon"]),
                    float(nodes.iloc[starts[vehicle_id]]["centroid_lat"]),
                ]
            ]
            total_delay = 0.0
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node >= station_count:
                    row = nodes.iloc[node]
                    arrival = solution.Value(time_dimension.CumulVar(index))
                    total_delay += float(row.get("expected_delay_clear", row.get("final_risk_0_100", 0.0)))
                    waypoints.append(
                        {
                            "cluster_id": int(row["cluster_id"]),
                            "arrival_min": int(arrival),
                            "expected_delay_clear": float(row.get("expected_delay_clear", row.get("final_risk_0_100", 0.0))),
                            "lat": float(row["centroid_lat"]),
                            "lon": float(row["centroid_lon"]),
                        }
                    )
                    coordinates.append([float(row["centroid_lon"]), float(row["centroid_lat"])])
                index = solution.Value(routing.NextVar(index))
            routes.append(
                {
                    "unit_id": f"BT-{vehicle_id + 1:02d}",
                    "shift_date": "2024-05-01",
                    "origin_station": str(nodes.iloc[starts[vehicle_id]].get("police_station", "BTP")),
                    "waypoints": waypoints,
                    "geojson": {"type": "LineString", "coordinates": coordinates},
                    "total_delay_cleared_est": round(total_delay, 3),
                    "model_version": "v1",
                }
            )
        return routes
