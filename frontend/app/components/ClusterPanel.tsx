"use client";

import { enforcementWindowLabel, formatNumber, riskColor } from "@/lib/format";
import type { Cluster } from "@/types/api";

export function ClusterPanel({ cluster }: { cluster: Cluster | null }) {
  if (!cluster) {
    return (
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Cluster detail</span>
            <h2>No cluster selected</h2>
          </div>
        </div>
      </section>
    );
  }

  const drivers = cluster.shap_context || [];
  const maxDriver = Math.max(...drivers.map((driver) => Math.abs(driver.shap_contribution_min)), 0.001);
  const color = riskColor(cluster.final_risk_0_100);

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Cluster detail</span>
          <h2>Cluster {cluster.cluster_id}</h2>
        </div>
        <span className="badge" style={{ borderColor: color, color }}>
          {Math.round(cluster.final_risk_0_100)}
        </span>
      </div>
      <div className="detail-grid">
        <div>
          <span>Jurisdiction</span>
          <strong>{cluster.police_station}</strong>
        </div>
        <div>
          <span>Predicted delay</span>
          <strong>{formatNumber(cluster.predicted_delay_min, 4)} min/vehicle</strong>
        </div>
        <div>
          <span>Records</span>
          <strong>{formatNumber(cluster.total_violations)}</strong>
        </div>
        <div>
          <span>Preferred window</span>
          <strong>{enforcementWindowLabel(cluster)}</strong>
        </div>
      </div>
      <div className="driver-block">
        <h3>Model drivers</h3>
        {drivers.slice(0, 5).map((driver) => {
          const impact = Math.abs(driver.shap_contribution_min);
          const width = Math.max(8, (impact / maxDriver) * 100);
          const positive = driver.direction === "increases";
          return (
            <div className="driver-row" key={driver.feature}>
              <div>
                <span>{driver.human_label}</span>
                <strong>
                  {positive ? "+" : "-"}
                  {formatNumber(impact, 4)} min
                </strong>
              </div>
              <div className="driver-track" aria-hidden="true">
                <span
                  style={{
                    width: `${width}%`,
                    background: positive ? "#b64232" : "#25754b"
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
      <p className="panel-note">
        {cluster.is_anomaly
          ? `Exception alert active: ${cluster.anomaly_zscore} sigma above the normal hour-of-day baseline.`
          : "No active exception alert is attached to this cluster."}
      </p>
    </section>
  );
}
