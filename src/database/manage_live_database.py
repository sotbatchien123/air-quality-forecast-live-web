"""Quan ly schema live TiDB cho project.

Muc luc:
1. Doc file SQL schema trong `data/setup_tables.sql`.
2. Ap dung migration/schema vao TiDB.
3. Kiem tra cac bang live va so dong hien co.
4. CLI cho migrate, check va summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
MODELS_SRC_DIR = SRC_DIR / "models"
for source_dir in (SRC_DIR, MODELS_SRC_DIR):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))

from database.live_database import (  # noqa: E402
    DEFAULT_ENV_FILE,
    DEFAULT_SCHEMA_FILE,
    DatabaseConfigError,
    LiveDatabase,
    model_version,
)
from live.live_hourly_predictor import (  # noqa: E402
    DEFAULT_OBSERVATIONS_FILE,
    DEFAULT_PREDICTIONS_DIR,
    MODEL_FILE,
    TOMTOM_UNSUPPORTED_LOCATIONS,
    load_locations,
)


def load_prediction_history(predictions_dir: Path, version: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(predictions_dir.glob("traffic_aqi_live_forecast_*.csv")):
        frame = pd.read_csv(path, encoding="utf-8-sig")
        frame["generated_at"] = pd.Timestamp(path.stat().st_mtime, unit="s")
        frame["model_version"] = version
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if "location_key" not in combined:
        combined["location_key"] = (
            combined["province_key"] + "__" + combined["district_key"]
        )
    combined["target_timestamp"] = pd.to_datetime(
        combined["target_timestamp"], errors="raise"
    )
    return combined.sort_values("generated_at").drop_duplicates(
        ["location_key", "target_timestamp", "model_version"],
        keep="last",
    )


def init_schema(database: LiveDatabase, schema_file: Path) -> None:
    count = database.initialize_schema(schema_file)
    print(f"Applied {count} schema statements from: {schema_file}")
    print(json.dumps(database.healthcheck(), ensure_ascii=False, indent=2, default=str))


def sync_live(
    database: LiveDatabase,
    observations_file: Path,
    predictions_dir: Path,
) -> None:
    bundle = joblib.load(MODEL_FILE)
    version = database.register_model(bundle, MODEL_FILE)

    locations = load_locations()
    locations["is_live_supported"] = ~locations["location_key"].isin(
        TOMTOM_UNSUPPORTED_LOCATIONS
    )
    location_count = database.upsert_locations(locations)

    observation_count = 0
    if observations_file.is_file():
        observations = pd.read_csv(observations_file, encoding="utf-8-sig")
        observation_count = database.upsert_observations(observations)

    predictions = load_prediction_history(predictions_dir, version)
    prediction_count = (
        database.upsert_predictions(predictions, version) if not predictions.empty else 0
    )
    print(
        f"Synced model={version}; locations={location_count}; "
        f"observations={observation_count}; predictions={prediction_count}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize and maintain the live hourly TiDB database"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-schema")
    init_parser.add_argument("--schema-file", type=Path, default=DEFAULT_SCHEMA_FILE)

    sync_parser = subparsers.add_parser("sync-live")
    sync_parser.add_argument(
        "--observations-file", type=Path, default=DEFAULT_OBSERVATIONS_FILE
    )
    sync_parser.add_argument(
        "--predictions-dir", type=Path, default=DEFAULT_PREDICTIONS_DIR
    )

    subparsers.add_parser("status")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        database = LiveDatabase.from_environment(
            required=True,
            env_file=args.env_file.resolve(),
        )
    except DatabaseConfigError as exc:
        raise SystemExit(
            f"ERROR: {exc}. Copy .env.example to .env and fill DB_* values."
        ) from None
    assert database is not None
    if args.command == "init-schema":
        init_schema(database, args.schema_file.resolve())
    elif args.command == "sync-live":
        sync_live(
            database,
            args.observations_file.resolve(),
            args.predictions_dir.resolve(),
        )
    else:
        print(json.dumps(database.status(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
