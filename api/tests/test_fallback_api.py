from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_health_reports_v1_osm_fallback() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["cache_tier"] == "fallback"
    assert payload["serving_order"] == ["redis", "postgres", "fallback"]
    assert payload["model_version"] == "v1-osm"
    assert payload["scored_rows"] == 65560


def test_hotspots_limit_and_source_header() -> None:
    response = client.get("/api/hotspots?limit=3")

    assert response.status_code == 200
    assert response.headers["x-curbclear-source"] == "fallback"
    payload = response.json()
    assert payload["metadata"]["model_version"] == "v1-osm"
    assert len(payload["items"]) == 3
    risks = [item["final_risk_0_100"] for item in payload["items"]]
    assert risks == sorted(risks, reverse=True)


def test_cluster_detail_and_missing_cluster_validation() -> None:
    top_cluster = client.get("/api/hotspots?limit=1").json()["items"][0]
    detail = client.get(f"/api/cluster/{top_cluster['cluster_id']}")

    assert detail.status_code == 200
    assert detail.headers["x-curbclear-source"] == "fallback"
    assert detail.json()["cluster_id"] == top_cluster["cluster_id"]
    assert len(detail.json()["shap_context"]) == 5

    missing = client.get("/api/cluster/999999")
    assert missing.status_code == 422


def test_patrol_routes_and_shift_date_filter() -> None:
    response = client.get("/api/patrol-routes?shift_date=2024-05-01")

    assert response.status_code == 200
    assert response.headers["x-curbclear-source"] == "fallback"
    payload = response.json()
    assert payload["metadata"]["model_version"] == "v1-osm"
    assert len(payload["items"]) == 3
    assert all(route["shift_date"] == "2024-05-01" for route in payload["items"])


def test_anomalies_response() -> None:
    response = client.get("/api/anomalies?limit=4")

    assert response.status_code == 200
    assert response.headers["x-curbclear-source"] == "fallback"
    payload = response.json()
    assert len(payload["items"]) == 4
    assert all(item["description"] for item in payload["items"])


def test_commander_grounded_cluster_and_route_answers() -> None:
    top_cluster = client.get("/api/hotspots?limit=1").json()["items"][0]
    cluster_response = client.post(
        "/api/commander",
        json={"user_message": f"Why is cluster {top_cluster['cluster_id']} high risk?"},
    )

    assert cluster_response.status_code == 200
    cluster_payload = cluster_response.json()
    assert top_cluster["cluster_id"] in cluster_payload["grounded_cluster_ids"]
    assert f"Cluster {top_cluster['cluster_id']}" in cluster_payload["response"]
    assert str(top_cluster["predicted_delay_min"]) in cluster_payload["response"]

    route_response = client.post("/api/commander", json={"user_message": "show patrol route"})
    assert route_response.status_code == 200
    assert "BT-01" in route_response.json()["response"]
