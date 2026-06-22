from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd

from next_day_traffic_aqi import (
    CURRENT_AQI_COLUMNS,
    CURRENT_TRAFFIC_COLUMNS,
    MODEL_DIR,
    ROLLING_COLUMNS,
    STATIC_COLUMNS,
    TARGET_COLUMNS,
    WEATHER_COLUMNS,
    add_periodic_features,
    clip_predictions,
    load_joined_history,
    require_columns,
)
from xgboost_traffic_aqi import train_variant


HORIZON_HOURS = 1
LAG_HOURS = [1, 2, 3, 6, 12]
ROLLING_WINDOWS = [3, 6, 12]
OUTPUT_DIR = MODEL_DIR / "xgboost_multisource_hourly"

HOURLY_FEATURE_COLUMNS = [
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
        for stat in ("mean", "std")
    ],
]

HOURLY_BASELINE_FEATURES = {
    "target_currentspeed": "lag1_currentspeed",
    "target_traffic_density": "lag1_traffic_density",
    "target_us_aqi": "lag1_us_aqi",
}


def build_hourly_frame(history: pd.DataFrame) -> pd.DataFrame:
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
            for stat in ("mean", "std"):
                values = getattr(rolling, stat)()
                derived[f"rolling{window}_{column}_{stat}"] = values.reset_index(
                    level=0,
                    drop=True,
                )

    frame = pd.concat([frame, pd.DataFrame(derived, index=frame.index)], axis=1)
    add_periodic_features(frame)
    required = HOURLY_FEATURE_COLUMNS + list(TARGET_COLUMNS) + ["target_timestamp"]
    frame = frame.dropna(subset=required).copy()

    horizon = (
        frame["target_timestamp"] - frame["timestamp"]
    ).dt.total_seconds() / 3600
    if (horizon != HORIZON_HOURS).any():
        raise ValueError("Supervised rows do not have an exact one-hour horizon")

    for column in HOURLY_FEATURE_COLUMNS + list(TARGET_COLUMNS):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float32")

    return frame[
        [
            "timestamp",
            "target_timestamp",
            "location_key",
            "province_key",
            "district_key",
            "district",
            *HOURLY_FEATURE_COLUMNS,
            *TARGET_COLUMNS,
        ]
    ]


def train(output_dir: Path, validation_start: str, test_start: str) -> None:
    history = load_joined_history()
    frame = build_hourly_frame(history)
    print(
        f"Hourly supervised rows: {len(frame):,}; "
        f"features: {len(HOURLY_FEATURE_COLUMNS)}; horizon: {HORIZON_HOURS} hour"
    )
    train_variant(
        name="xgboost_multisource_hourly",
        frame=frame,
        feature_columns=HOURLY_FEATURE_COLUMNS,
        test_start=test_start,
        validation_start=validation_start,
        output_dir=output_dir,
        include_persistence_baseline=True,
        baseline_features=HOURLY_BASELINE_FEATURES,
    )


def forecast_next_hour(
    current_timestamp: str,
    weather_file: Path,
    model_dir: Path,
    output_file: Path,
) -> None:
    bundle = joblib.load(model_dir / "xgboost_multisource_hourly_full.joblib")
    history = load_joined_history()
    current = pd.Timestamp(current_timestamp)
    target = current + pd.Timedelta(hours=HORIZON_HOURS)
    location_count = history["location_key"].nunique()

    current_rows = history[history["timestamp"] == current].copy()
    if len(current_rows) != location_count:
        raise ValueError(
            f"Expected {location_count} observations at {current}; "
            f"received {len(current_rows)}"
        )
    inference = current_rows[
        [
            "location_key",
            "province_key",
            "district_key",
            "district",
            *STATIC_COLUMNS,
        ]
    ].copy()
    derived: dict[str, pd.Series] = {
        "target_timestamp": pd.Series(target, index=inference.index)
    }

    weather = pd.read_csv(weather_file, encoding="utf-8-sig")
    require_columns(weather, ["date", "hour", *WEATHER_COLUMNS], weather_file)
    weather["target_timestamp"] = pd.to_datetime(
        weather["date"].astype(str) + " " + weather["hour"].astype(str),
        errors="raise",
    )
    target_weather = weather[weather["target_timestamp"] == target]
    if len(target_weather) != 1:
        raise ValueError(
            f"Expected one weather row for {target}; received {len(target_weather)}"
        )
    for column in WEATHER_COLUMNS:
        derived[f"forecast_{column}"] = pd.Series(
            target_weather.iloc[0][column],
            index=inference.index,
        )

    lag_columns = WEATHER_COLUMNS + CURRENT_TRAFFIC_COLUMNS + CURRENT_AQI_COLUMNS
    for lag in LAG_HOURS:
        source_timestamp = target - pd.Timedelta(hours=lag)
        lag_rows = history[history["timestamp"] == source_timestamp].set_index(
            "location_key"
        )
        if len(lag_rows) != location_count:
            raise ValueError(
                f"Incomplete lag{lag} observations at {source_timestamp}"
            )
        for column in lag_columns:
            derived[f"lag{lag}_{column}"] = inference["location_key"].map(
                lag_rows[column]
            )

    for window in ROLLING_WINDOWS:
        window_start = current - pd.Timedelta(hours=window - 1)
        window_rows = history[
            (history["timestamp"] >= window_start)
            & (history["timestamp"] <= current)
        ]
        counts = window_rows.groupby("location_key").size()
        if len(counts) != location_count or not counts.eq(window).all():
            raise ValueError(f"Incomplete rolling{window} observation window")
        grouped = window_rows.groupby("location_key")
        for column in ROLLING_COLUMNS:
            for stat in ("mean", "std"):
                values = grouped[column].agg(stat)
                derived[f"rolling{window}_{column}_{stat}"] = inference[
                    "location_key"
                ].map(values)

    inference = pd.concat(
        [inference, pd.DataFrame(derived, index=inference.index)],
        axis=1,
    )
    add_periodic_features(inference)
    for column in bundle["feature_columns"]:
        inference[column] = pd.to_numeric(inference[column], errors="raise").astype(
            "float32"
        )
    if inference[bundle["feature_columns"]].isna().any().any():
        raise ValueError("Hourly inference features contain missing values")

    result = inference[
        ["target_timestamp", "province_key", "district_key", "district"]
    ].copy()
    feature_map = bundle.get("feature_columns_by_target", {})
    for target_name, model in bundle["models"].items():
        target_features = feature_map.get(target_name, bundle["feature_columns"])
        result[f"predicted_{target_name.removeprefix('target_')}"] = clip_predictions(
            target_name,
            model.predict(inference[target_features]),
        )

    result = result.sort_values(["province_key", "district_key"])
    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"Saved {len(result):,} forecasts for {target} to: {output_file}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a one-hour-ahead weather, traffic, and AQI model"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train")
    train_parser.add_argument("--validation-start", default="2025-11-01")
    train_parser.add_argument("--test-start", default="2025-12-01")
    train_parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)

    forecast_parser = subparsers.add_parser("forecast-next-hour")
    forecast_parser.add_argument("--current-timestamp", required=True)
    forecast_parser.add_argument("--weather-file", type=Path, required=True)
    forecast_parser.add_argument("--model-dir", type=Path, default=OUTPUT_DIR)
    forecast_parser.add_argument("--output-file", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.command == "train":
        train(
            args.output_dir.resolve(),
            args.validation_start,
            args.test_start,
        )
    else:
        forecast_next_hour(
            args.current_timestamp,
            args.weather_file.resolve(),
            args.model_dir.resolve(),
            args.output_file.resolve(),
        )
