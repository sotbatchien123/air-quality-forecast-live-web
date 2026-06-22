from __future__ import annotations

import argparse
import json
import math
import os
import re
import unicodedata
import warnings
from datetime import datetime, timezone
from pathlib import Path

logical_cores = os.cpu_count() or 2
os.environ.setdefault(
    "LOKY_MAX_CPU_COUNT",
    str(min(8, max(1, logical_cores - 1))),
)
warnings.filterwarnings(
    "ignore",
    message="Could not find the number of physical cores.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    module=r"joblib\.externals\.loky\.backend\.context",
)

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


ROOT_DIR = Path(__file__).resolve().parents[2]
POLLUTION_DIR = ROOT_DIR / "data" / "processed" / "pollution_index_scaled"
AQI_DIR = ROOT_DIR / "data" / "raw" / "AQI" / "open_meteo_aqi_2025_output"
MODEL_DIR = ROOT_DIR / "models" / "next_day_traffic_aqi"

HORIZON_HOURS = 24
DEFAULT_TEST_START = "2025-12-01"

PROVINCES = {
    "ba_ria_vung_tau": {
        "pollution": "pollution_index_scaled_ba_ria_vung_tau_2025.csv",
        "aqi": "aqi_ba_ria_vung_tau_2025_open_meteo.csv",
    },
    "dong_nai": {
        "pollution": "pollution_index_scaled_dong_nai_2025.csv",
        "aqi": "aqi_dong_nai_2025_open_meteo.csv",
    },
    "ho_chi_minh": {
        "pollution": "pollution_index_scaled_ho_chi_minh_2025.csv",
        "aqi": "aqi_ho_chi_minh_2025_open_meteo.csv",
    },
    "long_an": {
        "pollution": "pollution_index_scaled_long_an_2025.csv",
        "aqi": "aqi_long_an_2025_open_meteo.csv",
    },
    "tay_ninh": {
        "pollution": "pollution_index_scaled_tay_ninh_2025.csv",
        "aqi": "aqi_tay_ninh_2025_open_meteo.csv",
    },
}

POLLUTION_COLUMNS = [
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

AQI_COLUMNS = [
    "date",
    "hour",
    "location_name",
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "us_aqi",
]

WEATHER_COLUMNS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "cloud_cover",
]

CURRENT_TRAFFIC_COLUMNS = [
    "currentspeed",
    "freeflowspeed",
    "congestion_ratio",
    "traffic_density",
]

CURRENT_AQI_COLUMNS = [
    "us_aqi",
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
]

STATIC_COLUMNS = [
    "lat",
    "lon",
    "estimated_vehicles",
    "area_km2",
    "population",
    "density_person_km2",
    "green_area_m2",
    "green_per_capita_m2",
]

ROLLING_COLUMNS = ["currentspeed", "traffic_density", "us_aqi", "pm2_5"]

TARGET_COLUMNS = {
    "target_currentspeed": "lag24_currentspeed",
    "target_traffic_density": "lag24_traffic_density",
    "target_us_aqi": "lag24_us_aqi",
}

TARGET_TOLERANCES = {
    "target_currentspeed": 5.0,
    "target_traffic_density": 0.05,
    "target_us_aqi": 20.0,
}

FEATURE_COLUMNS = [
    *STATIC_COLUMNS,
    "target_hour_sin",
    "target_hour_cos",
    "target_dow_sin",
    "target_dow_cos",
    "target_doy_sin",
    "target_doy_cos",
    *[f"forecast_{column}" for column in WEATHER_COLUMNS],
    *[f"lag24_{column}" for column in WEATHER_COLUMNS],
    *[f"lag24_{column}" for column in CURRENT_TRAFFIC_COLUMNS],
    *[f"lag24_{column}" for column in CURRENT_AQI_COLUMNS],
    *[
        f"rolling24_{column}_{stat}"
        for column in ROLLING_COLUMNS
        for stat in ("mean", "std")
    ],
]

WEATHER_ONLY_FEATURE_COLUMNS = [
    *STATIC_COLUMNS,
    "target_hour_sin",
    "target_hour_cos",
    "target_dow_sin",
    "target_dow_cos",
    "target_doy_sin",
    "target_doy_cos",
    *[f"forecast_{column}" for column in WEATHER_COLUMNS],
]


