"""Backfill live hourly predictions from observations already stored in TiDB.

Muc luc:
1. Tim cac gio observation da co trong TiDB nhung chua co prediction.
2. Tuy chon bu observation gap khi GitHub Actions bi skip gio.
3. Hydrate observation window can thiet de tao feature lag/rolling.
4. Du doan bang model hourly va upsert vao `live_hourly_predictions`.
5. Export lai `web/data/dashboard.json` de GitHub Pages co timeline moi.

Script nay khong goi TomTom cho qua khu. Neu gio target khong co weather row
trong observation, script dung weather cua gio current lam fallback. Cac
observation duoc bu gap co source `gap_fill_from_nearest_live_history` de phan
biet voi du lieu live thu that.
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
    LOCATION_CONTEXT_COLUMNS,
    MODEL_FILE,
    REQUIRED_HISTORY_HOURS,
    TIME_SERIES_COLUMNS,
    TOMTOM_UNSUPPORTED_LOCATIONS,
    TIMEZONE,
    WEATHER_COLUMNS,
    build_inference,
    clip_predictions,
    filter_observations_for_locations,
    load_locations,
)
from web.export_web_data import DEFAULT_OUTPUT, export_web_data  # noqa: E402

GAP_FILL_SOURCE = "gap_fill_from_nearest_live_history"
SOURCE_COLUMNS = ["traffic_source", "aqi_source", "weather_source"]

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


def fetch_observation_counts(
    database: LiveDatabase,
    start_current: pd.Timestamp,
    end_current: pd.Timestamp,
) -> dict[pd.Timestamp, int]:
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT o.observed_at, COUNT(DISTINCT o.location_key) AS location_count
                FROM live_hourly_observations o
                JOIN model_locations l ON l.location_key = o.location_key
                WHERE l.is_live_supported = 1
                  AND o.observed_at >= %s
                  AND o.observed_at <= %s
                GROUP BY o.observed_at
                ORDER BY o.observed_at
                """,
                (start_current.to_pydatetime(), end_current.to_pydatetime()),
            )
            return {
                pd.Timestamp(row["observed_at"]): int(row["location_count"])
                for row in cursor.fetchall()
            }
    finally:
        connection.close()


def build_gap_filled_observation_rows(
    observations: pd.DataFrame,
    missing_hours: list[pd.Timestamp],
    start_current: pd.Timestamp,
    end_current: pd.Timestamp,
) -> pd.DataFrame:
    if observations.empty or not missing_hours:
        return pd.DataFrame()

    frame = observations.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    grid_start = min(frame["timestamp"].min(), start_current)
    grid_end = max(frame["timestamp"].max(), end_current)
    hours = pd.date_range(grid_start, grid_end, freq="h")
    missing = set(pd.Timestamp(hour) for hour in missing_hours)
    existing_pairs = set(
        zip(frame["timestamp"], frame["location_key"].astype(str))
    )
    fill_columns = [
        column
        for column in [*LOCATION_CONTEXT_COLUMNS, *TIME_SERIES_COLUMNS]
        if column in frame.columns
    ]
    now = datetime.now(TIMEZONE).isoformat()
    groups: list[pd.DataFrame] = []
    for location_key, group in frame.groupby("location_key", sort=False):
        location_key = str(location_key)
        filled = (
            group.sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
            .set_index("timestamp")
            .reindex(hours)
        )
        filled["timestamp"] = filled.index
        filled["location_key"] = location_key
        filled[fill_columns] = filled[fill_columns].ffill().bfill().infer_objects()
        filled["collection_time"] = now
        for column in SOURCE_COLUMNS:
            filled[column] = GAP_FILL_SOURCE
        filled = filled.reset_index(drop=True)
        rows = filled[filled["timestamp"].isin(missing)].copy()
        rows = rows[
            [
                (row["timestamp"], str(row["location_key"])) not in existing_pairs
                for row in rows.to_dict("records")
            ]
        ]
        groups.append(rows)

    if not groups:
        return pd.DataFrame()
    output = pd.concat(groups, ignore_index=True)
    required = ["timestamp", "collection_time", "location_key", *TIME_SERIES_COLUMNS]
    return output.dropna(subset=[column for column in required if column in output])


def fill_missing_observation_hours(
    database: LiveDatabase,
    locations: pd.DataFrame,
    start_current: pd.Timestamp,
    end_current: pd.Timestamp,
    dry_run: bool,
) -> int:
    required_locations = len(locations)
    counts = fetch_observation_counts(database, start_current, end_current)
    all_hours = list(pd.date_range(start_current, end_current, freq="h"))
    missing_hours = [
        pd.Timestamp(hour)
        for hour in all_hours
        if counts.get(pd.Timestamp(hour), 0) < required_locations
    ]
    if not missing_hours:
        print("No missing observation hours found.")
        return 0

    hydrate_start = start_current - pd.Timedelta(hours=REQUIRED_HISTORY_HOURS)
    hydrate_end = end_current + pd.Timedelta(hours=REQUIRED_HISTORY_HOURS)
    observations = fetch_observations(database, hydrate_start, hydrate_end)
    observations = filter_observations_for_locations(observations, locations)
    synthetic = build_gap_filled_observation_rows(
        observations,
        missing_hours,
        start_current,
        end_current,
    )
    if synthetic.empty:
        print("No observation gap-fill rows could be generated.")
        return 0

    if dry_run:
        print(
            f"Dry run: would gap-fill {len(synthetic):,} observation rows "
            f"for {synthetic['timestamp'].nunique()} hours."
        )
        return int(len(synthetic))

    inserted = database.upsert_observations(synthetic)
    print(
        f"Gap-filled {inserted:,} observation rows "
        f"for {synthetic['timestamp'].nunique()} hours."
    )
    return inserted


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
    fill_observation_gaps: bool = False,
    export_json: bool = True,
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

    if fill_observation_gaps:
        end_current = (
            end_target - pd.Timedelta(hours=1)
            if end_target is not None
            else pd.Timestamp(datetime.now(TIMEZONE).replace(tzinfo=None)).floor("h")
        )
        start_current = (
            start_target - pd.Timedelta(hours=1)
            if start_target is not None
            else end_current - pd.Timedelta(hours=167)
        )
        fill_missing_observation_hours(
            database,
            locations,
            start_current,
            end_current,
            dry_run,
        )

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
        if export_json:
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
    parser.add_argument(
        "--fill-observation-gaps",
        action="store_true",
        help="Fill missing observation hours from nearest stored live history first.",
    )
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Do not rewrite web/data/dashboard.json after backfill.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    backfill_predictions(
        parse_timestamp(args.start_target),
        parse_timestamp(args.end_target),
        args.overwrite,
        args.dry_run,
        args.fill_observation_gaps,
        not args.skip_export,
    )


if __name__ == "__main__":
    main()
