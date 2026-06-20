from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from api.dependencies import get_prediction_store
from api.serving import TieredPredictionStore
from api.schemas.cluster import ClusterDetail


router = APIRouter(tags=["clusters"])


@router.get("/cluster/{cluster_id}", response_model=ClusterDetail)
async def get_cluster(cluster_id: int, response: Response, fallback: TieredPredictionStore = Depends(get_prediction_store)) -> dict:
    item = fallback.cluster(cluster_id)
    if item is None:
        raise HTTPException(status_code=422, detail=f"cluster_id {cluster_id} is not present in spatial_clusters")
    response.headers["X-CurbClear-Source"] = fallback.last_source
    return item
