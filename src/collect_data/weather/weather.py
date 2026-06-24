"""Script weather don gian cho TP.HCM nam 2025.

Muc luc:
1. Khai bao toa do, khoang ngay va cot weather can lay.
2. Goi Open-Meteo Archive API.
3. Chuan hoa thanh CSV co `date`, `hour`, `location_name`, `lat`, `lon`.

Neu can chay linh hoat theo tham so, uu tien dung
`collect_open_meteo_weather.py`.
"""

import requests
import pandas as pd

# =====================================================
# CONFIG
# =====================================================

LOCATION_NAME = "Ho_Chi_Minh"

LAT = 10.8231
LON = 106.6297

START_DATE = "2025-01-01"
END_DATE = "2025-12-31"

# =====================================================
# CALL API
# =====================================================

url = "https://archive-api.open-meteo.com/v1/archive"

params = {
    "latitude": LAT,
    "longitude": LON,
    "start_date": START_DATE,
    "end_date": END_DATE,
    "hourly": [
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "rain",
        "wind_speed_10m",
        "cloud_cover"
    ],
    "timezone": "Asia/Ho_Chi_Minh"
}

response = requests.get(url, params=params)
response.raise_for_status()

data = response.json()

# =====================================================
# DATAFRAME
# =====================================================

df = pd.DataFrame({
    "time": data["hourly"]["time"],
    "temperature_2m": data["hourly"]["temperature_2m"],
    "relative_humidity_2m": data["hourly"]["relative_humidity_2m"],
    "precipitation": data["hourly"]["precipitation"],
    "rain": data["hourly"]["rain"],
    "wind_speed_10m": data["hourly"]["wind_speed_10m"],
    "cloud_cover": data["hourly"]["cloud_cover"]
})

# =====================================================
# SPLIT DATE & HOUR
# =====================================================

df["datetime"] = pd.to_datetime(df["time"])

df["date"] = df["datetime"].dt.strftime("%Y-%m-%d")
df["hour"] = df["datetime"].dt.strftime("%H:%M")

# =====================================================
# ADD LOCATION INFO
# =====================================================

df["location_name"] = LOCATION_NAME
df["lat"] = LAT
df["lon"] = LON

# =====================================================
# REORDER COLUMNS
# =====================================================

df = df[
    [
        "date",
        "hour",
        "location_name",
        "lat",
        "lon",
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "rain",
        "wind_speed_10m",
        "cloud_cover"
    ]
]

# =====================================================
# SAVE CSV
# =====================================================

output_file = "data/raw/weather/hcm_weather_2025.csv"
df.to_csv(output_file, index=False)

print(f"Đã lưu: {output_file}")
print(df.head())
print(f"\nTổng số dòng: {len(df):,}")
