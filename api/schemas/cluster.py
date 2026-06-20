from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ShapDriver(BaseModel):
    feature: str
    shap_contribution_min: float
    direction: Literal["increases", "decreases"]
    human_label: str


class EnforcementWindow(BaseModel):
    start_h: int = Field(ge=0, le=23)
    end_h: int = Field(ge=0, le=23)
    yield_score: float = Field(ge=0.0)


class ClusterHotspot(BaseModel):
    cluster_id: int
    centroid_lat: float
    centroid_lon: float
    h3_res8: str
    final_risk_0_100: float = Field(ge=0.0, le=100.0)
    predicted_delay_min: float = Field(ge=0.0)
    is_anomaly: bool = False
    anomaly_zscore: float | None = None
    dominant_vehicle_type: str | None = None
    police_station: str | None = None


class ClusterDetail(ClusterHotspot):
    model_config = ConfigDict(protected_namespaces=())

    h3_res9: str | None = None
    shap_context: list[ShapDriver] = Field(default_factory=list)
    enforcement_windows: list[EnforcementWindow] = Field(default_factory=list)
    dominant_violation_type: str | None = None
    p50_duration_min: float | None = None
    p_active_at_dispatch: float | None = Field(default=None, ge=0.0, le=1.0)
    model_version: str | None = None
