from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import get_prediction_store
from api.schemas.prediction import CommanderRequest, CommanderResponse
from api.serving import TieredPredictionStore

try:
    from google import genai
    from google.genai import types

    HAS_GEMINI = True
except ImportError:  # pragma: no cover - depends on optional SDK install
    HAS_GEMINI = False

router = APIRouter(tags=["commander"])


def _top_cluster_ids(context: dict[str, Any]) -> list[int]:
    return [int(cluster["cluster_id"]) for cluster in context.get("top_clusters", [])[:10]]


def _format_hour_range(window: dict[str, Any]) -> str:
    return f"{int(window.get('start_h', 0)):02d}:00-{int(window.get('end_h', 0)):02d}:00"


def _format_windows(cluster: dict[str, Any]) -> str:
    windows = cluster.get("enforcement_windows") or []
    if not windows:
        return "No preferred enforcement window is available."
    return "; ".join(
        f"{'primary' if index == 0 else 'secondary'}: {_format_hour_range(window)} "
        f"({round(float(window.get('yield_score') or 0) * 100)}% expected yield)"
        for index, window in enumerate(windows[:2])
    )


def _format_driver(driver: dict[str, Any], index: int) -> str:
    direction = "raises" if driver.get("direction") == "increases" else "reduces"
    contribution = abs(float(driver.get("shap_contribution_min") or 0))
    return f"{index + 1}. {driver.get('human_label', driver.get('feature', 'Model driver'))}: {direction} expected delay by {contribution:.4f} min."


def _cluster_answer(cluster: dict[str, Any]) -> str:
    drivers = "\n".join(_format_driver(driver, index) for index, driver in enumerate((cluster.get("shap_context") or [])[:3]))
    severity = "Critical" if float(cluster.get("final_risk_0_100") or 0) >= 78 else "Elevated"
    anomaly = (
        f"Yes. It is {cluster.get('anomaly_zscore')} sigma above its normal hour-of-day baseline."
        if cluster.get("is_anomaly")
        else "No active exception alert is attached to this cluster."
    )
    return "\n".join(
        [
            f"Operational Briefing: Cluster {cluster.get('cluster_id')} ({cluster.get('police_station')})",
            "",
            f"Assessment: {severity} priority, risk score {round(float(cluster.get('final_risk_0_100') or 0))}/100.",
            f"Forecast: {cluster.get('predicted_delay_min')} min/vehicle, based on {int(cluster.get('total_violations') or 0):,} validated records.",
            f"Primary pattern: {cluster.get('dominant_violation_type')} involving {cluster.get('dominant_vehicle_type')}.",
            "",
            "Why this cluster is risky:",
            drivers or "No SHAP driver context is available for this cluster.",
            "",
            f"Exception status: {anomaly}",
            "",
            "Recommended action:",
            f"Assign a patrol unit for focused no-parking clearance during {_format_windows(cluster)}. Start with visible obstruction points and update the queue after field clearance.",
            "",
            "Data basis: local prediction artifacts, enforcement history, anomaly score, and model driver contributions.",
        ]
    )


def _route_answer(store: TieredPredictionStore) -> str:
    route_payload = store.read("patrol_routes.json") or []
    routes = route_payload.get("items", route_payload.get("patrol_routes", [])) if isinstance(route_payload, dict) else route_payload
    if not routes:
        return "No patrol assignment data is available for the current operational window."
    lines = []
    for index, route in enumerate(routes[:3]):
        stops = ", ".join(f"cluster {point.get('cluster_id')} at {point.get('arrival_label')}" for point in route.get("waypoints", []))
        lines.append(
            f"{index + 1}. {route.get('unit_id')} from {route.get('origin_station')}: {stops}. "
            f"Estimated clearance value {route.get('total_delay_cleared_est')}."
        )
    return "\n".join(
        [
            "Patrol Assignment Briefing",
            "",
            "Recommended assignments:",
            "\n".join(lines),
            "",
            "Operational note: prioritize the first stop for each unit, then reassess priority zones after field clearance.",
        ]
    )


