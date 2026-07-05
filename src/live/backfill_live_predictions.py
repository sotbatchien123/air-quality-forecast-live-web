"""Backfill live hourly predictions from observations already stored in TiDB.

Muc luc:
1. Tim cac gio observation da co trong TiDB nhung chua co prediction.
2. Hydrate observation window can thiet de tao feature lag/rolling.
3. Du doan bang model hourly va upsert vao `live_hourly_predictions`.
4. Export lai `web/data/dashboard.json` de GitHub Pages co timeline moi.

Script nay khong goi TomTom cho qua khu. Neu gio target khong co weather row
trong observation, script dung weather cua gio current lam fallback.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
MODELS_SRC_DIR = SRC_DIR / "models"
for source_dir in (SRC_DIR, MODELS_SRC_DIR):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))

from database.live_database import DatabaseConfigError, LiveDatabase, model_version  # noqa: E402
from live.live_hourly_predictor import (  # noqa: E402
    MODEL_FILE,
    REQUIRED_HISTORY_HOURS,
    TOMTOM_UNSUPPORTED_LOCATIONS,
    TIMEZONE,
    WEATHER_COLUMNS,
    build_inference,
    clip_predictions,
    filter_observations_for_locations,
    load_locations,
)
from web.export_web_data import DEFAULT_OUTPUT, export_web_data  # noqa: E402


OBSERVATION_WINDOW_SELECT = """
    SELECT
        o.observed_at AS timestamp,
        o.collected_at AS collection_time,
        o.location_key,
        l.province_key,
        l.district_key,
        l.display_name AS district,
        l.lat,
        l.lon,
        l.estimated_vehicles,
        l.area_km2,
        l.population,
        l.density_person_km2,
        l.green_area_m2,
        l.green_per_capita_m2,
        o.temperature_2m,
        o.relative_humidity_2m,
        o.precipitation,
        o.wind_speed_10m,
        o.cloud_cover,
        o.currentspeed,
        o.freeflowspeed,
        o.congestion_ratio,
        o.traffic_density,
        o.us_aqi,
        o.pm10,
        o.pm2_5,
        o.carbon_monoxide,
        o.nitrogen_dioxide,
        o.sulphur_dioxide,
        o.ozone,
        o.traffic_source,
        o.aqi_source,
        o.weather_source
    FROM live_hourly_observations o
    JOIN model_locations l ON l.location_key = o.location_key
    WHERE o.observed_at >= %s
      AND o.observed_at <= %s
    ORDER BY o.location_key, o.observed_at
