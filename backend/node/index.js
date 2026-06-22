import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

import { createAuth } from "./auth.js";
import { createFallbackStore } from "./fallback-store.js";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const rootDir = normalize(join(__dirname, "..", ".."));

function loadLocalEnv(root) {
  for (const fileName of [".env.local", ".env", ".env.example"]) {
    const envPath = join(root, fileName);
    if (!existsSync(envPath)) continue;
    const lines = readFileSync(envPath, "utf8").split(/\r?\n/);
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
      if (!match || process.env[match[1]] !== undefined) continue;
      process.env[match[1]] = match[2].trim().replace(/^(['"])(.*)\1$/, "$2");
    }
  }
}

loadLocalEnv(rootDir);

const fallbackDir = join(rootDir, "public", "fallback");
const webDir = join(rootDir, "frontend");
const port = Number(process.env.PORT || 8787);
const auth = createAuth();
const fallbackStore = createFallbackStore(fallbackDir);
const pageAliases = new Map([
  ["/", "/index.html"],
  ["/login", "/login.html"],
  ["/map", "/map.html"],
  ["/chat", "/chat.html"]
]);

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon"
};

let demoData = fallbackStore.loadData();
let mapRoads = fallbackStore.readJson("map_roads.json") || { metadata: { segment_count: 0 }, segments: [] };

function sendJson(res, status, payload, headers = {}) {
  const body = JSON.stringify(payload, null, 2);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "content-type",
    "cache-control": "no-store",
    ...headers
  });
  res.end(body);
}

function sendText(res, status, text, contentType = "text/plain; charset=utf-8") {
  res.writeHead(status, {
    "content-type": contentType,
    "cache-control": "no-store"
  });
  res.end(text);
}

function redirect(res, location) {
  res.writeHead(302, {
    location,
    "cache-control": "no-store"
  });
  res.end();
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1024 * 1024) {
        reject(new Error("Request body too large"));
        req.destroy();
      }
    });
    req.on("end", () => {
      if (!body) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch {
        reject(new Error("Invalid JSON"));
      }
    });
  });
}

function parseLimit(url, fallback = 50) {
  const raw = url.searchParams.get("limit");
  if (!raw) return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(1, Math.min(100, Math.floor(parsed)));
}

function publicCluster(cluster) {
  if (!cluster) return null;
  return {
    ...cluster,
    cell_key: undefined
  };
}

function availableClusterIds() {
  return demoData.commander_context.top_clusters.map((cluster) => cluster.cluster_id);
}

function describeTopClusters(limit = 3) {
  return demoData.commander_context.top_clusters.slice(0, limit).map((cluster) => {
    return `cluster ${cluster.cluster_id} under ${cluster.police_station} jurisdiction: forecast delay ${cluster.predicted_delay_min} min/vehicle, risk score ${cluster.final_risk_0_100}`;
  });
}

function formatHourRange(window) {
  const start = String(window.start_h).padStart(2, "0");
  const end = String(window.end_h).padStart(2, "0");
  return `${start}:00-${end}:00`;
}

function formatEnforcementWindows(cluster) {
  const windows = cluster.enforcement_windows || [];
  if (!windows.length) return "No preferred enforcement window is available.";
  return windows
    .slice(0, 2)
    .map((window, index) => {
      const label = index === 0 ? "primary" : "secondary";
      return `${label}: ${formatHourRange(window)} (${Math.round(Number(window.yield_score || 0) * 100)}% expected yield)`;
    })
    .join("; ");
}

function formatDriver(driver, index) {
  const direction = driver.direction === "increases" ? "raises" : "reduces";
  return `${index + 1}. ${driver.human_label}: ${direction} expected delay by ${Math.abs(Number(driver.shap_contribution_min || 0)).toFixed(4)} min.`;
}

function clusterAnswer(cluster) {
  const drivers = (cluster.shap_context || [])
    .slice(0, 3)
    .map(formatDriver)
    .join("\n");
  const anomaly = cluster.is_anomaly
    ? `Yes. It is ${cluster.anomaly_zscore} sigma above its normal hour-of-day baseline, so it should be treated as an exception alert.`
    : "No active exception alert is attached to this cluster.";
  const severity = Number(cluster.final_risk_0_100 || 0) >= 78 ? "Critical" : "Elevated";

  return [
    `Operational Briefing: Cluster ${cluster.cluster_id} (${cluster.police_station})`,
    "",
    `Assessment: ${severity} priority, risk score ${Math.round(cluster.final_risk_0_100)}/100.`,
    `Forecast: ${cluster.predicted_delay_min} min/vehicle, based on ${cluster.total_violations.toLocaleString("en-IN")} validated records.`,
    `Primary pattern: ${cluster.dominant_violation_type} involving ${cluster.dominant_vehicle_type}.`,
    "",
    "Why this cluster is risky:",
    drivers,
    "",
    `Exception status: ${anomaly}`,
    "",
    "Recommended action:",
    `Assign a patrol unit for focused no-parking clearance during ${formatEnforcementWindows(cluster)}. Start with visible obstruction points, then update the queue after clearance so the next forecast reflects the intervention.`,
    "",
    "Data basis: local prediction artifacts, enforcement history, anomaly score, and model driver contributions."
  ].join("\n");
}

