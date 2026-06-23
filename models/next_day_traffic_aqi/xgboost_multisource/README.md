# XGBoost multisource next-day

Model dự báo tốc độ, mật độ giao thông và US AQI cho cùng địa điểm, cùng giờ ở
ngày kế tiếp. Horizon được kiểm tra chính xác là 24 giờ.

## Feature engineering

Bộ feature đầy đủ có 115 cột:

- Feature static: tọa độ, dân số, diện tích, xe ước tính và diện tích xanh.
- Calendar dạng sin/cos cho giờ, thứ và ngày trong năm.
- Weather của giờ cần dự báo.
- Weather, traffic, AQI và pollutant tại lag 24, 48, 72 giờ.
- Mean, std, min, max theo rolling window 24, 48, 72 giờ cho tốc độ, mật độ,
  US AQI và PM2.5.

Speed và traffic density dùng toàn bộ 115 feature. AQI chỉ dùng bộ 43 feature
của `xgboost_next_day`; thử nghiệm mở rộng AQI với lag 48/72 giờ làm temporal
holdout kém hơn nên đã được loại bỏ.

Không có traffic hoặc AQI của giờ đích trong input.

## Temporal split

| Giai đoạn | Vai trò |
|---|---|
| 01-10/2025 | Fit candidate với early stopping |
| 11/2025 | Validation chọn số cây |
| 01-11/2025 | Refit evaluation model |
| 12/2025 | Holdout chưa nhìn thấy |
| 01-12/2025 | Refit production sau đánh giá |

## Kết quả holdout tháng 12/2025

| Target | Feature | Cây | MAE | RMSE | R2 | Cải thiện persistence |
|---|---:|---:|---:|---:|---:|---:|
| Current speed | 115 | 109 | 1.571 | 2.056 | 0.967 | 35.62% |
| Traffic density | 115 | 93 | 0.02812 | 0.03809 | 0.942 | 39.08% |
| US AQI | 43 | 64 | 15.171 | 20.225 | 0.561 | 15.77% |

Metric nguồn:
[`xgboost_multisource_next_day_metrics.csv`](xgboost_multisource_next_day_metrics.csv).

## Huấn luyện

```powershell
python src\models\xgboost_multisource_next_day.py
```

Tùy chỉnh split và output:

```powershell
python src\models\xgboost_multisource_next_day.py `
  --validation-start 2025-11-01 `
  --test-start 2025-12-01 `
  --output-dir models\next_day_traffic_aqi\xgboost_multisource
```

## Artifact

- `xgboost_multisource_next_day_full.joblib`: bundle production.
- `xgboost_multisource_next_day_metadata.json`: feature theo target, tham số và
  số cây.
- `xgboost_multisource_next_day_metrics.csv`: metric holdout.
- `xgboost_multisource_next_day_holdout_predictions.csv`: dữ liệu audit.
- `xgboost_multisource_next_day_feature_importance.csv`: gain importance.

## Khi nào dùng

Dùng model này khi cần dự báo ngày mai và có đủ dữ liệu lịch sử 72 giờ cho từng
location. Nếu chỉ có weather forecast, dùng `xgboost_weather_only`. Nếu cần dự
báo giờ kế tiếp, dùng model multisource hourly.

## Hạn chế

- AQI chưa hưởng lợi từ các lag dài hơn; feature AQI vẫn là bộ 43 cột.
- Lag và rolling window yêu cầu chuỗi theo giờ liên tục, không phù hợp với dữ
  liệu live vừa khởi tạo.
- Model production đã refit trên tháng 12/2025; dùng CSV metrics, không dùng
  bundle production, để tái hiện kết quả holdout.
