"""Kiem tra ket noi TiDB Cloud bang bien moi truong trong `.env`.

Muc luc:
1. Load `.env` qua helper trong `live_database.py`.
2. Tao connection MySQL/TiDB co TLS neu duoc cau hinh.
3. In thong tin database hien tai va dong ket noi.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from database.live_database import (  # noqa: E402
    DEFAULT_ENV_FILE,
    DatabaseConfigError,
    LiveDatabase,
)


EXPECTED_TABLES = [
    "schema_migrations",
    "model_locations",
    "model_registry",
    "live_hourly_observations",
    "live_hourly_predictions",
    "live_collector_runs",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check TiDB Cloud connection using DB_* values from .env"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        database = LiveDatabase.from_environment(
            required=True,
            env_file=args.env_file.resolve(),
        )
    except DatabaseConfigError as exc:
        raise SystemExit(f"ERROR: {exc}. Fill DB_* values in {args.env_file}.") from None
    assert database is not None

    config = database.config
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE() AS database_name, VERSION() AS version")
            info = cursor.fetchone()
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() ORDER BY table_name"
            )
            tables = [row["table_name"] for row in cursor.fetchall()]
    finally:
        connection.close()

    missing = sorted(set(EXPECTED_TABLES) - set(tables))
    result = {
        "status": "ok" if not missing else "missing_tables",
        "host": config.host,
        "port": config.port,
        "database": info["database_name"],
        "ssl_mode": config.ssl_mode,
        "version": info["version"],
        "expected_tables_present": not missing,
        "missing_tables": missing,
        "tables": tables,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
