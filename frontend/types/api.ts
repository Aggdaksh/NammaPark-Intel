export type RiskLabel = "Low" | "Watch" | "Elevated" | "Critical" | string;

export interface Metadata {
  generated_at?: string;
  model_version?: string;
  prediction_window?: string;
  total_records_read?: number;
  accepted_records?: number;
  hotspot_count?: number;
  risk_metrics?: {
    val_MAE_delay_min?: number;
    val_MAPE?: number;
    val_SpearmanR?: number;
    val_TopK10_precision?: number;
  };
  implementation_notes?: string[];
  model_stack?: Array<{ name: string; role: string }>;
}

export interface ShapDriver {
  feature: string;
  shap_contribution_min: number;
  direction: "increases" | "decreases" | string;
  human_label: string;
}

export interface EnforcementWindow {
  start_h: number;
  end_h: number;
  yield_score: number;
}

export interface Cluster {
  cluster_id: number;
  centroid_lat: number;
  centroid_lon: number;
  h3_res8?: string;
  h3_res9?: string;
  police_station: string;
  dominant_vehicle_type: string;
  dominant_violation_type: string;
  road_type?: string;
  total_violations: number;
  active_days?: number;
  avg_bpr_delay_min?: number;
  predicted_delay_min: number;
  p_active?: number;
  p_active_at_dispatch?: number;
  final_risk_0_100: number;
  risk_label?: RiskLabel;
  is_anomaly?: boolean;
  anomaly_zscore?: number;
  peak_hour?: number;
  peak_hour_count?: number;
  p50_duration_min?: number;
  hourly_pattern?: number[];
  enforcement_windows?: EnforcementWindow[];
  shap_context?: ShapDriver[];
  expected_delay_clear?: number;
  model_version?: string;
}

export interface RouteWaypoint {
  cluster_id: number;
  arrival_min: number;
  arrival_label: string;
  expected_delay_clear?: number;
  police_station?: string;
}

export interface PatrolRoute {
  route_id: string;
  unit_id: string;
  shift_date: string;
  origin_station: string;
  shift_start_hour: number;
  waypoints: RouteWaypoint[];
  total_delay_cleared_est?: number;
  geojson?: {
    type: string;
    coordinates: Array<[number, number]>;
  };
}

export interface AnomalyAlert {
  cluster_id: number;
  police_station: string;
  anomaly_zscore: number;
  predicted_delay_min: number;
  final_risk_0_100?: number;
}

export interface DemoData {
  metadata: Metadata;
  hotspots: Cluster[];
  clusters: Record<string, Cluster>;
  patrol_routes: PatrolRoute[];
  anomalies: AnomalyAlert[];
  commander_context?: {
    top_clusters?: Cluster[];
  };
}

export interface ListResponse<T> {
  metadata?: Metadata;
  items: T[];
}

export interface Session {
  authenticated: boolean;
  user: string | null;
  role?: "admin" | "operator" | "viewer" | string | null;
  label?: string | null;
  expires_at?: number | null;
}

export interface Health {
  status: "ok" | "degraded" | string;
  data?: boolean;
  cache?: string;
  model?: string | null;
  generated_at?: string | null;
}

export interface RoadSegment {
  tier: "arterial" | "collector" | "local" | string;
  highway?: string;
  length_m?: number;
  coords: Array<[number, number]>;
}

export interface MapRoads {
  metadata?: {
    source?: string;
    segment_count?: number;
    max_segments?: number;
  };
  segments: RoadSegment[];
}

export interface MapsConfig {
  provider: "google" | "local-osm" | string;
  google_maps_api_key?: string | null;
  google_maps_map_id?: string | null;
}

export interface OperationsData {
  session: Session | null;
  health: Health | null;
  metadata: Metadata;
  hotspots: Cluster[];
  clusters: Record<string, Cluster>;
  routes: PatrolRoute[];
  anomalies: AnomalyAlert[];
}