def strip_accents(value: object) -> str:
    text = str(value).replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def district_key(value: object) -> str:
    text = strip_accents(value)
    text = re.sub(r"([a-z])([A-Z])", r"\1_\2", text)
    text = re.sub(r"([A-Za-z])(\d)", r"\1_\2", text)
    text = re.sub(r"(\d)([A-Za-z])", r"\1_\2", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    text = re.sub(r"^(thanh_pho|tp|tx|huyen|quan)_", "", text)
    text = re.sub(r"_(tn|dn|la)$", "", text)
    if re.fullmatch(r"\d+", text):
        return f"quan_{text}"
    return text


def require_columns(frame: pd.DataFrame, columns: list[str], source: Path) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing columns in {source}: {', '.join(missing)}")


def load_joined_history() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for province_key, files in PROVINCES.items():
        pollution_path = POLLUTION_DIR / files["pollution"]
        aqi_path = AQI_DIR / files["aqi"]

        pollution = pd.read_csv(
            pollution_path,
            usecols=POLLUTION_COLUMNS,
            encoding="utf-8-sig",
        )
        aqi = pd.read_csv(
            aqi_path,
            usecols=AQI_COLUMNS,
            encoding="utf-8-sig",
        )
        require_columns(pollution, POLLUTION_COLUMNS, pollution_path)
        require_columns(aqi, AQI_COLUMNS, aqi_path)

        pollution["province_key"] = province_key
        aqi["district_key"] = aqi["location_name"].map(district_key)

        merge_columns = ["date", "hour", "district_key"]
        if pollution.duplicated(merge_columns).any():
            raise ValueError(f"Duplicate pollution keys in {pollution_path}")
        if aqi.duplicated(merge_columns).any():
            raise ValueError(f"Duplicate AQI keys in {aqi_path}")

        aqi = aqi.drop(columns="location_name")
        joined = pollution.merge(
            aqi,
            on=merge_columns,
            how="inner",
            validate="one_to_one",
        )
        if len(joined) != len(pollution):
            raise ValueError(
                f"Join lost rows for {province_key}: "
                f"pollution={len(pollution)}, joined={len(joined)}"
            )

        frames.append(joined)
        print(
            f"Loaded {province_key}: {len(joined):,} rows, "
            f"{joined['district_key'].nunique()} locations"
        )

    history = pd.concat(frames, ignore_index=True)
    history["timestamp"] = pd.to_datetime(
        history["date"].astype(str) + " " + history["hour"].astype(str),
        errors="raise",
    )
    history["location_key"] = (
        history["province_key"] + "__" + history["district_key"]
    )
    history = history.sort_values(["location_key", "timestamp"]).reset_index(drop=True)

    duplicate_keys = history.duplicated(["location_key", "timestamp"]).sum()
    if duplicate_keys:
        raise ValueError(f"History contains {duplicate_keys} duplicate location timestamps")

    return history


def add_periodic_features(frame: pd.DataFrame) -> None:
    target = frame["target_timestamp"]
    hour = target.dt.hour
    day_of_week = target.dt.dayofweek
    day_of_year = target.dt.dayofyear

    frame["target_hour_sin"] = np.sin(2 * math.pi * hour / 24)
    frame["target_hour_cos"] = np.cos(2 * math.pi * hour / 24)
    frame["target_dow_sin"] = np.sin(2 * math.pi * day_of_week / 7)
    frame["target_dow_cos"] = np.cos(2 * math.pi * day_of_week / 7)
    frame["target_doy_sin"] = np.sin(2 * math.pi * day_of_year / 365.25)
    frame["target_doy_cos"] = np.cos(2 * math.pi * day_of_year / 365.25)


def build_supervised_frame(history: pd.DataFrame) -> pd.DataFrame:
    frame = history.copy()
    grouped = frame.groupby("location_key", sort=False)

    frame["target_timestamp"] = grouped["timestamp"].shift(-HORIZON_HOURS)
    for column in WEATHER_COLUMNS:
        frame[f"forecast_{column}"] = grouped[column].shift(-HORIZON_HOURS)
        frame[f"lag24_{column}"] = frame[column]

    for column in CURRENT_TRAFFIC_COLUMNS + CURRENT_AQI_COLUMNS:
        frame[f"lag24_{column}"] = frame[column]

    for target_column, source_column in [
        ("target_currentspeed", "currentspeed"),
        ("target_traffic_density", "traffic_density"),
        ("target_us_aqi", "us_aqi"),
    ]:
        frame[target_column] = grouped[source_column].shift(-HORIZON_HOURS)

    for column in ROLLING_COLUMNS:
        rolling = grouped[column].rolling(24, min_periods=24)
        frame[f"rolling24_{column}_mean"] = (
            rolling.mean().reset_index(level=0, drop=True)
        )
        frame[f"rolling24_{column}_std"] = (
            rolling.std().reset_index(level=0, drop=True)
        )

    add_periodic_features(frame)

    required = FEATURE_COLUMNS + list(TARGET_COLUMNS) + ["target_timestamp"]
    frame = frame.dropna(subset=required).copy()

    horizon = (frame["target_timestamp"] - frame["timestamp"]).dt.total_seconds() / 3600
    invalid_horizon = int((horizon != HORIZON_HOURS).sum())
    if invalid_horizon:
        raise ValueError(f"Found {invalid_horizon} rows without an exact 24-hour horizon")

    for column in FEATURE_COLUMNS + list(TARGET_COLUMNS):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float32")

    keep_columns = [
        "timestamp",
        "target_timestamp",
        "location_key",
        "province_key",
        "district_key",
        "district",
        *FEATURE_COLUMNS,
        *TARGET_COLUMNS,
    ]
    return frame[keep_columns]


def build_weather_only_frame(history: pd.DataFrame) -> pd.DataFrame:
    frame = history.copy()
    frame["target_timestamp"] = frame["timestamp"]
    for column in WEATHER_COLUMNS:
        frame[f"forecast_{column}"] = frame[column]

    frame["target_currentspeed"] = frame["currentspeed"]
    frame["target_traffic_density"] = frame["traffic_density"]
    frame["target_us_aqi"] = frame["us_aqi"]
    add_periodic_features(frame)

    required = WEATHER_ONLY_FEATURE_COLUMNS + list(TARGET_COLUMNS)
    frame = frame.dropna(subset=required).copy()
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float32")

    return frame[
        [
            "target_timestamp",
            "location_key",
            "province_key",
            "district_key",
            "district",
            *WEATHER_ONLY_FEATURE_COLUMNS,
            *TARGET_COLUMNS,
        ]
    ]


def regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(math.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)),
    }


def create_model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        learning_rate=0.08,
        max_iter=180,
        max_leaf_nodes=31,
        min_samples_leaf=40,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=15,
        random_state=42,
    )


def clip_predictions(target: str, values: np.ndarray) -> np.ndarray:
    if target == "target_traffic_density":
        return np.clip(values, 0, 1)
    return np.clip(values, 0, None)


