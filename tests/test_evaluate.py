from __future__ import annotations

from pathlib import Path

from ml.pipeline.evaluate import build_report, compare_neural, gate_at_least, report_to_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_gate_at_least_handles_pass_and_fail() -> None:
    assert gate_at_least("metric", 0.9, 0.8).passed is True
    assert gate_at_least("metric", 0.7, 0.8).passed is False
    assert gate_at_least("metric", None, 0.8).passed is False


def test_neural_comparison_recommends_champion_when_it_loses() -> None:
    neural = {
        "version": "neural-smoke",
        "metrics": {"val_MAE_delay_min": 0.5},
        "comparison": {
            "beats_champion_mae": False,
            "beats_champion_spearman": False,
            "beats_champion_topk10": False,
        },
    }

    result = compare_neural(neural)

    assert result["available"] is True
    assert result["verdict"] == "keep_lightgbm_champion"


def test_v1_osm_report_passes_all_gates() -> None:
    report = build_report(ROOT / "ml/artifacts", ROOT / "public/fallback", "v1-osm", "neural-smoke")

    assert report.recommendation == "ship_v1_osm"
    assert all(gate.passed for gate in report.gates)
    assert report.neural_challenger["verdict"] == "keep_lightgbm_champion"
    assert "Evaluation Report: v1-osm" in report_to_markdown(report)
