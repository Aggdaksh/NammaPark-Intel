from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.database import create_engine_if_configured, database_url

router = APIRouter(tags=["ingestion"])

MAX_UPLOAD_BYTES = 150 * 1024 * 1024
BATCH_SIZE = 1000


def _safe_filename(filename: str | None) -> str:
    raw = filename or "upload.csv"
    return re.sub(r"[^A-Za-z0-9_. -]+", "_", raw)[:180]


def _ensure_upload_table(conn: Any) -> None:
    conn.execute(
        text(
            """
            CREATE EXTENSION IF NOT EXISTS pgcrypto;

            CREATE TABLE IF NOT EXISTS violation_csv_uploads (
                upload_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                filename        TEXT NOT NULL,
                content_sha256  TEXT NOT NULL,
                row_count       INTEGER NOT NULL DEFAULT 0,
                status          TEXT NOT NULL DEFAULT 'received',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS violation_csv_upload_rows (
                id              BIGSERIAL PRIMARY KEY,
                upload_id       UUID NOT NULL REFERENCES violation_csv_uploads(upload_id) ON DELETE CASCADE,
                row_number      INTEGER NOT NULL,
                payload         JSONB NOT NULL,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE INDEX IF NOT EXISTS idx_violation_csv_upload_rows_upload
                ON violation_csv_upload_rows (upload_id, row_number);
            """
        )
    )


def _insert_batch(conn: Any, upload_id: str, batch: list[dict[str, Any]]) -> None:
    if not batch:
        return
    conn.execute(
        text(
            """
            INSERT INTO violation_csv_upload_rows (upload_id, row_number, payload)
            VALUES (CAST(:upload_id AS uuid), :row_number, CAST(:payload AS jsonb))
            """
        ),
        [{"upload_id": upload_id, "row_number": item["row_number"], "payload": json.dumps(item["payload"])} for item in batch],
    )


@router.post("/ingest")
async def ingest_csv(file: UploadFile = File(...)) -> JSONResponse:
    filename = _safe_filename(file.filename)
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    if not database_url():
        return JSONResponse(
            {
                "status": "database_not_configured",
                "filename": filename,
                "inserted_rows": 0,
                "detail": "Set DATABASE_URL or POSTGRES_URL to enable CSV ingestion into PostgreSQL.",
            },
            status_code=503,
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV upload is larger than the 150 MB safety limit.")
    if not content.strip():
        raise HTTPException(status_code=400, detail="CSV file is empty.")

    content_hash = hashlib.sha256(content).hexdigest()
    engine = create_engine_if_configured()
    if engine is None:
        raise HTTPException(status_code=503, detail="DATABASE_URL or POSTGRES_URL is not configured.")

    text_stream = io.StringIO(content.decode("utf-8-sig", errors="replace"), newline="")
    reader = csv.DictReader(text_stream)
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV header row is missing.")

    inserted_rows = 0
    batch: list[dict[str, Any]] = []
    with engine.begin() as conn:
        _ensure_upload_table(conn)
        upload_id = conn.execute(
            text(
                """
                INSERT INTO violation_csv_uploads (filename, content_sha256, status)
                VALUES (:filename, :content_sha256, 'loading')
                RETURNING upload_id
                """
            ),
            {"filename": filename, "content_sha256": content_hash},
        ).scalar_one()

        for row_number, row in enumerate(reader, start=1):
            batch.append({"row_number": row_number, "payload": dict(row)})
            if len(batch) >= BATCH_SIZE:
                _insert_batch(conn, str(upload_id), batch)
                inserted_rows += len(batch)
                batch.clear()

        if batch:
            _insert_batch(conn, str(upload_id), batch)
            inserted_rows += len(batch)

        conn.execute(
            text(
                """
                UPDATE violation_csv_uploads
                SET row_count = :row_count, status = 'loaded'
                WHERE upload_id = :upload_id
                """
            ),
            {"row_count": inserted_rows, "upload_id": upload_id},
        )

    return JSONResponse(
        {
            "status": "loaded",
            "upload_id": str(upload_id),
            "filename": filename,
            "inserted_rows": inserted_rows,
            "content_sha256": content_hash,
            "target_table": "violation_csv_upload_rows",
        }
    )
