from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response

from api.dependencies import get_prediction_store
from api.serving import TieredPredictionStore
from api.schemas.patrol import PatrolRoutesResponse


router = APIRouter(tags=["patrol"])


@router.get("/patrol-routes", response_model=PatrolRoutesResponse)
async def get_patrol_routes(
    response: Response,
    shift_date: date | None = Query(default=None),
    fallback: TieredPredictionStore = Depends(get_prediction_store),
) -> dict:
    items = list(fallback.items("patrol_routes.json", []))
    if shift_date is not None:
        items = [item for item in items if item.get("shift_date") == shift_date.isoformat()]
    response.headers["X-CurbClear-Source"] = fallback.last_source
    return {"metadata": fallback.metadata(), "items": items}
