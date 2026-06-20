from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ml.config.settings import load_config


@dataclass
class GateResult:
    name: str
    passed: bool
    observed: float | bool | None
    threshold: float | bool | None
    direction: str


@dataclass
class EvaluationReport:
    model_version: str
    data_hash: str | None
    accepted_records: int
    cluster_count: int
    cluster_hour_rows: int
    risk_metrics: dict[str, float]
    survival_metrics: dict[str, Any]
    anomaly_flagged_rate: float | None
    patrol_routes: int
    osm_snap: dict[str, Any]
    fallback_export: dict[str, Any]
    neural_challenger: dict[str, Any]
    gates: list[GateResult]
    recommendation: str


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def gate_at_least(name: str, observed: float | None, threshold: float) -> GateResult:
    return GateResult(name, observed is not None and observed >= threshold, observed, threshold, ">=")


def gate_at_most(name: str, observed: float | None, threshold: float) -> GateResult:
    return GateResult(name, observed is not None and observed <= threshold, observed, threshold, "<=")


def gate_equal(name: str, observed: bool | None, expected: bool) -> GateResult:
    return GateResult(name, observed is expected, observed, expected, "==")


def compare_neural(neural: dict[str, Any] | None) -> dict[str, Any]:
    if not neural:
        return {"available": False}
    comparison = neural.get("comparison", {})
    metrics = neural.get("metrics", {})
    return {
        "available": True,
        "version": neural.get("version"),
        "metrics": metrics,
        "comparison": comparison,
        "verdict": (
            "keep_lightgbm_champion"
            if not any(
                comparison.get(key)
                for key in ["beats_champion_mae", "beats_champion_spearman", "beats_champion_topk10"]
            )
            else "investigate_ensemble"
        ),
    }


def build_report(
    artifacts_dir: Path,
    fallback_dir: Path,
    version: str,
    neural_version: str,
) -> EvaluationReport:
    config = load_config()
    risk_gates = config["models"]["risk"]["gates"]
    summary = load_json(artifacts_dir / f"training_summary_{version}.json", {})
    risk_metadata = load_json(artifacts_dir / f"risk_model_metadata_{version}.json", {})
    survival_metadata = load_json(artifacts_dir / f"survival_model_{version}.json", {})
    anomaly_metadata = load_json(artifacts_dir / f"anomaly_model_metadata_{version}.json", {})
    fallback_export = load_json(fallback_dir / "prediction_export_summary.json", {})
    neural_summary = load_json(artifacts_dir / f"neural_experiment_summary_{neural_version}.json", None)

    risk_metrics = risk_metadata.get("metrics") or summary.get("risk_metrics", {})
    survival_metrics = survival_metadata.get("metrics") or summary.get("survival_metrics", {})
    osm_snap = summary.get("osm_snap", {})
    gates = [
        gate_at_least("risk_spearman", risk_metrics.get("val_SpearmanR"), float(risk_gates["min_spearman"])),
        gate_at_most("risk_mae_min", risk_metrics.get("val_MAE_delay_min"), float(risk_gates["max_mae_min"])),
        gate_at_least("risk_topk10_precision", risk_metrics.get("val_TopK10_precision"), float(risk_gates["min_topk10_precision"])),
        gate_at_most("osm_snap_fallback_rate", osm_snap.get("fallback_rate"), 0.05),
        gate_at_least("fallback_hotspots", fallback_export.get("hotspot_count"), 50.0),
        gate_equal("survival_fallback_logged", survival_metrics.get("heuristic_fallback"), True),
    ]
    recommendation = "ship_v1_osm"
    if not all(gate.passed for gate in gates):
        recommendation = "hold_and_review_failed_gates"

    return EvaluationReport(
        model_version=version,
        data_hash=summary.get("data_hash") or risk_metadata.get("data_hash"),
        accepted_records=int(summary.get("accepted_records", 0)),
        cluster_count=int(summary.get("cluster_count", 0)),
        cluster_hour_rows=int(summary.get("cluster_hour_rows", 0)),
        risk_metrics={key: float(value) for key, value in risk_metrics.items()},
        survival_metrics=survival_metrics,
        anomaly_flagged_rate=(
            float(anomaly_metadata["flagged_rate"])
            if "flagged_rate" in anomaly_metadata
            else summary.get("anomaly_flagged_rate")
        ),
        patrol_routes=int(summary.get("patrol_routes", 0)),
        osm_snap=osm_snap,
        fallback_export=fallback_export,
        neural_challenger=compare_neural(neural_summary),
        gates=gates,
        recommendation=recommendation,
    )


