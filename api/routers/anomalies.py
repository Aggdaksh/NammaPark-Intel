from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from api.dependencies import get_prediction_store
from api.serving import TieredPredictionStore
from api.schemas.prediction import AnomalyList


router = APIRouter(tags=["anomalies"])


@router.get("/anomalies", response_model=AnomalyList)
async def get_anomalies(
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    fallback: TieredPredictionStore = Depends(get_prediction_store),
) -> dict:
    items = fallback.items("anomalies.json", [])
    response.headers["X-CurbClear-Source"] = fallback.last_source
    return {"metadata": fallback.metadata(), "items": list(items)[:limit]}
