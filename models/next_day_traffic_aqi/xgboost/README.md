# XGBoost next-day và weather-only

Thư mục này chứa hai biến thể `XGBRegressor`, mỗi biến thể gồm ba regressor độc
lập cho tốc độ, mật độ giao thông và US AQI.

## Các biến thể

| Variant | Horizon | Feature | Dữ liệu cần lúc inference |
|---|---:|---:|---|
| `xgboost_next_day` | 24 giờ | 43 | Weather giờ đích + traffic/AQI lịch sử 24 giờ |
| `xgboost_weather_only` | Nhiều ngày | 19 | Weather tương lai + feature static/calendar |

Next-day dùng lag 24 giờ và rolling statistics 24 giờ. Weather-only bỏ toàn bộ
lag để có thể dự báo một chuỗi thời gian tương lai liên tục.

## Cấu hình XGBoost

Cấu hình chung: `learning_rate=0.05`, `max_depth=8`,
`min_child_weight=20`, `subsample=0.9`, `colsample_bytree=0.9`,
`reg_alpha=0.05`, `reg_lambda=2.0`, `tree_method=hist` và `random_state=42`.

Quy trình chọn số cây:

1. Fit candidate trên 01-10/2025 với tối đa 700 cây.
2. Early stopping 35 vòng trên 11/2025.
3. Fit evaluation model trên 01-11/2025 bằng số cây tốt nhất.
4. Đánh giá một lần trên holdout 12/2025.
5. Refit production model trên toàn bộ năm 2025.

## Kết quả holdout tháng 12/2025

### XGBoost next-day

| Target | Cây | MAE | RMSE | R2 | Persistence MAE | Cải thiện |
|---|---:|---:|---:|---:|---:|---:|
| Current speed | 104 | 1.585 | 2.065 | 0.967 | 2.440 | 35.04% |
| Traffic density | 106 | 0.02828 | 0.03808 | 0.942 | 0.04616 | 38.73% |
| US AQI | 64 | 15.171 | 20.225 | 0.561 | 18.011 | 15.77% |

### XGBoost weather-only

| Target | Cây | MAE | RMSE | R2 |
|---|---:|---:|---:|---:|
| Current speed | 156 | 1.647 | 2.148 | 0.964 |
| Traffic density | 130 | 0.02950 | 0.04000 | 0.936 |
| US AQI | 31 | 20.789 | 26.976 | 0.220 |

Metric nguồn: [`xgboost_next_day_metrics.csv`](xgboost_next_day_metrics.csv) và
[`xgboost_weather_only_metrics.csv`](xgboost_weather_only_metrics.csv).

## Huấn luyện

```powershell
python src\models\xgboost_traffic_aqi.py train-all
```

Có thể đổi mốc thời gian hoặc output:

```powershell
python src\models\xgboost_traffic_aqi.py train-all `
  --validation-start 2025-11-01 `
  --test-start 2025-12-01 `
  --output-dir models\next_day_traffic_aqi\xgboost
```

## Forecast nhiều ngày

Forecast dài ngày dùng bundle weather-only:

```powershell
python src\models\xgboost_traffic_aqi.py forecast-weather-period `
  --weather-file data\raw\weather\hcm_weather_2026_01.csv `
  --output-file data\processed\model_predictions\traffic_aqi_forecast_2026_01_xgboost.csv
```

Input weather phải liên tục theo giờ, không trùng timestamp và không có missing
value. Output gồm forecast theo location-hour và một file tổng hợp ngày/tỉnh.

## Artifact

Mỗi variant tạo:

- `*_full.joblib`: bundle production fit trên toàn bộ năm 2025.
- `*_metadata.json`: feature, split, tham số và số cây.
- `*_metrics.csv`: metric holdout.
- `*_holdout_predictions.csv`: actual và predicted để audit.
- `*_feature_importance.csv`: gain importance theo target.

## Lưu ý sử dụng

- Next-day chính xác hơn weather-only nhưng đòi hỏi trạng thái lịch sử đúng 24
  giờ trước.
- Weather-only là lựa chọn cho multi-day forecast, không phải model tốt nhất về
  accuracy.
- AQI nguồn CAMS Global là dữ liệu mô hình; kết quả không thay thế quan trắc mặt
  đất hoặc cảnh báo y tế.
