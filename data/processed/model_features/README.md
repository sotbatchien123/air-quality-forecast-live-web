# Model Features

Thư mục này là nguồn dữ liệu nền sạch cho các model dự báo traffic/AQI.
Mỗi file tương ứng một tỉnh/thành và chứa dữ liệu theo giờ trong năm 2025.

## File theo tỉnh/thành

| File | Tỉnh/thành | Số địa điểm |
|---|---|---:|
| `traffic_weather_static_ba_ria_vung_tau_2025.csv` | Bà Rịa - Vũng Tàu | 8 |
| `traffic_weather_static_dong_nai_2025.csv` | Đồng Nai | 11 |
| `traffic_weather_static_ho_chi_minh_2025.csv` | TP. Hồ Chí Minh | 22 |
| `traffic_weather_static_long_an_2025.csv` | Long An | 15 |
| `traffic_weather_static_tay_ninh_2025.csv` | Tây Ninh | 9 |

Tổng cộng: 569.400 dòng = 65 địa điểm x 8.760 giờ.

## Nhóm cột

| Nhóm | Cột chính | Dùng để làm gì |
|---|---|---|
| Định danh | `date`, `hour`, `location_name`, `district_key`, `district` | Ghép với AQI và xác định địa điểm |
| Vị trí | `lat`, `lon` | Giúp model phân biệt không gian |
| Giao thông | `currentspeed`, `freeflowspeed`, `congestion_ratio`, `traffic_density` | Trạng thái giao thông hiện tại và lag |
| Dữ liệu tĩnh | `estimated_vehicles`, `area_km2`, `population`, `density_person_km2`, `green_area_m2`, `green_per_capita_m2` | Đặc trưng nền của địa phương |
| Thời tiết | `temperature_2m`, `relative_humidity_2m`, `precipitation`, `wind_speed_10m`, `cloud_cover` | Điều kiện thời tiết tại từng giờ |

AQI không nằm trong thư mục này. Khi train, script `src/models/next_day_traffic_aqi.py`
sẽ ghép các file ở đây với `data/raw/AQI/open_meteo_aqi_2025_output/aqi_*.csv`
theo khóa `date + hour + district_key`.

Kiểm tra nhanh dữ liệu:

```powershell
python src\data\validate_model_features.py
```
