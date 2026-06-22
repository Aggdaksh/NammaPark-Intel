from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter(tags=["pipeline"])

MAX_UPLOAD_BYTES = 150 * 1024 * 1024


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_filename(filename: str | None) -> str:
    raw = filename or "upload.csv"
    return re.sub(r"[^A-Za-z0-9_. -]+", "_", raw)[:160] or "upload.csv"


def _status_path() -> Path:
    return _workspace_root() / "ml" / "artifacts" / "pipeline_ui_run.json"


def _python_bin() -> str:
    configured = os.getenv("NAMMAPARK_PYTHON_BIN") or os.getenv("PYTHON_BIN")
    if configured:
        return configured
    venv_python = _workspace_root() / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else "python3"


def _read_status() -> dict[str, Any]:
    try:
        return json.loads(_status_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "idle", "message": "No pipeline job has been started yet."}


def _write_status(payload: dict[str, Any]) -> None:
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


@router.get("/pipeline")
async def pipeline_status() -> JSONResponse:
    return JSONResponse(_read_status())


@router.post("/pipeline")
async def start_pipeline(
    file: UploadFile = File(...),
    run: bool = Form(False),
    maxRows: int | None = Form(None),
) -> JSONResponse:
    filename = _safe_filename(file.filename)
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV upload is larger than the 150 MB safety limit.")
    if not content.strip():
        raise HTTPException(status_code=400, detail="CSV file is empty.")
    if maxRows is not None and maxRows <= 0:
        raise HTTPException(status_code=400, detail="Max rows must be a positive number.")

    root = _workspace_root()
    upload_dir = root / "ml" / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    upload_path = upload_dir / f"{stamp}-{filename}"
    upload_path.write_bytes(content)

    version = f"ui-{int(time.time())}"
    base_payload: dict[str, Any] = {
        "status": "running" if run else "uploaded",
        "filename": filename,
        "saved_path": str(upload_path),
        "size_bytes": len(content),
        "model_version": version,
    }

    if not run:
        return JSONResponse(
            {
                **base_payload,
                "message": "CSV saved on Render/FastAPI. Enable Run model pipeline to train and export refreshed data.",
            }
        )

    args = [
        _python_bin(),
        str(root / "tools" / "run_uploaded_pipeline.py"),
        "--csv",
        str(upload_path),
        "--version",
        version,
        "--status-path",
        str(_status_path()),
        "--use-osm-snap",
        "--graph-path",
        str(root / "ml" / "data" / "bengaluru.graphml"),
    ]
    if maxRows:
        args.extend(["--max-rows", str(maxRows)])

    process = subprocess.Popen(args, cwd=root, env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _write_status(
        {
            "status": "running",
            "current_step": "queued",
            "csv": str(upload_path),
            "version": version,
            "pid": process.pid,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "message": "Pipeline started on the backend worker.",
        }
    )

    return JSONResponse({**base_payload, "pid": process.pid, "message": "Pipeline started on Render/FastAPI."})
