from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from next_day_traffic_aqi import (
    CURRENT_AQI_COLUMNS,
    CURRENT_TRAFFIC_COLUMNS,
    HORIZON_HOURS,
    FEATURE_COLUMNS,
    MODEL_DIR,
    ROLLING_COLUMNS,
    STATIC_COLUMNS,
    TARGET_COLUMNS,
    WEATHER_COLUMNS,
    add_periodic_features,
    load_joined_history,
)
from xgboost_traffic_aqi import train_variant


LAG_HOURS = [24, 48, 72]
ROLLING_WINDOWS = [24, 48, 72]
OUTPUT_DIR = MODEL_DIR / "xgboost_multisource"

MULTISOURCE_FEATURE_COLUMNS = [
    *STATIC_COLUMNS,
    "target_hour_sin",
    "target_hour_cos",
    "target_dow_sin",
    "target_dow_cos",
    "target_doy_sin",
    "target_doy_cos",
    *[f"forecast_{column}" for column in WEATHER_COLUMNS],
    *[
        f"lag{lag}_{column}"
        for lag in LAG_HOURS
        for column in (
            WEATHER_COLUMNS
            + CURRENT_TRAFFIC_COLUMNS
            + CURRENT_AQI_COLUMNS
        )
    ],
    *[
        f"rolling{window}_{column}_{stat}"
        for window in ROLLING_WINDOWS
        for column in ROLLING_COLUMNS
        for stat in ("mean", "std", "min", "max")
    ],
]


def build_multisource_frame(history: pd.DataFrame) -> pd.DataFrame:
    frame = history.copy()
    grouped = frame.groupby("location_key", sort=False)
    derived: dict[str, pd.Series] = {
        "target_timestamp": grouped["timestamp"].shift(-HORIZON_HOURS)
    }

    for column in WEATHER_COLUMNS:
        derived[f"forecast_{column}"] = grouped[column].shift(-HORIZON_HOURS)

    lag_columns = WEATHER_COLUMNS + CURRENT_TRAFFIC_COLUMNS + CURRENT_AQI_COLUMNS
    for lag in LAG_HOURS:
        shift_rows = lag - HORIZON_HOURS
        for column in lag_columns:
            if shift_rows == 0:
                derived[f"lag{lag}_{column}"] = frame[column]
            else:
                derived[f"lag{lag}_{column}"] = grouped[column].shift(shift_rows)

    for target, source in [
        ("target_currentspeed", "currentspeed"),
        ("target_traffic_density", "traffic_density"),
        ("target_us_aqi", "us_aqi"),
    ]:
        derived[target] = grouped[source].shift(-HORIZON_HOURS)

    for window in ROLLING_WINDOWS:
        for column in ROLLING_COLUMNS:
            rolling = grouped[column].rolling(window, min_periods=window)
            for stat in ("mean", "std", "min", "max"):
                values = getattr(rolling, stat)()
                derived[f"rolling{window}_{column}_{stat}"] = values.reset_index(
                    level=0,
                    drop=True,
                )

    frame = pd.concat([frame, pd.DataFrame(derived, index=frame.index)], axis=1)
    add_periodic_features(frame)
    required = FEATURE_COLUMNS + list(TARGET_COLUMNS) + [
        "target_timestamp"
    ]
    frame = frame.dropna(subset=required).copy()

    horizon = (
        frame["target_timestamp"] - frame["timestamp"]
    ).dt.total_seconds() / 3600
    if (horizon != HORIZON_HOURS).any():
        raise ValueError("Supervised rows do not have an exact 24-hour horizon")

    for column in MULTISOURCE_FEATURE_COLUMNS + list(TARGET_COLUMNS):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float32")

    return frame[
        [
            "target_timestamp",
            "location_key",
            "province_key",
            "district_key",
            "district",
            *MULTISOURCE_FEATURE_COLUMNS,
            *TARGET_COLUMNS,
        ]
    ]


def train(output_dir: Path, validation_start: str, test_start: str) -> None:
    history = load_joined_history()
    frame = build_multisource_frame(history)
    print(
        f"Multisource supervised rows: {len(frame):,}; "
        f"features: {len(MULTISOURCE_FEATURE_COLUMNS)}"
    )
    train_variant(
        name="xgboost_multisource_next_day",
        frame=frame,
        feature_columns={
            "target_currentspeed": MULTISOURCE_FEATURE_COLUMNS,
            "target_traffic_density": MULTISOURCE_FEATURE_COLUMNS,
            "target_us_aqi": FEATURE_COLUMNS,
        },
        test_start=test_start,
        validation_start=validation_start,
        output_dir=output_dir,
        include_persistence_baseline=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a weather, traffic, and AQI XGBoost next-day model"
    )
    parser.add_argument("--validation-start", default="2025-11-01")
    parser.add_argument("--test-start", default="2025-12-01")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train(
        args.output_dir.resolve(),
        args.validation_start,
        args.test_start,
    )
