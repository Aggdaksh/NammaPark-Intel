"use client";

import { useMemo, useState } from "react";
import { formatNumber, riskColor, riskLabel } from "@/lib/format";
import type { Cluster } from "@/types/api";

export function EnforcementQueue({
  clusters,
  selectedClusterId,
  onSelect
}: {
  clusters: Cluster[];
  selectedClusterId: number | null;
  onSelect: (clusterId: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [station, setStation] = useState("");

  const stations = useMemo(() => {
    return Array.from(new Set(clusters.map((cluster) => cluster.police_station).filter(Boolean))).sort();
  }, [clusters]);

  const filtered = useMemo(() => {
    const search = query.trim().toLowerCase();
    return clusters.filter((cluster) => {
      const stationMatch = !station || cluster.police_station === station;
      const searchMatch =
        !search ||
        String(cluster.cluster_id).includes(search) ||
        cluster.police_station.toLowerCase().includes(search) ||
        cluster.dominant_violation_type.toLowerCase().includes(search);
      return stationMatch && searchMatch;
    });
  }, [clusters, query, station]);

  return (
    <div className="queue-workspace">
      <div className="queue-controls">
        <label>
          Search
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Cluster, station, or violation"
          />
        </label>
        <label>
          Jurisdiction
          <select value={station} onChange={(event) => setStation(event.target.value)}>
            <option value="">All jurisdictions</option>
            {stations.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="queue-table" role="table" aria-label="Priority enforcement queue">
        <div className="queue-row queue-head" role="row">
          <span>Rank</span>
          <span>Cluster</span>
          <span>Jurisdiction</span>
          <span>Delay</span>
          <span>Risk</span>
        </div>
        {filtered.slice(0, 14).map((cluster, index) => {
          const active = cluster.cluster_id === selectedClusterId;
          const color = riskColor(cluster.final_risk_0_100);
          return (
            <button
              className={`queue-row ${active ? "active" : ""}`}
              key={cluster.cluster_id}
              type="button"
              onClick={() => onSelect(cluster.cluster_id)}
              role="row"
            >
              <span>{index + 1}</span>
              <span>
                <strong>Cluster {cluster.cluster_id}</strong>
                <small>{cluster.dominant_violation_type}</small>
              </span>
              <span>{cluster.police_station}</span>
              <span>{formatNumber(cluster.predicted_delay_min, 4)} min</span>
              <span className="risk-chip" style={{ borderColor: color, color }}>
                {riskLabel(cluster.final_risk_0_100)} {Math.round(cluster.final_risk_0_100)}
              </span>
            </button>
          );
        })}
        {!filtered.length ? <div className="empty-state">No clusters match the selected filters.</div> : null}
      </div>
    </div>
  );
}
