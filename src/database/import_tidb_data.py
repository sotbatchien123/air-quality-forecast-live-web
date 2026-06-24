"""Import/upsert du lieu project vao TiDB.

Muc luc:
1. Tao schema typed va raw staging khi can.
2. Import model locations, registry, observations va predictions.
3. Import raw CSV/JSON vao bang staging de giu lineage.
4. CLI gom cac lenh typed-schema, raw-schema, typed-data, raw-data va all.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from database.live_database import (  # noqa: E402
    DEFAULT_ENV_FILE,
    DEFAULT_SCHEMA_FILE,
    DatabaseConfigError,
    LiveDatabase,
    split_sql_statements,
)
from database.tidb_import_utils import (  # noqa: E402
    DEFAULT_SCAN_ROOTS,
    MODEL_LOCATION_DB_COLUMNS,
    OBSERVATION_DB_COLUMNS,
    PREDICTION_DB_COLUMNS,
    dumps_json,
    file_sha256,
    iter_source_files,
    read_csv_header_sample,
    recommend_data_file,
    recommend_csv_import,
    relative_path,
    source_group,
)


DEFAULT_IMPORT_DIR = ROOT_DIR / "data" / "tidb_import"
DEFAULT_RAW_SCHEMA_FILE = ROOT_DIR / "data" / "raw_import_tables.sql"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import/upsert transformed and raw project data into TiDB"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("typed-schema")
    schema_parser.add_argument("--schema-file", type=Path, default=DEFAULT_SCHEMA_FILE)

    raw_schema_parser = subparsers.add_parser("raw-schema")
    raw_schema_parser.add_argument(
        "--schema-file", type=Path, default=DEFAULT_RAW_SCHEMA_FILE
    )

    typed_parser = subparsers.add_parser("typed")
    typed_parser.add_argument("--input-dir", type=Path, default=DEFAULT_IMPORT_DIR)
    typed_parser.add_argument("--chunksize", type=int, default=1000)

    raw_parser = subparsers.add_parser("raw")
    raw_parser.add_argument("--create-raw-schema", action="store_true")
    raw_parser.add_argument("--max-rows-per-file", type=int)
    raw_parser.add_argument("--limit-files", type=int)
    raw_parser.add_argument("--dry-run", action="store_true")
    raw_parser.add_argument("--skip-existing", action="store_true")
    raw_parser.add_argument("--resume-partial", action="store_true")
    raw_parser.add_argument("--batch-size", type=int, default=500)

    all_parser = subparsers.add_parser("all")
    all_parser.add_argument("--input-dir", type=Path, default=DEFAULT_IMPORT_DIR)
    all_parser.add_argument("--create-raw-schema", action="store_true")
    all_parser.add_argument("--max-rows-per-file", type=int)
    all_parser.add_argument("--limit-files", type=int)
    all_parser.add_argument("--skip-existing", action="store_true")
    all_parser.add_argument("--resume-partial", action="store_true")
    all_parser.add_argument("--batch-size", type=int, default=500)
    all_parser.add_argument("--chunksize", type=int, default=1000)
    return parser.parse_args()


def database_from_args(args: argparse.Namespace) -> LiveDatabase:
    try:
        database = LiveDatabase.from_environment(
            required=True,
            env_file=args.env_file.resolve(),
        )
    except DatabaseConfigError as exc:
        raise SystemExit(
            f"ERROR: {exc}. Fill DB_* values in {args.env_file}."
        ) from None
    assert database is not None
    return database


def clean_value(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is not None:
            value = value.tz_convert("Asia/Ho_Chi_Minh").tz_localize(None)
        return value.to_pydatetime()
    if isinstance(value, bool):
        return int(value)
    return value


def records_from_frame(frame: pd.DataFrame, columns: list[str]) -> list[tuple[object, ...]]:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError("Missing import columns: " + ", ".join(missing))
    return [
        tuple(clean_value(row[column]) for column in columns)
        for row in frame[columns].to_dict("records")
    ]


def execute_many(
    database: LiveDatabase,
    sql: str,
    records: list[tuple[object, ...]],
    batch_size: int,
) -> int:
    if not records:
        return 0
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            for start in range(0, len(records), batch_size):
                cursor.executemany(sql, records[start : start + batch_size])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return len(records)


def execute_sql_file(database: LiveDatabase, schema_file: Path) -> int:
    statements = split_sql_statements(schema_file.read_text(encoding="utf-8"))
    connection = database.connect()
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


def read_import_chunks(path: Path, chunksize: int) -> Iterable[pd.DataFrame]:
    return pd.read_csv(path, encoding="utf-8-sig", chunksize=chunksize)


def import_model_locations(database: LiveDatabase, input_dir: Path) -> int:
    path = input_dir / "model_locations.csv"
    if not path.is_file():
        return 0
    frame = pd.read_csv(path, encoding="utf-8-sig")
    records = records_from_frame(frame, MODEL_LOCATION_DB_COLUMNS)
    sql = """
        INSERT INTO model_locations (
            location_key, province_key, district_key, display_name,
            lat, lon, api_lat, api_lon, estimated_vehicles, area_km2,
            population, density_person_km2, green_area_m2,
            green_per_capita_m2, is_live_supported
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            province_key=VALUES(province_key),
            district_key=VALUES(district_key),
            display_name=VALUES(display_name),
            lat=VALUES(lat),
            lon=VALUES(lon),
            api_lat=VALUES(api_lat),
            api_lon=VALUES(api_lon),
            estimated_vehicles=VALUES(estimated_vehicles),
            area_km2=VALUES(area_km2),
            population=VALUES(population),
            density_person_km2=VALUES(density_person_km2),
            green_area_m2=VALUES(green_area_m2),
            green_per_capita_m2=VALUES(green_per_capita_m2),
            is_live_supported=VALUES(is_live_supported)
    """
    return execute_many(database, sql, records, 500)


def import_model_registry(database: LiveDatabase, input_dir: Path) -> int:
    path = input_dir / "model_registry.csv"
    if not path.is_file():
        return 0
    columns = [
        "model_version",
        "variant",
        "algorithm",
        "artifact_path",
        "horizon_hours",
        "feature_count",
        "training_target_start",
        "training_target_end",
        "metadata_json",
        "is_active",
    ]
    frame = pd.read_csv(path, encoding="utf-8-sig")
    records = records_from_frame(frame, columns)
    sql = """
        INSERT INTO model_registry (
            model_version, variant, algorithm, artifact_path, horizon_hours,
            feature_count, training_target_start, training_target_end,
            metadata_json, is_active
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            variant=VALUES(variant),
            algorithm=VALUES(algorithm),
            artifact_path=VALUES(artifact_path),
            horizon_hours=VALUES(horizon_hours),
            feature_count=VALUES(feature_count),
            training_target_start=VALUES(training_target_start),
            training_target_end=VALUES(training_target_end),
            metadata_json=VALUES(metadata_json),
            is_active=VALUES(is_active)
    """
    return execute_many(database, sql, records, 500)


def import_observations(database: LiveDatabase, input_dir: Path, chunksize: int) -> int:
    path = input_dir / "live_hourly_observations.csv"
    if not path.is_file():
        return 0
    columns = OBSERVATION_DB_COLUMNS
    placeholders = ", ".join(["%s"] * len(columns))
    update_columns = [column for column in columns if column not in {"location_key", "observed_at"}]
    updates = ", ".join(f"{column}=VALUES({column})" for column in update_columns)
    sql = (
        "INSERT INTO live_hourly_observations "
        f"({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {updates}"
    )
    connection = database.connect()
    total = 0
    try:
        with connection.cursor() as cursor:
            for frame in read_import_chunks(path, chunksize):
                frame["observed_at"] = pd.to_datetime(frame["observed_at"], errors="raise")
                frame["collected_at"] = pd.to_datetime(frame["collected_at"], errors="raise")
                records = records_from_frame(frame, columns)
                cursor.executemany(sql, records)
                connection.commit()
                total += len(records)
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
        raise
    finally:
        connection.close()
    return total


def import_predictions(database: LiveDatabase, input_dir: Path, chunksize: int) -> int:
    path = input_dir / "live_hourly_predictions.csv"
    if not path.is_file():
        return 0
    columns = PREDICTION_DB_COLUMNS
    placeholders = ", ".join(["%s"] * len(columns))
    update_columns = [
        column
        for column in columns
        if column not in {"location_key", "target_at", "model_version"}
    ]
    updates = ", ".join(f"{column}=VALUES({column})" for column in update_columns)
    sql = (
        "INSERT INTO live_hourly_predictions "
        f"({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {updates}"
    )
    connection = database.connect()
    total = 0
    try:
        with connection.cursor() as cursor:
            for frame in read_import_chunks(path, chunksize):
                frame["target_at"] = pd.to_datetime(frame["target_at"], errors="raise")
                frame["generated_at"] = pd.to_datetime(frame["generated_at"], errors="raise")
                records = records_from_frame(frame, columns)
                cursor.executemany(sql, records)
                connection.commit()
                total += len(records)
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
        raise
    finally:
        connection.close()
    return total


def import_typed(database: LiveDatabase, input_dir: Path, chunksize: int) -> dict[str, int]:
    input_dir = input_dir.resolve()
    counts = {
        "model_locations": import_model_locations(database, input_dir),
        "model_registry": import_model_registry(database, input_dir),
        "live_hourly_observations": import_observations(database, input_dir, chunksize),
        "live_hourly_predictions": import_predictions(database, input_dir, chunksize),
    }
    return counts


def json_payload(row: dict[str, str | None]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def existing_raw_file_metadata(database: LiveDatabase, source: str) -> dict[str, object] | None:
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT sha256, row_count FROM raw_csv_import_files WHERE source_path=%s",
                (source,),
            )
            return cursor.fetchone()
    finally:
        connection.close()


def raw_file_is_complete(database: LiveDatabase, path: Path) -> bool:
    metadata = existing_raw_file_metadata(database, relative_path(path))
    return bool(metadata and metadata["sha256"] == file_sha256(path))


def existing_raw_max_row(database: LiveDatabase, source: str) -> int:
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(MAX(row_index), 0) AS max_row "
                "FROM raw_csv_import_rows WHERE source_path=%s",
                (source,),
            )
            return int(cursor.fetchone()["max_row"])
    finally:
        connection.close()


def open_csv_dict_reader(path: Path):
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            stream = path.open("r", encoding=encoding, newline="")
            reader = csv.DictReader(stream)
            _ = reader.fieldnames
            return stream, reader
        except UnicodeDecodeError:
            continue
    stream = path.open("r", encoding="utf-8", errors="replace", newline="")
    return stream, csv.DictReader(stream)


def upsert_raw_file_metadata(
    database: LiveDatabase,
    path: Path,
    header: list[str],
    row_count: int,
) -> None:
    recommendation = recommend_data_file(path)
    record = (
        relative_path(path),
        source_group(path),
        recommendation.target_table,
        recommendation.transform,
        path.stat().st_size,
        datetime.fromtimestamp(path.stat().st_mtime),
        file_sha256(path),
        json.dumps(header, ensure_ascii=False),
        row_count,
    )
    sql = """
        INSERT INTO raw_csv_import_files (
            source_path, source_group, recommended_target_table, transform_action,
            file_size_bytes, file_modified_at, sha256, header_json, row_count
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            source_group=VALUES(source_group),
            recommended_target_table=VALUES(recommended_target_table),
            transform_action=VALUES(transform_action),
            file_size_bytes=VALUES(file_size_bytes),
            file_modified_at=VALUES(file_modified_at),
            sha256=VALUES(sha256),
            header_json=VALUES(header_json),
            row_count=VALUES(row_count)
    """
    execute_many(database, sql, [record], 1)


def import_raw_csv_file(
    database: LiveDatabase,
    path: Path,
    max_rows: int | None,
    batch_size: int,
    resume_partial: bool,
) -> int:
    source = relative_path(path)
    resume_after = existing_raw_max_row(database, source) if resume_partial else 0
    stream, reader = open_csv_dict_reader(path)
    try:
        header = list(reader.fieldnames or [])
        records: list[tuple[object, ...]] = []
        total_rows = 0
        imported_rows = 0
        sql = """
            INSERT INTO raw_csv_import_rows (
                source_path, row_index, row_hash, payload_json
            ) VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                row_hash=VALUES(row_hash),
                payload_json=VALUES(payload_json)
        """
        connection = database.connect()
        try:
            with connection.cursor() as cursor:
                for row_number, row in enumerate(reader, start=1):
                    total_rows = row_number
                    if row_number <= resume_after:
                        continue
                    payload = json_payload(row)
                    row_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                    records.append((source, row_number, row_hash, payload))
                    imported_rows += 1
                    if len(records) >= batch_size:
                        cursor.executemany(sql, records)
                        connection.commit()
                        records = []
                    if max_rows is not None and imported_rows >= max_rows:
                        break
                if records:
                    cursor.executemany(sql, records)
                    connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        finally:
            connection.close()
        upsert_raw_file_metadata(database, path, header, total_rows)
        return imported_rows
    finally:
        stream.close()


def import_raw_json_file(database: LiveDatabase, path: Path) -> int:
    source = relative_path(path)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        header = list(payload.keys())
    else:
        header = [type(payload).__name__]
    payload_json = dumps_json(payload)
    row_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    sql = """
        INSERT INTO raw_csv_import_rows (
            source_path, row_index, row_hash, payload_json
        ) VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            row_hash=VALUES(row_hash),
            payload_json=VALUES(payload_json)
    """
    execute_many(database, sql, [(source, 1, row_hash, payload_json)], 1)
    upsert_raw_file_metadata(database, path, header, 1)
    return 1


def raw_source_paths(limit_files: int | None) -> list[Path]:
    paths = [
        path
        for path in iter_source_files(DEFAULT_SCAN_ROOTS, suffixes=(".csv", ".json"))
        if path.suffix.lower() in {".csv", ".json"}
    ]
    return paths[:limit_files] if limit_files is not None else paths


def import_raw(
    database: LiveDatabase | None,
    create_raw_schema: bool,
    max_rows_per_file: int | None,
    limit_files: int | None,
    dry_run: bool,
    batch_size: int,
    skip_existing: bool,
    resume_partial: bool,
) -> dict[str, int]:
    paths = raw_source_paths(limit_files)
    if dry_run:
        for path in paths:
            if path.suffix.lower() == ".csv":
                header, _ = read_csv_header_sample(path)
                recommendation = recommend_csv_import(path, header)
            else:
                recommendation = recommend_data_file(path)
            print(
                f"{relative_path(path)} -> {recommendation.target_table} "
                f"({recommendation.transform})"
            )
        return {"files": len(paths), "rows": 0}
    assert database is not None
    if create_raw_schema:
        statement_count = execute_sql_file(database, DEFAULT_RAW_SCHEMA_FILE)
        print(f"Applied {statement_count} raw schema statements")
    total_rows = 0
    for index, path in enumerate(paths, start=1):
        if skip_existing and raw_file_is_complete(database, path):
            print(f"[{index}/{len(paths)}] skipped unchanged {relative_path(path)}")
            continue
        if path.suffix.lower() == ".json":
            rows = import_raw_json_file(database, path)
        else:
            rows = import_raw_csv_file(
                database,
                path,
                max_rows_per_file,
                batch_size,
                resume_partial,
            )
        total_rows += rows
        print(f"[{index}/{len(paths)}] raw upserted {rows:,} rows from {relative_path(path)}")
    return {"files": len(paths), "rows": total_rows}


def main() -> None:
    args = parse_args()

    if args.command == "typed-schema":
        database = database_from_args(args)
        count = execute_sql_file(database, args.schema_file.resolve())
        print(f"Applied {count} typed schema statements")
        return
    if args.command == "raw-schema":
        database = database_from_args(args)
        count = execute_sql_file(database, args.schema_file.resolve())
        print(f"Applied {count} raw schema statements")
        return
    if args.command == "typed":
        database = database_from_args(args)
        print(json.dumps(import_typed(database, args.input_dir, args.chunksize), indent=2))
        return
    if args.command == "raw":
        database = None if args.dry_run else database_from_args(args)
        print(
            json.dumps(
                import_raw(
                    database=database,
                    create_raw_schema=args.create_raw_schema,
                    max_rows_per_file=args.max_rows_per_file,
                    limit_files=args.limit_files,
                    dry_run=args.dry_run,
                    batch_size=args.batch_size,
                    skip_existing=args.skip_existing,
                    resume_partial=args.resume_partial,
                ),
                indent=2,
            )
        )
        return
    if args.command == "all":
        database = database_from_args(args)
        typed_counts = import_typed(database, args.input_dir, args.chunksize)
        raw_counts = import_raw(
            database=database,
            create_raw_schema=args.create_raw_schema,
            max_rows_per_file=args.max_rows_per_file,
            limit_files=args.limit_files,
            dry_run=False,
            batch_size=args.batch_size,
            skip_existing=args.skip_existing,
            resume_partial=args.resume_partial,
        )
        print(json.dumps({"typed": typed_counts, "raw": raw_counts}, indent=2))


if __name__ == "__main__":
    main()
