"""Utility chung cho viec inspect/transform/import du lieu TiDB.

Muc luc:
1. Quet file du lieu trong project va tinh hash/metadata.
2. De xuat bang TiDB phu hop cho tung CSV/JSON/artifact.
3. Chuan hoa row payload cho raw staging.
4. Dung chung bo cot typed table cua observations, predictions va locations.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SCAN_ROOTS = [
    ROOT_DIR / "data" / "raw",
    ROOT_DIR / "data" / "processed",
    ROOT_DIR / "data" / "live",
    ROOT_DIR / "outputs",
    ROOT_DIR / "src",
    ROOT_DIR / "models",
]

OBSERVATION_DB_COLUMNS = [
    "location_key",
    "observed_at",
    "collected_at",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "cloud_cover",
    "currentspeed",
    "freeflowspeed",
    "congestion_ratio",
    "traffic_density",
    "us_aqi",
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "traffic_source",
    "aqi_source",
    "weather_source",
]

PREDICTION_DB_COLUMNS = [
    "location_key",
    "target_at",
    "model_version",
    "generated_at",
    "predicted_currentspeed",
    "predicted_traffic_density",
    "predicted_us_aqi",
]

MODEL_LOCATION_DB_COLUMNS = [
    "location_key",
    "province_key",
    "district_key",
    "display_name",
    "lat",
    "lon",
    "api_lat",
    "api_lon",
    "estimated_vehicles",
    "area_km2",
    "population",
    "density_person_km2",
    "green_area_m2",
    "green_per_capita_m2",
    "is_live_supported",
]


@dataclass(frozen=True)
class ImportRecommendation:
    target_table: str
    transform: str
    reason: str


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def iter_source_files(
    roots: Iterable[Path] = DEFAULT_SCAN_ROOTS,
    suffixes: tuple[str, ...] = (".csv", ".json", ".joblib", ".pkl", ".xlsx", ".xls"),
) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in suffixes:
                if "data/tidb_import/" in relative_path(path):
                    continue
                yield path


def read_csv_header_sample(path: Path) -> tuple[list[str], list[str]]:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as stream:
                reader = csv.reader(stream)
                header = next(reader, [])
                sample = next(reader, [])
                return header, sample
        except UnicodeDecodeError:
            continue
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        reader = csv.reader(stream)
        return next(reader, []), next(reader, [])


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def source_group(path: Path) -> str:
    rel = relative_path(path)
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "data":
        return "/".join(parts[:3])
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def _has(columns: set[str], *required: str) -> bool:
    return set(required).issubset(columns)


def recommend_csv_import(path: Path, columns: Iterable[str]) -> ImportRecommendation:
    rel = relative_path(path)
    lowered = {column.strip().lower() for column in columns}

    if rel == "data/live/hourly_observations.csv":
        return ImportRecommendation(
            "live_hourly_observations",
            "direct_or_transform_names",
            "Live collector observations already contain the required hourly features.",
        )

    if rel == "data/live/hourly_predictions.csv" or rel.startswith(
        "data/live/predictions/"
    ):
        return ImportRecommendation(
            "live_hourly_predictions",
            "add_location_key_model_version_generated_at_if_missing",
            "Live forecast output maps to the prediction table after normalizing names.",
        )

    if _has(
        lowered,
        "target_timestamp",
        "predicted_currentspeed",
        "predicted_traffic_density",
        "predicted_us_aqi",
    ):
        is_evaluation_with_actuals = bool(
            lowered
            & {
                "actual_us_aqi",
                "actual_aqi_category",
                "target_currentspeed",
                "target_traffic_density",
                "target_us_aqi",
                "error",
                "absolute_error",
                "squared_error",
            }
        )
        if not _has(
            lowered,
            "target_currentspeed",
            "target_traffic_density",
            "target_us_aqi",
        ) and not is_evaluation_with_actuals and (
            rel.startswith("data/processed/model_predictions/")
            or (
                rel.startswith("data/processed/model_evaluation/")
                and "forecast" in path.stem
            )
        ):
            return ImportRecommendation(
                "live_hourly_predictions",
                "add_location_key_model_version_generated_at",
                "Processed forecast CSV has predicted targets without actual holdout labels.",
            )
        return ImportRecommendation(
            "raw_csv_import_rows",
            "raw_json_payload",
            "Holdout/test prediction CSV contains actual labels or evaluation-only context.",
        )

    if (
        path.name.startswith("locations_")
        and _has(lowered, "province_slug", "location_name", "lat", "lon")
    ):
        return ImportRecommendation(
            "model_locations",
            "derive_from_project_location_loader",
            "Location manifests are inputs for model_locations, but static fields come from joined history.",
        )

    if rel.startswith("data/raw/"):
        return ImportRecommendation(
            "raw_csv_import_rows",
            "raw_json_payload",
            "Raw source CSV is preserved in staging; joined historical observations are built by transform script.",
        )

    if rel.startswith("data/processed/model_features/"):
        return ImportRecommendation(
            "raw_csv_import_rows",
            "raw_json_payload",
            "Clean model feature CSVs contribute to historical observations and should also be retained raw.",
        )

    if rel.startswith("models/"):
        return ImportRecommendation(
            "raw_csv_import_rows",
            "raw_json_payload",
            "Model metrics, feature importance, and holdout CSVs are lineage/evaluation data.",
        )

    return ImportRecommendation(
        "raw_csv_import_rows",
        "raw_json_payload",
        "No typed TiDB table matches this CSV without losing columns.",
    )


def recommend_data_file(path: Path) -> ImportRecommendation:
    rel = relative_path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        header, _ = read_csv_header_sample(path)
        return recommend_csv_import(path, header)
    if suffix == ".json" and rel.startswith("models/") and "metadata" in path.name:
        return ImportRecommendation(
            "model_registry",
            "metadata_json_to_registry",
            "Model metadata JSON can populate registry fields and metadata_json.",
        )
    if suffix == ".json":
        return ImportRecommendation(
            "raw_csv_import_rows",
            "raw_json_payload",
            "Dataset metadata JSON is stored as a single raw payload row.",
        )
    if suffix in {".joblib", ".pkl"} and rel.startswith("models/"):
        return ImportRecommendation(
            "model_registry",
            "artifact_path_reference",
            "Model artifacts are referenced by path; the binary is not stored in TiDB.",
        )
    if suffix in {".xlsx", ".xls"}:
        return ImportRecommendation(
            "raw_csv_import_rows",
            "convert_to_csv_first",
            "Spreadsheet import needs an explicit sheet conversion before loading raw rows.",
        )
    return ImportRecommendation(
        "not_imported",
        "manual_review",
        "This file type is not handled by the import scripts.",
    )


def json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def dumps_json(value: object) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, allow_nan=False, default=str)
