# HistGradientBoosting: next-day và weather-only

Thư mục này chứa hai nhánh `HistGradientBoostingRegressor` và các báo cáo
backtest. Đây là bước baseline học máy trước khi dự án chuyển sang XGBoost.

## Mục tiêu

Ba model độc lập dự báo:

- `target_currentspeed`.
- `target_traffic_density`.
- `target_us_aqi`.

## Model next-day

Model dự báo cùng địa điểm và cùng giờ của ngày kế tiếp, horizon chính xác 24
giờ. Bộ 43 feature gồm:

- 8 feature tĩnh về tọa độ, dân số, xe và diện tích xanh.
- 6 feature chu kỳ của giờ, thứ và ngày trong năm.
- 5 feature thời tiết tại giờ đích.
- Weather, traffic, AQI và pollutant tại `t-24h`.
- Rolling mean/std 24 giờ của tốc độ, mật độ, US AQI và PM2.5.

Model không dùng traffic hoặc AQI tại giờ đích và không dùng trực tiếp
`pollution_index_scaled`.

### Holdout tháng 12/2025

| Target | MAE | RMSE | R2 | Persistence MAE | Cải thiện MAE |
|---|---:|---:|---:|---:|---:|
| Current speed | 1.594 | 2.075 | 0.967 | 2.440 | 34.67% |
| Traffic density | 0.02844 | 0.03819 | 0.942 | 0.04616 | 38.38% |
| US AQI | 16.669 | 23.201 | 0.423 | 18.011 | 7.45% |

Metric nguồn: [`metrics.csv`](metrics.csv).

### Huấn luyện

```powershell
python src\models\next_day_traffic_aqi.py train
```

Lệnh tạo:

- `model_bundle.joblib`: chỉ fit trên target trước 01/12/2025, dùng tái hiện
  đánh giá hoặc historical prediction tháng 12.
- `model_bundle_full.joblib`: refit trên toàn bộ supervised rows năm 2025, dùng
  forecast production.
- `metadata.json`, `metadata_full.json`, `metrics.csv` và sample prediction.

### Dự báo lịch sử hoặc ngày tiếp theo

```powershell
python src\models\next_day_traffic_aqi.py predict `
  --target-date 2025-12-31

python src\models\next_day_traffic_aqi.py forecast `
  --current-date 2025-12-31 `
  --weather-file path\to\weather_forecast_2026-01-01.csv
```

Weather CSV cho một ngày phải có đúng 24 dòng liên tục và các cột `date`,
`hour`, `temperature_2m`, `relative_humidity_2m`, `precipitation`,
`wind_speed_10m`, `cloud_cover`.

## Model weather-only

Biến thể này chỉ dùng 19 feature: feature static, calendar và thời tiết tại giờ
đích. Vì không cần lag traffic/AQI, model có thể dự báo toàn bộ một khoảng thời
gian tương lai khi đã có weather forecast.

### Holdout tháng 12/2025

| Target | MAE | RMSE | R2 |
|---|---:|---:|---:|
| Current speed | 1.747 | 2.227 | 0.962 |
| Traffic density | 0.03161 | 0.04141 | 0.932 |
| US AQI | 19.864 | 26.293 | 0.259 |

Metric nguồn: [`weather_only_metrics.csv`](weather_only_metrics.csv).

### Huấn luyện và dự báo nhiều ngày

```powershell
python src\models\next_day_traffic_aqi.py train-weather-only

python src\models\next_day_traffic_aqi.py forecast-weather-period `
  --weather-file data\raw\weather\hcm_weather_2026_01.csv `
  --output-file data\processed\model_predictions\traffic_aqi_forecast_2026_01.csv
```

Bundle production là `model_bundle_weather_only_full.joblib`.

## Expanding-window backtest

```powershell
python src\models\next_day_traffic_aqi.py backtest `
  --first-test-month 2025-03 `
  --last-test-month 2025-12
```

Mỗi tháng chỉ được dự báo bởi model fit trên các tháng trước đó. Tổng hợp 10
fold, model next-day đạt:

| Target | MAE | R2 | Cải thiện so với persistence |
|---|---:|---:|---:|
| Current speed | 2.589 | 0.913 | 27.59% |
| Traffic density | 0.048 | 0.852 | 28.38% |
| US AQI | 13.838 | 0.643 | 6.71% |

Xem nhận định chi tiết tại [`backtest_assessment.md`](backtest_assessment.md).

## Hạn chế

- AQI next-day chỉ cải thiện nhẹ so với persistence và kém baseline ở một số
  tháng.
- Weather-only tiện cho forecast dài ngày nhưng mất thông tin trạng thái gần
  nhất, đặc biệt ảnh hưởng đến AQI.
- Một chuỗi weather TP. Hồ Chí Minh được dùng lại cho cả 5 tỉnh/thành.
- Bundle `*_full` đã thấy tháng 12/2025; không dùng bundle này để báo cáo lại
  holdout tháng 12.
