"""Thu thap du lieu live va du bao AQI/traffic theo gio.

Muc luc:
1. Khai bao API, file live, model artifact va nhom cot feature.
2. Lay weather/AQI/traffic tu Open-Meteo va TomTom.
3. Ghi observation, tao feature inference va predict t+1h.
4. Dong bo observation/prediction/model registry len TiDB neu co `.env`.
5. CLI: chay mot lan, chay loop 24/24 hoac chi sync database.

File nay la pipeline van hanh. Khi khong co du TomTom cho mot dia diem,
script co co che fallback tu lich su gan nhat de job 24/24 khong bi dut.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
import requests


ROOT_DIR = Path(__file__).resolve().parents[2]
MODELS_DIR = (
    ROOT_DIR
    / "models"
    / "next_day_traffic_aqi"
    / "xgboost_multisource_hourly"
)
MODEL_FILE = MODELS_DIR / "xgboost_multisource_hourly_full.joblib"
LOCATIONS_FILE = (
    ROOT_DIR
    / "data"
    / "raw"
    / "AQI"
    / "open_meteo_aqi_2025_output"
    / "locations_5_provinces_old_boundaries.csv"
)
DEFAULT_OBSERVATIONS_FILE = ROOT_DIR / "data" / "live" / "hourly_observations.csv"
DEFAULT_PREDICTIONS_DIR = ROOT_DIR / "data" / "live" / "predictions"
DEFAULT_PREDICTIONS_FILE = ROOT_DIR / "data" / "live" / "hourly_predictions.csv"
DEFAULT_LOCK_FILE = ROOT_DIR / "data" / "live" / "collector.lock"
DATABASE_SYNC_LOOKBACK_HOURS = 72

TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
WEATHER_API = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_API = "https://air-quality-api.open-meteo.com/v1/air-quality"
TOMTOM_API = (
    "https://api.tomtom.com/traffic/services/4/flowSegmentData/"
    "absolute/10/json"
)
HCM_LAT = 10.8231
HCM_LON = 106.6297

WEATHER_COLUMNS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "cloud_cover",
]
TRAFFIC_COLUMNS = [
    "currentspeed",
    "freeflowspeed",
    "congestion_ratio",
    "traffic_density",
]
AQI_COLUMNS = [
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
LAG_HOURS = [1, 2, 3, 6, 12]
ROLLING_WINDOWS = [3, 6, 12]
REQUIRED_HISTORY_HOURS = max(LAG_HOURS)
TIME_SERIES_COLUMNS = WEATHER_COLUMNS + TRAFFIC_COLUMNS + AQI_COLUMNS
LOCATION_CONTEXT_COLUMNS = [
    "province_key",
    "district_key",
    "district",
    *STATIC_COLUMNS,
]
TOMTOM_UNSUPPORTED_LOCATIONS = {
    "ba_ria_vung_tau__con_dao",
    "dong_nai__tan_phu",
    "ho_chi_minh__can_gio",
}


class ApiRequestError(RuntimeError):
    def __init__(self, source: str, status_code: int | None, reason: str) -> None:
        self.status_code = status_code
        super().__init__(f"{source}: {reason}")


def add_source_paths() -> None:
    for source_path in (ROOT_DIR / "src", ROOT_DIR / "src" / "models"):
        path = str(source_path)
        if path not in sys.path:
            sys.path.insert(0, path)


add_source_paths()
from database.live_database import (  # noqa: E402
    LiveDatabase,
    database_sync_required,
    model_version,
)
from next_day_traffic_aqi import (  # noqa: E402
    add_periodic_features,
    clip_predictions,
    district_key,
    load_joined_history,
)


def request_json(
    url: str,
    params: dict[str, Any],
    source: str,
    timeout: int = 30,
    retries: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(payload.get("reason", f"{source} API error"))
            return payload
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            last_error = ApiRequestError(source, status, f"HTTP {status}")
            if status not in {408, 425, 429, 500, 502, 503, 504}:
                raise last_error from None
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
        except requests.RequestException as exc:
            last_error = ApiRequestError(
                source,
                None,
                type(exc).__name__,
            )
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
        except (ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
    raise RuntimeError(f"{source} failed after {retries} attempts: {last_error}")


def local_hour(value: str | None) -> pd.Timestamp:
    if value:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(TIMEZONE).tz_localize(None)
        return timestamp.floor("h")
    return pd.Timestamp(datetime.now(TIMEZONE).replace(tzinfo=None)).floor("h")


def load_tomtom_keys(key_file: Path | None, required: bool) -> list[str]:
    if key_file is not None:
        if not key_file.is_file():
            raise ValueError(f"TomTom key file does not exist: {key_file}")
        api_keys = [
            line.strip()
            for line in key_file.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    else:
        api_key = os.getenv("TOMTOM_API_KEY", "").strip()
        api_keys = [api_key] if api_key else []
    if required and not api_keys:
        raise RuntimeError(
            "TomTom API key is missing. Set TOMTOM_API_KEY or use "
            "--tomtom-key-file."
        )
    return api_keys


def hourly_values(
    payload: dict[str, Any],
    timestamp: pd.Timestamp,
    columns: list[str],
) -> dict[str, float]:
    hourly = payload["hourly"]
    times = pd.to_datetime(hourly["time"], errors="raise")
    matches = np.flatnonzero(times == timestamp)
    if len(matches) != 1:
        raise ValueError(f"API response has {len(matches)} rows for {timestamp}")
    index = int(matches[0])
    values = {column: float(hourly[column][index]) for column in columns}
    if not all(np.isfinite(value) for value in values.values()):
        raise ValueError(f"API response contains non-finite values at {timestamp}")
    return values


def fetch_weather_hours(
    current: pd.Timestamp,
) -> tuple[dict[str, float], dict[str, float]]:
    target = current + pd.Timedelta(hours=1)
    payload = request_json(
        WEATHER_API,
        {
            "latitude": HCM_LAT,
            "longitude": HCM_LON,
            "hourly": ",".join(WEATHER_COLUMNS),
            "start_date": current.strftime("%Y-%m-%d"),
            "end_date": target.strftime("%Y-%m-%d"),
            "timezone": "Asia/Ho_Chi_Minh",
        },
        "Open-Meteo weather",
    )
    return (
        hourly_values(payload, current, WEATHER_COLUMNS),
        hourly_values(payload, target, WEATHER_COLUMNS),
    )


def fetch_aqi(location: pd.Series, current: pd.Timestamp) -> dict[str, float]:
    payload = request_json(
        AIR_QUALITY_API,
        {
            "latitude": float(location["api_lat"]),
            "longitude": float(location["api_lon"]),
            "hourly": ",".join(AQI_COLUMNS),
            "start_date": current.strftime("%Y-%m-%d"),
            "end_date": current.strftime("%Y-%m-%d"),
            "timezone": "Asia/Ho_Chi_Minh",
            "domains": "cams_global",
            "cell_selection": "nearest",
        },
        f"Open-Meteo AQI {location['location_key']}",
    )
    return hourly_values(payload, current, AQI_COLUMNS)


def fetch_traffic(
    location: pd.Series,
    api_key: str,
) -> dict[str, float]:
    payload = request_json(
        TOMTOM_API,
        {
            "key": api_key,
            "point": f"{location['api_lat']},{location['api_lon']}",
            "unit": "KMPH",
        },
        f"TomTom traffic {location['location_key']}",
    )
    segment = payload.get("flowSegmentData")
    if not segment:
        raise ValueError(f"TomTom returned no segment for {location['location_key']}")
    current_speed = float(segment["currentSpeed"])
    free_flow_speed = float(segment["freeFlowSpeed"])
    if free_flow_speed <= 0:
        raise ValueError(f"Invalid free-flow speed for {location['location_key']}")
    congestion_ratio = current_speed / free_flow_speed
    return {
        "currentspeed": current_speed,
        "freeflowspeed": free_flow_speed,
        "congestion_ratio": congestion_ratio,
        "traffic_density": float(np.clip(1 - congestion_ratio, 0, 1)),
    }


def fetch_traffic_with_keys(
    location: pd.Series,
    api_keys: list[str],
    start_index: int = 0,
) -> dict[str, float]:
    errors: list[str] = []
    for offset in range(len(api_keys)):
        api_key = api_keys[(start_index + offset) % len(api_keys)]
        try:
            return fetch_traffic(location, api_key)
        except ApiRequestError as exc:
            errors.append(str(exc))
            if exc.status_code not in {401, 403, 429}:
                raise
    raise RuntimeError(
        f"No usable TomTom key for {location['location_key']}; "
        f"attempts={len(errors)}"
    )


def load_locations() -> pd.DataFrame:
    manifest = pd.read_csv(LOCATIONS_FILE, encoding="utf-8-sig")
    manifest["district_key"] = manifest["location_name"].map(district_key)
    manifest["location_key"] = (
        manifest["province_slug"] + "__" + manifest["district_key"]
    )

    history = load_joined_history()
    static = history.sort_values("timestamp").drop_duplicates(
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
    locations = static.merge(
        manifest[["location_key", "lat", "lon"]].rename(
            columns={"lat": "api_lat", "lon": "api_lon"}
        ),
        on="location_key",
        how="left",
        validate="one_to_one",
    )
    if locations[["api_lat", "api_lon"]].isna().any().any():
        raise ValueError("Location manifest does not cover every model location")
    return locations.sort_values("location_key").reset_index(drop=True)


def collect_rows(
    locations: pd.DataFrame,
    current: pd.Timestamp,
    api_keys: list[str],
) -> tuple[pd.DataFrame, dict[str, float]]:
    current_weather, target_weather = fetch_weather_hours(current)
    collected: dict[str, dict[str, float]] = {}

    def collect_location(
        location: pd.Series,
        key_index: int,
    ) -> tuple[str, dict[str, float]]:
        return (
            str(location["location_key"]),
            {
                **fetch_traffic_with_keys(location, api_keys, key_index),
                **fetch_aqi(location, current),
            },
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(collect_location, row, index)
            for index, (_, row) in enumerate(locations.iterrows())
        ]
        for future in as_completed(futures):
            key, values = future.result()
            collected[key] = values

    rows: list[dict[str, Any]] = []
    collection_time = datetime.now(TIMEZONE).isoformat()
    for _, location in locations.iterrows():
        key = str(location["location_key"])
        rows.append(
            {
                "timestamp": current,
                "collection_time": collection_time,
                "location_key": key,
                "province_key": location["province_key"],
                "district_key": location["district_key"],
                "district": location["district"],
                **{column: location[column] for column in STATIC_COLUMNS},
                **current_weather,
                **collected[key],
                "traffic_source": "tomtom_flow_segment_live",
                "aqi_source": "open_meteo_cams_global",
                "weather_source": "open_meteo_forecast",
            }
        )
    return pd.DataFrame(rows), target_weather


def drop_repeated_header_rows(frame: pd.DataFrame, marker_column: str) -> pd.DataFrame:
    """Remove CSV header rows that were accidentally imported as data."""

    if marker_column not in frame.columns:
        return frame
    marker = frame[marker_column].astype(str).str.strip().str.casefold()
    return frame.loc[marker != marker_column.casefold()].copy()


def filter_observations_for_locations(
    observations: pd.DataFrame,
    locations: pd.DataFrame,
) -> pd.DataFrame:
    """Keep only locations that the live hourly model can score in this run."""

    supported_keys = set(locations["location_key"].astype(str))
    mask = observations["location_key"].astype(str).isin(supported_keys)
    return observations.loc[mask].copy()


def fill_history_gaps(observations: pd.DataFrame, current: pd.Timestamp) -> pd.DataFrame:
    """Create a complete hourly panel for lag/rolling features.

    GitHub Actions schedules can be delayed or skipped. TomTom live traffic cannot
    be fetched retroactively, so missed hours are bridged with nearest known values
    to keep the public forecast running instead of staying stale indefinitely.
    """

    start = current - pd.Timedelta(hours=REQUIRED_HISTORY_HOURS - 1)
    hours = pd.date_range(start, current, freq="h")
    frame = observations[
        (observations["timestamp"] >= start) & (observations["timestamp"] <= current)
    ].copy()
    if frame.empty:
        return frame

    fill_columns = [
        column
        for column in [*LOCATION_CONTEXT_COLUMNS, *TIME_SERIES_COLUMNS]
        if column in frame.columns
    ]
    groups: list[pd.DataFrame] = []
    for location_key, group in frame.groupby("location_key", sort=False):
        group = (
            group.sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
            .set_index("timestamp")
            .reindex(hours)
        )
        group["timestamp"] = group.index
        group["location_key"] = location_key
        group[fill_columns] = group[fill_columns].ffill().bfill()
        groups.append(group.reset_index(drop=True))

    return pd.concat(groups, ignore_index=True)


def upsert_observations(new_rows: pd.DataFrame, output_file: Path) -> pd.DataFrame:
    if output_file.exists():
        existing = pd.read_csv(output_file, encoding="utf-8-sig")
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows.copy()
    combined = drop_repeated_header_rows(combined, "timestamp")
    combined["timestamp"] = pd.to_datetime(combined["timestamp"], errors="raise")
    combined = combined.sort_values("collection_time").drop_duplicates(
        ["timestamp", "location_key"],
        keep="last",
    )
    combined = combined.sort_values(["location_key", "timestamp"])
    output_file.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_file, index=False, encoding="utf-8-sig")
    return combined


def build_inference(
    observations: pd.DataFrame,
    current: pd.Timestamp,
    target_weather: dict[str, float],
    bundle: dict[str, Any],
) -> pd.DataFrame | None:
    observations = observations.copy()
    observations = drop_repeated_header_rows(observations, "timestamp")
    observations["timestamp"] = pd.to_datetime(
        observations["timestamp"],
        errors="raise",
    )
    target = current + pd.Timedelta(hours=1)
    current_rows = observations[observations["timestamp"] == current].copy()
    location_count = observations["location_key"].nunique()
    if len(current_rows) != location_count:
        return None
    observations = fill_history_gaps(observations, current)
    current_rows = observations[observations["timestamp"] == current].copy()

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
    for column in WEATHER_COLUMNS:
        derived[f"forecast_{column}"] = pd.Series(
            target_weather[column],
            index=inference.index,
        )

    lag_columns = TIME_SERIES_COLUMNS
    for lag in LAG_HOURS:
        source_timestamp = target - pd.Timedelta(hours=lag)
        lag_rows = observations[
            observations["timestamp"] == source_timestamp
        ].set_index("location_key")
        if len(lag_rows) != location_count:
            return None
        for column in lag_columns:
            derived[f"lag{lag}_{column}"] = inference["location_key"].map(
                lag_rows[column]
            )

    for window in ROLLING_WINDOWS:
        start = current - pd.Timedelta(hours=window - 1)
        window_rows = observations[
            (observations["timestamp"] >= start)
            & (observations["timestamp"] <= current)
        ]
        counts = window_rows.groupby("location_key").size()
        if len(counts) != location_count or not counts.eq(window).all():
            return None
        grouped = window_rows.groupby("location_key")
        for column in ROLLING_COLUMNS:
            for stat in ("mean", "std"):
                derived[f"rolling{window}_{column}_{stat}"] = inference[
                    "location_key"
                ].map(grouped[column].agg(stat))

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
        raise ValueError("Live inference contains missing feature values")
    return inference


def predict(
    inference: pd.DataFrame,
    bundle: dict[str, Any],
    output_file: Path,
    version: str,
) -> pd.DataFrame:
    result = inference[
        [
            "target_timestamp",
            "location_key",
            "province_key",
            "district_key",
            "district",
        ]
    ].copy()
    feature_map = bundle.get("feature_columns_by_target", {})
    for target, model in bundle["models"].items():
        features = feature_map.get(target, bundle["feature_columns"])
        result[f"predicted_{target.removeprefix('target_')}"] = clip_predictions(
            target,
            model.predict(inference[features]),
        )
    result["generated_at"] = datetime.now(TIMEZONE).isoformat()
    result["model_version"] = version
    result = result.sort_values(["province_key", "district_key"])
    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_file, index=False, encoding="utf-8-sig")
    return result


def upsert_predictions(new_rows: pd.DataFrame, output_file: Path) -> pd.DataFrame:
    if output_file.exists():
        existing = pd.read_csv(output_file, encoding="utf-8-sig")
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows.copy()
    combined = drop_repeated_header_rows(combined, "target_timestamp")
    combined["target_timestamp"] = pd.to_datetime(
        combined["target_timestamp"], errors="raise"
    )
    combined = combined.sort_values("generated_at").drop_duplicates(
        ["target_timestamp", "location_key", "model_version"],
        keep="last",
    )
    combined = combined.sort_values(
        ["target_timestamp", "province_key", "district_key"]
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_file, index=False, encoding="utf-8-sig")
    return combined


def read_observations_file(observations_file: Path) -> pd.DataFrame:
    if not observations_file.is_file():
        return pd.DataFrame()
    observations = pd.read_csv(observations_file, encoding="utf-8-sig")
    observations = drop_repeated_header_rows(observations, "timestamp")
    if observations.empty:
        return observations
    observations["timestamp"] = pd.to_datetime(
        observations["timestamp"],
        errors="raise",
    )
    return observations


def read_predictions_file(predictions_file: Path) -> pd.DataFrame:
    if not predictions_file.is_file():
        return pd.DataFrame()
    predictions = pd.read_csv(predictions_file, encoding="utf-8-sig")
    predictions = drop_repeated_header_rows(predictions, "target_timestamp")
    if predictions.empty:
        return predictions
    predictions["target_timestamp"] = pd.to_datetime(
        predictions["target_timestamp"],
        errors="raise",
    )
    return predictions


def configured_database() -> LiveDatabase | None:
    return LiveDatabase.from_environment(required=False)


def verify_database(database: LiveDatabase) -> dict[str, object]:
    status = database.healthcheck()
    if status["live_table_count"] != 5:
        raise RuntimeError(
            "Live database schema is incomplete. Run: "
            "python src\\database\\manage_live_database.py init-schema"
        )
    return status


def sync_database_window(
    database: LiveDatabase,
    locations: pd.DataFrame,
    bundle: dict[str, Any],
    observations: pd.DataFrame,
    predictions: pd.DataFrame,
    current: pd.Timestamp,
) -> tuple[int, int, str]:
    version = database.register_model(bundle, MODEL_FILE)
    location_rows = locations.copy()
    location_rows["is_live_supported"] = ~location_rows["location_key"].isin(
        TOMTOM_UNSUPPORTED_LOCATIONS
    )
    database.upsert_locations(location_rows)

    start = current - pd.Timedelta(hours=DATABASE_SYNC_LOOKBACK_HOURS)
    recent_observations = observations[observations["timestamp"] >= start]
    observation_count = database.upsert_observations(recent_observations)

    prediction_count = 0
    if not predictions.empty:
        recent_predictions = predictions[
            predictions["target_timestamp"] >= start
        ]
        prediction_count = database.upsert_predictions(recent_predictions, version)
    return observation_count, prediction_count, version


def predict_from_existing_observations(
    timestamp: str | None,
    observations_file: Path,
    predictions_dir: Path,
    predictions_file: Path,
) -> bool:
    current = local_hour(timestamp)
    all_locations = load_locations()
    locations = all_locations[
        ~all_locations["location_key"].isin(TOMTOM_UNSUPPORTED_LOCATIONS)
    ].reset_index(drop=True)
    bundle = joblib.load(MODEL_FILE)
    version = model_version(bundle)
    database = configured_database()
    run_id: str | None = None
    if database is not None:
        try:
            verify_database(database)
            run_id = database.start_run(current, version)
        except Exception as exc:
            if database_sync_required():
                raise
            print(f"WARNING: database sync disabled for this run: {exc}")
            database = None

    observation_count = 0
    prediction_count = 0
    try:
        observations = read_observations_file(observations_file)
        scoring_observations = filter_observations_for_locations(
            observations,
            locations,
        )
        current_rows = scoring_observations[
            scoring_observations["timestamp"] == current
        ]
        observation_count = len(current_rows)
        if observation_count != len(locations):
            predictions = read_predictions_file(predictions_file)
            if database is not None:
                sync_database_window(
                    database,
                    all_locations,
                    bundle,
                    observations,
                    predictions,
                    current,
                )
                database.finish_run(
                    run_id,
                    "waiting_for_history",
                    observation_count,
                    0,
                )
            print(
                f"Prediction not ready: {observation_count}/{len(locations)} "
                f"current observations are available for {current}."
            )
            return False

        _, target_weather = fetch_weather_hours(current)
        inference = build_inference(
            scoring_observations,
            current,
            target_weather,
            bundle,
        )
        if inference is None:
            predictions = read_predictions_file(predictions_file)
            if database is not None:
                sync_database_window(
                    database,
                    all_locations,
                    bundle,
                    observations,
                    predictions,
                    current,
                )
                database.finish_run(
                    run_id,
                    "waiting_for_history",
                    observation_count,
                    0,
                )
            available_hours = scoring_observations["timestamp"].nunique()
            print(
                f"Prediction not ready: {available_hours}/{REQUIRED_HISTORY_HOURS} "
                "distinct hourly snapshots are available. "
                "Continue collecting once per hour."
            )
            return False

        target = current + pd.Timedelta(hours=1)
        output_file = predictions_dir / (
            f"traffic_aqi_live_forecast_{target:%Y-%m-%d_%H00}.csv"
        )
        result = predict(inference, bundle, output_file, version)
        prediction_count = len(result)
        predictions = upsert_predictions(result, predictions_file)
        print(
            f"Saved {prediction_count:,} live forecasts from existing observations "
            f"to: {output_file}"
        )

        if database is not None:
            synced_observations, synced_predictions, _ = sync_database_window(
                database,
                all_locations,
                bundle,
                observations,
                predictions,
                current,
            )
            database.finish_run(
                run_id,
                "success",
                observation_count,
                prediction_count,
            )
            print(
                f"Database sync complete: observations={synced_observations:,}; "
                f"predictions={synced_predictions:,}"
            )
        return True
    except Exception as exc:
        if database is not None and run_id is not None:
            try:
                database.finish_run(
                    run_id,
                    "failed",
                    observation_count,
                    prediction_count,
                    str(exc),
                )
            except Exception as finish_error:
                print(
                    f"WARNING: could not update failed collector run: {finish_error}",
                    file=sys.stderr,
                )
        raise


def doctor(timestamp: str | None, key_file: Path | None) -> None:
    current = local_hour(timestamp)
    locations = load_locations()
    supported_locations = locations[
        ~locations["location_key"].isin(TOMTOM_UNSUPPORTED_LOCATIONS)
    ].copy()
    bundle = joblib.load(MODEL_FILE)
    current_weather, target_weather = fetch_weather_hours(current)
    sample_aqi = fetch_aqi(supported_locations.iloc[0], current)
    api_keys = load_tomtom_keys(key_file, required=False)
    sample_traffic = (
        fetch_traffic_with_keys(supported_locations.iloc[0], api_keys)
        if api_keys
        else None
    )
    has_key = bool(api_keys)
    database = configured_database()
    database_status = (
        {"configured": True, **verify_database(database)}
        if database is not None
        else {"configured": False}
    )
    print(
        json.dumps(
            {
                "status": "ok" if has_key else "tomtom_key_missing",
                "timestamp": str(current),
                "target_timestamp": str(current + pd.Timedelta(hours=1)),
                "locations": len(locations),
                "tomtom_supported_locations": len(supported_locations),
                "tomtom_excluded_locations": sorted(TOMTOM_UNSUPPORTED_LOCATIONS),
                "model_targets": list(bundle["models"]),
                "model_features": len(bundle["feature_columns"]),
                "weather_current": current_weather,
                "weather_target": target_weather,
                "sample_aqi": sample_aqi,
                "sample_traffic": sample_traffic,
                "tomtom_api_key_configured": has_key,
                "tomtom_key_count": len(api_keys),
                "database": database_status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def run(
    timestamp: str | None,
    observations_file: Path,
    predictions_dir: Path,
    predictions_file: Path,
    key_file: Path | None,
) -> None:
    api_keys = load_tomtom_keys(key_file, required=True)
    current = local_hour(timestamp)
    all_locations = load_locations()
    locations = all_locations[
        ~all_locations["location_key"].isin(TOMTOM_UNSUPPORTED_LOCATIONS)
    ].reset_index(drop=True)
    bundle = joblib.load(MODEL_FILE)
    version = model_version(bundle)
    database = configured_database()
    run_id: str | None = None
    if database is not None:
        try:
            verify_database(database)
            run_id = database.start_run(current, version)
        except Exception as exc:
            if database_sync_required():
                raise
            print(f"WARNING: database sync disabled for this run: {exc}")
            database = None

    observation_count = 0
    prediction_count = 0
    try:
        rows, target_weather = collect_rows(locations, current, api_keys)
        observations = upsert_observations(rows, observations_file)
        scoring_observations = filter_observations_for_locations(observations, locations)
        observation_count = len(rows)
        print(f"Stored {observation_count:,} live observations for {current}")

        inference = build_inference(scoring_observations, current, target_weather, bundle)
        if inference is None:
            predictions = read_predictions_file(predictions_file)
            if database is not None:
                sync_database_window(
                    database,
                    all_locations,
                    bundle,
                    observations,
                    predictions,
                    current,
                )
                database.finish_run(
                    run_id,
                    "waiting_for_history",
                    observation_count,
                    0,
                )
            available_hours = scoring_observations["timestamp"].nunique()
            print(
                f"Prediction not ready: {available_hours}/{REQUIRED_HISTORY_HOURS} "
                "distinct hourly snapshots are available. "
                "Continue collecting once per hour."
            )
            return

        target = current + pd.Timedelta(hours=1)
        output_file = predictions_dir / (
            f"traffic_aqi_live_forecast_{target:%Y-%m-%d_%H00}.csv"
        )
        result = predict(inference, bundle, output_file, version)
        prediction_count = len(result)
        predictions = upsert_predictions(result, predictions_file)
        print(f"Saved {prediction_count:,} live forecasts to: {output_file}")

        if database is not None:
            synced_observations, synced_predictions, _ = sync_database_window(
                database,
                all_locations,
                bundle,
                observations,
                predictions,
                current,
            )
            database.finish_run(
                run_id,
                "success",
                observation_count,
                prediction_count,
            )
            print(
                f"Database sync complete: observations={synced_observations:,}; "
                f"predictions={synced_predictions:,}"
            )
    except Exception as exc:
        if database is not None and run_id is not None:
            try:
                database.finish_run(
                    run_id,
                    "failed",
                    observation_count,
                    prediction_count,
                    str(exc),
                )
            except Exception as finish_error:
                print(
                    f"WARNING: could not update failed collector run: {finish_error}",
                    file=sys.stderr,
                )
        raise


def acquire_lock(lock_file: Path) -> None:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            lock_file,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError:
        owner = lock_file.read_text(encoding="utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Live collector is already locked by process {owner or 'unknown'}. "
            f"If no collector is running, remove {lock_file}."
        ) from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))


def sleep_until(target: datetime) -> None:
    while True:
        remaining = (target - datetime.now(TIMEZONE)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60))


def next_scheduled_time(minute: int) -> datetime:
    now = datetime.now(TIMEZONE)
    target = now.replace(minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(hours=1)
    return target


def run_forever(
    key_file: Path | None,
    observations_file: Path,
    predictions_dir: Path,
    predictions_file: Path,
    lock_file: Path,
    minute: int,
    run_now: bool,
    max_retries: int,
    retry_delay_seconds: int,
    log_file: Path | None,
) -> None:
    log_stream = None
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_stream = log_file.open("a", encoding="utf-8", buffering=1)
        sys.stdout = log_stream
        sys.stderr = log_stream
    if not 0 <= minute <= 59:
        raise ValueError("minute must be between 0 and 59")
    if max_retries < 1:
        raise ValueError("max-retries must be at least 1")
    load_tomtom_keys(key_file, required=True)
    acquire_lock(lock_file)
    print(
        f"Live collector started with PID {os.getpid()}; "
        f"scheduled at minute {minute:02d} every hour",
        flush=True,
    )
    try:
        should_run = run_now
        while True:
            if not should_run:
                scheduled = next_scheduled_time(minute)
                print(f"Next collection: {scheduled.isoformat()}", flush=True)
                sleep_until(scheduled)
            should_run = False

            for attempt in range(1, max_retries + 1):
                try:
                    print(
                        f"Collection attempt {attempt}/{max_retries} at "
                        f"{datetime.now(TIMEZONE).isoformat()}",
                        flush=True,
                    )
                    run(
                        None,
                        observations_file,
                        predictions_dir,
                        predictions_file,
                        key_file,
                    )
                    break
                except Exception as exc:
                    print(
                        f"Collection attempt {attempt} failed: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    if attempt < max_retries:
                        time.sleep(retry_delay_seconds)
            else:
                print(
                    "All collection attempts failed; waiting for the next hour.",
                    file=sys.stderr,
                    flush=True,
                )
    except KeyboardInterrupt:
        print("Live collector stopped by user.", flush=True)
    finally:
        lock_file.unlink(missing_ok=True)
        if log_stream is not None:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_stream.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect live APIs and forecast traffic and AQI one hour ahead"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--timestamp")
    doctor_parser.add_argument("--tomtom-key-file", type=Path)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--timestamp")
    run_parser.add_argument("--tomtom-key-file", type=Path)
    run_parser.add_argument(
        "--observations-file",
        type=Path,
        default=DEFAULT_OBSERVATIONS_FILE,
    )
    run_parser.add_argument(
        "--predictions-dir",
        type=Path,
        default=DEFAULT_PREDICTIONS_DIR,
    )
    run_parser.add_argument(
        "--predictions-file",
        type=Path,
        default=DEFAULT_PREDICTIONS_FILE,
    )

    forever_parser = subparsers.add_parser("run-forever")
    forever_parser.add_argument("--tomtom-key-file", type=Path)
    forever_parser.add_argument(
        "--observations-file",
        type=Path,
        default=DEFAULT_OBSERVATIONS_FILE,
    )
    forever_parser.add_argument(
        "--predictions-dir",
        type=Path,
        default=DEFAULT_PREDICTIONS_DIR,
    )
    forever_parser.add_argument(
        "--predictions-file",
        type=Path,
        default=DEFAULT_PREDICTIONS_FILE,
    )
    forever_parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    forever_parser.add_argument("--minute", type=int, default=5)
    forever_parser.add_argument("--run-now", action="store_true")
    forever_parser.add_argument("--max-retries", type=int, default=3)
    forever_parser.add_argument("--retry-delay-seconds", type=int, default=120)
    forever_parser.add_argument("--log-file", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        if args.command == "doctor":
            key_file = args.tomtom_key_file.resolve() if args.tomtom_key_file else None
            doctor(args.timestamp, key_file)
        elif args.command == "run":
            key_file = args.tomtom_key_file.resolve() if args.tomtom_key_file else None
            run(
                args.timestamp,
                args.observations_file.resolve(),
                args.predictions_dir.resolve(),
                args.predictions_file.resolve(),
                key_file,
            )
        else:
            key_file = args.tomtom_key_file.resolve() if args.tomtom_key_file else None
            run_forever(
                key_file,
                args.observations_file.resolve(),
                args.predictions_dir.resolve(),
                args.predictions_file.resolve(),
                args.lock_file.resolve(),
                args.minute,
                args.run_now,
                args.max_retries,
                args.retry_delay_seconds,
                args.log_file.resolve() if args.log_file else None,
            )
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
