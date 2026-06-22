from __future__ import annotations

from typing import Any

from fastapi import Depends
from fastapi import FastAPI

from api.database import database_status
from api.dependencies import get_config, get_prediction_store
from api.routers import anomalies, clusters, commander, hotspots, ingestion, patrol, pipeline
from api.serving import TieredPredictionStore, redis_status

import os
import sentry_sdk

sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )

app = FastAPI(title="NammaPark Intel API", version="1.0.0")
app.include_router(hotspots.router, prefix="/api")
app.include_router(clusters.router, prefix="/api")
app.include_router(patrol.router, prefix="/api")
app.include_router(anomalies.router, prefix="/api")
app.include_router(commander.router, prefix="/api")
app.include_router(ingestion.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")


@app.get("/health")
async def health(store: TieredPredictionStore = Depends(get_prediction_store)) -> dict[str, Any]:
    metadata = store.metadata()
    summary = store.read("prediction_export_summary.json") or {}
    ready = store.is_ready()
    cfg = get_config()
    db = database_status()
    return {
        "status": "ok" if ready else "degraded",
        "db": bool(db["configured"]),
        "database": db,
        "cache": redis_status(cfg),
        "cache_tier": store.last_source,
        "serving_order": store.serving_order(),
        "model": bool(metadata.get("model_version")),
        "model_version": metadata.get("model_version"),
        "generated_at": metadata.get("generated_at"),
        "scored_rows": summary.get("scored_rows"),
        "cluster_count": summary.get("cluster_count"),
    }


@app.get("/health/db")
async def database_health(ping: bool = False) -> dict[str, Any]:
    return database_status(ping=ping)