"""


def parse_timestamp(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    return pd.Timestamp(value).floor("h")


def fetch_existing_prediction_targets(database: LiveDatabase) -> set[pd.Timestamp]:
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DISTINCT target_at FROM live_hourly_predictions")
            return {pd.Timestamp(row["target_at"]) for row in cursor.fetchall()}
    finally:
        connection.close()


def fetch_full_observation_hours(
    database: LiveDatabase,
    required_locations: int,
    start_current: pd.Timestamp | None,
    end_current: pd.Timestamp | None,
) -> list[pd.Timestamp]:
    filters = ["l.is_live_supported = 1"]
    params: list[Any] = []
    if start_current is not None:
        filters.append("o.observed_at >= %s")
        params.append(start_current.to_pydatetime())
    if end_current is not None:
        filters.append("o.observed_at <= %s")
        params.append(end_current.to_pydatetime())
    where_clause = " AND ".join(filters)
    sql = f"""
        SELECT o.observed_at, COUNT(DISTINCT o.location_key) AS location_count
        FROM live_hourly_observations o
        JOIN model_locations l ON l.location_key = o.location_key
        WHERE {where_clause}
        GROUP BY o.observed_at
        HAVING location_count >= %s
        ORDER BY o.observed_at
    """
    params.append(required_locations)
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return [pd.Timestamp(row["observed_at"]) for row in cursor.fetchall()]
    finally:
        connection.close()


def fetch_observations(
    database: LiveDatabase,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                OBSERVATION_WINDOW_SELECT,
                (start.to_pydatetime(), end.to_pydatetime()),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    return frame


def target_weather_from_observations(
    observations: pd.DataFrame,
    current: pd.Timestamp,
) -> dict[str, float]:
    target = current + pd.Timedelta(hours=1)
    for timestamp in (target, current):
        rows = observations[observations["timestamp"] == timestamp]
        if not rows.empty:
            return {
                column: float(pd.to_numeric(rows[column], errors="raise").median())
                for column in WEATHER_COLUMNS
            }
    raise ValueError(f"No weather values are available for {current}")


def prediction_frame(
    inference: pd.DataFrame,
    bundle: dict[str, Any],
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
    return result.sort_values(["target_timestamp", "province_key", "district_key"])


def candidate_current_hours(
    database: LiveDatabase,
    required_locations: int,
    start_target: pd.Timestamp | None,
    end_target: pd.Timestamp | None,
    overwrite: bool,
) -> list[pd.Timestamp]:
    start_current = start_target - pd.Timedelta(hours=1) if start_target is not None else None
    end_current = end_target - pd.Timedelta(hours=1) if end_target is not None else None
    observed_hours = fetch_full_observation_hours(
        database,
        required_locations,
        start_current,
        end_current,
    )
    existing_targets = fetch_existing_prediction_targets(database)
    candidates: list[pd.Timestamp] = []
    for current in observed_hours:
        target = current + pd.Timedelta(hours=1)
        if start_target is not None and target < start_target:
            continue
        if end_target is not None and target > end_target:
            continue
        if overwrite or target not in existing_targets:
            candidates.append(current)
    return candidates


def backfill_predictions(
    start_target: pd.Timestamp | None,
    end_target: pd.Timestamp | None,
    overwrite: bool,
    dry_run: bool,
) -> int:
    try:
        database = LiveDatabase.from_environment(required=True)
    except DatabaseConfigError as exc:
        raise SystemExit(f"ERROR: {exc}") from None
    assert database is not None

    all_locations = load_locations()
    all_locations["is_live_supported"] = ~all_locations["location_key"].isin(
        TOMTOM_UNSUPPORTED_LOCATIONS
    )
    locations = all_locations[all_locations["is_live_supported"]].reset_index(drop=True)
    required_locations = len(locations)

    candidates = candidate_current_hours(
        database,
        required_locations,
        start_target,
        end_target,
        overwrite,
    )
    if not candidates:
        print("No missing prediction hours found.")
        return 0

    hydrate_start = min(candidates) - pd.Timedelta(hours=REQUIRED_HISTORY_HOURS)
    hydrate_end = max(candidates) + pd.Timedelta(hours=1)
    observations = fetch_observations(database, hydrate_start, hydrate_end)
    observations = filter_observations_for_locations(observations, locations)

    bundle = joblib.load(MODEL_FILE)
    version = database.register_model(bundle, MODEL_FILE)
    database.upsert_locations(all_locations)

    output_frames: list[pd.DataFrame] = []
    skipped: list[str] = []
    for current in candidates:
        try:
            target_weather = target_weather_from_observations(observations, current)
            inference = build_inference(observations, current, target_weather, bundle)
            if inference is None:
                skipped.append(str(current))
                continue
            output_frames.append(prediction_frame(inference, bundle, version))
        except Exception as exc:
            skipped.append(f"{current} ({exc})")

    if not output_frames:
        print("No predictions were generated.")
        if skipped:
            print("Skipped hours:")
            for item in skipped:
                print(f"- {item}")
        return 0

    predictions = pd.concat(output_frames, ignore_index=True)
    if dry_run:
        print(
            f"Dry run: would upsert {len(predictions):,} rows "
            f"for {predictions['target_timestamp'].nunique()} target hours."
        )
    else:
        inserted = database.upsert_predictions(predictions, version)
        print(
            f"Backfilled {inserted:,} prediction rows "
            f"for {predictions['target_timestamp'].nunique()} target hours."
        )
        export_web_data(DEFAULT_OUTPUT)

    if skipped:
        print(f"Skipped {len(skipped)} current hours without usable features.")
        for item in skipped[:20]:
            print(f"- {item}")
        if len(skipped) > 20:
            print(f"... {len(skipped) - 20} more")
    return int(predictions["target_timestamp"].nunique())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill missing TiDB live predictions from stored observations"
    )
    parser.add_argument("--start-target", help="Inclusive target hour, local time")
    parser.add_argument("--end-target", help="Inclusive target hour, local time")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    backfill_predictions(
        parse_timestamp(args.start_target),
        parse_timestamp(args.end_target),
        args.overwrite,
        args.dry_run,
    )


if __name__ == "__main__":
    main()
