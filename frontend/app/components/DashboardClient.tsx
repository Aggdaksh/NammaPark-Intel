"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { loadOperationsData } from "@/lib/api";
import { enforcementWindowLabel, formatNumber, formatPredictionWindow, riskColor } from "@/lib/format";
import type { Cluster, OperationsData } from "@/types/api";
import { ClusterPanel } from "./ClusterPanel";
import { EnforcementQueue } from "./EnforcementQueue";
import { PatrolRouteMap } from "./PatrolRouteMap";
import { CsvUploader } from "./CsvUploader";

export function DashboardClient() {
  const [data, setData] = useState<OperationsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);

  useEffect(() => {
    loadOperationsData()
      .then((nextData) => {
        setData(nextData);
        setSelectedClusterId(nextData.hotspots[0]?.cluster_id || null);
      })
      .catch((nextError) => setError(nextError.message || "Unable to load operations data."));
  }, []);

  const selectedCluster = useMemo<Cluster | null>(() => {
    if (!data || selectedClusterId === null) return data?.hotspots[0] || null;
    return data.clusters[String(selectedClusterId)] || data.hotspots.find((item) => item.cluster_id === selectedClusterId) || null;
  }, [data, selectedClusterId]);

  if (error) {
    return <div className="notice error">{error}</div>;
  }

  if (!data) {
    return <div className="notice">Loading operations console...</div>;
  }

  const topCluster = data.hotspots[0];
  const records = data.metadata.accepted_records || topCluster?.total_violations || 0;
  const routeYield = data.routes.reduce((sum, route) => sum + Number(route.total_delay_cleared_est || 0), 0);

  return (
    <div className="dashboard-layout">
      <section className="brief-panel">
        <div>
          <span className="eyebrow">Live shift</span>
          <h1>Bengaluru parking enforcement desk</h1>
          <p>
            Current model output for hotspot prioritization, patrol queueing, anomaly review, and officer dispatch planning.
          </p>
        </div>
        <div className="brief-kpis">
          <div>
            <span>Forecast window</span>
            <strong>{formatPredictionWindow(data.metadata.prediction_window)}</strong>
          </div>
          <div>
            <span>Top jurisdiction</span>
            <strong>{topCluster?.police_station || "--"}</strong>
          </div>
        </div>
        <div className="brief-actions">
          <Link className="primary-button" href="/map">Open map</Link>
          <Link className="secondary-button" href="/commander">Ask assistant</Link>
        </div>
        <CsvUploader />
      </section>

      <section className="metric-strip" aria-label="Operational metrics">
        <MetricCard label="Priority zones" value={formatNumber(data.hotspots.length)} tone="#0d766d" />
        <MetricCard label="Exception alerts" value={formatNumber(data.anomalies.length)} tone="#b64232" />
        <MetricCard label="Route yield" value={formatNumber(routeYield, 2)} tone="#c38119" />
        <MetricCard label="Validated records" value={formatNumber(records)} tone="#145c8c" />
      </section>

      <div className="content-grid">
        <section className="panel queue-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Action queue</span>
              <h2>Priority enforcement queue</h2>
            </div>
            <button type="button" onClick={() => window.location.reload()}>
              Reload
            </button>
          </div>
          <EnforcementQueue
            clusters={data.hotspots}
            selectedClusterId={selectedCluster?.cluster_id || null}
            onSelect={setSelectedClusterId}
          />
        </section>

        <aside className="side-stack">
          <ClusterPanel cluster={selectedCluster} />
          <PatrolRouteMap routes={data.routes} />
          <section className="panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Shift brief</span>
                <h2>Immediate instruction</h2>
              </div>
              <span className="badge">{selectedCluster ? `#${selectedCluster.cluster_id}` : "--"}</span>
            </div>
            <p className="brief-copy">
              Begin with cluster {selectedCluster?.cluster_id || "--"} near {selectedCluster?.police_station || "--"} during{" "}
              {selectedCluster ? enforcementWindowLabel(selectedCluster) : "--"}. Confirm obstruction density before sending the
              next patrol unit.
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}

function MetricCard({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <article className="metric-card" style={{ borderTopColor: tone }}>
      <span>{label}</span>
      <strong style={{ color: tone }}>{value}</strong>
    </article>
  );
}