def report_to_markdown(report: EvaluationReport) -> str:
    gate_lines = [
        f"| {gate.name} | {'PASS' if gate.passed else 'FAIL'} | {gate.observed} | {gate.direction} {gate.threshold} |"
        for gate in report.gates
    ]
    neural = report.neural_challenger
    neural_lines = [
        "## Neural Challenger",
        "",
        f"- Available: `{neural.get('available', False)}`",
        f"- Version: `{neural.get('version', 'n/a')}`",
        f"- Verdict: `{neural.get('verdict', 'n/a')}`",
    ]
    if neural.get("metrics"):
        metrics = neural["metrics"]
        neural_lines.extend(
            [
                f"- MAE: `{metrics.get('val_MAE_delay_min')}`",
                f"- Spearman: `{metrics.get('val_SpearmanR')}`",
                f"- TopK@10: `{metrics.get('val_TopK10_precision')}`",
            ]
        )

    return "\n".join(
        [
            f"# Evaluation Report: {report.model_version}",
            "",
            f"- Recommendation: `{report.recommendation}`",
            f"- Accepted records: `{report.accepted_records:,}`",
            f"- Clusters: `{report.cluster_count:,}`",
            f"- Cluster-hour rows: `{report.cluster_hour_rows:,}`",
            f"- OSM snap fallback rate: `{report.osm_snap.get('fallback_rate')}`",
            f"- Fallback hotspots: `{report.fallback_export.get('hotspot_count')}`",
            "",
            "## Risk Model",
            "",
            f"- MAE: `{report.risk_metrics.get('val_MAE_delay_min')}`",
            f"- MAPE: `{report.risk_metrics.get('val_MAPE')}`",
            f"- Spearman: `{report.risk_metrics.get('val_SpearmanR')}`",
            f"- TopK@10: `{report.risk_metrics.get('val_TopK10_precision')}`",
            "",
            "## Gates",
            "",
            "| Gate | Status | Observed | Rule |",
            "|---|---:|---:|---|",
            *gate_lines,
            "",
            "## Survival",
            "",
            f"- C-index: `{report.survival_metrics.get('val_concordance_index')}`",
            f"- Heuristic fallback: `{report.survival_metrics.get('heuristic_fallback')}`",
            "",
            "## Anomaly And Routing",
            "",
            f"- Isolation Forest flagged rate: `{report.anomaly_flagged_rate}`",
            f"- Patrol routes: `{report.patrol_routes}`",
            "",
            *neural_lines,
            "",
        ]
    )


def write_report(report: EvaluationReport, artifacts_dir: Path, version: str) -> tuple[Path, Path]:
    json_path = artifacts_dir / f"evaluation_report_{version}.json"
    md_path = artifacts_dir / f"evaluation_report_{version}.md"
    json_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    md_path.write_text(report_to_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir", default="ml/artifacts")
    parser.add_argument("--fallback-dir", default="public/fallback")
    parser.add_argument("--version", default="v1-osm")
    parser.add_argument("--neural-version", default="neural-smoke")
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir)
    report = build_report(
        artifacts_dir,
        Path(args.fallback_dir),
        args.version,
        args.neural_version,
    )
    json_path, md_path = write_report(report, artifacts_dir, args.version)
    print(json.dumps({**asdict(report), "json_path": str(json_path), "markdown_path": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
