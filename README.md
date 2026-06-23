# DAP391m - Air Quality Forecast

Hệ thống dự báo giao thông và chất lượng không khí theo giờ cho 65 địa điểm
thuộc 5 tỉnh/thành Đông Nam Bộ theo địa giới trong bộ dữ liệu năm 2025:
TP. Hồ Chí Minh, Đồng Nai, Bà Rịa - Vũng Tàu, Tây Ninh và Long An.

Ba biến mục tiêu được dự báo độc lập:

- `currentspeed`: tốc độ giao thông hiện tại (km/h).
- `traffic_density`: mật độ giao thông đã chuẩn hóa trong khoảng `[0, 1]`.
- `us_aqi`: chỉ số chất lượng không khí theo thang US AQI.

## Phạm vi dữ liệu

| Thành phần | Phạm vi |
|---|---|
| Thời gian huấn luyện | 01/01/2025 - 31/12/2025, dữ liệu theo giờ |
| Không gian | 65 quận/huyện/thành phố thuộc 5 tỉnh/thành |
| Tổng số bản ghi gốc | 569.400 dòng (`65 x 8.760 giờ`) |
| Giao thông | Tốc độ, tốc độ tự do, tỷ lệ ùn tắc, mật độ giao thông |
| Không khí | US AQI, PM10, PM2.5, CO, NO2, SO2, O3 |
| Thời tiết | Nhiệt độ, độ ẩm, mưa, tốc độ gió, độ che phủ mây |
| Dữ liệu tĩnh | Tọa độ, dân số, diện tích, số xe ước tính, diện tích xanh |

AQI lịch sử lấy từ Open-Meteo với mô hình nền CAMS Global. Đây là dữ liệu mô
phỏng theo lưới, không phải số đo trực tiếp từ trạm quan trắc.

## Các model

| Nhóm model | Thuật toán | Chân trời | Số feature | Mục đích |
|---|---|---:|---:|---|
| [HistGradientBoosting](models/next_day_traffic_aqi/README.md) | HistGradientBoostingRegressor | 24 giờ | 43 | Baseline học máy, backtest theo tháng |
| [Weather-only](models/next_day_traffic_aqi/README.md#model-weather-only) | HistGradientBoostingRegressor | Nhiều ngày | 19 | Dự báo khi chỉ có thời tiết tương lai |
| [XGBoost](models/next_day_traffic_aqi/xgboost/README.md) | XGBRegressor | 24 giờ / nhiều ngày | 43 / 19 | Cải thiện baseline và chọn số cây bằng validation |
| [XGBoost multisource next-day](models/next_day_traffic_aqi/xgboost_multisource/README.md) | XGBRegressor | 24 giờ | 115 | Bổ sung lag 48/72 giờ và rolling statistics |
| [XGBoost multisource hourly](models/next_day_traffic_aqi/xgboost_multisource_hourly/README.md) | XGBRegressor | 1 giờ | 123 | Dự báo vận hành theo giờ và pipeline live |

Catalog đầy đủ, quá trình phát triển, cách chia tập và bảng so sánh kết quả nằm
tại [models/README.md](models/README.md).

## Cài đặt

Chạy các lệnh từ thư mục gốc repository:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-ml.txt
```

Các thư viện chính: pandas, NumPy, scikit-learn, joblib và XGBoost.

## Chạy nhanh

Huấn luyện model next-day HistGradientBoosting và tạo cả bundle đánh giá lẫn
bundle production:

```powershell
python src\models\next_day_traffic_aqi.py train
```

Huấn luyện hai biến thể XGBoost cơ bản:

```powershell
python src\models\xgboost_traffic_aqi.py train-all
```

Huấn luyện model next-day đa nguồn và model hourly:

```powershell
python src\models\xgboost_multisource_next_day.py
python src\models\xgboost_multisource_hourly.py train
```

Dự báo một giờ tiếp theo bằng model hourly:

```powershell
python src\models\xgboost_multisource_hourly.py forecast-next-hour `
  --current-timestamp "2025-12-31 23:00" `
  --weather-file data\raw\weather\hcm_weather_2026_01.csv `
  --output-file data\processed\model_predictions\forecast_next_hour.csv
```

Chạy collector và predictor live được mô tả tại
[src/live/README.md](src/live/README.md).

## Cấu trúc repository

```text
|-- data/
|   |-- raw/                         # AQI, giao thông, thời tiết, dân số, cây xanh
|   `-- processed/                   # feature đã ghép, forecast và báo cáo đánh giá
|-- models/
|   |-- README.md                    # catalog và quá trình phát triển model
|   `-- next_day_traffic_aqi/        # joblib, metadata, metrics, predictions
|-- outputs/                         # tài liệu trình bày kết quả
|-- src/
|   |-- collect_data/                # mã thu thập dữ liệu
|   |-- EDA/                         # tính chỉ số và EDA
|   |-- live/                        # thu thập + dự báo hourly theo lịch
|   |-- models/                      # train, forecast, backtest, evaluate
|   `-- visualization/               # notebook trực quan hóa
|-- requirements-ml.txt
`-- README.md
```

## Đánh giá và giới hạn

- Việc chia tập luôn theo thời gian: tháng 11/2025 dùng chọn số cây, tháng
  12/2025 là holdout chưa nhìn thấy, sau đó model production mới được refit trên
  toàn bộ năm 2025.
- Baseline so sánh là persistence: giá trị tương lai bằng giá trị quan sát gần
  nhất tương ứng (`t-24h` cho next-day, `t-1h` cho hourly).
- Một chuỗi thời tiết của TP. Hồ Chí Minh hiện được dùng lại cho cả 5
  tỉnh/thành, làm giảm độ tin cậy ngoài TP. Hồ Chí Minh.
- Model hourly cần đủ 12 giờ lịch sử liên tục; model weather-only không cần lịch
  sử giao thông/AQI tương lai nhưng có độ chính xác thấp hơn.
- Dự báo AQI chỉ nên dùng cho phân tích tham khảo, chưa phù hợp làm cảnh báo sức
  khỏe công cộng khi chưa hiệu chỉnh bằng dữ liệu trạm quan trắc.

Chi tiết metric theo tháng và đánh giá điểm yếu của model next-day có tại
[backtest_assessment.md](models/next_day_traffic_aqi/backtest_assessment.md).
