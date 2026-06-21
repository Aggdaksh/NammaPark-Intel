from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ml.pipeline.etl import run_etl
from ml.pipeline.predict import export_fallback
from ml.pipeline.train import train_all


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--version", default="ui-latest")
    parser.add_argument("--artifacts-dir", default="ml/artifacts")
    parser.add_argument("--fallback-dir", default="public/fallback")
    parser.add_argument("--status-path", default="ml/artifacts/pipeline_ui_run.json")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--use-osm-snap", action="store_true")
    parser.add_argument("--graph-path", default="ml/data/bengaluru.graphml")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    artifacts_dir = Path(args.artifacts_dir)
    fallback_dir = Path(args.fallback_dir)
    status_path = Path(args.status_path)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    base_status: dict[str, Any] = {
        "status": "running",
        "csv": str(csv_path),
        "version": args.version,
        "started_at": started_at,
        "current_step": "initializing",
        "steps": [],
    }
    write_status(status_path, base_status)

    try:
        base_status["current_step"] = "etl"
        write_status(status_path, base_status)
        etl_report = run_etl(csv_path, os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL"))
        base_status["steps"].append({"name": "etl", "status": "complete", "summary": asdict(etl_report)})
        write_status(status_path, base_status)

        base_status["current_step"] = "training"
        write_status(status_path, base_status)
        train_summary = train_all(
            csv_path,
            artifacts_dir,
            args.max_rows,
            args.version,
            use_osm_snap=args.use_osm_snap,
            graph_path=Path(args.graph_path) if args.use_osm_snap else None,
        )
        base_status["steps"].append({"name": "training", "status": "complete", "summary": asdict(train_summary)})
        write_status(status_path, base_status)

        base_status["current_step"] = "fallback-export"
        write_status(status_path, base_status)
        export_summary = export_fallback(
            artifacts_dir / f"cluster_hour_features_{args.version}.parquet",
            artifacts_dir,
            fallback_dir,
            args.version,
            hotspot_limit=50,
            shift_hour=17,
        )
        base_status["steps"].append({"name": "fallback-export", "status": "complete", "summary": asdict(export_summary)})
        base_status.update(
            {
                "status": "complete",
                "current_step": "complete",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "message": "Pipeline complete. Refresh the dashboard to load the new fallback predictions.",
            }
        )
        write_status(status_path, base_status)
    except Exception as exc:
        base_status.update(
            {
                "status": "failed",
                "current_step": "failed",
                "failed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }
        )
        write_status(status_path, base_status)
        raise


if __name__ == "__main__":
    main()