def train(test_start: str, output_dir: Path) -> None:
    history = load_joined_history()
    frame = build_supervised_frame(history)
    split_timestamp = pd.Timestamp(test_start)

    train_mask = frame["target_timestamp"] < split_timestamp
    test_mask = ~train_mask
    if not train_mask.any() or not test_mask.any():
        raise ValueError(
            f"Invalid temporal split at {test_start}: "
            f"train={int(train_mask.sum())}, test={int(test_mask.sum())}"
        )

    x_train = frame.loc[train_mask, FEATURE_COLUMNS]
    x_test = frame.loc[test_mask, FEATURE_COLUMNS]

    output_dir.mkdir(parents=True, exist_ok=True)
    models: dict[str, HistGradientBoostingRegressor] = {}
    metrics_rows: list[dict[str, object]] = []
    prediction_frame = frame.loc[
        test_mask,
        [
            "target_timestamp",
            "province_key",
            "district_key",
            "district",
            *TARGET_COLUMNS,
        ],
    ].copy()

    print(
        f"Supervised rows: {len(frame):,}; "
        f"train={len(x_train):,}; test={len(x_test):,}"
    )
    print(
        f"Train targets: {frame.loc[train_mask, 'target_timestamp'].min()} to "
        f"{frame.loc[train_mask, 'target_timestamp'].max()}"
    )
    print(
        f"Test targets: {frame.loc[test_mask, 'target_timestamp'].min()} to "
        f"{frame.loc[test_mask, 'target_timestamp'].max()}"
    )

    for target, baseline_feature in TARGET_COLUMNS.items():
        print(f"Training {target}...")
        y_train = frame.loc[train_mask, target]
        y_test = frame.loc[test_mask, target]

        model = create_model()
        model.fit(x_train, y_train)
        predicted = clip_predictions(target, model.predict(x_test))
        baseline = clip_predictions(
            target,
            frame.loc[test_mask, baseline_feature].to_numpy(),
        )

        model_scores = regression_metrics(y_test.to_numpy(), predicted)
        baseline_scores = regression_metrics(y_test.to_numpy(), baseline)
        improvement = (
            100 * (baseline_scores["mae"] - model_scores["mae"])
            / baseline_scores["mae"]
            if baseline_scores["mae"]
            else 0.0
        )

        metrics_rows.append(
            {
                "target": target,
                **model_scores,
                "baseline_mae": baseline_scores["mae"],
                "baseline_rmse": baseline_scores["rmse"],
                "baseline_r2": baseline_scores["r2"],
                "mae_improvement_pct": improvement,
                "iterations": int(model.n_iter_),
            }
        )
        prediction_frame[f"predicted_{target.removeprefix('target_')}"] = predicted
        models[target] = model

        print(
            f"  MAE={model_scores['mae']:.4f}; "
            f"RMSE={model_scores['rmse']:.4f}; R2={model_scores['r2']:.4f}; "
            f"baseline MAE={baseline_scores['mae']:.4f}; "
            f"improvement={improvement:.2f}%"
        )

    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(output_dir / "metrics.csv", index=False, encoding="utf-8-sig")
    prediction_frame.sort_values(
        ["target_timestamp", "province_key", "district_key"]
    ).head(1000).to_csv(
        output_dir / "test_predictions_sample.csv",
        index=False,
        encoding="utf-8-sig",
    )

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_type": "HistGradientBoostingRegressor",
        "forecast_horizon_hours": HORIZON_HOURS,
        "test_start": str(split_timestamp),
        "training_rows": int(train_mask.sum()),
        "test_rows": int(test_mask.sum()),
        "feature_count": len(FEATURE_COLUMNS),
        "features": FEATURE_COLUMNS,
        "targets": list(TARGET_COLUMNS),
        "training_target_start": str(frame.loc[train_mask, "target_timestamp"].min()),
        "training_target_end": str(frame.loc[train_mask, "target_timestamp"].max()),
        "test_target_start": str(frame.loc[test_mask, "target_timestamp"].min()),
        "test_target_end": str(frame.loc[test_mask, "target_timestamp"].max()),
        "weather_scope_note": (
            "The current project supplies Ho Chi Minh City weather for all five provinces."
        ),
        "aqi_source_note": (
            "Open-Meteo CAMS Global modeled AQI, not monitoring-station observations."
        ),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    bundle = {
        "models": models,
        "feature_columns": FEATURE_COLUMNS,
        "target_columns": list(TARGET_COLUMNS),
        "metadata": metadata,
    }
    joblib.dump(bundle, output_dir / "model_bundle.joblib", compress=3)

    print("Refitting production models on all available supervised rows...")
    x_full = frame[FEATURE_COLUMNS]
    production_models: dict[str, HistGradientBoostingRegressor] = {}
    for target in TARGET_COLUMNS:
        print(f"  Refitting {target}...")
        production_model = create_model()
        production_model.fit(x_full, frame[target])
        production_models[target] = production_model

    production_metadata = {
        **metadata,
        "fit_scope": "all_available_supervised_rows",
        "production_training_rows": len(frame),
        "production_target_start": str(frame["target_timestamp"].min()),
        "production_target_end": str(frame["target_timestamp"].max()),
    }
    (output_dir / "metadata_full.json").write_text(
        json.dumps(production_metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    production_bundle = {
        "models": production_models,
        "feature_columns": FEATURE_COLUMNS,
        "target_columns": list(TARGET_COLUMNS),
        "metadata": production_metadata,
    }
    joblib.dump(
        production_bundle,
        output_dir / "model_bundle_full.joblib",
        compress=3,
    )
    print(f"Saved model artifacts to: {output_dir}")


def train_weather_only(test_start: str, output_dir: Path) -> None:
    history = load_joined_history()
    frame = build_weather_only_frame(history)
    split_timestamp = pd.Timestamp(test_start)
    train_mask = frame["target_timestamp"] < split_timestamp
    test_mask = ~train_mask
    if not train_mask.any() or not test_mask.any():
        raise ValueError(
            f"Invalid weather-only split at {test_start}: "
            f"train={int(train_mask.sum())}, test={int(test_mask.sum())}"
        )

    x_train = frame.loc[train_mask, WEATHER_ONLY_FEATURE_COLUMNS]
    x_test = frame.loc[test_mask, WEATHER_ONLY_FEATURE_COLUMNS]
    metrics_rows: list[dict[str, object]] = []
    holdout_predictions = frame.loc[
        test_mask,
        [
            "target_timestamp",
            "province_key",
            "district_key",
            "district",
            *TARGET_COLUMNS,
        ],
    ].copy()

    print(
        f"Weather-only rows: {len(frame):,}; "
        f"train={int(train_mask.sum()):,}; test={int(test_mask.sum()):,}"
    )
    for target in TARGET_COLUMNS:
        print(f"Evaluating {target}...")
        model = create_model()
        model.fit(x_train, frame.loc[train_mask, target])
        actual = frame.loc[test_mask, target].to_numpy()
        predicted = clip_predictions(target, model.predict(x_test))
        scores = regression_metrics(actual, predicted)
        metrics_rows.append(
            {
                "target": target,
                "train_rows": int(train_mask.sum()),
                "test_rows": int(test_mask.sum()),
                **scores,
                **comparison_metrics(
                    actual,
                    predicted,
                    TARGET_TOLERANCES[target],
                ),
            }
        )
        holdout_predictions[f"predicted_{target.removeprefix('target_')}"] = predicted
        print(
            f"  MAE={scores['mae']:.4f}; RMSE={scores['rmse']:.4f}; "
            f"R2={scores['r2']:.4f}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(metrics_rows).to_csv(
        output_dir / "weather_only_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    holdout_predictions.sort_values(
        ["target_timestamp", "province_key", "district_key"]
    ).to_csv(
        output_dir / "weather_only_holdout_predictions.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print("Refitting weather-only production models on all 2025 rows...")
    x_full = frame[WEATHER_ONLY_FEATURE_COLUMNS]
    models: dict[str, HistGradientBoostingRegressor] = {}
    for target in TARGET_COLUMNS:
        print(f"  Refitting {target}...")
        model = create_model()
        model.fit(x_full, frame[target])
        models[target] = model

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_type": "HistGradientBoostingRegressor",
        "fit_scope": "all_2025_weather_only_rows",
        "training_rows": len(frame),
        "training_target_start": str(frame["target_timestamp"].min()),
        "training_target_end": str(frame["target_timestamp"].max()),
        "holdout_test_start": str(split_timestamp),
        "feature_count": len(WEATHER_ONLY_FEATURE_COLUMNS),
        "features": WEATHER_ONLY_FEATURE_COLUMNS,
        "targets": list(TARGET_COLUMNS),
        "weather_scope_note": (
            "The current project supplies Ho Chi Minh City weather for all five provinces."
        ),
        "usage_note": (
            "This exogenous model supports multi-day forecasts from weather, calendar, "
            "location, population, traffic capacity, and green-space features without "
            "requiring future traffic or AQI observations."
        ),
    }
    (output_dir / "weather_only_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    joblib.dump(
        {
            "models": models,
            "feature_columns": WEATHER_ONLY_FEATURE_COLUMNS,
            "target_columns": list(TARGET_COLUMNS),
            "metadata": metadata,
        },
        output_dir / "model_bundle_weather_only_full.joblib",
        compress=3,
    )
    print(f"Saved weather-only model artifacts to: {output_dir}")


def forecast_weather_period(
    weather_file: Path,
    model_dir: Path,
    output_file: Path,
) -> None:
    bundle_path = model_dir / "model_bundle_weather_only_full.joblib"
    bundle = joblib.load(bundle_path)
    weather = pd.read_csv(weather_file, encoding="utf-8-sig")
    require_columns(weather, ["date", "hour", *WEATHER_COLUMNS], weather_file)
    weather["target_timestamp"] = pd.to_datetime(
        weather["date"].astype(str) + " " + weather["hour"].astype(str),
        errors="raise",
    )
    weather = weather[["target_timestamp", *WEATHER_COLUMNS]].copy()
    if weather["target_timestamp"].duplicated().any():
        raise ValueError("Weather period contains duplicate timestamps")
    if weather.isna().any().any():
        raise ValueError("Weather period contains missing values")
    expected = pd.date_range(
        weather["target_timestamp"].min(),
        weather["target_timestamp"].max(),
        freq="h",
    )
    if len(weather) != len(expected) or not np.array_equal(
        weather["target_timestamp"].sort_values().to_numpy(),
        expected.to_numpy(),
    ):
        raise ValueError("Weather period must contain one continuous row per hour")

    history = load_joined_history()
    locations = history.sort_values("timestamp").drop_duplicates(
        "location_key",
        keep="last",
    )[
        [
            "location_key",
            "province_key",
            "district_key",
            "district",
            *STATIC_COLUMNS,
        ]
    ]
    inference = locations.merge(weather, how="cross")
    for column in WEATHER_COLUMNS:
        inference[f"forecast_{column}"] = inference[column]
    add_periodic_features(inference)
    for column in bundle["feature_columns"]:
        inference[column] = pd.to_numeric(
            inference[column],
            errors="raise",
        ).astype("float32")

    result = inference[
        ["target_timestamp", "province_key", "district_key", "district"]
    ].copy()
    x = inference[bundle["feature_columns"]]
    for target, model in bundle["models"].items():
        result[f"predicted_{target.removeprefix('target_')}"] = clip_predictions(
            target,
            model.predict(x),
        )

    result = result.sort_values(
        ["target_timestamp", "province_key", "district_key"]
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_file, index=False, encoding="utf-8-sig")
    daily = result.assign(date=result["target_timestamp"].dt.strftime("%Y-%m-%d"))
    daily = daily.groupby(["date", "province_key"], as_index=False).agg(
        location_count=("district_key", "nunique"),
        predicted_currentspeed_mean=("predicted_currentspeed", "mean"),
        predicted_currentspeed_min=("predicted_currentspeed", "min"),
        predicted_currentspeed_max=("predicted_currentspeed", "max"),
        predicted_traffic_density_mean=("predicted_traffic_density", "mean"),
        predicted_traffic_density_min=("predicted_traffic_density", "min"),
        predicted_traffic_density_max=("predicted_traffic_density", "max"),
        predicted_us_aqi_mean=("predicted_us_aqi", "mean"),
        predicted_us_aqi_min=("predicted_us_aqi", "min"),
        predicted_us_aqi_max=("predicted_us_aqi", "max"),
    )
    daily_output = output_file.with_name(
        f"{output_file.stem}_daily_by_province.csv"
    )
    daily.to_csv(daily_output, index=False, encoding="utf-8-sig")
    print(
        f"Saved {len(result):,} forecasts for "
        f"{result['target_timestamp'].min()} to {result['target_timestamp'].max()} "
        f"at: {output_file}"
    )
    print(f"Saved {len(daily):,} daily province summaries at: {daily_output}")


def comparison_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    tolerance: float,
) -> dict[str, float]:
    return {
        "actual_mean": float(np.mean(actual)),
        "predicted_mean": float(np.mean(predicted)),
        "mean_bias": float(np.mean(predicted - actual)),
        "actual_std": float(np.std(actual)),
        "predicted_std": float(np.std(predicted)),
        "actual_min": float(np.min(actual)),
        "predicted_min": float(np.min(predicted)),
        "actual_max": float(np.max(actual)),
        "predicted_max": float(np.max(predicted)),
        "within_tolerance_pct": float(
            100 * np.mean(np.abs(predicted - actual) <= tolerance)
        ),
        "tolerance": tolerance,
    }


def backtest_monthly(
    first_test_month: str,
    last_test_month: str,
    output_dir: Path,
) -> None:
    history = load_joined_history()
    frame = build_supervised_frame(history)
    first_period = pd.Period(first_test_month, freq="M")
    last_period = pd.Period(last_test_month, freq="M")
    if first_period > last_period:
        raise ValueError("first-test-month must not be after last-test-month")

    periods = pd.period_range(first_period, last_period, freq="M")
    available_start = frame["target_timestamp"].min()
    available_end = frame["target_timestamp"].max()

    monthly_rows: list[dict[str, object]] = []
    province_rows: list[dict[str, object]] = []
    comparison_rows: list[dict[str, object]] = []
    all_actual: dict[str, list[np.ndarray]] = {target: [] for target in TARGET_COLUMNS}
    all_predicted: dict[str, list[np.ndarray]] = {
        target: [] for target in TARGET_COLUMNS
    }
    all_baseline: dict[str, list[np.ndarray]] = {
        target: [] for target in TARGET_COLUMNS
    }

    for period in periods:
        test_start = period.start_time
        test_end = (period + 1).start_time
        if test_end <= available_start or test_start > available_end:
            print(f"Skipping {period}: outside available target range")
            continue

        train_mask = frame["target_timestamp"] < test_start
        test_mask = (
            (frame["target_timestamp"] >= test_start)
            & (frame["target_timestamp"] < test_end)
        )
        if not train_mask.any() or not test_mask.any():
            print(f"Skipping {period}: train or test partition is empty")
            continue

        x_train = frame.loc[train_mask, FEATURE_COLUMNS]
        test_frame = frame.loc[test_mask]
        x_test = test_frame[FEATURE_COLUMNS]
        print(
            f"Backtest {period}: train={len(x_train):,}, "
            f"test={len(x_test):,}"
        )

        for target, baseline_feature in TARGET_COLUMNS.items():
            model = create_model()
            y_train = frame.loc[train_mask, target]
            actual = test_frame[target].to_numpy()
            model.fit(x_train, y_train)
            predicted = clip_predictions(target, model.predict(x_test))
            baseline = clip_predictions(
                target,
                test_frame[baseline_feature].to_numpy(),
            )

            scores = regression_metrics(actual, predicted)
            baseline_scores = regression_metrics(actual, baseline)
            improvement = (
                100 * (baseline_scores["mae"] - scores["mae"])
                / baseline_scores["mae"]
                if baseline_scores["mae"]
                else 0.0
            )
            monthly_rows.append(
                {
                    "test_month": str(period),
                    "target": target,
                    "train_rows": int(train_mask.sum()),
                    "test_rows": int(test_mask.sum()),
                    **scores,
                    "baseline_mae": baseline_scores["mae"],
                    "baseline_rmse": baseline_scores["rmse"],
                    "baseline_r2": baseline_scores["r2"],
                    "mae_improvement_pct": improvement,
                    "iterations": int(model.n_iter_),
                    **comparison_metrics(
                        actual,
                        predicted,
                        TARGET_TOLERANCES[target],
                    ),
                }
            )

            all_actual[target].append(actual)
            all_predicted[target].append(predicted)
            all_baseline[target].append(baseline)

            for province in sorted(test_frame["province_key"].unique()):
                province_mask = (
                    test_frame["province_key"].to_numpy() == province
                )
                province_actual = actual[province_mask]
                province_predicted = predicted[province_mask]
                province_baseline = baseline[province_mask]
                province_scores = regression_metrics(
                    province_actual,
                    province_predicted,
                )
                province_baseline_scores = regression_metrics(
                    province_actual,
                    province_baseline,
                )
                province_rows.append(
                    {
                        "test_month": str(period),
                        "province_key": province,
                        "target": target,
                        "rows": int(province_mask.sum()),
                        **province_scores,
                        "baseline_mae": province_baseline_scores["mae"],
                        "mae_improvement_pct": (
                            100
                            * (
                                province_baseline_scores["mae"]
                                - province_scores["mae"]
                            )
                            / province_baseline_scores["mae"]
                            if province_baseline_scores["mae"]
                            else 0.0
                        ),
                    }
                )
                comparison_rows.append(
                    {
                        "test_month": str(period),
                        "province_key": province,
                        "target": target,
                        "rows": int(province_mask.sum()),
                        **comparison_metrics(
                            province_actual,
                            province_predicted,
                            TARGET_TOLERANCES[target],
                        ),
                    }
                )

            print(
                f"  {target}: MAE={scores['mae']:.4f}, "
                f"R2={scores['r2']:.4f}, "
                f"baseline improvement={improvement:.2f}%"
            )

    if not monthly_rows:
        raise ValueError("No monthly backtest folds were produced")

    summary_rows: list[dict[str, object]] = []
    for target in TARGET_COLUMNS:
        actual = np.concatenate(all_actual[target])
        predicted = np.concatenate(all_predicted[target])
        baseline = np.concatenate(all_baseline[target])
        scores = regression_metrics(actual, predicted)
        baseline_scores = regression_metrics(actual, baseline)
        summary_rows.append(
            {
                "target": target,
                "months": len(all_actual[target]),
                "rows": len(actual),
                **scores,
                "baseline_mae": baseline_scores["mae"],
                "baseline_rmse": baseline_scores["rmse"],
                "baseline_r2": baseline_scores["r2"],
                "mae_improvement_pct": (
                    100 * (baseline_scores["mae"] - scores["mae"])
                    / baseline_scores["mae"]
                    if baseline_scores["mae"]
                    else 0.0
                ),
                **comparison_metrics(
                    actual,
                    predicted,
                    TARGET_TOLERANCES[target],
                ),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(monthly_rows).to_csv(
        output_dir / "backtest_metrics_monthly.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(province_rows).to_csv(
        output_dir / "backtest_metrics_monthly_by_province.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(comparison_rows).to_csv(
        output_dir / "backtest_actual_vs_predicted.csv",
        index=False,
        encoding="utf-8-sig",
    )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(
        output_dir / "backtest_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    print("\nBacktest summary:")
    print(
        summary[
            [
                "target",
                "months",
                "rows",
                "mae",
                "rmse",
                "r2",
                "baseline_mae",
                "mae_improvement_pct",
                "mean_bias",
                "within_tolerance_pct",
            ]
        ].to_string(index=False)
    )
    print(f"Saved monthly backtest reports to: {output_dir}")


def evaluate_excluded_period(
    test_start: str,
    test_end: str,
    output_dir: Path,
) -> None:
    """Evaluate a calendar period excluded from training.

    This is a retrospective seasonal holdout when training rows occur after the
    test period. It measures generalization, not a causal historical forecast.
    """
    history = load_joined_history()
    frame = build_supervised_frame(history)
    start = pd.Timestamp(test_start)
    end = pd.Timestamp(test_end)
    if start >= end:
        raise ValueError("test-start must be before test-end")

    test_mask = (
        (frame["target_timestamp"] >= start)
        & (frame["target_timestamp"] < end)
    )
    embargo = pd.Timedelta(hours=HORIZON_HOURS)
    train_mask = (
        (frame["target_timestamp"] < start - embargo)
        | (frame["target_timestamp"] >= end + embargo)
    )
    if not train_mask.any() or not test_mask.any():
        raise ValueError(
            f"Invalid excluded-period split: train={int(train_mask.sum())}, "
            f"test={int(test_mask.sum())}"
        )

    x_train = frame.loc[train_mask, FEATURE_COLUMNS]
    test_frame = frame.loc[test_mask].copy()
    x_test = test_frame[FEATURE_COLUMNS]
    predictions = test_frame[
        [
            "target_timestamp",
            "province_key",
            "district_key",
            "district",
            *TARGET_COLUMNS,
        ]
    ].copy()
    metrics_rows: list[dict[str, object]] = []
    province_rows: list[dict[str, object]] = []

    print(
        f"Excluded-period evaluation: train={len(x_train):,}, "
        f"test={len(x_test):,}"
    )
    print(
        f"Test targets: {test_frame['target_timestamp'].min()} to "
        f"{test_frame['target_timestamp'].max()}"
    )

    for target, baseline_feature in TARGET_COLUMNS.items():
        print(f"Training {target}...")
        model = create_model()
        model.fit(x_train, frame.loc[train_mask, target])
        actual = test_frame[target].to_numpy()
        predicted = clip_predictions(target, model.predict(x_test))
        baseline = clip_predictions(
            target,
            test_frame[baseline_feature].to_numpy(),
        )
        scores = regression_metrics(actual, predicted)
        baseline_scores = regression_metrics(actual, baseline)
        improvement = (
            100 * (baseline_scores["mae"] - scores["mae"])
            / baseline_scores["mae"]
            if baseline_scores["mae"]
            else 0.0
        )
        metrics_rows.append(
            {
                "target": target,
                "train_rows": int(train_mask.sum()),
                "test_rows": int(test_mask.sum()),
                **scores,
                "baseline_mae": baseline_scores["mae"],
                "baseline_rmse": baseline_scores["rmse"],
                "baseline_r2": baseline_scores["r2"],
                "mae_improvement_pct": improvement,
                **comparison_metrics(
                    actual,
                    predicted,
                    TARGET_TOLERANCES[target],
                ),
            }
        )
        predictions[f"predicted_{target.removeprefix('target_')}"] = predicted

        for province in sorted(test_frame["province_key"].unique()):
            province_mask = test_frame["province_key"].to_numpy() == province
            province_actual = actual[province_mask]
            province_predicted = predicted[province_mask]
            province_baseline = baseline[province_mask]
            province_scores = regression_metrics(
                province_actual,
                province_predicted,
            )
            province_baseline_scores = regression_metrics(
                province_actual,
                province_baseline,
            )
            province_rows.append(
                {
                    "province_key": province,
                    "target": target,
                    "rows": int(province_mask.sum()),
                    **province_scores,
                    "baseline_mae": province_baseline_scores["mae"],
                    "mae_improvement_pct": (
                        100
                        * (province_baseline_scores["mae"] - province_scores["mae"])
                        / province_baseline_scores["mae"]
                        if province_baseline_scores["mae"]
                        else 0.0
                    ),
                    **comparison_metrics(
                        province_actual,
                        province_predicted,
                        TARGET_TOLERANCES[target],
                    ),
                }
            )

        print(
            f"  MAE={scores['mae']:.4f}; RMSE={scores['rmse']:.4f}; "
            f"R2={scores['r2']:.4f}; baseline improvement={improvement:.2f}%"
        )

    label = f"{start:%Y_%m}_to_{end - pd.Timedelta(days=1):%Y_%m_%d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(
        output_dir / f"excluded_period_{label}_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(province_rows).to_csv(
        output_dir / f"excluded_period_{label}_metrics_by_province.csv",
        index=False,
        encoding="utf-8-sig",
    )
    predictions.sort_values(
        ["target_timestamp", "province_key", "district_key"]
    ).to_csv(
        output_dir / f"excluded_period_{label}_predictions.csv",
        index=False,
        encoding="utf-8-sig",
    )
    metadata = {
        "evaluation_type": "retrospective_excluded_period",
        "causal_forecast": False,
        "test_start": str(start),
        "test_end_exclusive": str(end),
        "embargo_hours": HORIZON_HOURS,
        "train_rows": int(train_mask.sum()),
        "test_rows": int(test_mask.sum()),
        "note": (
            "The test period is excluded from training, but training data occurs "
            "after it; use this only as a seasonal generalization check."
        ),
    }
    (output_dir / f"excluded_period_{label}_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\nExcluded-period summary:")
    print(
        metrics[
            [
                "target",
                "test_rows",
                "mae",
                "rmse",
                "r2",
                "baseline_mae",
                "mae_improvement_pct",
                "mean_bias",
                "within_tolerance_pct",
            ]
        ].to_string(index=False)
    )
    print(f"Saved excluded-period reports to: {output_dir}")


def predict_historical_date(
    target_date: str,
    model_dir: Path,
    output_file: Path,
) -> None:
    bundle = joblib.load(model_dir / "model_bundle.joblib")
    history = load_joined_history()
    frame = build_supervised_frame(history)

    target_day = pd.Timestamp(target_date)
    selected = frame[frame["target_timestamp"].dt.normalize() == target_day].copy()
    if selected.empty:
        raise ValueError(f"No supervised rows available for target date {target_date}")

    x = selected[bundle["feature_columns"]]
    result = selected[
        [
            "target_timestamp",
            "province_key",
            "district_key",
            "district",
            *bundle["target_columns"],
        ]
    ].copy()

    for target, model in bundle["models"].items():
        predicted = clip_predictions(target, model.predict(x))
        result[f"predicted_{target.removeprefix('target_')}"] = predicted

    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"Saved {len(result):,} predictions to: {output_file}")


def load_forecast_weather(
    history: pd.DataFrame,
    target_date: pd.Timestamp,
    weather_file: Path | None,
) -> pd.DataFrame:
    if weather_file is None:
        weather = history.loc[
            history["timestamp"].dt.normalize() == target_date,
            ["timestamp", *WEATHER_COLUMNS],
        ].drop_duplicates("timestamp")
    else:
        weather = pd.read_csv(weather_file, encoding="utf-8-sig")
        require_columns(weather, ["date", "hour", *WEATHER_COLUMNS], weather_file)
        weather["timestamp"] = pd.to_datetime(
            weather["date"].astype(str) + " " + weather["hour"].astype(str),
            errors="raise",
        )
        weather = weather[["timestamp", *WEATHER_COLUMNS]]
        weather = weather[weather["timestamp"].dt.normalize() == target_date]

    if weather["timestamp"].duplicated().any():
        raise ValueError("Forecast weather contains duplicate timestamps")
    if len(weather) != 24:
        source = str(weather_file) if weather_file else "project history"
        raise ValueError(
            f"Expected 24 weather rows for {target_date.date()} from {source}; "
            f"received {len(weather)}"
        )

    return weather.sort_values("timestamp").reset_index(drop=True)


def build_next_day_feature_frame(
    history: pd.DataFrame,
    current_date: str,
    weather_file: Path | None,
) -> pd.DataFrame:
    frame = history.copy()
    grouped = frame.groupby("location_key", sort=False)

    for column in ROLLING_COLUMNS:
        rolling = grouped[column].rolling(24, min_periods=24)
        frame[f"rolling24_{column}_mean"] = (
            rolling.mean().reset_index(level=0, drop=True)
        )
        frame[f"rolling24_{column}_std"] = (
            rolling.std().reset_index(level=0, drop=True)
        )

    current_day = pd.Timestamp(current_date)
    selected = frame[frame["timestamp"].dt.normalize() == current_day].copy()
    expected_rows = history["location_key"].nunique() * 24
    if len(selected) != expected_rows:
        raise ValueError(
            f"Expected {expected_rows} current observations for {current_date}; "
            f"received {len(selected)}"
        )

    selected["target_timestamp"] = selected["timestamp"] + pd.Timedelta(
        hours=HORIZON_HOURS
    )
    target_date = current_day + pd.Timedelta(days=1)
    forecast_weather = load_forecast_weather(history, target_date, weather_file)
    forecast_weather = forecast_weather.rename(
        columns={
            "timestamp": "target_timestamp",
            **{column: f"forecast_{column}" for column in WEATHER_COLUMNS},
        }
    )
    selected = selected.merge(
        forecast_weather,
        on="target_timestamp",
        how="left",
        validate="many_to_one",
    )

    for column in WEATHER_COLUMNS:
        selected[f"lag24_{column}"] = selected[column]
    for column in CURRENT_TRAFFIC_COLUMNS + CURRENT_AQI_COLUMNS:
        selected[f"lag24_{column}"] = selected[column]

    add_periodic_features(selected)
    selected = selected.dropna(subset=FEATURE_COLUMNS).copy()
    if len(selected) != expected_rows:
        raise ValueError("Inference features contain missing values")

    for column in FEATURE_COLUMNS:
        selected[column] = pd.to_numeric(selected[column], errors="raise").astype(
            "float32"
        )

    return selected[
        [
            "target_timestamp",
            "province_key",
            "district_key",
            "district",
            *FEATURE_COLUMNS,
        ]
    ]


def forecast_next_day(
    current_date: str,
    weather_file: Path | None,
    model_dir: Path,
    output_file: Path,
) -> None:
    production_bundle = model_dir / "model_bundle_full.joblib"
    bundle_path = (
        production_bundle
        if production_bundle.exists()
        else model_dir / "model_bundle.joblib"
    )
    bundle = joblib.load(bundle_path)
    print(f"Using model bundle: {bundle_path.name}")
    history = load_joined_history()
    inference = build_next_day_feature_frame(history, current_date, weather_file)
    x = inference[bundle["feature_columns"]]
    result = inference[
        ["target_timestamp", "province_key", "district_key", "district"]
    ].copy()

    for target, model in bundle["models"].items():
        predicted = clip_predictions(target, model.predict(x))
        result[f"predicted_{target.removeprefix('target_')}"] = predicted

    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(
        f"Saved {len(result):,} next-day forecasts for "
        f"{result['target_timestamp'].dt.date.min()} to: {output_file}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train or backtest a 24-hour traffic and AQI forecasting model."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train", help="Train and evaluate the model")
    train_parser.add_argument("--test-start", default=DEFAULT_TEST_START)
    train_parser.add_argument("--output-dir", type=Path, default=MODEL_DIR)

    weather_train_parser = subparsers.add_parser(
        "train-weather-only",
        help="Train a full-year model for weather-driven multi-day forecasts",
    )
    weather_train_parser.add_argument("--test-start", default=DEFAULT_TEST_START)
    weather_train_parser.add_argument("--output-dir", type=Path, default=MODEL_DIR)

    predict_parser = subparsers.add_parser(
        "predict",
        help="Generate historical next-day predictions for one target date",
    )
    predict_parser.add_argument("--target-date", required=True)
    predict_parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    predict_parser.add_argument("--output-file", type=Path)

    forecast_parser = subparsers.add_parser(
        "forecast",
        help="Forecast the next day from current observations and weather forecast",
    )
    forecast_parser.add_argument("--current-date", required=True)
    forecast_parser.add_argument(
        "--weather-file",
        type=Path,
        help=(
            "CSV with 24 target-day rows and date, hour, plus weather columns. "
            "If omitted, weather is read from project history for backtesting."
        ),
    )
    forecast_parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    forecast_parser.add_argument("--output-file", type=Path)

    weather_period_parser = subparsers.add_parser(
        "forecast-weather-period",
        help="Forecast all hours in a multi-day weather CSV",
    )
    weather_period_parser.add_argument("--weather-file", type=Path, required=True)
    weather_period_parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    weather_period_parser.add_argument("--output-file", type=Path, required=True)

    backtest_parser = subparsers.add_parser(
        "backtest",
        help="Run expanding-window monthly backtests",
    )
    backtest_parser.add_argument("--first-test-month", default="2025-03")
    backtest_parser.add_argument("--last-test-month", default="2025-12")
    backtest_parser.add_argument("--output-dir", type=Path, default=MODEL_DIR)

    excluded_parser = subparsers.add_parser(
        "evaluate-period",
        help="Evaluate a date range excluded from training",
    )
    excluded_parser.add_argument("--test-start", required=True)
    excluded_parser.add_argument("--test-end", required=True)
    excluded_parser.add_argument("--output-dir", type=Path, default=MODEL_DIR)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "train":
        train(args.test_start, args.output_dir.resolve())
        return

    if args.command == "train-weather-only":
        train_weather_only(args.test_start, args.output_dir.resolve())
        return

    if args.command == "forecast":
        target_date = (pd.Timestamp(args.current_date) + pd.Timedelta(days=1)).date()
        output_file = args.output_file
        if output_file is None:
            output_file = (
                ROOT_DIR
                / "data"
                / "processed"
                / "model_predictions"
                / f"traffic_aqi_forecast_{target_date}.csv"
            )
        weather_file = args.weather_file.resolve() if args.weather_file else None
        forecast_next_day(
            args.current_date,
            weather_file,
            args.model_dir.resolve(),
            output_file.resolve(),
        )
        return

    if args.command == "forecast-weather-period":
        forecast_weather_period(
            args.weather_file.resolve(),
            args.model_dir.resolve(),
            args.output_file.resolve(),
        )
        return

    if args.command == "backtest":
        backtest_monthly(
            args.first_test_month,
            args.last_test_month,
            args.output_dir.resolve(),
        )
        return

    if args.command == "evaluate-period":
        evaluate_excluded_period(
            args.test_start,
            args.test_end,
            args.output_dir.resolve(),
        )
        return

    output_file = args.output_file
    if output_file is None:
        output_file = (
            ROOT_DIR
            / "data"
            / "processed"
            / "model_predictions"
            / f"traffic_aqi_predictions_{args.target_date}.csv"
        )
    predict_historical_date(
        args.target_date,
        args.model_dir.resolve(),
        output_file.resolve(),
    )


if __name__ == "__main__":
    main()
