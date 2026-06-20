import type { Cluster } from "@/types/api";

export function formatNumber(value: number | undefined, digits = 0) {
  if (value === undefined || Number.isNaN(value)) return "--";
  return value.toLocaleString("en-IN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  });
}

export function formatPredictionWindow(value?: string) {
  if (!value) return "--";
  return new Date(value).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function padHour(hour: number) {
  return `${String(hour).padStart(2, "0")}:00`;
}

export function riskLabel(score: number) {
  if (score >= 80) return "Critical";
  if (score >= 55) return "Watch";
  return "Low";
}

export function riskColor(score: number) {
  if (score >= 80) return "#b64232";
  if (score >= 55) return "#c38119";
  return "#25754b";
}

export function hourlyRisk(cluster: Cluster, hour: number) {
  const pattern = cluster.hourly_pattern || [];
  const peak = Math.max(...pattern, 1);
  const value = pattern[hour] || 0;
  const baseline = Number(cluster.final_risk_0_100 || 0);
  if (!pattern.length || !peak) return baseline;
  return Math.max(0, Math.min(100, baseline * (0.48 + 0.62 * (value / peak))));
}

export function enforcementWindowLabel(cluster: Cluster) {
  const window = cluster.enforcement_windows?.[0];
  if (!window) return "--";
  return `${padHour(window.start_h)}-${padHour(window.end_h)}`;
}
