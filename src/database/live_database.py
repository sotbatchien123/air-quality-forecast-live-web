"""Helper ket noi va upsert du lieu live vao TiDB.

Muc luc:
1. Load `.env`, doc cau hinh DB va tao connection TLS.
2. Chuan hoa dataframe observations/predictions/model locations.
3. Upsert vao cac bang live_hourly_* va model_registry.
4. Ghi trang thai `live_collector_runs` de theo doi job 24/24.
"""

from __future__ import annotations

import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_SCHEMA_FILE = ROOT_DIR / "data" / "setup_tables.sql"
LOCAL_TIMEZONE = "Asia/Ho_Chi_Minh"

OBSERVATION_COLUMNS = [
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
]
SOURCE_COLUMNS = ["traffic_source", "aqi_source", "weather_source"]
PREDICTION_COLUMNS = [
    "predicted_currentspeed",
    "predicted_traffic_density",
    "predicted_us_aqi",
]


class DatabaseConfigError(RuntimeError):
    pass


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    ssl_mode: str = "VERIFY_IDENTITY"
    ssl_ca: str | None = None
    connect_timeout: int = 10

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, str],
        required: bool = False,
    ) -> DatabaseConfig | None:
        aliases = {
            "host": values.get("DB_HOST", "").strip(),
            "user": (
                values.get("DB_USERNAME", "") or values.get("DB_USER", "")
            ).strip(),
            "password": values.get("DB_PASSWORD", ""),
            "database": values.get("DB_DATABASE", "").strip(),
        }
        configured = any(aliases.values())
        if not configured and not required:
            return None
        missing = [name for name, value in aliases.items() if not value]
        if missing:
            raise DatabaseConfigError(
                "Incomplete database configuration; missing: " + ", ".join(missing)
            )
        try:
            port = int(values.get("DB_PORT", "4000"))
            timeout = int(values.get("DB_CONNECT_TIMEOUT", "10"))
        except ValueError as exc:
            raise DatabaseConfigError("DB_PORT and DB_CONNECT_TIMEOUT must be integers") from exc
        return cls(
            host=aliases["host"],
            port=port,
            user=aliases["user"],
            password=aliases["password"],
            database=aliases["database"],
            ssl_mode=values.get("DB_SSL_MODE", "VERIFY_IDENTITY").strip().upper(),
            ssl_ca=values.get("DB_SSL_CA", "").strip() or None,
            connect_timeout=timeout,
        )

    @classmethod
    def from_environment(
        cls,
        required: bool = False,
        env_file: Path = DEFAULT_ENV_FILE,
    ) -> DatabaseConfig | None:
        load_env_file(env_file)
        return cls.from_mapping(os.environ, required=required)


def database_sync_required() -> bool:
    load_env_file()
    return _parse_bool(os.getenv("LIVE_DB_REQUIRED"), default=True)


def model_version(bundle: Mapping[str, Any]) -> str:
    metadata = bundle.get("metadata", {})
    variant = str(metadata.get("variant") or "xgboost_multisource_hourly")
    created = str(metadata.get("created_at_utc") or "unknown")
    return f"{variant}@{created}"[:191]


def _timestamp(value: object, timezone: str = LOCAL_TIMEZONE) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(timezone).tz_localize(None)
    return timestamp.to_pydatetime()


