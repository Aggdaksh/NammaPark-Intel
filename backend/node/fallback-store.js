import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

export function createFallbackStore(fallbackDir) {
  function readJson(name) {
    const path = join(fallbackDir, name);
    if (!existsSync(path)) return null;
    return JSON.parse(readFileSync(path, "utf-8"));
  }

  function loadData() {
    const data = readJson("demo_data.json");
    return data || {
      metadata: { model_version: "missing", generated_at: null },
      hotspots: [],
      clusters: {},
      patrol_routes: [],
      anomalies: [],
      commander_context: { top_clusters: [], patrol_routes: [], anomaly_alerts: [] }
    };
  }

  return { readJson, loadData };
}
