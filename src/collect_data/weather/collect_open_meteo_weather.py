"""Thu thap weather lich su tu Open-Meteo Archive API.

Muc luc:
1. Khai bao toa do TP.HCM, timezone va cac cot hourly can tai.
2. `collect_weather()`: goi API, chuan hoa date/hour va kiem tra du so dong.
3. CLI: truyen `--start-date`, `--end-date`, `--output-file`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import requests


API_URL = "https://archive-api.open-meteo.com/v1/archive"
LATITUDE = 10.8231
LONGITUDE = 106.6297
TIMEZONE = "Asia/Ho_Chi_Minh"
HOURLY_COLUMNS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "wind_speed_10m",
    "cloud_cover",
]


def collect_weather(start_date: str, end_date: str, output_file: Path) -> None:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if start > end:
        raise ValueError("start-date must not be after end-date")

    response = requests.get(
        API_URL,
        params={
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "hourly": ",".join(HOURLY_COLUMNS),
            "timezone": TIMEZONE,
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    hourly = payload["hourly"]
    weather = pd.DataFrame({column: hourly[column] for column in ["time", *HOURLY_COLUMNS]})
    weather["datetime"] = pd.to_datetime(weather.pop("time"), errors="raise")
    weather["date"] = weather["datetime"].dt.strftime("%Y-%m-%d")
    weather["hour"] = weather["datetime"].dt.strftime("%H:%M")
    weather["location_name"] = "Ho_Chi_Minh"
    weather["lat"] = LATITUDE
    weather["lon"] = LONGITUDE
    weather = weather[
        [
            "date",
            "hour",
            "location_name",
            "lat",
            "lon",
            *HOURLY_COLUMNS,
        ]
    ]

    expected_rows = len(pd.date_range(start, end + pd.Timedelta(hours=23), freq="h"))
    if len(weather) != expected_rows:
        raise ValueError(f"Expected {expected_rows} hourly rows, received {len(weather)}")
    if weather.isna().any().any():
        raise ValueError("Downloaded weather contains missing values")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    weather.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"Saved {len(weather):,} hourly weather rows to: {output_file}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect historical Open-Meteo weather")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    collect_weather(args.start_date, args.end_date, args.output_file.resolve())
