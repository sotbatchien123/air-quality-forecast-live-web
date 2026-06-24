# TiDB import guide

Guide này dùng cho database TiDB Cloud `air_quality_forecast`.

## Mapping dữ liệu

| Nguồn dữ liệu | Bảng nên import | Cách xử lý |
|---|---|---|
| `data/live/hourly_observations.csv` | `live_hourly_observations` | Đổi tên `timestamp -> observed_at`, `collection_time -> collected_at`. |
| `data/live/hourly_predictions.csv`, `data/live/predictions/*.csv` | `live_hourly_predictions` | Đổi `target_timestamp -> target_at`; thêm `model_version/generated_at` nếu file cũ thiếu. |
| `data/processed/model_predictions/*forecast*.csv` và forecast trong `data/processed/model_evaluation` | `live_hourly_predictions` | Thêm `location_key`, `model_version`, `generated_at`. Không import holdout/test có actual label vào bảng live. |
| `data/raw/AQI/**/locations_5_provinces_old_boundaries.csv` | `model_locations` | Chỉ dùng làm manifest; static fields lấy từ joined history qua `load_locations()`. |
| `models/next_day_traffic_aqi/**/*metadata*.json` | `model_registry` | Import metadata JSON, variant, algorithm, horizon, feature_count; `.joblib` chỉ lưu `artifact_path`. |
| `data/processed/model_features/*.csv` + `data/raw/AQI/open_meteo_aqi_2025_output/aqi_*.csv` | `live_hourly_observations` khi chạy `--include-history` | Script dùng lại `load_joined_history()` để join traffic/weather/static/AQI đúng logic training. |
| `data/raw/traffic/*.csv`, `data/raw/weather/*.csv`, `data/raw/population/*.csv`, `data/raw/tree/*.csv` | `raw_csv_import_rows` | Giữ raw payload JSON vì schema live không có đủ cột gốc. |
| `data/raw/AQI/**/dataset_metadata.json` | `raw_csv_import_rows` | Lưu một JSON payload row để giữ metadata nguồn dữ liệu. |
| `models/**/metrics.csv`, `models/**/*feature_importance.csv`, `models/**/*holdout_predictions.csv`, `models/**/backtest*.csv` | `raw_csv_import_rows` | Đây là lineage/evaluation data, không phải production forecast. |
| `outputs/*.pptx` | Không import bằng script CSV | Artifact trình bày, không phải dữ liệu bảng. |
| `live_collector_runs` | Không import từ CSV | Collector 24/7 tự ghi run status. |
| `schema_migrations` | Không import từ CSV | SQL schema tự ghi migration version. |

## Vì sao cần raw staging

6 bảng live hiện tại là schema typed cho production model hourly. Nhiều CSV cũ có cấu trúc rất khác nhau: raw AQI có pollutant source fields, traffic raw có speed fields, metrics có MAE/RMSE/R2, feature importance có gain, holdout prediction có cả actual label. Nếu ép tất cả vào bảng live sẽ mất cột hoặc làm bẩn dữ liệu production.

File [`data/raw_import_tables.sql`](../../data/raw_import_tables.sql) tạo:

- `raw_csv_import_files`: metadata, hash, header, target recommendation cho từng CSV.
- `raw_csv_import_rows`: từng row CSV dưới dạng JSON payload, upsert theo `source_path + row_number`.

## PowerShell commands

Chạy các lệnh dưới đây từ root repo sau khi clone project. Không cần sửa
đường dẫn theo máy cá nhân.

Tạo `.env` và điền thông tin TiDB Cloud. Không commit file này.

```powershell
Copy-Item .env.example .env
notepad .env
```

Các biến cần có:

```text
DB_HOST=...
DB_PORT=4000
DB_USERNAME=...
DB_PASSWORD=...
DB_DATABASE=air_quality_forecast
DB_SSL_MODE=VERIFY_IDENTITY
DB_SSL_CA=
```

Kiểm tra kết nối:

```powershell
python src\database\check_tidb_connection.py
```

Áp dụng schema typed và raw staging:

```powershell
python src\database\import_tidb_data.py typed-schema
python src\database\import_tidb_data.py raw-schema
```

Quét project và tạo report mapping:

```powershell
python src\database\inspect_tidb_import_sources.py
```

Transform dữ liệu live + processed forecast sang CSV đúng schema:

```powershell
python src\database\transform_tidb_imports.py
```

Nếu muốn backfill cả historical observations 2025:

```powershell
python src\database\transform_tidb_imports.py --include-history
```

Import/upsert các CSV đã transform vào 4 bảng typed:

```powershell
python src\database\import_tidb_data.py typed --input-dir data\tidb_import
```

Xem trước raw CSV sẽ đi vào staging:

```powershell
python src\database\import_tidb_data.py raw --dry-run --limit-files 20
```

Import toàn bộ raw CSV vào staging:

```powershell
python src\database\import_tidb_data.py raw --create-raw-schema
```

Nếu chỉ muốn test sample trước:

```powershell
python src\database\import_tidb_data.py raw --create-raw-schema --max-rows-per-file 1000
```

Kiểm tra số dòng sau import:

```powershell
python src\database\manage_live_database.py status
python src\database\check_tidb_connection.py
```
