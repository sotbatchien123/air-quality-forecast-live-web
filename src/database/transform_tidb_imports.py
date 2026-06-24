"""Transform file project sang CSV dung schema import TiDB.

Muc luc:
1. Tao `data/tidb_import` lam thu muc trung gian.
2. Chuyen observations/predictions/location/model metadata sang cot typed.
3. Ghi manifest file import de `import_tidb_data.py` upsert vao TiDB.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
MODELS_SRC_DIR = SRC_DIR / "models"
for source_dir in (SRC_DIR, MODELS_SRC_DIR):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))

from database.tidb_import_utils import (  # noqa: E402
    MODEL_LOCATION_DB_COLUMNS,
    OBSERVATION_DB_COLUMNS,
    PREDICTION_DB_COLUMNS,
    dumps_json,
    read_csv_header_sample,
    recommend_csv_import,
    relative_path,
)
from live.live_hourly_predictor import (  # noqa: E402
    DEFAULT_OBSERVATIONS_FILE,
    DEFAULT_PREDICTIONS_FILE,
    TOMTOM_UNSUPPORTED_LOCATIONS,
    load_locations,
)
from next_day_traffic_aqi import load_joined_history  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "tidb_import"
PROCESSED_FORECAST_DIRS = [
    ROOT_DIR / "data" / "processed" / "model_predictions",
    ROOT_DIR / "data" / "processed" / "model_evaluation",
]
MODEL_METADATA_ROOT = ROOT_DIR / "models" / "next_day_traffic_aqi"
LOCAL_TIMEZONE = "Asia/Ho_Chi_Minh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform project CSV/model files into TiDB schema-shaped CSVs"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--include-history",
        action="store_true",
        help="Also build 2025 historical observations from joined training sources.",
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Do not include data/live hourly observations and predictions.",
    )
    parser.add_argument(
        "--skip-processed-forecasts",
        action="store_true",
        help="Do not include forecast CSV files under data/processed.",
    )
    return parser.parse_args()


def file_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(sep=" ")


def to_naive_timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(LOCAL_TIMEZONE).tz_localize(None)
    return timestamp


def write_frame(frame: pd.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return len(frame)


def build_model_locations() -> pd.DataFrame:
    locations = load_locations().copy()
    locations["display_name"] = locations["district"]
    locations["is_live_supported"] = ~locations["location_key"].isin(
        TOMTOM_UNSUPPORTED_LOCATIONS
    )
    return locations[MODEL_LOCATION_DB_COLUMNS].sort_values("location_key")


def normalize_observations(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = frame.rename(
        columns={"timestamp": "observed_at", "collection_time": "collected_at"}
    ).copy()
    missing = sorted(set(OBSERVATION_DB_COLUMNS) - set(renamed.columns))
    if missing:
        raise ValueError("Observation data is missing columns: " + ", ".join(missing))
    renamed["observed_at"] = renamed["observed_at"].map(to_naive_timestamp)
    renamed["collected_at"] = renamed["collected_at"].map(to_naive_timestamp)
    return renamed[OBSERVATION_DB_COLUMNS].sort_values(["location_key", "observed_at"])


def load_live_observations() -> pd.DataFrame:
    if not DEFAULT_OBSERVATIONS_FILE.is_file():
        return pd.DataFrame(columns=OBSERVATION_DB_COLUMNS)
    return normalize_observations(
        pd.read_csv(DEFAULT_OBSERVATIONS_FILE, encoding="utf-8-sig")
    )


def build_historical_observations(import_time: str) -> pd.DataFrame:
    history = load_joined_history().copy()
    history["collection_time"] = import_time
    history["traffic_source"] = "historical_csv_traffic"
    history["aqi_source"] = "open_meteo_cams_global_historical"
    history["weather_source"] = "historical_csv_weather"
    return normalize_observations(history)


def default_prediction_version(path: Path) -> str:
    stem = path.stem.replace("traffic_aqi_forecast_", "")
    version = f"csv_forecast@{stem}"
    return version[:191]


def normalize_predictions(path: Path, default_version: str | None = None) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    renamed = frame.rename(
        columns={"target_timestamp": "target_at", "timestamp": "target_at"}
    ).copy()
    if "location_key" not in renamed:
        required = {"province_key", "district_key"}
        missing = required - set(renamed.columns)
        if missing:
            raise ValueError(
                f"Prediction file {path} cannot derive location_key; missing {missing}"
            )
        renamed["location_key"] = (
            renamed["province_key"].astype(str) + "__" + renamed["district_key"].astype(str)
        )
    if "model_version" not in renamed:
        renamed["model_version"] = default_version or default_prediction_version(path)
    if "generated_at" not in renamed:
        renamed["generated_at"] = file_timestamp(path)
    missing = sorted(set(PREDICTION_DB_COLUMNS) - set(renamed.columns))
    if missing:
        raise ValueError("Prediction data is missing columns: " + ", ".join(missing))
    renamed["target_at"] = renamed["target_at"].map(to_naive_timestamp)
    renamed["generated_at"] = renamed["generated_at"].map(to_naive_timestamp)
    return renamed[PREDICTION_DB_COLUMNS].sort_values(
        ["target_at", "location_key", "model_version"]
    )


def iter_processed_forecast_files() -> list[Path]:
    paths: list[Path] = []
    for directory in PROCESSED_FORECAST_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.csv")):
            header, _ = read_csv_header_sample(path)
            recommendation = recommend_csv_import(path, header)
            if recommendation.target_table == "live_hourly_predictions":
                paths.append(path)
    return paths


def build_predictions(include_live: bool, include_processed: bool) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if include_live and DEFAULT_PREDICTIONS_FILE.is_file():
        frames.append(normalize_predictions(DEFAULT_PREDICTIONS_FILE))
    if include_processed:
        for path in iter_processed_forecast_files():
            frames.append(normalize_predictions(path))
    if not frames:
        return pd.DataFrame(columns=PREDICTION_DB_COLUMNS)
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values("generated_at").drop_duplicates(
        ["location_key", "target_at", "model_version"],
        keep="last",
    )[PREDICTION_DB_COLUMNS].sort_values(["target_at", "location_key", "model_version"])


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def artifact_for_metadata(path: Path) -> Path:
    candidates = [
        path.with_name(path.name.replace("_metadata.json", "_full.joblib")),
        path.with_name(path.name.replace("_metadata.json", ".joblib")),
    ]
    if path.name == "metadata.json":
        candidates.append(path.with_name("model_bundle.joblib"))
    if path.name == "metadata_full.json":
        candidates.append(path.with_name("model_bundle_full.joblib"))
    if path.name == "weather_only_metadata.json":
        candidates.append(path.with_name("model_bundle_weather_only_full.joblib"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    bundles = sorted(path.parent.glob("*.joblib"))
    return bundles[0] if bundles else path


def registry_record_from_metadata(path: Path) -> dict[str, object]:
    metadata = load_json(path)
    variant = str(
        metadata.get("variant")
        or metadata.get("model_type")
        or path.stem.replace("_metadata", "")
    )
    algorithm = str(metadata.get("algorithm") or metadata.get("model_type") or "unknown")
    created = str(metadata.get("created_at_utc") or file_timestamp(path))
    feature_count = int(metadata.get("feature_count") or len(metadata.get("features", [])) or 0)
    horizon = int(metadata.get("forecast_horizon_hours") or (1 if "hourly" in variant else 24))
    artifact = artifact_for_metadata(path)
    return {
        "model_version": f"{variant}@{created}"[:191],
        "variant": variant,
        "algorithm": algorithm,
        "artifact_path": relative_path(artifact),
        "horizon_hours": horizon,
        "feature_count": feature_count,
        "training_target_start": metadata.get("training_target_start"),
        "training_target_end": metadata.get("training_target_end"),
        "metadata_json": dumps_json(metadata),
        "is_active": int(variant == "xgboost_multisource_hourly"),
    }


def build_model_registry() -> pd.DataFrame:
    records = [
        registry_record_from_metadata(path)
        for path in sorted(MODEL_METADATA_ROOT.rglob("*metadata*.json"))
    ]
    registry = pd.DataFrame(records)
    return registry.sort_values("is_active").drop_duplicates(
        "model_version",
        keep="last",
    ).sort_values(["is_active", "variant"], ascending=[False, True])


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, object]] = []

    locations = build_model_locations()
    count = write_frame(locations, output_dir / "model_locations.csv")
    manifest_rows.append(
        {"output_file": "model_locations.csv", "target_table": "model_locations", "rows": count}
    )

    registry = build_model_registry()
    count = write_frame(registry, output_dir / "model_registry.csv")
    manifest_rows.append(
        {"output_file": "model_registry.csv", "target_table": "model_registry", "rows": count}
    )

    observation_frames: list[pd.DataFrame] = []
    import_time = datetime.now().isoformat(sep=" ")
    if not args.skip_live:
        observation_frames.append(load_live_observations())
    if args.include_history:
        observation_frames.append(build_historical_observations(import_time))
    observations = (
        pd.concat(observation_frames, ignore_index=True)
        if observation_frames
        else pd.DataFrame(columns=OBSERVATION_DB_COLUMNS)
    )
    if not observations.empty:
        observations = observations.sort_values("collected_at").drop_duplicates(
            ["location_key", "observed_at"],
            keep="last",
        )
    count = write_frame(
        observations[OBSERVATION_DB_COLUMNS],
        output_dir / "live_hourly_observations.csv",
    )
    manifest_rows.append(
        {
            "output_file": "live_hourly_observations.csv",
            "target_table": "live_hourly_observations",
            "rows": count,
        }
    )

    predictions = build_predictions(
        include_live=not args.skip_live,
        include_processed=not args.skip_processed_forecasts,
    )
    count = write_frame(predictions, output_dir / "live_hourly_predictions.csv")
    manifest_rows.append(
        {
            "output_file": "live_hourly_predictions.csv",
            "target_table": "live_hourly_predictions",
            "rows": count,
        }
    )

    manifest = pd.DataFrame(manifest_rows)
    write_frame(manifest, output_dir / "manifest.csv")
    print(f"Wrote TiDB import files to: {output_dir}")
    print(manifest.to_string(index=False))


if __name__ == "__main__":
    main()