function routeAnswer() {
  if (!demoData.patrol_routes.length) {
    return "No patrol assignment data is available for the current operational window.";
  }
  const lines = demoData.patrol_routes.slice(0, 3).map((route, index) => {
    const stops = route.waypoints.map((point) => `cluster ${point.cluster_id} at ${point.arrival_label}`).join(", ");
    return `${index + 1}. ${route.unit_id} from ${route.origin_station}: ${stops}. Estimated clearance value ${route.total_delay_cleared_est}.`;
  });
  return [
    "Patrol Assignment Briefing",
    "",
    "Recommended assignments:",
    lines.join("\n"),
    "",
    "Operational note: prioritize the first stop for each unit, then reassess priority zones after field clearance."
  ].join("\n");
}

function anomalyAnswer() {
  if (!demoData.anomalies.length) {
    return [
      "Exception Alert Briefing",
      "",
      "No active exception alerts are currently present.",
      "",
      `Current priority context: ${describeTopClusters(3).join(" | ")}.`
    ].join("\n");
  }
  const alerts = demoData.anomalies
    .slice(0, 4)
    .map((alert, index) => {
      return `${index + 1}. Cluster ${alert.cluster_id} (${alert.police_station}): ${alert.anomaly_zscore} sigma above baseline, forecast delay ${alert.predicted_delay_min} min/vehicle.`;
    });
  return [
    "Exception Alert Briefing",
    "",
    "Active alerts:",
    alerts.join("\n"),
    "",
    "Recommended action: verify field conditions at the top alert first, then dispatch clearance support if obstruction is confirmed."
  ].join("\n");
}

