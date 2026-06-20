import type {
  AnomalyAlert,
  Cluster,
  DemoData,
  Health,
  ListResponse,
  MapRoads,
  MapsConfig,
  OperationsData,
  PatrolRoute,
  Session
} from "@/types/api";

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store"
  });

  if (response.status === 401 && typeof window !== "undefined") {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    throw new Error("Authentication required");
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `${path} returned ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function loadSession() {
  return apiFetch<Session>("/api/session");
}

export async function loadOperationsData(): Promise<OperationsData> {
  const [session, health, hotspots, routes, anomalies, demoData] = await Promise.all([
    apiFetch<Session>("/api/session").catch(() => null),
    apiFetch<Health>("/api/health").catch(() => null),
    apiFetch<ListResponse<Cluster>>("/api/hotspots?limit=50").catch(() => ({ items: [] })),
    apiFetch<ListResponse<PatrolRoute>>("/api/patrol-routes").catch(() => ({ items: [] })),
    apiFetch<ListResponse<AnomalyAlert>>("/api/anomalies").catch(() => ({ items: [] })),
    apiFetch<DemoData>("/api/demo-data").catch(() => ({} as DemoData))
  ]);

  return {
    session,
    health,
    metadata: demoData?.metadata || hotspots?.metadata || {},
    hotspots: hotspots?.items || demoData?.hotspots || [],
    clusters: demoData?.clusters || {},
    routes: routes?.items || demoData?.patrol_routes || [],
    anomalies: anomalies?.items || demoData?.anomalies || []
  };
}

export async function loadMapSupport() {
  const [roads, config] = await Promise.all([
    apiFetch<MapRoads>("/api/map-roads").catch(() => ({ segments: [] })),
    apiFetch<MapsConfig>("/api/maps-config").catch(() => ({ provider: "local-osm" }))
  ]);
  return { roads, config };
}
