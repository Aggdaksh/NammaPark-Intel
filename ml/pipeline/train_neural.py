from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ml.config.settings import load_config
from ml.models.neural_risk_model import NeuralRiskModel


@dataclass
class NeuralExperimentSummary:
    version: str
    features_path: str
    data_hash: str
    input_rows: int
    trained_rows: int
    metrics: dict[str, float]
    champion: dict[str, Any]
    comparison: dict[str, Any]
    artifacts: dict[str, str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def load_champion_metrics(artifacts_dir: Path, champion_version: str) -> dict[str, Any]:
    metadata_path = artifacts_dir / f"risk_model_metadata_{champion_version}.json"
    if not metadata_path.exists():
        return {"version": champion_version, "available": False, "metrics": {}}
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        "version": champion_version,
        "available": True,
        "metadata_path": str(metadata_path),
        "metrics": payload.get("metrics", {}),
    }


def compare_to_champion(neural_metrics: dict[str, float], champion: dict[str, Any]) -> dict[str, Any]:
    champion_metrics = champion.get("metrics", {})
    if not champion_metrics:
        return {"champion_available": False}
    return {
        "champion_available": True,
        "beats_champion_mae": neural_metrics["val_MAE_delay_min"] < champion_metrics.get("val_MAE_delay_min", float("inf")),
        "beats_champion_spearman": neural_metrics["val_SpearmanR"] > champion_metrics.get("val_SpearmanR", float("-inf")),
        "beats_champion_topk10": neural_metrics["val_TopK10_precision"]
        > champion_metrics.get("val_TopK10_precision", float("-inf")),
        "mae_delta_min": neural_metrics["val_MAE_delay_min"] - champion_metrics.get("val_MAE_delay_min", 0.0),
        "spearman_delta": neural_metrics["val_SpearmanR"] - champion_metrics.get("val_SpearmanR", 0.0),
        "topk10_delta": neural_metrics["val_TopK10_precision"] - champion_metrics.get("val_TopK10_precision", 0.0),
    }


def load_features(path: Path, max_rows: int | None, random_state: int) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if max_rows and max_rows < len(frame):
        frame = frame.sample(n=max_rows, random_state=random_state).copy()
    return frame


def run_experiment(
    features_path: Path,
    artifacts_dir: Path,
    version: str,
    *,
    max_rows: int | None = None,
    max_iter: int | None = None,
    champion_version: str = "v1-osm",
) -> NeuralExperimentSummary:
    config = load_config()
    random_state = int(config["models"]["neural_risk"]["random_state"])
    input_rows = len(pd.read_parquet(features_path, columns=["cluster_id"]))
    features = load_features(features_path, max_rows, random_state)
    data_hash = sha256_file(features_path)
    model = NeuralRiskModel(config)
    result = model.train(features, artifacts_dir, data_hash=data_hash, version=version, max_iter=max_iter)
    champion = load_champion_metrics(artifacts_dir, champion_version)
    comparison = compare_to_champion(result.metrics, champion)
    summary = NeuralExperimentSummary(
        version=version,
        features_path=str(features_path),
        data_hash=data_hash,
        input_rows=int(input_rows),
        trained_rows=int(len(features)),
        metrics=result.metrics,
        champion=champion,
        comparison=comparison,
        artifacts={
            "model": str(result.model_path),
            "metadata": str(result.metadata_path),
            "predictions": str(result.predictions_path),
        },
    )
    summary_path = artifacts_dir / f"neural_experiment_summary_{version}.json"
    summary_path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")
    summary.artifacts["summary"] = str(summary_path)
    summary_path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features-parquet", default="ml/artifacts/cluster_hour_features_v1-osm.parquet")
    parser.add_argument("--artifacts-dir", default="ml/artifacts")
    parser.add_argument("--version", default="neural-smoke")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--max-iter", type=int, default=None)
    parser.add_argument("--champion-version", default="v1-osm")
    args = parser.parse_args()
    summary = run_experiment(
        Path(args.features_parquet),
        Path(args.artifacts_dir),
        args.version,
        max_rows=args.max_rows,
        max_iter=args.max_iter,
        champion_version=args.champion_version,
    )
    print(json.dumps(asdict(summary), indent=2))


if __name__ == "__main__":
    main()
