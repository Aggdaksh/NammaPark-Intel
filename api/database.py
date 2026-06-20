from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache
from typing import Any


def database_url() -> str | None:
    value = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    return value.strip() if value and value.strip() else None


@lru_cache(maxsize=1)
def create_engine_if_configured() -> Any | None:
    url = database_url()
    if not url:
        return None
    try:
        from sqlalchemy import create_engine
    except ModuleNotFoundError as exc:
        raise RuntimeError("SQLAlchemy is required for PostgreSQL support; install the Python dependencies first.") from exc

    return create_engine(url, pool_pre_ping=True, future=True)


def session_scope() -> Iterator[Any | None]:
    engine = create_engine_if_configured()
    if engine is None:
        yield None
        return

    try:
        from sqlalchemy.orm import Session
    except ModuleNotFoundError as exc:
        raise RuntimeError("SQLAlchemy ORM is required for PostgreSQL sessions.") from exc

    with Session(engine) as session:
        yield session


def database_status(*, ping: bool = False) -> dict[str, Any]:
    url = database_url()
    if not url:
        return {"configured": False, "available": False, "dialect": "postgresql", "detail": "DATABASE_URL is not set"}

    status: dict[str, Any] = {"configured": True, "available": None, "dialect": "postgresql"}
    if not ping:
        status["detail"] = "DATABASE_URL is set; connection ping skipped"
        return status

    try:
        from sqlalchemy import text

        engine = create_engine_if_configured()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status.update({"available": True, "detail": "connection ok"})
    except Exception as exc:  # pragma: no cover - depends on external DB availability
        status.update({"available": False, "detail": str(exc)})
    return status
