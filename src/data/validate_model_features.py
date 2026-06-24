"""Kiem tra bo du lieu feature sach cho cac model du bao.

Muc luc:
1. Khai bao file feature theo tung tinh/thanh.
2. Kiem tra cac cot bat buoc ma model can.
3. Bao loi neu file thieu cot, trung khoa hoac co cot khong mong muon.

Bo `model_features` chi giu traffic, weather va du lieu tinh. Script nay
giup kiem tra nhanh truoc khi train lai model.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
MODEL_FEATURE_DIR = ROOT_DIR / "data" / "processed" / "model_features"

PROVINCE_FILES = {
    "ba_ria_vung_tau": "traffic_weather_static_ba_ria_vung_tau_2025.csv",
    "dong_nai": "traffic_weather_static_dong_nai_2025.csv",
    "ho_chi_minh": "traffic_weather_static_ho_chi_minh_2025.csv",
    "long_an": "traffic_weather_static_long_an_2025.csv",
    "tay_ninh": "traffic_weather_static_tay_ninh_2025.csv",
}

REQUIRED_COLUMNS = [
    "date",
    "hour",
    "location_name",
    "district_key",
    "district",
    "lat",
    "lon",
    "currentspeed",
    "freeflowspeed",
    "congestion_ratio",
    "traffic_density",
    "estimated_vehicles",
    "area_km2",
    "population",
    "density_person_km2",
    "green_area_m2",
    "green_per_capita_m2",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "cloud_cover",
]

FORBIDDEN_COLUMNS = {
    "emission_vehicle",
    "emission_population",
    "emission_sum_grams",
    "trees",
    "absorption",
    "ERI",
}


def require_columns(frame: pd.DataFrame, columns: list[str], source: Path) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing columns in {source}: {', '.join(missing)}")


def validate_model_features() -> None:
    total_rows = 0
    total_locations = 0

    for province_key, file_name in PROVINCE_FILES.items():
        feature_path = MODEL_FEATURE_DIR / file_name
        frame = pd.read_csv(feature_path, encoding="utf-8-sig")
        require_columns(frame, REQUIRED_COLUMNS, feature_path)

        extra_forbidden = sorted(FORBIDDEN_COLUMNS & set(frame.columns))
        if extra_forbidden:
            raise ValueError(
                f"Forbidden columns in {feature_path}: {', '.join(extra_forbidden)}"
            )

        key_columns = ["date", "hour", "district_key"]
        if frame.duplicated(key_columns).any():
            raise ValueError(f"Duplicate keys in {feature_path}")

        total_rows += len(frame)
        total_locations += frame["district_key"].nunique()
        print(
            f"{province_key}: {len(frame):,} rows, "
            f"{frame['district_key'].nunique()} locations -> OK"
        )

    print(f"Total: {total_rows:,} rows, {total_locations} locations")


if __name__ == "__main__":
    validate_model_features()
