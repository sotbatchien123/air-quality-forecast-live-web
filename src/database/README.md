# Live database

Database mới phục vụ trực tiếp model XGBoost multisource hourly và collector
chạy 24/7. Schema dùng kiểu số/thời gian thật, khóa upsert idempotent và không
xóa các bảng import CSV cũ.

## Các bảng

| Bảng | Mục đích | Khóa chống trùng |
|---|---|---|
| `model_locations` | 65 location, dữ liệu static và trạng thái TomTom | `location_key` |
| `model_registry` | Version, feature và metadata của bundle | `model_version` |
| `live_hourly_observations` | Weather, traffic, AQI theo giờ | `location_key + observed_at` |
| `live_hourly_predictions` | Ba target dự báo cho giờ kế tiếp | `location_key + target_at + model_version` |
| `live_collector_runs` | Theo dõi success, retry, lỗi và số dòng mỗi run | `run_id` |
| `schema_migrations` | Version schema đã áp dụng | `version` |

## 1. Cấu hình

```powershell
Copy-Item .env.example .env
notepad .env
```

Điền `DB_HOST`, `DB_PORT`, `DB_USERNAME`, `DB_PASSWORD`, `DB_DATABASE`. File
`.env` đã nằm trong `.gitignore` và không được commit.

Với TiDB Cloud giữ:

```text
DB_SSL_MODE=VERIFY_IDENTITY
```

Nếu nhà cung cấp yêu cầu CA riêng, ưu tiên đặt file trong repo, ví dụ
`certs/tidb-ca.pem`, rồi điền `DB_SSL_CA=certs/tidb-ca.pem`.

## 2. Cài dependency

```powershell
pip install -r requirements-ml.txt
```

## 3. Khởi tạo schema

Tạo database rỗng trên TiDB Cloud trước, sau đó chạy:

```powershell
python src\database\manage_live_database.py init-schema
```

Lệnh đọc [`data/setup_tables.sql`](../../data/setup_tables.sql), chỉ dùng
`CREATE TABLE IF NOT EXISTS` và không drop bảng cũ.

## 4. Backfill dữ liệu live đang có

```powershell
python src\database\manage_live_database.py sync-live
```

Lệnh đồng bộ:

- 65 location và đánh dấu 3 location TomTom chưa hỗ trợ.
- Bundle hourly hiện hành vào model registry.
- Toàn bộ `data/live/hourly_observations.csv`.
- Các file forecast trong `data/live/predictions`.

Có thể chạy lại an toàn vì mọi bảng đều upsert theo khóa nghiệp vụ.

## 5. Kiểm tra

```powershell
python src\database\manage_live_database.py status
python src\live\live_hourly_predictor.py doctor `
  --tomtom-key-file secrets\tomtom_key.txt
```

`status` trả số dòng và timestamp mới nhất. `doctor` kiểm tra API, model và đủ
5 bảng live trước khi collector bắt đầu.

## Đồng bộ 24/7

Khi `.env` có đủ cấu hình, cả `run`, `run-forever` và Windows Scheduled Task tự
động ghi TiDB. Mỗi run vẫn ghi CSV trước, sau đó upsert lại 72 giờ gần nhất vào
database. Cửa sổ này tự bù các giờ bị thiếu sau một đợt mất kết nối ngắn.

```powershell
powershell -ExecutionPolicy Bypass -File src\live\register_live_collector_task.ps1
Start-ScheduledTask -TaskName DAP391_Live_Hourly_Collector
```

Các lệnh Scheduled Task có thể cần PowerShell chạy với quyền phù hợp của user
Windows hiện tại.

Nếu database đã được cấu hình nhưng lỗi, `LIVE_DB_REQUIRED=true` làm task fail
để Windows/retry loop thử lại; dữ liệu đã thu vẫn còn trong CSV. Chỉ đặt biến
này thành `false` khi chủ động chấp nhận chế độ CSV-only trong lúc DB lỗi.

## Truy vấn mẫu

```sql
-- Observation mới nhất của từng location
SELECT o.*
FROM live_hourly_observations o
JOIN (
    SELECT location_key, MAX(observed_at) AS observed_at
    FROM live_hourly_observations
    GROUP BY location_key
) latest USING (location_key, observed_at);

-- Forecast mới nhất
SELECT p.*, l.province_key, l.display_name
FROM live_hourly_predictions p
JOIN model_locations l USING (location_key)
ORDER BY p.target_at DESC, p.location_key
LIMIT 100;
```

## Migration từ schema cũ

Các bảng `traffic_*`, `weather_hcm`, `population_southeast`,
`tree_green_data`, `vehicle_count` không bị xóa. Pipeline live mới không còn ghi
vào các bảng này. Chỉ xóa chúng sau khi đã xác nhận backfill và backup thành
công; migration mặc định không thực hiện thao tác phá hủy dữ liệu.
