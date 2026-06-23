# Model Catalog và quá trình phát triển

Tài liệu này là điểm vào chung cho toàn bộ model trong dự án. Các con số bên
dưới được lấy trực tiếp từ CSV metrics và JSON metadata đã lưu trong
`models/next_day_traffic_aqi`.

## Bài toán

Mỗi model gồm ba regressor độc lập cho:

- `target_currentspeed`.
- `target_traffic_density`.
- `target_us_aqi`.

Giá trị dự báo được chặn ở `0` đối với tốc độ và AQI, và trong `[0, 1]` đối với
mật độ giao thông. `pollution_index_scaled` được dùng trong pipeline chuẩn bị dữ
liệu nhưng không được đưa trực tiếp vào feature của các model ở đây.

## Dữ liệu đầu vào

Pipeline `load_joined_history()` ghép dữ liệu theo bộ khóa
`date + hour + district_key`, sau đó kiểm tra trùng khóa và số dòng bị mất.

| Nhóm | Cột chính |
|---|---|
| Traffic | `currentspeed`, `freeflowspeed`, `congestion_ratio`, `traffic_density` |
| AQI/pollutant | `us_aqi`, `pm10`, `pm2_5`, `carbon_monoxide`, `nitrogen_dioxide`, `sulphur_dioxide`, `ozone` |
| Weather | `temperature_2m`, `relative_humidity_2m`, `precipitation`, `wind_speed_10m`, `cloud_cover` |
| Static | `lat`, `lon`, `estimated_vehicles`, `area_km2`, `population`, `density_person_km2`, `green_area_m2`, `green_per_capita_m2` |
| Calendar | sin/cos của giờ, thứ trong tuần và ngày trong năm |

## Quá trình phát triển

### 1. Persistence baseline

Mốc tham chiếu đầu tiên giả định trạng thái lặp lại:

- Next-day: `y(t) = y(t-24h)`.
- Hourly: `y(t) = y(t-1h)`.

Mọi tỷ lệ `MAE improvement` trong báo cáo đều đo mức cải thiện so với baseline
này. Baseline không tạo bundle riêng.

### 2. HistGradientBoosting next-day

Model học máy đầu tiên dùng 43 feature: dữ liệu tĩnh, chu kỳ thời gian, thời tiết
của giờ đích, lag 24 giờ của weather/traffic/AQI và rolling mean/std 24 giờ.
Expanding-window backtest từ 03/2025 đến 12/2025 được bổ sung để kiểm tra model
trên nhiều chế độ thời gian thay vì chỉ một holdout.

### 3. Weather-only

Biến thể 19 feature bỏ toàn bộ lag traffic/AQI. Model này có thể dự báo một giai
đoạn nhiều ngày chỉ từ forecast thời tiết và dữ liệu tĩnh, đổi lại accuracy thấp
hơn. Đây là nhánh được dùng để tạo forecast tháng 01/2026.

### 4. XGBoost và temporal validation

HistGradientBoosting được thay bằng XGBoost. Giai đoạn 01-10/2025 dùng fit ứng
viên, 11/2025 dùng early stopping để chọn số cây, và 12/2025 giữ nguyên làm test.
Sau khi đánh giá, model production được refit trên toàn bộ năm 2025 với số cây
đã chọn.

### 5. Multisource next-day

Feature traffic được mở rộng với lag và rolling window 24, 48, 72 giờ. Tổng hợp
feature có 115 cột. Riêng AQI vẫn dùng bộ 43 feature của nhánh XGBoost next-day
vì thử nghiệm thêm lag 48/72 giờ làm kết quả temporal holdout kém hơn.

### 6. Multisource hourly

Chân trời được rút xuống một giờ. Model dùng lag 1, 2, 3, 6, 12 giờ và rolling
mean/std 3, 6, 12 giờ, tổng cộng 123 feature. Đây là model phù hợp cho pipeline
live khi có đủ 12 snapshot liên tiếp.

### 7. Kiểm tra ngoài năm huấn luyện

Forecast weather-only cho TP. Hồ Chí Minh trong 01/2026 được ghép một-một với
16.368 bản ghi AQI lưu trữ. Kết quả: MAE `16.794`, RMSE `20.505`, R2 `0.113`,
bias `+7.686`, accuracy nhóm AQI `61.50%`. Kết quả này cho thấy model chưa ổn
định khi chuyển sang thời gian mới và cần được giám sát sau triển khai.

## Giao thức đánh giá

```text
01/2025 ---------------- 10/2025 | 11/2025 | 12/2025
             fit                  validation   holdout
```

