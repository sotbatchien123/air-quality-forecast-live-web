# DAP391m - Air Quality Forecast

Dự án dự báo giao thông và chất lượng không khí theo giờ cho 65 địa điểm thuộc
5 tỉnh/thành Đông Nam Bộ: TP. Hồ Chí Minh, Đồng Nai, Bà Rịa - Vũng Tàu,
Long An và Tây Ninh.

Model dự báo 3 giá trị:

- `currentspeed`: tốc độ giao thông.
- `traffic_density`: mật độ giao thông, chuẩn hóa từ 0 đến 1.
- `us_aqi`: chỉ số chất lượng không khí theo thang US AQI.

Tất cả đường dẫn trong README này là đường dẫn tương đối từ root repo. Sau khi
clone project, chỉ cần `cd` vào thư mục repo rồi chạy lệnh; không cần sửa đường
dẫn theo máy cá nhân.

## Mục Lục

1. [Quy tắc đường dẫn](#quy-tắc-đường-dẫn)
2. [File nào dùng để làm gì](#file-nào-dùng-để-làm-gì)
3. [Luồng xử lý dữ liệu](#luồng-xử-lý-dữ-liệu)
4. [Features của model](#features-của-model)
5. [Model chạy như thế nào](#model-chạy-như-thế-nào)
6. [Các model trong project](#các-model-trong-project)
7. [Cách chạy model](#cách-chạy-model)
8. [Live 24/24 và TiDB](#live-2424-và-tidb)
9. [Deploy web bằng GitHub Actions](#deploy-web-bằng-github-actions)
10. [Kết quả thử nghiệm chính](#kết-quả-thử-nghiệm-chính)
11. [Những phần đã bỏ](#những-phần-đã-bỏ)

## Quy Tắc Đường Dẫn

Chạy mọi lệnh từ root repo:

```powershell
cd <thu-muc-repo>
```

Không hardcode đường dẫn tuyệt đối theo máy cá nhân trong code hoặc README.
Project tự tìm root bằng vị trí file Python, ví dụ các script trong `src/models` lấy root bằng
`Path(__file__).resolve().parents[2]`.

Thông tin nhạy cảm đặt bằng biến môi trường hoặc file local bị ignore:

```powershell
$env:TOMTOM_API_KEY = "your_tomtom_api_key"
Copy-Item .env.example .env
```

Nếu muốn dùng file key local:

```powershell
New-Item -ItemType Directory -Force secrets
Set-Content -Path secrets\tomtom_key.txt -Value "your_tomtom_api_key"
```

Thư mục `secrets/`, `.env`, `data/live/` và `data/tidb_import/` không được commit.

## File Nào Dùng Để Làm Gì

| Đường dẫn | Công dụng |
|---|---|
| `data/raw/AQI/` | AQI lịch sử từ Open-Meteo, gồm file theo tỉnh/thành và danh sách địa điểm. |
| `data/raw/traffic/` | Dữ liệu giao thông lịch sử theo tỉnh/thành. |
| `data/raw/weather/` | Dữ liệu thời tiết lịch sử hoặc forecast. |
| `data/raw/population/` | Dân số, diện tích và mật độ dân cư. |
| `data/raw/tree/` | Dữ liệu cây xanh/diện tích xanh ước tính. |
| `data/processed/model_features/` | Dữ liệu nền sạch cho model: traffic + weather + dữ liệu tĩnh. |
| `data/processed/model_predictions/` | Forecast offline đã sinh từ model. |
| `data/processed/model_evaluation/` | Bảng đánh giá forecast với actual AQI. |
| `data/live/` | Observation/prediction do live collector ghi ra, không commit. |
| `models/next_day_traffic_aqi/` | Artifact, metadata, metric và prediction mẫu của model. |
| `src/data/validate_model_features.py` | Kiểm tra bộ `model_features`. |
| `src/models/next_day_traffic_aqi.py` | File lõi: ghép dữ liệu, tạo feature, train/backtest baseline. |
| `src/models/xgboost_traffic_aqi.py` | Train XGBoost next-day cơ bản và weather-only. |
| `src/models/xgboost_multisource_next_day.py` | Train XGBoost next-day nhiều lag/rolling. |
| `src/models/xgboost_multisource_hourly.py` | Train/forecast model hourly. |
| `src/live/live_hourly_predictor.py` | Pipeline live: lấy API, tạo feature, predict t+1h, sync TiDB. |
| `src/live/replay_live_prediction.py` | Predict lại một giờ đã có observation, không train lại. |
| `src/database/` | Kết nối, migrate, transform và import/upsert TiDB. |

## Luồng Xử Lý Dữ Liệu

```text
data/raw
  -> data/processed/model_features
  -> load_joined_history()
  -> tạo features theo từng model
  -> train/evaluate/backtest
  -> lưu artifact trong models/
  -> forecast offline hoặc live predictor
  -> data/live và TiDB nếu có .env
```

Giải thích ngắn:

1. Thu dữ liệu gốc: AQI, traffic, weather, dân số, cây xanh.
2. Chuẩn hóa thành `data/processed/model_features/*.csv`, tách theo tỉnh/thành.
3. `load_joined_history()` ghép `model_features` với AQI lịch sử bằng khóa
   `date + hour + district_key`.
4. Mỗi model tự tạo lag/rolling/calendar feature theo horizon riêng.
5. Model được train theo thời gian, không shuffle.
6. Kết quả train lưu vào `models/next_day_traffic_aqi/`.

## Features Của Model

### 1. Feature gốc trong `model_features`

| Nhóm | Cột | Ý nghĩa |
|---|---|---|
| Định danh | `date`, `hour`, `location_name`, `district_key`, `district` | Xác định thời điểm và địa điểm. |
| Vị trí | `lat`, `lon` | Giúp model phân biệt không gian. |
| Traffic | `currentspeed`, `freeflowspeed`, `congestion_ratio`, `traffic_density` | Tình trạng giao thông tại thời điểm quan sát. |
| Dữ liệu tĩnh | `estimated_vehicles`, `area_km2`, `population`, `density_person_km2`, `green_area_m2`, `green_per_capita_m2` | Điều kiện nền của địa phương. |
| Weather | `temperature_2m`, `relative_humidity_2m`, `precipitation`, `wind_speed_10m`, `cloud_cover` | Điều kiện thời tiết theo giờ. |

### 2. Feature AQI ghép thêm từ `data/raw/AQI`

| Cột | Ý nghĩa |
|---|---|
| `us_aqi` | Chỉ số AQI cần dự báo. |
| `pm10`, `pm2_5` | Bụi mịn theo mô hình CAMS Global. |
| `carbon_monoxide`, `nitrogen_dioxide`, `sulphur_dioxide`, `ozone` | Các chất ô nhiễm phụ trợ. |

AQI là dữ liệu mô hình hóa từ Open-Meteo/CAMS Global, chưa phải số đo trực tiếp
từ trạm quan trắc.

### 3. Feature tạo thêm khi train

| Nhóm feature tạo thêm | Ví dụ | Dùng để làm gì |
|---|---|---|
| Calendar | `target_hour_sin`, `target_hour_cos`, `target_dow_sin`, `target_doy_cos` | Giúp model hiểu chu kỳ giờ, ngày trong tuần, mùa trong năm. |
| Forecast weather | `forecast_temperature_2m`, `forecast_wind_speed_10m` | Thời tiết tại giờ cần dự báo. |
| Lag weather | `lag24_temperature_2m`, `lag1_cloud_cover` | Thời tiết của các giờ trước. |
| Lag traffic | `lag24_currentspeed`, `lag1_traffic_density` | Trạng thái giao thông trước giờ dự báo. |
| Lag AQI | `lag24_us_aqi`, `lag1_pm2_5` | Chất lượng không khí trước giờ dự báo. |
| Rolling mean/std | `rolling24_us_aqi_mean`, `rolling3_currentspeed_std` | Xu hướng trung bình và độ dao động gần đây. |
| Rolling min/max | `rolling72_currentspeed_min`, `rolling48_us_aqi_max` | Biên thấp/cao trong cửa sổ thời gian. |

### 4. Feature theo từng model

| Model | Số feature | Feature chính |
|---|---:|---|
| HistGradientBoosting next-day | 43 | Static, calendar, weather giờ đích, lag 24h, rolling 24h. |
| HistGradientBoosting weather-only | 19 | Static, calendar, weather giờ đích. Không cần lag traffic/AQI. |
| XGBoost next-day | 43 | Giống next-day baseline nhưng dùng XGBoost. |
| XGBoost weather-only | 19 | Giống weather-only baseline nhưng dùng XGBoost. |
| XGBoost multisource next-day | 115/43 | Traffic dùng lag/rolling 24/48/72h; AQI giữ bộ 43 feature vì thử nghiệm nhiều lag hơn không cải thiện. |
| XGBoost multisource hourly | 123 | Lag 1/2/3/6/12h và rolling 3/6/12h, dùng cho live t+1h. |

## Model Chạy Như Thế Nào

### Train offline

```text
1. load_joined_history()
2. build_*_frame()
3. chia dữ liệu theo thời gian
4. train 3 regressor riêng: speed, density, AQI
5. đánh giá bằng MAE/RMSE/R2 và baseline persistence
6. refit production model trên toàn bộ dữ liệu hợp lệ
7. lưu .joblib, metadata, metrics, feature importance
```

Vì có 3 target, mỗi model thật ra là một bundle gồm 3 regressor độc lập:

- `target_currentspeed`
- `target_traffic_density`
- `target_us_aqi`

### Forecast offline

```text
history + weather forecast
  -> tạo feature cho target_timestamp
  -> load model bundle .joblib
  -> predict 3 target
  -> ghi CSV trong data/processed/model_predictions/
```

### Live hourly

```text
Open-Meteo weather + Open-Meteo AQI + TomTom traffic
  -> data/live/hourly_observations.csv
  -> build_inference()
  -> xgboost_multisource_hourly_full.joblib
  -> data/live/hourly_predictions.csv
  -> upsert TiDB nếu .env hợp lệ
```

Model hourly cần đủ history gần nhất cho các lag/rolling, tối thiểu 12 giờ liên tục.

## Các Model Trong Project

| Model | Script | Artifact chính |
|---|---|---|
| HistGradientBoosting next-day | `src/models/next_day_traffic_aqi.py train` | `models/next_day_traffic_aqi/model_bundle_full.joblib` |
| HistGradientBoosting weather-only | `src/models/next_day_traffic_aqi.py train-weather-only` | `models/next_day_traffic_aqi/model_bundle_weather_only_full.joblib` |
| XGBoost next-day | `src/models/xgboost_traffic_aqi.py train-all` | `models/next_day_traffic_aqi/xgboost/xgboost_next_day_full.joblib` |
| XGBoost weather-only | `src/models/xgboost_traffic_aqi.py train-all` | `models/next_day_traffic_aqi/xgboost/xgboost_weather_only_full.joblib` |
| XGBoost multisource next-day | `src/models/xgboost_multisource_next_day.py` | `models/next_day_traffic_aqi/xgboost_multisource/xgboost_multisource_next_day_full.joblib` |
| XGBoost multisource hourly | `src/models/xgboost_multisource_hourly.py train` | `models/next_day_traffic_aqi/xgboost_multisource_hourly/xgboost_multisource_hourly_full.joblib` |

## Cách Chạy Model

### 1. Cài môi trường

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-ml.txt
```

### 2. Kiểm tra dữ liệu feature

```powershell
python src\data\validate_model_features.py
```

Kỳ vọng:

```text
Total: 569,400 rows, 65 locations
```

### 3. Train baseline HistGradientBoosting

```powershell
python src\models\next_day_traffic_aqi.py train
```

Train weather-only:

```powershell
python src\models\next_day_traffic_aqi.py train-weather-only
```

Backtest theo tháng:

```powershell
python src\models\next_day_traffic_aqi.py backtest `
  --first-test-month 2025-03 `
  --last-test-month 2025-12
```

### 4. Train XGBoost cơ bản

```powershell
python src\models\xgboost_traffic_aqi.py train-all
```

Lệnh này train cả:

- `xgboost_next_day`
- `xgboost_weather_only`

### 5. Train XGBoost multisource next-day

```powershell
python src\models\xgboost_multisource_next_day.py
```

### 6. Train XGBoost multisource hourly

```powershell
python src\models\xgboost_multisource_hourly.py train
```

### 7. Forecast next-day từ dữ liệu lịch sử

Predict historical target date:

```powershell
python src\models\next_day_traffic_aqi.py predict `
  --target-date 2025-12-31
```

Forecast ngày tiếp theo từ current date:

```powershell
python src\models\next_day_traffic_aqi.py forecast `
  --current-date 2025-12-31 `
  --weather-file data\raw\weather\hcm_weather_2026_01.csv
```

### 8. Forecast nhiều ngày chỉ từ weather

```powershell
python src\models\xgboost_traffic_aqi.py forecast-weather-period `
  --weather-file data\raw\weather\hcm_weather_2026_01.csv `
  --output-file data\processed\model_predictions\traffic_aqi_forecast_2026_01_xgboost.csv
```

### 9. Forecast hourly t+1h offline

```powershell
python src\models\xgboost_multisource_hourly.py forecast-next-hour `
  --current-timestamp "2025-12-31 23:00" `
  --weather-file data\raw\weather\hcm_weather_2026_01.csv `
  --output-file data\processed\model_predictions\traffic_aqi_forecast_next_hour.csv
```

### 10. Predict lại một thời điểm live đã lưu

Không train lại model, chỉ đọc `data/live/hourly_observations.csv`:

```powershell
python src\live\replay_live_prediction.py `
  --target-timestamp "2026-06-23 09:00:00"
```

## Live 24/24 Và TiDB

### Kiểm tra API/model

Dùng biến môi trường:

```powershell
$env:TOMTOM_API_KEY = "your_tomtom_api_key"
python src\live\live_hourly_predictor.py doctor
```

Hoặc dùng file local trong `secrets/`:

```powershell
python src\live\live_hourly_predictor.py doctor `
  --tomtom-key-file secrets\tomtom_key.txt
```

### Chạy live một lần

```powershell
python src\live\live_hourly_predictor.py run
```

### Chạy nền mỗi giờ

```powershell
powershell -ExecutionPolicy Bypass -File src\live\start_live_collector.ps1
```

Nếu dùng file key:

```powershell
powershell -ExecutionPolicy Bypass -File src\live\start_live_collector.ps1 `
  -TomTomKeyFile secrets\tomtom_key.txt
```

### Windows Task Scheduler

```powershell
powershell -ExecutionPolicy Bypass -File src\live\register_live_collector_task.ps1
Start-ScheduledTask -TaskName DAP391_Live_Hourly_Collector
```

### TiDB

Tạo `.env` từ mẫu:

```powershell
Copy-Item .env.example .env
notepad .env
```

Kiểm tra kết nối:

```powershell
python src\database\check_tidb_connection.py
```

Khởi tạo schema và sync dữ liệu live:

```powershell
python src\database\manage_live_database.py init-schema
python src\database\manage_live_database.py sync-live
python src\database\manage_live_database.py status
```

Import/upsert dữ liệu đã transform:

```powershell
python src\database\transform_tidb_imports.py
python src\database\import_tidb_data.py typed --input-dir data\tidb_import
```

## Deploy Web Bằng GitHub Actions

Project đã có static web trong `web/` và workflow:

```text
.github/workflows/live_pages.yml
```

Workflow chạy theo lịch mỗi giờ:

```text
17 * * * *
```

Mỗi lần chạy:

```text
1. Checkout repo
2. Cài Python dependencies
3. Hydrate 36 giờ observation/prediction gần nhất từ TiDB
4. Gọi live collector để lấy Open-Meteo + TomTom
5. Predict bằng model hourly nếu đủ history
6. Upsert kết quả vào TiDB
7. Export web/data/dashboard.json
8. Deploy thư mục web/ lên GitHub Pages
```

### GitHub Secrets cần tạo

Repo có thể để public 100%, web và file `web/data/dashboard.json` cũng public được.
Riêng password TiDB và API key không nên commit vào repo, vì người khác có thể dùng chúng
để ghi/xóa database hoặc dùng hết quota API. Cách đúng là để GitHub Actions đọc qua
GitHub Secrets.

Nếu muốn tạo thủ công: vào GitHub repo -> Settings -> Secrets and variables -> Actions ->
New repository secret.

| Secret | Ý nghĩa |
|---|---|
| `TOMTOM_API_KEY` | Key TomTom dùng cho traffic live. |
| `DB_HOST` | Host TiDB Cloud. |
| `DB_PORT` | Thường là `4000`. |
| `DB_USERNAME` | User TiDB. |
| `DB_PASSWORD` | Password TiDB. |
| `DB_DATABASE` | Database, ví dụ `air_quality_forecast`. |
| `DB_SSL_MODE` | Nên dùng `VERIFY_IDENTITY`. |
| `DB_SSL_CA` | Có thể để trống nếu TiDB không yêu cầu CA file riêng. |

### Tự động cấu hình Secrets, Pages và chạy workflow

Project có script:

```text
scripts/configure_github_pages_actions.ps1
```

Script này đọc `.env` local, đẩy các biến cần thiết lên GitHub Secrets, bật GitHub Pages
theo workflow, và có thể chạy workflow ngay. Script không in password/API key ra màn hình.

Lần đầu cần cài GitHub CLI và login:

```powershell
winget install --id GitHub.cli -e
gh auth login
```

Sau khi đã login, chạy từ root repo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\configure_github_pages_actions.ps1 -RunWorkflow
```

Nếu chỉ muốn deploy web từ dữ liệu đang có trong TiDB, không gọi TomTom/Open-Meteo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\configure_github_pages_actions.ps1 -RunWorkflow -SkipCollection
```

### Bật GitHub Pages

Vào GitHub repo -> Settings -> Pages:

```text
Build and deployment -> Source -> GitHub Actions
```

Sau đó vào tab Actions, chạy workflow `Live forecast and GitHub Pages` bằng
`Run workflow`. Các lần sau GitHub sẽ tự chạy theo lịch mỗi giờ.

### Test chỉ export web, không gọi API live

Trong `Run workflow`, bật `skip_collection=true`. Cách này chỉ đọc TiDB và deploy
web, hữu ích khi muốn kiểm tra giao diện mà không gọi TomTom/Open-Meteo.

### Chạy web local

```powershell
python -m http.server 8000 -d web
```

Mở:

```text
http://localhost:8000
```

## Kết Quả Thử Nghiệm Chính

Holdout chính là tháng 12/2025. Split thời gian:

```text
01/2025 -> 10/2025: fit
11/2025: validation/early stopping
12/2025: holdout test
```

| Model | Horizon | Feature | Speed MAE | Density MAE | AQI MAE |
|---|---:|---:|---:|---:|---:|
| HistGradientBoosting next-day | 24h | 43 | 1.594 | 0.02844 | 16.669 |
| HistGradientBoosting weather-only | nhiều ngày | 19 | 1.747 | 0.03161 | 19.864 |
| XGBoost next-day | 24h | 43 | 1.585 | 0.02828 | 15.171 |
| XGBoost weather-only | nhiều ngày | 19 | 1.647 | 0.02950 | 20.789 |
| XGBoost multisource next-day | 24h | 115/43 | 1.571 | 0.02812 | 15.171 |
| XGBoost multisource hourly | 1h | 123 | 1.578 | 0.02790 | 0.796 |

Không nên so trực tiếp hourly với next-day để kết luận model nào tốt nhất, vì
hourly chỉ dự báo trước 1 giờ và có lợi thế từ history rất gần hiện tại.

Thử nghiệm ngoài năm train:

- Forecast AQI TP.HCM tháng 01/2026 bằng XGBoost weather-only.
- MAE `16.794`, RMSE `20.505`, R2 `0.113`, accuracy nhóm AQI `61.50%`.
- Kết luận: model chạy được ngoài năm 2025 nhưng cần theo dõi drift và hiệu chỉnh
  bằng dữ liệu trạm thật nếu dùng cho cảnh báo sức khỏe.

## Những Phần Đã Bỏ

Các file và pipeline liên quan WDI, pollution_index và bản đồ chỉ số ô nhiễm tự
tạo đã được loại khỏi luồng model. Lý do: model hiện tại không dùng trực tiếp các
chỉ số đó; giữ lại sẽ làm người đọc nhầm rằng đây là feature quan trọng.

Nguồn feature chính hiện nay là `data/processed/model_features`, chỉ chứa những
cột thật sự đi vào pipeline train/predict: traffic, weather và dữ liệu tĩnh.

## Giới Hạn Cần Nhớ

- Weather hiện dùng một chuỗi TP.HCM cho cả 5 tỉnh/thành, nên độ tin cậy ngoài
  TP.HCM còn hạn chế.
- AQI là dữ liệu mô hình CAMS Global, chưa phải ground truth từ trạm đo.
- Model học tốt quy luật thông thường hơn các biến động đột ngột.
- Muốn dùng cho cảnh báo sức khỏe cần thêm dữ liệu trạm, calibration địa phương
  và monitoring drift sau triển khai.