def _anomaly_answer(store: TieredPredictionStore, context: dict[str, Any]) -> str:
    anomalies = store.read("anomalies.json") or []
    if not anomalies:
        top = context.get("top_clusters", [])[:3]
        summary = " | ".join(
            f"cluster {cluster.get('cluster_id')} under {cluster.get('police_station')}" for cluster in top
        )
        return f"Exception Alert Briefing\n\nNo active exception alerts are currently present.\n\nCurrent priority context: {summary}."
    lines = [
        f"{index + 1}. Cluster {alert.get('cluster_id')} ({alert.get('police_station')}): "
        f"{alert.get('anomaly_zscore')} sigma above baseline, forecast delay {alert.get('predicted_delay_min')} min/vehicle."
        for index, alert in enumerate(anomalies[:4])
    ]
    return "\n".join(
        [
            "Exception Alert Briefing",
            "",
            "Active alerts:",
            "\n".join(lines),
            "",
            "Recommended action: verify field conditions at the top alert first, then dispatch clearance support if obstruction is confirmed.",
        ]
    )


def _local_grounded_response(message: str, context: dict[str, Any], store: TieredPredictionStore) -> str:
    clusters_by_id = {int(cluster["cluster_id"]): cluster for cluster in context.get("top_clusters", [])}
    match = re.search(r"cluster\s*#?\s*(\d+)", message, flags=re.IGNORECASE) or re.search(r"\b(\d{1,4})\b", message)
    if match:
        cluster_id = int(match.group(1))
        cluster = clusters_by_id.get(cluster_id) or (store.read("clusters.json") or {}).get(str(cluster_id))
        if cluster:
            return _cluster_answer(cluster)
        return f"Current prediction data is not available for cluster {cluster_id}. Available priority clusters: {', '.join(map(str, clusters_by_id))}."

    if re.search(r"route|patrol|unit|dispatch", message, flags=re.IGNORECASE):
        return _route_answer(store)

    if re.search(r"anomal|exception|alert|spike|unusual|event", message, flags=re.IGNORECASE):
        return _anomaly_answer(store, context)

    top = context.get("top_clusters", [])[:3]
    summary = " | ".join(
        f"cluster {cluster.get('cluster_id')} under {cluster.get('police_station')} jurisdiction: "
        f"forecast delay {cluster.get('predicted_delay_min')} min/vehicle, risk score {cluster.get('final_risk_0_100')}"
        for cluster in top
    )
    return "\n".join(
        [
            "Priority Enforcement Briefing",
            "",
            f"Highest-priority enforcement zones: {summary}.",
            "",
            "Recommended action: open the geospatial map, confirm the nearest patrol unit, and begin with the highest-risk cluster.",
        ]
    )


def _gemini_response(message: str, context: dict[str, Any]) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not HAS_GEMINI or not api_key:
        return None

    system_prompt = (
        "You are the NammaPark Intel command assistant for Bengaluru Traffic Police. "
        "Answer using only the supplied hotspot, route, anomaly, and SHAP context. "
        "Be formal, operational, and concise.\n\nTop cluster context:\n"
    )
    for cluster in context.get("top_clusters", [])[:5]:
        drivers = "; ".join(
            f"{driver.get('human_label', driver.get('feature'))}: {driver.get('shap_contribution_min')} min"
            for driver in cluster.get("shap_context", [])
        )
        system_prompt += (
            f"- Cluster {cluster.get('cluster_id')} near {cluster.get('police_station')}: "
            f"{cluster.get('predicted_delay_min')} min/vehicle, risk {cluster.get('final_risk_0_100')}. "
            f"Drivers: {drivers}.\n"
        )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        contents=message,
        config=types.GenerateContentConfig(system_instruction=system_prompt, max_output_tokens=900),
    )
    return response.text


@router.post("/commander", response_model=CommanderResponse)
async def ask_commander(
    request: CommanderRequest, fallback: TieredPredictionStore = Depends(get_prediction_store)
) -> dict[str, Any]:
    context = fallback.read("commander_context.json") or {"top_clusters": []}
    ids = _top_cluster_ids(context)
    if not ids:
        return {"response": "No cluster prediction data is available.", "grounded_cluster_ids": [], "source": fallback.last_source}

    message = request.user_message.strip()
    try:
        response_text = _gemini_response(message, context) or _local_grounded_response(message, context, fallback)
    except Exception as exc:  # pragma: no cover - external provider failure
        response_text = (
            f"External LLM call failed, so I am using the local grounded briefing.\n\n"
            f"{_local_grounded_response(message, context, fallback)}\n\nProvider error: {exc}"
        )

    return {"response": response_text, "grounded_cluster_ids": ids, "source": fallback.last_source}