- Không shuffle dữ liệu thời gian.
- Feature lag/rolling chỉ lấy từ thời điểm đã có trước giờ đích.
- Model holdout chỉ fit đến hết 30/11/2025.
- Model `*_full.joblib` mới được refit trên toàn bộ dữ liệu sau khi đánh giá.
- Metric chính: MAE, RMSE, R2, bias và tỷ lệ nằm trong tolerance.

## So sánh holdout tháng 12/2025

| Model | Horizon | Features | Speed MAE | Density MAE | AQI MAE |
|---|---:|---:|---:|---:|---:|
| HistGradientBoosting next-day | 24h | 43 | 1.594 | 0.02844 | 16.669 |
| HistGradientBoosting weather-only | nhiều ngày | 19 | 1.747 | 0.03161 | 19.864 |
| XGBoost next-day | 24h | 43 | 1.585 | 0.02828 | 15.171 |
| XGBoost weather-only | nhiều ngày | 19 | 1.647 | 0.02950 | 20.789 |
| XGBoost multisource next-day | 24h | 115/43 | **1.571** | 0.02812 | 15.171 |
| XGBoost multisource hourly | 1h | 123 | 1.578 | **0.02790** | **0.796** |

Không so sánh trực tiếp model hourly với model next-day để chọn model "tốt
nhất": hourly có chân trời ngắn hơn và cần dữ liệu vừa quan sát đến `t`, trong
khi next-day phải dự báo xa 24 giờ. AQI hourly rất cao trên holdout
(`R2 = 0.998`) nhưng vẫn cần kiểm tra bằng dữ liệu live độc lập để loại trừ sự
phụ thuộc quá mạnh vào tính liên tục của chuỗi CAMS.

## Model nên dùng

| Nhu cầu | Model |
|---|---|
| Dự báo giờ tiếp theo khi có đủ lịch sử 12 giờ | `xgboost_multisource_hourly_full.joblib` |
| Dự báo cùng giờ ngày mai | `xgboost_multisource_next_day_full.joblib` |
| Dự báo nhiều ngày chỉ từ weather forecast | `xgboost_weather_only_full.joblib` |
| Tái hiện baseline và monthly backtest | `model_bundle.joblib` |

## Tái hiện quá trình huấn luyện

```powershell
# 1. Baseline học máy, weather-only và expanding-window backtest
python src\models\next_day_traffic_aqi.py train
python src\models\next_day_traffic_aqi.py train-weather-only
python src\models\next_day_traffic_aqi.py backtest `
  --first-test-month 2025-03 --last-test-month 2025-12

# 2. XGBoost 43-feature và weather-only 19-feature
python src\models\xgboost_traffic_aqi.py train-all

# 3. XGBoost multisource
python src\models\xgboost_multisource_next_day.py
python src\models\xgboost_multisource_hourly.py train

# 4. Đánh giá forecast AQI TP.HCM tháng 01/2026
python src\models\evaluate_hcm_aqi_2026_01.py
```

## Artifact và khả năng tái lập

Mỗi nhánh XGBoost lưu bốn loại artifact:

- `*_full.joblib`: ba regressor production, danh sách feature và metadata.
- `*_metadata.json`: phiên bản thư viện, split, tham số, số cây và feature.
- `*_metrics.csv`: kết quả trên holdout tháng 12/2025.
- `*_holdout_predictions.csv` và `*_feature_importance.csv`: dữ liệu audit.

Không đánh giá lại model bằng bundle `*_full.joblib` trên tháng 12/2025 vì bundle
này đã được refit có sử dụng tháng 12. Dùng CSV metrics đã sinh từ evaluation
model hoặc chạy lại pipeline temporal split.

## Tài liệu từng nhóm

- [HistGradientBoosting và weather-only](next_day_traffic_aqi/README.md)
- [XGBoost cơ bản](next_day_traffic_aqi/xgboost/README.md)
- [XGBoost multisource next-day](next_day_traffic_aqi/xgboost_multisource/README.md)
- [XGBoost multisource hourly](next_day_traffic_aqi/xgboost_multisource_hourly/README.md)
- [Live collection và prediction](../src/live/README.md)

## Giới hạn chung

- Weather hiện chỉ có một chuỗi của TP. Hồ Chí Minh và được tái sử dụng cho 5
  tỉnh/thành.
- AQI là dữ liệu mô hình CAMS Global, không phải ground truth từ trạm.
- Dữ liệu static thay đổi chậm và chủ yếu giúp model phân biệt địa điểm; chưa có
  chuỗi cập nhật dân số, số xe hoặc cây xanh theo thời gian.
- Các model học tốt quy luật thông thường hơn các đỉnh AQI hay thay đổi giao
  thông đột ngột.
- Trước khi dùng cho cảnh báo sức khỏe cần thêm dữ liệu trạm, calibration theo
  địa phương, backtest rolling ngoài năm 2025 và monitoring drift.
