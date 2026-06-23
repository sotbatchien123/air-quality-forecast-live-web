# XGBoost multisource hourly

Model dự báo một giờ tiếp theo cho từng location. Đây là model được tích hợp vào
pipeline live vì cân bằng giữa chân trời ngắn và khả năng cập nhật mỗi giờ.

## Đầu vào và feature

Model dùng 123 feature:

- 8 feature static và 6 feature calendar dạng sin/cos.
- Weather forecast của giờ đích.
- Weather, traffic, AQI và pollutant tại lag 1, 2, 3, 6, 12 giờ.
- Rolling mean/std 3, 6, 12 giờ của tốc độ, mật độ, US AQI và PM2.5.

Model không sử dụng traffic hoặc AQI tại giờ đích. Khi inference, mọi location
phải có đủ snapshot liên tục cho 12 giờ trước đó và đúng một dòng weather cho
giờ đích.

## Temporal split

- 01-10/2025: fit candidate.
- 11/2025: early stopping và chọn số cây.
- 01-11/2025: refit evaluation model.
- 12/2025: holdout.
- Toàn bộ 2025: refit production model sau đánh giá.

Persistence baseline của model hourly là giá trị tại giờ ngay trước đó.

## Kết quả holdout tháng 12/2025

| Target | Cây | MAE | RMSE | R2 | Baseline MAE | Cải thiện |
|---|---:|---:|---:|---:|---:|---:|
| Current speed | 105 | 1.578 | 2.046 | 0.968 | 3.294 | 52.09% |
| Traffic density | 100 | 0.02790 | 0.03721 | 0.945 | 0.06817 | 59.07% |
| US AQI | 700 | 0.796 | 1.322 | 0.998 | 1.722 | 53.79% |

Metric nguồn:
[`xgboost_multisource_hourly_metrics.csv`](xgboost_multisource_hourly_metrics.csv).

AQI hourly đạt kết quả rất cao vì chuỗi CAMS biến đổi trơn giữa hai giờ liên
tiếp. Không suy rộng kết quả này sang forecast 24 giờ hoặc dữ liệu trạm thực tế;
cần theo dõi drift bằng dữ liệu live độc lập.

## Huấn luyện

```powershell
python src\models\xgboost_multisource_hourly.py train
```

Tùy chỉnh split:

```powershell
python src\models\xgboost_multisource_hourly.py train `
  --validation-start 2025-11-01 `
  --test-start 2025-12-01 `
  --output-dir models\next_day_traffic_aqi\xgboost_multisource_hourly
```

## Forecast giờ tiếp theo

```powershell
python src\models\xgboost_multisource_hourly.py forecast-next-hour `
  --current-timestamp "2025-12-31 23:00" `
  --weather-file data\raw\weather\hcm_weather_2026_01.csv `
  --output-file data\processed\model_predictions\traffic_aqi_forecast_2026-01-01_00_xgboost_hourly.csv
```

Lệnh kiểm tra:

1. Có đúng một observation cho mọi location tại `current_timestamp`.
2. Có đủ lag 1, 2, 3, 6, 12 giờ.
3. Mỗi rolling window có đủ số dòng theo giờ.
4. Weather giờ đích tồn tại đúng một lần.
5. Không có missing value trong feature inference.

## Artifact

- `xgboost_multisource_hourly_full.joblib`: bundle production, khoảng 4,23 MB.
- `xgboost_multisource_hourly_metadata.json`: 123 feature, split, tham số và số
  cây theo target.
- `xgboost_multisource_hourly_metrics.csv`: metric holdout.
- `xgboost_multisource_hourly_holdout_predictions.csv`: dữ liệu audit.
- `xgboost_multisource_hourly_feature_importance.csv`: gain importance.

## Pipeline live

Collector live lấy traffic từ TomTom và weather/AQI từ Open-Meteo, lưu snapshot
theo giờ rồi tự động gọi model khi đủ 12 giờ liên tục. Xem cách cấu hình API key,
kiểm tra dependency và chạy theo lịch tại
[`src/live/README.md`](../../../src/live/README.md).

Pipeline live hiện thu thập được 62/65 location do TomTom trả HTTP 400 cho ba
địa điểm. Đây là giới hạn của dữ liệu live, không thay đổi bundle offline đã
train trên 65 location.
