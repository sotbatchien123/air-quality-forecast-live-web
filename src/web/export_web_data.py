"""Export TiDB live data to static JSON for GitHub Pages.

Muc luc:
1. Ket noi TiDB bang bien moi truong/GitHub Secrets.
2. Doc prediction moi nhat, observation moi nhat va run gan nhat.
3. Tong hop KPI theo toan bo khu vuc va theo tinh/thanh.
4. Ghi `web/data/dashboard.json` de frontend tinh doc truc tiep.

Script nay chi chay o backend/Actions. Frontend khong ket noi truc tiep TiDB
nen khong lam lo DB password hay API key.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from database.live_database import DatabaseConfigError, LiveDatabase  # noqa: E402


DEFAULT_OUTPUT = ROOT_DIR / "web" / "data" / "dashboard.json"


def as_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, np.generic):
        return as_json_value(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    return value


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: as_json_value(value) for key, value in row.items()}


def aqi_category(value: Any) -> str:
    if value is None:
        return "Unknown"
    aqi = float(value)
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for sensitive groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very unhealthy"
    return "Hazardous"


def average(rows: list[dict[str, Any]], column: str) -> float | None:
    values = [float(row[column]) for row in rows if row.get(column) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def maximum(rows: list[dict[str, Any]], column: str) -> float | None:
    values = [float(row[column]) for row in rows if row.get(column) is not None]
    return round(max(values), 4) if values else None


def fetch_table_counts(cursor) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in [
        "model_locations",
        "model_registry",
        "live_hourly_observations",
        "live_hourly_predictions",
        "live_collector_runs",
    ]:
        cursor.execute(f"SELECT COUNT(*) AS row_count FROM {table}")
        counts[table] = int(cursor.fetchone()["row_count"])
    return counts


def fetch_latest_predictions(cursor) -> list[dict[str, Any]]:
    cursor.execute("SELECT MAX(target_at) AS target_at FROM live_hourly_predictions")
    latest = cursor.fetchone()["target_at"]
    if latest is None:
        return []
    cursor.execute(
        """
        SELECT
            p.location_key,
            p.target_at,
            p.model_version,
            p.generated_at,
            p.predicted_currentspeed,
            p.predicted_traffic_density,
            p.predicted_us_aqi,
            l.province_key,
            l.district_key,
            l.display_name,
            l.lat,
            l.lon,
            l.is_live_supported
        FROM live_hourly_predictions p
        JOIN model_locations l ON l.location_key = p.location_key
        JOIN (
            SELECT location_key, MAX(generated_at) AS generated_at
            FROM live_hourly_predictions
            WHERE target_at = %s
            GROUP BY location_key
        ) latest
          ON latest.location_key = p.location_key
         AND latest.generated_at = p.generated_at
        WHERE p.target_at = %s
        ORDER BY l.province_key, l.display_name
        """,
        (latest, latest),
    )
    rows = [clean_row(row) for row in cursor.fetchall()]
    for row in rows:
        row["aqi_category"] = aqi_category(row.get("predicted_us_aqi"))
    return rows


def fetch_latest_observations(cursor) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            o.location_key,
            o.observed_at,
            o.collected_at,
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
            o.weather_source,
            l.province_key,
            l.district_key,
            l.display_name,
            l.lat,
            l.lon,
            l.is_live_supported
        FROM live_hourly_observations o
        JOIN model_locations l ON l.location_key = o.location_key
        JOIN (
            SELECT location_key, MAX(observed_at) AS observed_at
            FROM live_hourly_observations
            GROUP BY location_key
        ) latest
          ON latest.location_key = o.location_key
         AND latest.observed_at = o.observed_at
        ORDER BY l.province_key, l.display_name
        """
    )
    rows = [clean_row(row) for row in cursor.fetchall()]
    for row in rows:
        row["aqi_category"] = aqi_category(row.get("us_aqi"))
    return rows


def fetch_runs(cursor, limit: int = 10) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            run_id,
            scheduled_at,
            started_at,
            finished_at,
            status,
            observations_count,
            predictions_count,
            model_version,
            error_message
        FROM live_collector_runs
        ORDER BY started_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return [clean_row(row) for row in cursor.fetchall()]


def fetch_models(cursor, limit: int = 5) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            model_version,
            variant,
            algorithm,
            artifact_path,
            horizon_hours,
            feature_count,
            training_target_start,
            training_target_end,
            is_active,
            registered_at
        FROM model_registry
        ORDER BY registered_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return [clean_row(row) for row in cursor.fetchall()]


def province_summary(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        groups[str(row.get("province_key", "unknown"))].append(row)
    output: list[dict[str, Any]] = []
    for province_key, rows in sorted(groups.items()):
        output.append(
            {
                "province_key": province_key,
                "location_count": len(rows),
                "avg_predicted_us_aqi": average(rows, "predicted_us_aqi"),
                "max_predicted_us_aqi": maximum(rows, "predicted_us_aqi"),
                "avg_predicted_currentspeed": average(rows, "predicted_currentspeed"),
                "avg_predicted_traffic_density": average(
                    rows,
                    "predicted_traffic_density",
                ),
            }
        )
    return output


def build_payload(database: LiveDatabase) -> dict[str, Any]:
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            predictions = fetch_latest_predictions(cursor)
            observations = fetch_latest_observations(cursor)
            runs = fetch_runs(cursor)
            models = fetch_models(cursor)
            counts = fetch_table_counts(cursor)
    finally:
        connection.close()

    category_counts = Counter(row["aqi_category"] for row in predictions)
    latest_prediction = predictions[0] if predictions else {}
    latest_observation = observations[0] if observations else {}
    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "status": "ready" if predictions else "waiting_for_predictions",
        "counts": counts,
        "latest_target_at": latest_prediction.get("target_at"),
        "latest_observed_at": latest_observation.get("observed_at"),
        "latest_model_version": latest_prediction.get("model_version"),
        "summary": {
            "prediction_count": len(predictions),
            "observation_count": len(observations),
            "avg_predicted_us_aqi": average(predictions, "predicted_us_aqi"),
            "max_predicted_us_aqi": maximum(predictions, "predicted_us_aqi"),
            "avg_predicted_currentspeed": average(
                predictions,
                "predicted_currentspeed",
            ),
            "avg_predicted_traffic_density": average(
                predictions,
                "predicted_traffic_density",
            ),
            "aqi_category_counts": dict(sorted(category_counts.items())),
        },
        "provinces": province_summary(predictions),
        "predictions": predictions,
        "observations": observations,
        "collector_runs": runs,
        "models": models,
    }


def export_web_data(output_file: Path) -> Path:
    try:
        database = LiveDatabase.from_environment(required=True)
    except DatabaseConfigError as exc:
        raise SystemExit(f"ERROR: {exc}") from None
    assert database is not None
    payload = build_payload(database)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Exported web dashboard data: {output_file} "
        f"({payload['summary']['prediction_count']} predictions)"
    )
    return output_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export TiDB data for GitHub Pages")
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    export_web_data(args.output_file.resolve())


if __name__ == "__main__":
    main()
