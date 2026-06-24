-- TiDB/MySQL schema for the live hourly forecasting pipeline.
-- Select the target database before running this file. The migration is
-- additive and intentionally does not drop the legacy CSV-import tables.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) NOT NULL PRIMARY KEY,
    description VARCHAR(255) NOT NULL,
    applied_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS model_locations (
    location_key VARCHAR(128) NOT NULL PRIMARY KEY,
    province_key VARCHAR(64) NOT NULL,
    district_key VARCHAR(64) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    lat DECIMAL(10,7) NOT NULL,
    lon DECIMAL(10,7) NOT NULL,
    api_lat DECIMAL(10,7) NOT NULL,
    api_lon DECIMAL(10,7) NOT NULL,
    estimated_vehicles BIGINT NULL,
    area_km2 DOUBLE NULL,
    population BIGINT NULL,
    density_person_km2 DOUBLE NULL,
    green_area_m2 DOUBLE NULL,
    green_per_capita_m2 DOUBLE NULL,
    is_live_supported TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_model_locations_province_district (province_key, district_key),
    KEY idx_model_locations_live (is_live_supported, province_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS model_registry (
    model_version VARCHAR(191) NOT NULL PRIMARY KEY,
    variant VARCHAR(128) NOT NULL,
    algorithm VARCHAR(128) NOT NULL,
    artifact_path VARCHAR(512) NOT NULL,
    horizon_hours SMALLINT NOT NULL,
    feature_count SMALLINT NOT NULL,
    training_target_start DATETIME NULL,
    training_target_end DATETIME NULL,
    metadata_json JSON NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    registered_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_model_registry_active (is_active, variant)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS live_hourly_observations (
    location_key VARCHAR(128) NOT NULL,
    observed_at DATETIME NOT NULL,
    collected_at DATETIME(6) NOT NULL,
    temperature_2m DOUBLE NOT NULL,
    relative_humidity_2m DOUBLE NOT NULL,
    precipitation DOUBLE NOT NULL,
    wind_speed_10m DOUBLE NOT NULL,
    cloud_cover DOUBLE NOT NULL,
    currentspeed DOUBLE NOT NULL,
    freeflowspeed DOUBLE NOT NULL,
    congestion_ratio DOUBLE NOT NULL,
    traffic_density DOUBLE NOT NULL,
    us_aqi DOUBLE NOT NULL,
    pm10 DOUBLE NOT NULL,
    pm2_5 DOUBLE NOT NULL,
    carbon_monoxide DOUBLE NOT NULL,
    nitrogen_dioxide DOUBLE NOT NULL,
    sulphur_dioxide DOUBLE NOT NULL,
    ozone DOUBLE NOT NULL,
    traffic_source VARCHAR(128) NOT NULL,
    aqi_source VARCHAR(128) NOT NULL,
    weather_source VARCHAR(128) NOT NULL,
    inserted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (location_key, observed_at),
    KEY idx_live_observations_time (observed_at),
    KEY idx_live_observations_collected (collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS live_hourly_predictions (
    location_key VARCHAR(128) NOT NULL,
    target_at DATETIME NOT NULL,
    model_version VARCHAR(191) NOT NULL,
    generated_at DATETIME(6) NOT NULL,
    predicted_currentspeed DOUBLE NOT NULL,
    predicted_traffic_density DOUBLE NOT NULL,
    predicted_us_aqi DOUBLE NOT NULL,
    inserted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (location_key, target_at, model_version),
    KEY idx_live_predictions_target (target_at),
    KEY idx_live_predictions_model (model_version, target_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS live_collector_runs (
    run_id CHAR(32) NOT NULL PRIMARY KEY,
    scheduled_at DATETIME NOT NULL,
    started_at DATETIME(6) NOT NULL,
    finished_at DATETIME(6) NULL,
    status VARCHAR(32) NOT NULL,
    observations_count INT NOT NULL DEFAULT 0,
    predictions_count INT NOT NULL DEFAULT 0,
    model_version VARCHAR(191) NULL,
    error_message TEXT NULL,
    KEY idx_collector_runs_scheduled (scheduled_at),
    KEY idx_collector_runs_status (status, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO schema_migrations (version, description)
VALUES ('2026_06_live_hourly_v2', 'Typed live observations and hourly model predictions')
ON DUPLICATE KEY UPDATE description = VALUES(description);
