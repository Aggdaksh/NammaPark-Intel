from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from api.database import session_scope
from api.serving import TieredPredictionStore
from ml.config.settings import load_config


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    return load_config()


@lru_cache(maxsize=1)
def get_prediction_store() -> TieredPredictionStore:
    cfg = get_config()
    return TieredPredictionStore(cfg, cfg["api"]["fallback_dir"])


def get_fallback() -> TieredPredictionStore:
    return get_prediction_store()


def get_db() -> Iterator[Any | None]:
    yield from session_scope()


async def get_redis() -> Any:
    # Real Upstash wiring lands in task 7.1 after UPSTASH_REDIS_URL is available.
    return None


def get_model_version() -> str:
    return str(get_config()["project"]["model_version"])
