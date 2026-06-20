from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from api.schemas.cluster import ClusterDetail, ClusterHotspot
from api.schemas.patrol import PatrolRoute


class HotspotList(BaseModel):
    metadata: dict[str, Any] | None = None
    items: list[ClusterHotspot]


class AnomalyAlert(BaseModel):
    cluster_id: int
    anomaly_zscore: float
    final_risk_0_100: float = Field(ge=0.0, le=100.0)
    predicted_delay_min: float = Field(ge=0.0)
    police_station: str | None = None
    description: str


class AnomalyList(BaseModel):
    metadata: dict[str, Any] | None = None
    items: list[AnomalyAlert]


class ClusterPrediction(ClusterDetail):
    prediction_for: datetime | None = None
    created_at: datetime | None = None


class CommanderRequest(BaseModel):
    user_message: str = Field(min_length=1)


class CommanderResponse(BaseModel):
    response: str
    grounded_cluster_ids: list[int] = Field(default_factory=list)
    source: str = "fallback"


class DemoData(BaseModel):
    hotspots: list[ClusterHotspot]
    patrol_routes: list[PatrolRoute]
    anomalies: list[AnomalyAlert]
