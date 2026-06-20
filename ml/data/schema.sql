CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_name       TEXT NOT NULL,
    data_hash           TEXT NOT NULL,
    started_at          TIMESTAMPTZ DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'started',
    metrics             JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key           TEXT PRIMARY KEY,
    payload             JSONB NOT NULL,
    source              TEXT NOT NULL DEFAULT 'postgres',
    updated_at          TIMESTAMPTZ DEFAULT now(),
    expires_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_cache_expires
    ON api_cache (expires_at);

CREATE TABLE IF NOT EXISTS violations_enriched (
    violation_id        TEXT PRIMARY KEY,
    lat                 DOUBLE PRECISION NOT NULL,
    lon                 DOUBLE PRECISION NOT NULL,
    geom                GEOMETRY(POINT, 4326)
                            GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
    h3_res8             VARCHAR(20),
    h3_res9             VARCHAR(20),
    vehicle_type        VARCHAR(30),
    violation_type      VARCHAR(120),
    created_ist         TIMESTAMPTZ NOT NULL,
    closed_ist          TIMESTAMPTZ,
    action_taken_ist    TIMESTAMPTZ,
    duration_min        DOUBLE PRECISION,
    osm_way_id          BIGINT,
    lane_count          SMALLINT,
    road_type           VARCHAR(30),
    speed_limit_kph     DOUBLE PRECISION,
    junction_flag       BOOLEAN DEFAULT FALSE,
    osm_snap_fallback   BOOLEAN DEFAULT FALSE,
    blockage_fraction   DOUBLE PRECISION,
    bpr_delay_min       DOUBLE PRECISION,
    cluster_id          INTEGER,
    is_anomaly          BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_violations_geom
    ON violations_enriched USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_violations_h3_res8
    ON violations_enriched USING HASH(h3_res8);
CREATE INDEX IF NOT EXISTS idx_violations_cluster_created
    ON violations_enriched (cluster_id, created_ist DESC);

CREATE TABLE IF NOT EXISTS spatial_clusters (
    cluster_id               INTEGER PRIMARY KEY,
    centroid_lat             DOUBLE PRECISION NOT NULL,
    centroid_lon             DOUBLE PRECISION NOT NULL,
    geom                     GEOMETRY(POLYGON, 4326),
    h3_res8                  VARCHAR(20) NOT NULL,
    h3_res9                  VARCHAR(20) NOT NULL,
    police_station           VARCHAR(60),
    dominant_vehicle_type    VARCHAR(30),
    dominant_violation_type  VARCHAR(120),
    junction_flag            BOOLEAN DEFAULT FALSE,
    is_sparse                BOOLEAN DEFAULT FALSE,
    hps_score                DOUBLE PRECISION,
    p50_duration_min         DOUBLE PRECISION,
    total_observed_days      INTEGER,
    active_days              INTEGER
);

CREATE INDEX IF NOT EXISTS idx_spatial_clusters_geom
    ON spatial_clusters USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_spatial_clusters_h3
    ON spatial_clusters USING HASH(h3_res8);

CREATE TABLE IF NOT EXISTS cluster_hour_features (
    cluster_id               INTEGER REFERENCES spatial_clusters(cluster_id),
    date                     DATE NOT NULL,
    hour_ist                 SMALLINT NOT NULL,
    day_of_week              SMALLINT,
    month                    SMALLINT,
    violation_count          INTEGER,
    bpr_delay_sum_min        DOUBLE PRECISION,
    avg_blockage_fraction    DOUBLE PRECISION,
    delay_lag_1h             DOUBLE PRECISION,
    delay_lag_2h             DOUBLE PRECISION,
    delay_lag_3h             DOUBLE PRECISION,
    delay_lag_6h             DOUBLE PRECISION,
    delay_lag_24h            DOUBLE PRECISION,
    delay_lag_48h            DOUBLE PRECISION,
    delay_lag_168h           DOUBLE PRECISION,
    delay_roll3h_mean        DOUBLE PRECISION,
    delay_roll6h_mean        DOUBLE PRECISION,
    delay_roll24h_mean       DOUBLE PRECISION,
    delay_roll24h_std        DOUBLE PRECISION,
    kring1_delay_lag         DOUBLE PRECISION,
    kring2_delay_lag         DOUBLE PRECISION,
    vehicle_mix_entropy      DOUBLE PRECISION,
    is_peak                  BOOLEAN,
    is_weekend               BOOLEAN,
    enforcement_yield        DOUBLE PRECISION,
    PRIMARY KEY (cluster_id, date, hour_ist)
);

CREATE INDEX IF NOT EXISTS idx_cluster_hour_cluster_date
    ON cluster_hour_features (cluster_id, date DESC, hour_ist);

CREATE TABLE IF NOT EXISTS cluster_predictions (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id               INTEGER REFERENCES spatial_clusters(cluster_id),
    prediction_for           TIMESTAMPTZ NOT NULL,
    predicted_delay_min      DOUBLE PRECISION,
    final_risk_0_100         DOUBLE PRECISION,
    p_active_at_dispatch     DOUBLE PRECISION,
    is_anomaly               BOOLEAN DEFAULT FALSE,
    anomaly_zscore           DOUBLE PRECISION,
    enforcement_windows      JSONB,
    shap_context             JSONB,
    model_version            VARCHAR(20) NOT NULL,
    created_at               TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_predictions_cluster_time
    ON cluster_predictions (cluster_id, prediction_for DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_window_risk
    ON cluster_predictions (prediction_for DESC, final_risk_0_100 DESC);

CREATE TABLE IF NOT EXISTS patrol_routes (
    route_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id                  VARCHAR(20) NOT NULL,
    shift_date               DATE NOT NULL,
    origin_station           VARCHAR(60),
    waypoints                JSONB NOT NULL,
    geojson                  JSONB,
    total_delay_cleared_est  DOUBLE PRECISION,
    model_version            VARCHAR(20),
    generated_at             TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patrol_routes_shift_unit
    ON patrol_routes (shift_date, unit_id);
