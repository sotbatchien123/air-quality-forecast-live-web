#!/usr/bin/env python3
"""
Collect hourly Open-Meteo/CAMS Global air-quality data for 65 old-boundary
district/city representative points in five southern Vietnamese provinces.

Default period: 2025-01-01 through 2025-12-31, timezone Asia/Ho_Chi_Minh.

No third-party packages are required.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIMEZONE = "Asia/Ho_Chi_Minh"
DOMAIN = "cams_global"

HOURLY_VARIABLES = [
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "us_aqi",
    "us_aqi_pm2_5",
    "us_aqi_pm10",
    "us_aqi_nitrogen_dioxide",
    "us_aqi_carbon_monoxide",
    "us_aqi_ozone",
    "us_aqi_sulphur_dioxide",
]

LOCATIONS: List[Dict[str, Any]] = [
    {
        "province": "Bà Rịa - Vũng Tàu",
        "province_slug": "ba_ria_vung_tau",
        "source_traffic_file": "traffic_ba_ria_vung_tau_2025_old_map.csv",
        "location_name": "Vung_Tau",
        "lat": 10.34599,
        "lon": 107.08426
    },
    {
        "province": "Bà Rịa - Vũng Tàu",
        "province_slug": "ba_ria_vung_tau",
        "source_traffic_file": "traffic_ba_ria_vung_tau_2025_old_map.csv",
        "location_name": "Ba_Ria",
        "lat": 10.49631,
        "lon": 107.16849
    },
    {
        "province": "Bà Rịa - Vũng Tàu",
        "province_slug": "ba_ria_vung_tau",
        "source_traffic_file": "traffic_ba_ria_vung_tau_2025_old_map.csv",
        "location_name": "Phu_My",
        "lat": 10.568,
        "lon": 107.07
    },
    {
        "province": "Bà Rịa - Vũng Tàu",
        "province_slug": "ba_ria_vung_tau",
        "source_traffic_file": "traffic_ba_ria_vung_tau_2025_old_map.csv",
        "location_name": "Chau_Duc",
        "lat": 10.658,
        "lon": 107.25
    },
    {
        "province": "Bà Rịa - Vũng Tàu",
        "province_slug": "ba_ria_vung_tau",
        "source_traffic_file": "traffic_ba_ria_vung_tau_2025_old_map.csv",
        "location_name": "Con_Dao",
        "lat": 8.686,
        "lon": 106.608
    },
    {
        "province": "Bà Rịa - Vũng Tàu",
        "province_slug": "ba_ria_vung_tau",
        "source_traffic_file": "traffic_ba_ria_vung_tau_2025_old_map.csv",
        "location_name": "Dat_Do",
        "lat": 10.48,
        "lon": 107.272
    },
    {
        "province": "Bà Rịa - Vũng Tàu",
        "province_slug": "ba_ria_vung_tau",
        "source_traffic_file": "traffic_ba_ria_vung_tau_2025_old_map.csv",
        "location_name": "Long_Dien",
        "lat": 10.485,
        "lon": 107.216
    },
    {
        "province": "Bà Rịa - Vũng Tàu",
        "province_slug": "ba_ria_vung_tau",
        "source_traffic_file": "traffic_ba_ria_vung_tau_2025_old_map.csv",
        "location_name": "Xuyen_Moc",
        "lat": 10.541,
        "lon": 107.401
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_1",
        "lat": 10.7756,
        "lon": 106.7009
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_3",
        "lat": 10.7844,
        "lon": 106.6843
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_4",
        "lat": 10.7578,
        "lon": 106.7013
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_5",
        "lat": 10.754,
        "lon": 106.6636
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_6",
        "lat": 10.7467,
        "lon": 106.6366
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_7",
        "lat": 10.734,
        "lon": 106.7216
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_8",
        "lat": 10.7246,
        "lon": 106.6282
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_10",
        "lat": 10.7746,
        "lon": 106.6679
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_11",
        "lat": 10.7628,
        "lon": 106.65
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Quan_12",
        "lat": 10.8672,
        "lon": 106.6413
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Binh_Tan",
        "lat": 10.7653,
        "lon": 106.6033
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Binh_Thanh",
        "lat": 10.8111,
        "lon": 106.711
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Go_Vap",
        "lat": 10.8387,
        "lon": 106.6653
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Phu_Nhuan",
        "lat": 10.7992,
        "lon": 106.6802
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Tan_Binh",
        "lat": 10.801,
        "lon": 106.6526
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Tan_Phu",
        "lat": 10.7902,
        "lon": 106.6284
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Thanh_Pho_Thu_Duc",
        "lat": 10.8494,
        "lon": 106.7537
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Binh_Chanh",
        "lat": 10.6779,
        "lon": 106.5647
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Can_Gio",
        "lat": 10.4114,
        "lon": 106.9547
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Cu_Chi",
        "lat": 10.9733,
        "lon": 106.4931
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Hoc_Mon",
        "lat": 10.8836,
        "lon": 106.5897
    },
    {
        "province": "Hồ Chí Minh",
        "province_slug": "ho_chi_minh",
        "source_traffic_file": "traffic_ho_chi_minh_2025_old_map.csv",
        "location_name": "Nha_Be",
        "lat": 10.6956,
        "lon": 106.7402
    },
    {
        "province": "Tây Ninh",
        "province_slug": "tay_ninh",
        "source_traffic_file": "traffic_tay_ninh_2025_old_map.csv",
        "location_name": "Tay_Ninh",
        "lat": 11.313,
        "lon": 106.096
    },
    {
        "province": "Tây Ninh",
        "province_slug": "tay_ninh",
        "source_traffic_file": "traffic_tay_ninh_2025_old_map.csv",
        "location_name": "Hoa_Thanh",
        "lat": 11.286,
        "lon": 106.132
    },
    {
        "province": "Tây Ninh",
        "province_slug": "tay_ninh",
        "source_traffic_file": "traffic_tay_ninh_2025_old_map.csv",
        "location_name": "Trang_Bang",
        "lat": 11.029,
        "lon": 106.357
    },
    {
        "province": "Tây Ninh",
        "province_slug": "tay_ninh",
        "source_traffic_file": "traffic_tay_ninh_2025_old_map.csv",
        "location_name": "Ben_Cau",
        "lat": 11.111,
        "lon": 106.17
    },
    {
        "province": "Tây Ninh",
        "province_slug": "tay_ninh",
        "source_traffic_file": "traffic_tay_ninh_2025_old_map.csv",
        "location_name": "Chau_Thanh",
        "lat": 11.252,
        "lon": 106.045
    },
    {
        "province": "Tây Ninh",
        "province_slug": "tay_ninh",
        "source_traffic_file": "traffic_tay_ninh_2025_old_map.csv",
        "location_name": "Duong_Minh_Chau",
        "lat": 11.361,
        "lon": 106.243
    },
    {
        "province": "Tây Ninh",
        "province_slug": "tay_ninh",
        "source_traffic_file": "traffic_tay_ninh_2025_old_map.csv",
        "location_name": "Go_Dau",
        "lat": 11.088,
        "lon": 106.264
    },
    {
        "province": "Tây Ninh",
        "province_slug": "tay_ninh",
        "source_traffic_file": "traffic_tay_ninh_2025_old_map.csv",
        "location_name": "Tan_Bien",
        "lat": 11.548,
        "lon": 106.012
    },
    {
        "province": "Tây Ninh",
        "province_slug": "tay_ninh",
        "source_traffic_file": "traffic_tay_ninh_2025_old_map.csv",
        "location_name": "Tan_Chau",
        "lat": 11.576,
        "lon": 106.176
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Tan_An",
        "lat": 10.5359,
        "lon": 106.4137
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Kien_Tuong",
        "lat": 10.766,
        "lon": 105.927
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Ben_Luc",
        "lat": 10.642,
        "lon": 106.485
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Can_Duoc",
        "lat": 10.541,
        "lon": 106.598
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Can_Giuoc",
        "lat": 10.608,
        "lon": 106.672
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Chau_Thanh",
        "lat": 10.458,
        "lon": 106.492
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Duc_Hoa",
        "lat": 10.895,
        "lon": 106.403
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Duc_Hue",
        "lat": 10.874,
        "lon": 106.267
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Moc_Hoa",
        "lat": 10.756,
        "lon": 105.96
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Tan_Hung",
        "lat": 10.833,
        "lon": 105.662
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Tan_Thanh",
        "lat": 10.603,
        "lon": 106.075
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Tan_Tru",
        "lat": 10.524,
        "lon": 106.517
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Thanh_Hoa",
        "lat": 10.62,
        "lon": 106.183
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Thu_Thua",
        "lat": 10.657,
        "lon": 106.344
    },
    {
        "province": "Long An",
        "province_slug": "long_an",
        "source_traffic_file": "traffic_long_an_2025_old_map.csv",
        "location_name": "Vinh_Hung",
        "lat": 10.892,
        "lon": 105.785
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Bien_Hoa",
        "lat": 10.9574,
        "lon": 106.8427
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Long_Khanh",
        "lat": 10.9273,
        "lon": 107.2465
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Cam_My",
        "lat": 10.787,
        "lon": 107.257
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Dinh_Quan",
        "lat": 11.199,
        "lon": 107.353
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Long_Thanh",
        "lat": 10.79,
        "lon": 106.947
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Nhon_Trach",
        "lat": 10.708,
        "lon": 106.883
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Tan_Phu",
        "lat": 11.374,
        "lon": 107.401
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Thong_Nhat",
        "lat": 10.951,
        "lon": 107.159
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Trang_Bom",
        "lat": 10.951,
        "lon": 107.005
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Vinh_Cuu",
        "lat": 11.204,
        "lon": 107.054
    },
    {
        "province": "Đồng Nai",
        "province_slug": "dong_nai",
        "source_traffic_file": "traffic_dong_nai_2025_old_map.csv",
        "location_name": "Xuan_Loc",
        "lat": 10.926,
        "lon": 107.416
    }
]

PROVINCE_OUTPUTS = {
    "ho_chi_minh": "aqi_ho_chi_minh_2025_open_meteo.csv",
    "long_an": "aqi_long_an_2025_open_meteo.csv",
    "ba_ria_vung_tau": "aqi_ba_ria_vung_tau_2025_open_meteo.csv",
    "tay_ninh": "aqi_tay_ninh_2025_open_meteo.csv",
    "dong_nai": "aqi_dong_nai_2025_open_meteo.csv",
}

FINAL_FIELDS = [
    "date",
    "hour",
    "datetime",
    "province",
    "province_slug",
    "source_traffic_file",
    "location_name",
    "lat",
    "lon",
    "model_lat",
    "model_lon",
    "elevation",
    "timezone",
    "source_model",
    *HOURLY_VARIABLES,
]


def inclusive_hour_count(start_date: str, end_date: str) -> int:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    return ((end - start).days + 1) * 24


def build_url(location: Dict[str, Any], start_date: str, end_date: str) -> str:
    params = {
        "latitude": location["lat"],
        "longitude": location["lon"],
        "hourly": ",".join(HOURLY_VARIABLES),
        "start_date": start_date,
        "end_date": end_date,
        "timezone": TIMEZONE,
        "domains": DOMAIN,
        "cell_selection": "nearest",
    }
    return API_URL + "?" + urllib.parse.urlencode(params)


def parse_retry_after(headers: Any) -> Optional[float]:
    value = headers.get("Retry-After") if headers else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def request_json(
    url: str,
    max_retries: int,
    timeout: int,
) -> Tuple[Dict[str, Any], int]:
    last_error: Optional[BaseException] = None

    for attempt in range(1, max_retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AQI-Research-Collector/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            if payload.get("error"):
                raise RuntimeError(payload.get("reason", "Open-Meteo returned an error"))
            return payload, attempt

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            last_error = RuntimeError(f"HTTP {exc.code}: {body}")
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                break
            delay = parse_retry_after(exc.headers)
            if delay is None:
                delay = min(60.0, 2.0 ** (attempt - 1))
            print(f"  HTTP {exc.code}; retrying in {delay:.1f} s", flush=True)
            time.sleep(delay)

        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            delay = min(60.0, 2.0 ** (attempt - 1))
            print(f"  Request failed: {exc}; retrying in {delay:.1f} s", flush=True)
            time.sleep(delay)

    raise RuntimeError(f"Request failed after {max_retries} attempts: {last_error}")


def raw_path(raw_dir: Path, location: Dict[str, Any]) -> Path:
    return raw_dir / (
        f'{location["province_slug"]}__{location["location_name"]}.csv'
    )


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        return sum(1 for _ in reader)


def validate_payload(
    payload: Dict[str, Any],
    expected_hours: int,
) -> Tuple[List[str], Dict[str, List[Any]]]:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("Response has no 'hourly' object")

    times = hourly.get("time")
    if not isinstance(times, list):
        raise ValueError("Response has no hourly time list")
    if len(times) != expected_hours:
        raise ValueError(
            f"Expected {expected_hours} hourly timestamps, received {len(times)}"
        )

    arrays: Dict[str, List[Any]] = {}
    for variable in HOURLY_VARIABLES:
        values = hourly.get(variable)
        if not isinstance(values, list):
            raise ValueError(f"Response has no list for {variable}")
        if len(values) != len(times):
            raise ValueError(
                f"{variable} has {len(values)} values; expected {len(times)}"
            )
        arrays[variable] = values

    return times, arrays


def write_location_csv(
    destination: Path,
    payload: Dict[str, Any],
    location: Dict[str, Any],
    expected_hours: int,
) -> Dict[str, int]:
    times, arrays = validate_payload(payload, expected_hours)
    model_lat = payload.get("latitude")
    model_lon = payload.get("longitude")
    elevation = payload.get("elevation")
    timezone_name = payload.get("timezone", TIMEZONE)

    null_counts = {name: 0 for name in HOURLY_VARIABLES}
    tmp = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FINAL_FIELDS)
        writer.writeheader()

        for i, timestamp in enumerate(times):
            # Open-Meteo normally returns YYYY-MM-DDTHH:MM.
            date_text = timestamp[:10]
            hour_text = timestamp[11:16]
            row: Dict[str, Any] = {
                "date": date_text,
                "hour": hour_text,
                "datetime": timestamp,
                "province": location["province"],
                "province_slug": location["province_slug"],
                "source_traffic_file": location["source_traffic_file"],
                "location_name": location["location_name"],
                "lat": location["lat"],
                "lon": location["lon"],
                "model_lat": model_lat,
                "model_lon": model_lon,
                "elevation": elevation,
                "timezone": timezone_name,
                "source_model": DOMAIN,
            }
            for variable in HOURLY_VARIABLES:
                value = arrays[variable][i]
                if value is None:
                    null_counts[variable] += 1
                    row[variable] = ""
                else:
                    row[variable] = value
            writer.writerow(row)

    os.replace(tmp, destination)
    return null_counts


def write_locations_manifest(output_dir: Path, selected: Sequence[Dict[str, Any]]) -> Path:
    path = output_dir / "locations_5_provinces_old_boundaries.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "province",
                "province_slug",
                "source_traffic_file",
                "location_name",
                "lat",
                "lon",
                "expected_hours",
            ],
        )
        writer.writeheader()
        for location in selected:
            writer.writerow({
                **location,
                "expected_hours": 8760,
            })
    return path


def merge_province(
    province_slug: str,
    locations: Sequence[Dict[str, Any]],
    raw_dir: Path,
    output_path: Path,
    expected_hours: int,
) -> int:
    """
    Merge location files in time-major order:
    each timestamp is followed by all locations in that province.
    """
    tmp = output_path.with_suffix(output_path.suffix + ".part")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        readers: List[Tuple[Dict[str, Any], csv.DictReader]] = []
        for location in locations:
            path = raw_path(raw_dir, location)
            f = stack.enter_context(
                path.open("r", newline="", encoding="utf-8-sig")
            )
            reader = csv.DictReader(f)
            readers.append((location, reader))

        with tmp.open("w", newline="", encoding="utf-8-sig") as out:
            writer = csv.DictWriter(out, fieldnames=FINAL_FIELDS)
            writer.writeheader()
            rows_written = 0

            for hour_index in range(expected_hours):
                reference_datetime: Optional[str] = None
                for location, reader in readers:
                    row = next(reader, None)
                    if row is None:
                        raise ValueError(
                            f'Unexpected end of {raw_path(raw_dir, location)} '
                            f'at hour index {hour_index}'
                        )
                    if reference_datetime is None:
                        reference_datetime = row["datetime"]
                    elif row["datetime"] != reference_datetime:
                        raise ValueError(
                            "Location files are not aligned at hour index "
                            f"{hour_index}: {row['datetime']} != {reference_datetime}"
                        )
                    writer.writerow(row)
                    rows_written += 1

            # Ensure no file contains extra rows.
            for location, reader in readers:
                if next(reader, None) is not None:
                    raise ValueError(
                        f'Extra rows found in {raw_path(raw_dir, location)}'
                    )

    os.replace(tmp, output_path)
    return rows_written


def write_report(output_dir: Path, report_rows: Sequence[Dict[str, Any]]) -> Path:
    path = output_dir / "collection_report.csv"
    fields = [
        "province",
        "province_slug",
        "location_name",
        "lat",
        "lon",
        "status",
        "attempts",
        "rows",
        "total_null_values",
        "error",
        "request_url",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in report_rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    return path


def write_metadata(
    output_dir: Path,
    start_date: str,
    end_date: str,
    expected_hours: int,
    selected: Sequence[Dict[str, Any]],
) -> Path:
    path = output_dir / "dataset_metadata.json"
    metadata = {
        "source": "Open-Meteo Air Quality API",
        "underlying_model": "CAMS Global Atmospheric Composition Forecast",
        "domain_parameter": DOMAIN,
        "timezone": TIMEZONE,
        "start_date": start_date,
        "end_date": end_date,
        "hours_per_location": expected_hours,
        "locations": len(selected),
        "expected_total_rows": expected_hours * len(selected),
        "hourly_variables": HOURLY_VARIABLES,
        "note": (
            "us_aqi follows the United States AQI convention. "
            "This is modeled gridded data, not direct station observations."
        ),
    }
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def make_zip(output_dir: Path, files: Sequence[Path]) -> Path:
    archive = output_dir / "open_meteo_aqi_2025_5_provinces.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            if path.exists() and path.is_file():
                zf.write(path, arcname=path.name)
    return archive


def select_locations(
    province_slugs: Optional[str],
    only_location: Optional[str],
) -> List[Dict[str, Any]]:
    selected = list(LOCATIONS)
    if province_slugs:
        allowed = {
            value.strip()
            for value in province_slugs.split(",")
            if value.strip()
        }
        unknown = allowed - set(PROVINCE_OUTPUTS)
        if unknown:
            raise ValueError(
                "Unknown province slug(s): " + ", ".join(sorted(unknown))
            )
        selected = [
            location
            for location in selected
            if location["province_slug"] in allowed
        ]
    if only_location:
        selected = [
            location
            for location in selected
            if location["location_name"] == only_location
        ]
    if not selected:
        raise ValueError("No locations selected")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect Open-Meteo hourly AQI and pollutant concentrations "
            "for five southern Vietnamese provinces."
        )
    )
    parser.add_argument(
        "--output-dir",
        default="open_meteo_aqi_2025_output",
        help="Output directory (default: open_meteo_aqi_2025_output)",
    )
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument(
        "--provinces",
        help=(
            "Comma-separated slugs: ho_chi_minh,long_an,"
            "ba_ria_vung_tau,tay_ninh,dong_nai"
        ),
    )
    parser.add_argument(
        "--only-location",
        help="Collect only one exact location_name, useful for testing",
    )
    parser.add_argument("--sleep", type=float, default=0.8)
    parser.add_argument("--max-retries", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Download again even when a complete raw location file exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and print sample URLs without downloading",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    expected_hours = inclusive_hour_count(args.start_date, args.end_date)
    selected = select_locations(args.provinces, args.only_location)

    output_dir = Path(args.output_dir).resolve()
    raw_dir = output_dir / "raw_locations"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    locations_manifest = write_locations_manifest(output_dir, selected)
    metadata_path = write_metadata(
        output_dir,
        args.start_date,
        args.end_date,
        expected_hours,
        selected,
    )

    print("=" * 72)
    print("Open-Meteo AQI collector")
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Timezone: {TIMEZONE}")
    print(f"Locations: {len(selected)}")
    print(f"Expected hours/location: {expected_hours}")
    print(f"Expected total rows: {expected_hours * len(selected):,}")
    print(f"Output: {output_dir}")
    print("=" * 72)

    if args.dry_run:
        print("Dry run: no network requests will be made.")
        print("First URL:")
        print(build_url(selected[0], args.start_date, args.end_date))
        print("Last URL:")
        print(build_url(selected[-1], args.start_date, args.end_date))
        return 0

    report_rows: List[Dict[str, Any]] = []
    failures = 0

    for index, location in enumerate(selected, start=1):
        destination = raw_path(raw_dir, location)
        url = build_url(location, args.start_date, args.end_date)
        prefix = (
            f"[{index:02d}/{len(selected):02d}] "
            f'{location["province"]} / {location["location_name"]}'
        )
        print(prefix, flush=True)

        existing_rows = count_csv_rows(destination)
        if (
            destination.exists()
            and existing_rows == expected_hours
            and not args.overwrite
        ):
            print(f"  Complete file already exists ({existing_rows} rows); skipped.")
            report_rows.append({
                **location,
                "status": "skipped_complete",
                "attempts": 0,
                "rows": existing_rows,
                "total_null_values": "",
                "error": "",
                "request_url": url,
            })
            continue

        try:
            payload, attempts = request_json(
                url,
                max_retries=args.max_retries,
                timeout=args.timeout,
            )
            null_counts = write_location_csv(
                destination,
                payload,
                location,
                expected_hours,
            )
            rows = count_csv_rows(destination)
            if rows != expected_hours:
                raise ValueError(
                    f"File validation failed: {rows} rows, "
                    f"expected {expected_hours}"
                )
            total_nulls = sum(null_counts.values())
            print(f"  Saved {rows} rows; null values: {total_nulls}.")
            report_rows.append({
                **location,
                "status": "success",
                "attempts": attempts,
                "rows": rows,
                "total_null_values": total_nulls,
                "error": "",
                "request_url": url,
            })
        except Exception as exc:
            failures += 1
            print(f"  FAILED: {exc}", file=sys.stderr, flush=True)
            report_rows.append({
                **location,
                "status": "failed",
                "attempts": args.max_retries,
                "rows": count_csv_rows(destination),
                "total_null_values": "",
                "error": str(exc),
                "request_url": url,
            })

        if index < len(selected) and args.sleep > 0:
            time.sleep(args.sleep)

    report_path = write_report(output_dir, report_rows)

    # Merge only provinces for which every selected location is complete.
    merged_files: List[Path] = []
    selected_slugs = sorted({
        location["province_slug"] for location in selected
    })

    for province_slug in selected_slugs:
        province_locations = [
            location
            for location in selected
            if location["province_slug"] == province_slug
        ]
        incomplete = [
            location
            for location in province_locations
            if count_csv_rows(raw_path(raw_dir, location)) != expected_hours
        ]
        if incomplete:
            names = ", ".join(
                location["location_name"] for location in incomplete
            )
            print(
                f"Province {province_slug} not merged; incomplete: {names}",
                file=sys.stderr,
            )
            continue

        output_name = PROVINCE_OUTPUTS[province_slug]
        # Preserve a sensible name if a non-default date range was selected.
        if args.start_date != "2025-01-01" or args.end_date != "2025-12-31":
            output_name = (
                f"aqi_{province_slug}_{args.start_date}_to_"
                f"{args.end_date}_open_meteo.csv"
            )
        output_path = output_dir / output_name
        rows = merge_province(
            province_slug,
            province_locations,
            raw_dir,
            output_path,
            expected_hours,
        )
        expected_rows = expected_hours * len(province_locations)
        if rows != expected_rows:
            raise RuntimeError(
                f"{output_path.name} has {rows} rows; "
                f"expected {expected_rows}"
            )
        merged_files.append(output_path)
        print(f"Merged {output_path.name}: {rows:,} rows.")

    all_five_selected = (
        len(selected) == len(LOCATIONS)
        and set(selected_slugs) == set(PROVINCE_OUTPUTS)
    )
    if failures == 0 and all_five_selected and len(merged_files) == 5:
        archive = make_zip(
            output_dir,
            [
                *merged_files,
                report_path,
                locations_manifest,
                metadata_path,
            ],
        )
        print(f"Created archive: {archive}")

    print("=" * 72)
    print(f"Completed with {failures} failed location(s).")
    print(f"Report: {report_path}")
    if failures:
        print("Run the same command again to resume only incomplete locations.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
