-- Optional staging tables for legacy CSV files that do not match the typed
-- live schema. These tables preserve source provenance and full row payloads.

CREATE TABLE IF NOT EXISTS raw_csv_import_files (
    source_path VARCHAR(512) NOT NULL PRIMARY KEY,
    source_group VARCHAR(128) NOT NULL,
    recommended_target_table VARCHAR(128) NOT NULL,
    transform_action VARCHAR(128) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    file_modified_at DATETIME(6) NULL,
    sha256 CHAR(64) NOT NULL,
    header_json JSON NOT NULL,
    row_count BIGINT NULL,
    imported_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_raw_csv_files_group (source_group),
    KEY idx_raw_csv_files_target (recommended_target_table)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS raw_csv_import_rows (
    source_path VARCHAR(512) NOT NULL,
    row_index INT NOT NULL,
    row_hash CHAR(64) NOT NULL,
    payload_json JSON NOT NULL,
    imported_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (source_path, row_index),
    KEY idx_raw_csv_rows_hash (row_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO schema_migrations (version, description)
VALUES ('2026_06_raw_csv_staging', 'Raw CSV staging tables for legacy project data')
ON DUPLICATE KEY UPDATE description = VALUES(description);
