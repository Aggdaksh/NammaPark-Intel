from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PatrolWaypoint(BaseModel):
    cluster_id: int
    arrival_min: int = Field(ge=0)
    expected_delay_clear: float = Field(ge=0.0)
    lat: float | None = None
    lon: float | None = None


class PatrolRoute(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    route_id: str | None = None
    unit_id: str
    shift_date: date
    origin_station: str | None = None
    waypoints: list[PatrolWaypoint]
    geojson: dict[str, Any] | None = None
    total_delay_cleared_est: float = Field(ge=0.0)
    model_version: str | None = None


class PatrolRoutesResponse(BaseModel):
    metadata: dict[str, Any] | None = None
    items: list[PatrolRoute]
