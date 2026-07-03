"""Run one GitHub Actions hourly collection and export web data.

Muc luc:
1. Hydrate observation/prediction CSV tam thoi tu TiDB cho runner moi.
2. Chay live collector mot lan bang `live_hourly_predictor.run()`.
3. Export JSON dashboard cho GitHub Pages.

GitHub-hosted runner la moi truong tam thoi. Vi vay script nay khong dua vao
`data/live` da ton tai san; no doc lai history gan nhat tu TiDB truoc khi tao
feature lag/rolling cho model hourly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
MODELS_SRC_DIR = SRC_DIR / "models"
for source_dir in (SRC_DIR, MODELS_SRC_DIR):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))

from database.live_database import DatabaseConfigError, LiveDatabase  # noqa: E402
from live.live_hourly_predictor import (  # noqa: E402
    DEFAULT_OBSERVATIONS_FILE,
    DEFAULT_PREDICTIONS_DIR,
    DEFAULT_PREDICTIONS_FILE,
    TOMTOM_UNSUPPORTED_LOCATIONS,
    load_locations,
    local_hour,
    run,
)
from web.export_web_data import DEFAULT_OUTPUT, export_web_data  # noqa: E402


OBSERVATION_SELECT = """
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
    ORDER BY o.location_key, o.observed_at
"""

PREDICTION_SELECT = """
    SELECT
        p.target_at AS target_timestamp,
        p.location_key,
        l.province_key,
        l.district_key,
        l.display_name AS district,
        p.predicted_currentspeed,
        p.predicted_traffic_density,
        p.predicted_us_aqi,
        p.generated_at,
        p.model_version
    FROM live_hourly_predictions p
    JOIN model_locations l ON l.location_key = p.location_key
    WHERE p.target_at >= %s
    ORDER BY p.target_at, p.location_key
"""


def hydrate_table(
    database: LiveDatabase,
    sql: str,
    start: pd.Timestamp,
    output_file: Path,
) -> int:
    connection = database.connect()
    try:
        frame = pd.read_sql(sql, connection, params=(start.to_pydatetime(),))
    finally:
        connection.close()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        output_file.unlink(missing_ok=True)
        print(f"No rows to hydrate for {output_file}")
        return 0
    frame.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"Hydrated {len(frame):,} rows -> {output_file}")
    return len(frame)


def hydrate_live_files(
    database: LiveDatabase,
    timestamp: str | None,
    hours: int,
    observations_file: Path,
    predictions_file: Path,
) -> tuple[int, int]:
    current = local_hour(timestamp)
    start = current - pd.Timedelta(hours=hours)
    observation_count = hydrate_table(
        database,
        OBSERVATION_SELECT,
        start,
        observations_file,
    )
    prediction_count = hydrate_table(
        database,
        PREDICTION_SELECT,
        start,
        predictions_file,
    )
    return observation_count, prediction_count


def live_supported_location_count() -> int:
    locations = load_locations()
    supported = locations[
        ~locations["location_key"].isin(TOMTOM_UNSUPPORTED_LOCATIONS)
    ]
    return int(len(supported))


def has_current_hour_observations(
    observations_file: Path,
    current: pd.Timestamp,
    required_locations: int,
) -> bool:
    if not observations_file.is_file():
        return False
    frame = pd.read_csv(observations_file, encoding="utf-8-sig")
    required_columns = {"timestamp", "location_key"}
    if frame.empty or not required_columns.issubset(frame.columns):
        return False
    timestamps = pd.to_datetime(frame["timestamp"], errors="coerce")
    current_rows = frame[timestamps == current]
    location_count = current_rows["location_key"].astype(str).nunique()
    return location_count >= required_locations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run hourly GitHub Actions collection and export Pages data"
    )
    parser.add_argument("--timestamp")
    parser.add_argument("--hydrate-hours", type=int, default=36)
    parser.add_argument(
        "--observations-file",
        type=Path,
        default=DEFAULT_OBSERVATIONS_FILE,
    )
    parser.add_argument(
        "--predictions-dir",
        type=Path,
        default=DEFAULT_PREDICTIONS_DIR,
    )
    parser.add_argument(
        "--predictions-file",
        type=Path,
        default=DEFAULT_PREDICTIONS_FILE,
    )
    parser.add_argument("--web-output-file", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-collection", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        database = LiveDatabase.from_environment(required=True)
    except DatabaseConfigError as exc:
        raise SystemExit(f"ERROR: {exc}") from None
    assert database is not None

    hydrate_live_files(
        database,
        args.timestamp,
        args.hydrate_hours,
        args.observations_file.resolve(),
        args.predictions_file.resolve(),
    )

    should_collect = not args.skip_collection
    if should_collect:
        current = local_hour(args.timestamp)
        required_locations = live_supported_location_count()
        if has_current_hour_observations(
            args.observations_file.resolve(),
            current,
            required_locations,
        ):
            print(
                f"Current hour {current} already has "
                f"{required_locations} live observations; skip API collection."
            )
            should_collect = False

    if should_collect:
        try:
            run(
                args.timestamp,
                args.observations_file.resolve(),
                args.predictions_dir.resolve(),
                args.predictions_file.resolve(),
                None,
            )
        except Exception as exc:
            print(
                "WARNING: live collection failed; exporting latest TiDB data only: "
                f"{exc}",
                file=sys.stderr,
            )

    export_web_data(args.web_output_file.resolve())


if __name__ == "__main__":
    main()