function commanderResponse(userMessage) {
  const message = String(userMessage || "").trim();
  if (!demoData.commander_context.top_clusters.length) {
    return "I do not have current prediction data loaded. Run npm run generate, then restart the server.";
  }

  const clusterMatch = message.match(/cluster\s*#?\s*(\d+)/i) || message.match(/\b(\d{1,4})\b/);
  if (clusterMatch) {
    const clusterId = Number(clusterMatch[1]);
    const cluster = demoData.clusters[String(clusterId)];
    const allowed = availableClusterIds();
    if (!cluster || !allowed.includes(clusterId)) {
      return `Current prediction data is not available for cluster ${clusterId}. Available priority clusters: ${allowed.join(", ")}.`;
    }
    return clusterAnswer(cluster);
  }

  if (/route|patrol|unit|dispatch/i.test(message)) {
    return routeAnswer();
  }

  if (/anomal|exception|alert|spike|unusual|event/i.test(message)) {
    return anomalyAnswer();
  }

  const top = describeTopClusters(3).join(" | ");
  const route = demoData.patrol_routes[0];
  const routeLine = route
    ? `Recommended patrol assignment: ${route.unit_id} from ${route.origin_station}, estimated clearance value ${route.total_delay_cleared_est}.`
    : "";
  return [
    "Priority Enforcement Briefing",
    "",
    `Highest-priority enforcement zones: ${top}.`,
    "",
    routeLine || "No patrol assignment is currently available.",
    "",
    "Recommended action: open the geospatial map, confirm the nearest patrol unit, and begin with the highest-risk cluster."
  ].join("\n");
}

function serveStatic(req, res, pathname) {
  const requested = pageAliases.get(pathname) || pathname;
  const safePath = normalize(join(webDir, requested));
  if (!safePath.startsWith(webDir)) {
    sendText(res, 403, "Forbidden");
    return true;
  }
  if (!existsSync(safePath)) {
    return false;
  }
  const ext = extname(safePath);
  const contentType = mimeTypes[ext] || "application/octet-stream";
  sendText(res, 200, readFileSync(safePath), contentType);
  return true;
}

async function handleApi(req, res, url) {
  if (req.method === "OPTIONS") {
    sendJson(res, 204, {});
    return;
  }

  if (url.pathname === "/health" && req.method === "GET") {
    const generated = Boolean(demoData.metadata?.generated_at);
    sendJson(res, generated ? 200 : 503, {
      status: generated ? "ok" : "degraded",
      data: generated,
      cache: "static-fallback",
      model: demoData.metadata?.model_version || null,
      generated_at: demoData.metadata?.generated_at || null
    });
    return;
  }

  if (url.pathname === "/api/session" && req.method === "GET") {
    const session = auth.sessionFromRequest(req);
    sendJson(res, 200, {
      authenticated: Boolean(session),
      user: session?.username || null,
      role: session?.role || null,
      label: session?.label || null,
      expires_at: session?.expires_at || null
    });
    return;
  }

  if (url.pathname === "/api/login" && req.method === "POST") {
    try {
      const body = await parseBody(req);
      if (!auth.validateCredentials(body.username, body.password)) {
        sendJson(res, 401, { detail: "Invalid username or password" });
        return;
      }
      sendJson(
        res,
        200,
        {
          authenticated: true,
          user: body.username,
          role: auth.users.find((item) => item.username === body.username)?.role || "operator",
          label: auth.users.find((item) => item.username === body.username)?.label || "Operator",
          max_age_seconds: auth.maxAgeSeconds
        },
        auth.loginHeaders(body.username)
      );
    } catch (error) {
      sendJson(res, 400, { detail: error.message });
    }
    return;
  }

  if (url.pathname === "/api/logout" && req.method === "POST") {
    sendJson(res, 200, { authenticated: false }, auth.logoutHeaders());
    return;
  }

  if (!auth.isAuthenticated(req)) {
    sendJson(res, 401, { detail: "Authentication required" });
    return;
  }

  if (url.pathname === "/api/reload" && req.method === "POST") {
    demoData = fallbackStore.loadData();
    mapRoads = fallbackStore.readJson("map_roads.json") || { metadata: { segment_count: 0 }, segments: [] };
    sendJson(res, 200, { status: "reloaded", generated_at: demoData.metadata?.generated_at || null });
    return;
  }

  if (url.pathname === "/api/hotspots" && req.method === "GET") {
    const limit = parseLimit(url, 50);
    sendJson(
      res,
      200,
      { metadata: demoData.metadata, items: demoData.hotspots.slice(0, limit).map(publicCluster) },
      { "x-curbclear-source": "fallback" }
    );
    return;
  }

  if (url.pathname.startsWith("/api/cluster/") && req.method === "GET") {
    const rawId = decodeURIComponent(url.pathname.replace("/api/cluster/", ""));
    if (!/^\d+$/.test(rawId)) {
      sendJson(res, 422, { detail: [{ loc: ["path", "cluster_id"], msg: "Input should be a valid integer" }] });
      return;
    }
    const cluster = demoData.clusters[rawId];
    if (!cluster) {
      sendJson(res, 404, { detail: `Cluster ${rawId} not found` });
      return;
    }
    sendJson(res, 200, publicCluster(cluster), { "x-curbclear-source": "fallback" });
    return;
  }

  if (url.pathname === "/api/patrol-routes" && req.method === "GET") {
    sendJson(res, 200, { metadata: demoData.metadata, items: demoData.patrol_routes }, { "x-curbclear-source": "fallback" });
    return;
  }

  if (url.pathname === "/api/anomalies" && req.method === "GET") {
    sendJson(res, 200, { metadata: demoData.metadata, items: demoData.anomalies }, { "x-curbclear-source": "fallback" });
    return;
  }

  if (url.pathname === "/api/demo-data" && req.method === "GET") {
    sendJson(res, 200, demoData, { "x-curbclear-source": "fallback" });
    return;
  }

  if (url.pathname === "/api/maps-config" && req.method === "GET") {
    sendJson(res, 200, {
      provider: process.env.GOOGLE_MAPS_API_KEY ? "google" : "local-osm",
      google_maps_api_key: process.env.GOOGLE_MAPS_API_KEY || null,
      google_maps_map_id: process.env.GOOGLE_MAPS_MAP_ID || null
    });
    return;
  }

  if (url.pathname === "/api/map-roads" && req.method === "GET") {
    sendJson(res, 200, mapRoads, { "x-curbclear-source": "osm-graphml" });
    return;
  }

  if (url.pathname === "/api/commander" && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const response = commanderResponse(body.user_message);
      sendJson(res, 200, {
        response,
        model: "local-grounded-commander",
        grounded_cluster_ids: availableClusterIds(),
        source: "fallback"
      });
    } catch (error) {
      sendJson(res, 400, { detail: error.message });
    }
    return;
  }

  sendJson(res, 404, { detail: "Not found" });
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  if (url.pathname === "/health" || url.pathname.startsWith("/api/")) {
    await handleApi(req, res, url);
    return;
  }
  const publicStatic = new Set(["/login", "/login.html", "/login.js", "/styles.css", "/favicon.ico"]);
  const isPublicAsset = url.pathname.startsWith("/assets/");
  if (!auth.isAuthenticated(req) && !publicStatic.has(url.pathname) && !isPublicAsset) {
    redirect(res, `/login?next=${encodeURIComponent(url.pathname)}`);
    return;
  }
  if (auth.isAuthenticated(req) && (url.pathname === "/login" || url.pathname === "/login.html")) {
    redirect(res, "/");
    return;
  }
  if (!serveStatic(req, res, url.pathname)) {
    sendText(res, 404, "Not found");
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`NammaPark Intel demo listening on http://127.0.0.1:${port}`);
  console.log("Demo logins: operator/gridlock, admin/admin123, viewer/viewer123");
  if (!demoData.metadata?.generated_at) {
    console.log("No generated artifacts found. Run npm run generate in this project.");
  }
});
