from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.database import create_engine_if_configured


@dataclass(frozen=True)
class StoreResult:
    payload: Any
    source: str


class StaticFallbackStore:
    def __init__(self, fallback_dir: str | Path) -> None:
        self.fallback_dir = Path(fallback_dir)

    def read(self, filename: str) -> StoreResult | None:
        path = self.fallback_dir / filename
        if not path.exists():
            return None
        return StoreResult(json.loads(path.read_text(encoding="utf-8")), "fallback")


class RedisJsonStore:
    def __init__(self, config: dict[str, Any]) -> None:
        redis_cfg = config["serving"]["redis"]
        self.url = os.getenv(redis_cfg["url_env"]) or os.getenv(redis_cfg["fallback_url_env"])
        self.key_prefix = str(redis_cfg["key_prefix"]).strip(":")

    def read(self, filename: str) -> StoreResult | None:
        if not self.url:
            return None
        try:
            import redis

            client = redis.Redis.from_url(self.url, decode_responses=True)
            raw = client.get(f"{self.key_prefix}:{filename}")
            if not raw:
                return None
            return StoreResult(json.loads(raw), "redis")
        except Exception:
            return None


class PostgresApiCacheStore:
    def __init__(self, config: dict[str, Any]) -> None:
        table = str(config["serving"]["postgres"]["api_cache_table"])
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise ValueError(f"Unsafe API cache table name: {table}")
        self.table = table

    def read(self, filename: str) -> StoreResult | None:
        engine = create_engine_if_configured()
        if engine is None:
            return None
        try:
            from sqlalchemy import text

            query = text(
                f"""
                SELECT payload
                FROM {self.table}
                WHERE cache_key = :cache_key
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            with engine.connect() as conn:
                row = conn.execute(query, {"cache_key": filename}).mappings().first()
            if not row:
                return None
            payload = row["payload"]
            return StoreResult(payload if isinstance(payload, (dict, list)) else json.loads(payload), "postgres")
        except Exception:
            return None


class TieredPredictionStore:
    def __init__(self, config: dict[str, Any], fallback_dir: str | Path) -> None:
        self.cache = RedisJsonStore(config)
        self.postgres = PostgresApiCacheStore(config)
        self.fallback = StaticFallbackStore(fallback_dir)
        self.last_source = "unavailable"

    def read(self, filename: str) -> Any:
        for store in (self.cache, self.postgres, self.fallback):
            result = store.read(filename)
            if result is not None:
                self.last_source = result.source
                return result.payload
        self.last_source = "unavailable"
        return None

    def demo_data(self) -> dict[str, Any]:
        payload = self.read("demo_data.json")
        return payload if isinstance(payload, dict) else {}

    def metadata(self) -> dict[str, Any]:
        return self.demo_data().get("metadata", {})

    def items(self, filename: str, default: Any) -> Any:
        payload = self.read(filename)
        if isinstance(payload, dict) and "items" in payload:
            return payload["items"]
        return payload if payload is not None else default

    def cluster(self, cluster_id: int) -> dict[str, Any] | None:
        clusters = self.items("clusters.json", {})
        if not isinstance(clusters, dict):
            return None
        item = clusters.get(str(cluster_id))
        return item if isinstance(item, dict) else None

    def is_ready(self) -> bool:
        metadata = self.metadata()
        return bool(metadata.get("generated_at") and metadata.get("model_version"))

    def serving_order(self) -> list[str]:
        return ["redis", "postgres", "fallback"]


def redis_status(config: dict[str, Any]) -> dict[str, Any]:
    redis_cfg = config["serving"]["redis"]
    configured = bool(os.getenv(redis_cfg["url_env"]) or os.getenv(redis_cfg["fallback_url_env"]))
    return {
        "configured": configured,
        "key_prefix": redis_cfg["key_prefix"],
        "detail": "Redis URL is set" if configured else "Redis URL is not set",
    }
