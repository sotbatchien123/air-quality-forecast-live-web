from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
MODELS_SRC_DIR = SRC_DIR / "models"
for source_dir in (SRC_DIR, MODELS_SRC_DIR):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))

from database.live_database import (  # noqa: E402
    DatabaseConfig,
    DatabaseConfigError,
    model_version,
    split_sql_statements,
)
from live.live_hourly_predictor import (  # noqa: E402
    upsert_observations,
    upsert_predictions,
)


class DatabaseConfigTests(unittest.TestCase):
    def test_complete_mapping(self) -> None:
        config = DatabaseConfig.from_mapping(
            {
                "DB_HOST": "db.example.com",
                "DB_PORT": "4000",
                "DB_USERNAME": "user",
                "DB_PASSWORD": "secret",
                "DB_DATABASE": "air_quality",
            },
            required=True,
        )
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.port, 4000)
        self.assertEqual(config.ssl_mode, "VERIFY_IDENTITY")

    def test_partial_mapping_is_rejected(self) -> None:
        with self.assertRaises(DatabaseConfigError):
            DatabaseConfig.from_mapping({"DB_HOST": "db.example.com"})

    def test_empty_optional_mapping_disables_database(self) -> None:
        self.assertIsNone(DatabaseConfig.from_mapping({}, required=False))


class SchemaTests(unittest.TestCase):
    def test_schema_contains_all_live_tables(self) -> None:
        script = (ROOT_DIR / "data" / "setup_tables.sql").read_text(encoding="utf-8")
        statements = split_sql_statements(script)
        self.assertEqual(len(statements), 7)
        joined = "\n".join(statements)
        for table in (
            "model_locations",
            "model_registry",
            "live_hourly_observations",
            "live_hourly_predictions",
            "live_collector_runs",
        ):
            self.assertIn(table, joined)

    def test_model_version_is_stable(self) -> None:
        bundle = {
            "metadata": {
                "variant": "hourly",
                "created_at_utc": "2026-06-21T15:44:29+00:00",
            }
        }
        self.assertEqual(
            model_version(bundle),
            "hourly@2026-06-21T15:44:29+00:00",
        )


class PredictionFileTests(unittest.TestCase):
    def test_upsert_observations_ignores_repeated_header_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "observations.csv"
            existing = pd.DataFrame(
                [
                    {
                        "timestamp": "timestamp",
                        "collection_time": "collection_time",
                        "location_key": "location_key",
                    },
                    {
                        "timestamp": "2026-06-23 08:00:00",
                        "collection_time": "2026-06-23T08:05:00+07:00",
                        "location_key": "ho_chi_minh__quan_1",
                    },
                ]
            )
            existing.to_csv(output, index=False, encoding="utf-8-sig")
            new_rows = pd.DataFrame(
                [
                    {
                        "timestamp": "2026-06-23 09:00:00",
                        "collection_time": "2026-06-23T09:05:00+07:00",
                        "location_key": "ho_chi_minh__quan_1",
                    }
                ]
            )

            result = upsert_observations(new_rows, output)

            self.assertEqual(len(result), 2)
            self.assertNotIn("timestamp", result["timestamp"].astype(str).tolist())

    def test_upsert_replaces_same_model_location_and_hour(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "predictions.csv"
            base = {
                "target_timestamp": "2026-06-23 08:00:00",
                "location_key": "ho_chi_minh__quan_1",
                "province_key": "ho_chi_minh",
                "district_key": "quan_1",
                "district": "Quận 1",
                "predicted_currentspeed": 30.0,
                "predicted_traffic_density": 0.3,
                "predicted_us_aqi": 70.0,
                "generated_at": "2026-06-23T07:05:00+07:00",
                "model_version": "hourly@test",
            }
            upsert_predictions(pd.DataFrame([base]), output)
            newer = {**base, "predicted_us_aqi": 75.0, "generated_at": "2026-06-23T07:06:00+07:00"}
            result = upsert_predictions(pd.DataFrame([newer]), output)
            self.assertEqual(len(result), 1)
            self.assertEqual(float(result.iloc[0]["predicted_us_aqi"]), 75.0)


if __name__ == "__main__":
    unittest.main()
