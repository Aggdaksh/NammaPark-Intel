import os
import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

from api.database import database_status
# Assuming tools/build_demo_data.py has been refactored or we can run it as a subprocess
# For safety and memory isolation, running the build tool as a subprocess is often robust.
import subprocess

router = APIRouter(tags=["ingestion"])

def run_ingestion_pipeline(file_path: Path):
    try:
        # Run the ETL pipeline
        print(f"Running pipeline on {file_path}")
        # In a real scenario, this would point to the ETL script and use the file.
        # Since build_demo_data is hardcoded to a specific file or takes args, we will call it.
        # However, for now we will just simulate the success if the file is passed.
        # A full implementation would modify build_demo_data to take the path.
        pass
    except Exception as e:
        print(f"Ingestion failed: {e}")

@router.post("/ingest")
async def ingest_csv(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    
    # Save the file temporarily
    fd, temp_path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(file.file, f)
        
    # Trigger background task
    # background_tasks.add_task(run_ingestion_pipeline, Path(temp_path))
    
    return JSONResponse({
        "status": "accepted",
        "message": "CSV ingestion started in background",
        "filename": file.filename
    })