def _scalar(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return str(value)
    return value


def _chunks(values: list[tuple[object, ...]], size: int = 500) -> Iterable[list[tuple[object, ...]]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def split_sql_statements(script: str) -> list[str]:
    without_comments = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


class LiveDatabase:
    def __init__(self, config: DatabaseConfig):
        self.config = config

    @classmethod
    def from_environment(
        cls,
        required: bool = False,
        env_file: Path = DEFAULT_ENV_FILE,
    ) -> LiveDatabase | None:
        config = DatabaseConfig.from_environment(required=required, env_file=env_file)
        return cls(config) if config else None

    def connect(self):
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "PyMySQL is required for database sync. Run: "
                "pip install -r requirements-ml.txt"
            ) from exc

        kwargs: dict[str, Any] = {
            "host": self.config.host,
            "port": self.config.port,
            "user": self.config.user,
            "password": self.config.password,
            "database": self.config.database,
            "charset": "utf8mb4",
            "autocommit": False,
            "connect_timeout": self.config.connect_timeout,
            "read_timeout": int(os.getenv("DB_READ_TIMEOUT", "300")),
            "write_timeout": int(os.getenv("DB_WRITE_TIMEOUT", "300")),
            "cursorclass": pymysql.cursors.DictCursor,
        }
        if self.config.ssl_mode != "DISABLED":
            kwargs["ssl"] = {"ca": self.config.ssl_ca} if self.config.ssl_ca else {}
            kwargs["ssl_verify_cert"] = self.config.ssl_mode in {
                "VERIFY_CA",
                "VERIFY_IDENTITY",
            }
            kwargs["ssl_verify_identity"] = self.config.ssl_mode == "VERIFY_IDENTITY"
        return pymysql.connect(**kwargs)

    def initialize_schema(self, schema_file: Path = DEFAULT_SCHEMA_FILE) -> int:
        statements = split_sql_statements(schema_file.read_text(encoding="utf-8"))
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return len(statements)

    def healthcheck(self) -> dict[str, object]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT DATABASE() AS database_name, VERSION() AS version")
                result = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) AS table_count FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name IN "
                    "('model_locations', 'model_registry', "
                    "'live_hourly_observations', 'live_hourly_predictions', "
                    "'live_collector_runs')"
                )
                result["live_table_count"] = int(cursor.fetchone()["table_count"])
                return result
        finally:
            connection.close()

    def _executemany(self, sql: str, records: list[tuple[object, ...]]) -> int:
        if not records:
            return 0
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                for batch in _chunks(records):
                    cursor.executemany(sql, batch)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return len(records)

    def upsert_locations(self, locations: pd.DataFrame) -> int:
        records: list[tuple[object, ...]] = []
        for row in locations.to_dict("records"):
            records.append(
                (
                    row["location_key"],
                    row["province_key"],
                    row["district_key"],
                    row["district"],
                    _scalar(row["lat"]),
                    _scalar(row["lon"]),
                    _scalar(row.get("api_lat", row["lat"])),
                    _scalar(row.get("api_lon", row["lon"])),
                    _scalar(row.get("estimated_vehicles")),
                    _scalar(row.get("area_km2")),
                    _scalar(row.get("population")),
                    _scalar(row.get("density_person_km2")),
                    _scalar(row.get("green_area_m2")),
                    _scalar(row.get("green_per_capita_m2")),
                    int(bool(row.get("is_live_supported", True))),
                )
            )
        sql = """
            INSERT INTO model_locations (
                location_key, province_key, district_key, display_name,
                lat, lon, api_lat, api_lon, estimated_vehicles, area_km2,
                population, density_person_km2, green_area_m2,
                green_per_capita_m2, is_live_supported
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                display_name=VALUES(display_name), lat=VALUES(lat), lon=VALUES(lon),
                api_lat=VALUES(api_lat), api_lon=VALUES(api_lon),
                estimated_vehicles=VALUES(estimated_vehicles), area_km2=VALUES(area_km2),
                population=VALUES(population),
                density_person_km2=VALUES(density_person_km2),
                green_area_m2=VALUES(green_area_m2),
                green_per_capita_m2=VALUES(green_per_capita_m2),
                is_live_supported=VALUES(is_live_supported)
        """
        return self._executemany(sql, records)

    def register_model(self, bundle: Mapping[str, Any], artifact_path: Path) -> str:
        metadata = dict(bundle.get("metadata", {}))
        version = model_version(bundle)
        variant = str(metadata.get("variant") or "xgboost_multisource_hourly")
        algorithm = str(metadata.get("algorithm") or "XGBRegressor")
        feature_count = int(metadata.get("feature_count") or len(bundle["feature_columns"]))
        horizon = int(metadata.get("forecast_horizon_hours") or 1)
        record = (
            version,
            variant,
            algorithm,
            str(artifact_path),
            horizon,
            feature_count,
            _timestamp(metadata.get("training_target_start")),
            _timestamp(metadata.get("training_target_end")),
            json.dumps(_json_safe(metadata), ensure_ascii=False, allow_nan=False),
        )
        sql = """
            INSERT INTO model_registry (
                model_version, variant, algorithm, artifact_path, horizon_hours,
                feature_count, training_target_start, training_target_end,
                metadata_json, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
                artifact_path=VALUES(artifact_path), metadata_json=VALUES(metadata_json),
                feature_count=VALUES(feature_count), is_active=1
        """
        self._executemany(sql, [record])
        return version

    def upsert_observations(self, observations: pd.DataFrame) -> int:
        required = {"timestamp", "collection_time", "location_key", *OBSERVATION_COLUMNS, *SOURCE_COLUMNS}
        missing = sorted(required - set(observations.columns))
        if missing:
            raise ValueError("Observation frame is missing: " + ", ".join(missing))
        records: list[tuple[object, ...]] = []
        for row in observations.to_dict("records"):
            records.append(
                (
                    row["location_key"],
                    _timestamp(row["timestamp"]),
                    _timestamp(row["collection_time"]),
                    *[_scalar(row[column]) for column in OBSERVATION_COLUMNS],
                    *[row[column] for column in SOURCE_COLUMNS],
                )
            )
        columns = ", ".join(OBSERVATION_COLUMNS + SOURCE_COLUMNS)
        placeholders = ", ".join(["%s"] * (3 + len(OBSERVATION_COLUMNS) + len(SOURCE_COLUMNS)))
        updates = ", ".join(
            ["collected_at=VALUES(collected_at)"]
            + [f"{column}=VALUES({column})" for column in OBSERVATION_COLUMNS + SOURCE_COLUMNS]
        )
        sql = (
            "INSERT INTO live_hourly_observations "
            f"(location_key, observed_at, collected_at, {columns}) "
            f"VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"
        )
        return self._executemany(sql, records)

    def upsert_predictions(
        self,
        predictions: pd.DataFrame,
        default_model_version: str | None = None,
    ) -> int:
        frame = predictions.copy()
        if "location_key" not in frame:
            frame["location_key"] = frame["province_key"] + "__" + frame["district_key"]
        if "model_version" not in frame:
            if not default_model_version:
                raise ValueError("Prediction frame has no model_version")
            frame["model_version"] = default_model_version
        if "generated_at" not in frame:
            frame["generated_at"] = datetime.now()
        required = {"location_key", "target_timestamp", "model_version", "generated_at", *PREDICTION_COLUMNS}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError("Prediction frame is missing: " + ", ".join(missing))
        records = [
            (
                row["location_key"],
                _timestamp(row["target_timestamp"]),
                row["model_version"],
                _timestamp(row["generated_at"]),
                *[_scalar(row[column]) for column in PREDICTION_COLUMNS],
            )
            for row in frame.to_dict("records")
        ]
        sql = """
            INSERT INTO live_hourly_predictions (
                location_key, target_at, model_version, generated_at,
                predicted_currentspeed, predicted_traffic_density, predicted_us_aqi
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                generated_at=VALUES(generated_at),
                predicted_currentspeed=VALUES(predicted_currentspeed),
                predicted_traffic_density=VALUES(predicted_traffic_density),
                predicted_us_aqi=VALUES(predicted_us_aqi)
        """
        return self._executemany(sql, records)

    def start_run(self, scheduled_at: object, version: str | None) -> str:
        run_id = uuid.uuid4().hex
        record = (
            run_id,
            _timestamp(scheduled_at),
            datetime.now(),
            "running",
            version,
        )
        self._executemany(
            "INSERT INTO live_collector_runs "
            "(run_id, scheduled_at, started_at, status, model_version) "
            "VALUES (%s, %s, %s, %s, %s)",
            [record],
        )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        observations_count: int,
        predictions_count: int,
        error_message: str | None = None,
    ) -> None:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE live_collector_runs SET finished_at=%s, status=%s, "
                    "observations_count=%s, predictions_count=%s, error_message=%s "
                    "WHERE run_id=%s",
                    (
                        datetime.now(),
                        status,
                        observations_count,
                        predictions_count,
                        error_message[:4000] if error_message else None,
                        run_id,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def status(self) -> dict[str, object]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                output: dict[str, object] = {}
                for table, time_column in [
                    ("model_locations", None),
                    ("live_hourly_observations", "observed_at"),
                    ("live_hourly_predictions", "target_at"),
                    ("live_collector_runs", "scheduled_at"),
                ]:
                    select = "COUNT(*) AS row_count"
                    if time_column:
                        select += f", MIN({time_column}) AS first_at, MAX({time_column}) AS latest_at"
                    cursor.execute(f"SELECT {select} FROM {table}")
                    output[table] = cursor.fetchone()
                cursor.execute(
                    "SELECT run_id, scheduled_at, finished_at, status, "
                    "observations_count, predictions_count, error_message "
                    "FROM live_collector_runs ORDER BY started_at DESC LIMIT 1"
                )
                output["latest_run"] = cursor.fetchone()
                return output
        finally:
            connection.close()
