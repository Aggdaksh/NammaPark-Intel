"use client";

import { formatNumber, formatPredictionWindow } from "@/lib/format";
import type { OperationsData } from "@/types/api";

export function ShiftBriefExport({ data }: { data: OperationsData }) {
  function handleExport() {
    const top = data.hotspots.slice(0, 5);
    const routes = data.routes.slice(0, 3);
    const anomalies = data.anomalies.slice(0, 5);
    const lines = [
      "# NammaPark Intel Shift Brief",
      "",
      `Generated: ${new Date().toLocaleString()}`,
      `Forecast window: ${formatPredictionWindow(data.metadata.prediction_window)}`,
      `Model version: ${data.metadata.model_version || "unknown"}`,
      `Validated records: ${formatNumber(data.metadata.accepted_records || 0)}`,
      "",
      "## Priority Zones",
      ...top.map(
        (cluster, index) =>
          `${index + 1}. Cluster ${cluster.cluster_id} - ${cluster.police_station} - risk ${Math.round(cluster.final_risk_0_100)}/100 - delay ${formatNumber(cluster.predicted_delay_min, 4)} min/vehicle`
      ),
      "",
      "## Patrol Assignments",
      ...(routes.length
        ? routes.map(
            (route) =>
              `- ${route.unit_id} from ${route.origin_station}: ${route.waypoints.map((point) => `cluster ${point.cluster_id} at ${point.arrival_label}`).join(", ")}`
          )
        : ["- No route assignments available."]),
      "",
      "## Exception Alerts",
      ...(anomalies.length
        ? anomalies.map(
            (alert) =>
              `- Cluster ${alert.cluster_id} - ${alert.police_station} - ${formatNumber(alert.anomaly_zscore, 2)} sigma above baseline`
          )
        : ["- No active exception alerts."]),
      "",
      "## Recommended Opening Action",
      top[0]
        ? `Begin with cluster ${top[0].cluster_id} under ${top[0].police_station}. Confirm obstruction density, dispatch nearest unit, then refresh the queue after field clearance.`
        : "No priority cluster is available."
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `nammapark-shift-brief-${new Date().toISOString().slice(0, 10)}.md`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <button type="button" className="secondary-button export-brief-button" onClick={handleExport}>
      Export shift brief
    </button>
  );
}
