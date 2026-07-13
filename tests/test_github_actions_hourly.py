from __future__ import annotations

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

from live.github_actions_hourly import (  # noqa: E402
    has_current_hour_observations,
    hydrate_table,
)
from live.backfill_live_predictions import (  # noqa: E402
    GAP_FILL_SOURCE,
    build_gap_filled_observation_rows,
)
from live.live_hourly_predictor import fill_history_gaps  # noqa: E402


class GitHubActionsHourlyTests(unittest.TestCase):
    def test_hydrate_table_reads_dict_cursor_rows_as_values(self) -> None:
        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback) -> None:
                return None

            def execute(self, sql: str, params: tuple[object, ...]) -> None:
                self.sql = sql
                self.params = params

            def fetchall(self) -> list[dict[str, object]]:
                return [
                    {
                        "timestamp": pd.Timestamp("2026-07-05 11:00:00"),
                        "location_key": "location_a",
                    }
                ]

        class FakeConnection:
            def cursor(self) -> FakeCursor:
                return FakeCursor()

            def close(self) -> None:
                return None

        class FakeDatabase:
            def connect(self) -> FakeConnection:
                return FakeConnection()

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "hourly_observations.csv"

            count = hydrate_table(
                FakeDatabase(),
                "SELECT timestamp, location_key FROM fake WHERE timestamp >= %s",
                pd.Timestamp("2026-07-05 00:00:00"),
                output,
            )

            frame = pd.read_csv(output, encoding="utf-8-sig")
            self.assertEqual(count, 1)
            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.loc[0, "location_key"], "location_a")
            self.assertNotEqual(frame.loc[0, "timestamp"], "timestamp")

    def test_current_hour_observation_gate_requires_enough_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "hourly_observations.csv"
            frame = pd.DataFrame(
                [
                    {
                        "timestamp": "2026-07-03 10:00:00",
                        "location_key": "location_a",
                    },
                    {
                        "timestamp": "2026-07-03 10:00:00",
                        "location_key": "location_b",
                    },
                    {
                        "timestamp": "2026-07-03 09:00:00",
                        "location_key": "location_c",
                    },
                ]
            )
            frame.to_csv(output, index=False, encoding="utf-8-sig")

            current = pd.Timestamp("2026-07-03 10:00:00")

            self.assertTrue(has_current_hour_observations(output, current, 2))
            self.assertFalse(has_current_hour_observations(output, current, 3))

    def test_fill_history_gaps_creates_continuous_hourly_panel(self) -> None:
        current = pd.Timestamp("2026-07-05 11:00:00")
        frame = pd.DataFrame(
            [
                {
                    "timestamp": current - pd.Timedelta(hours=11),
                    "location_key": "location_a",
                    "currentspeed": 20.0,
                },
                {
                    "timestamp": current,
                    "location_key": "location_a",
                    "currentspeed": 30.0,
                },
            ]
        )

        filled = fill_history_gaps(frame, current)

        self.assertEqual(len(filled), 12)
        self.assertEqual(filled["timestamp"].nunique(), 12)
        middle = filled.loc[
            filled["timestamp"] == current - pd.Timedelta(hours=5),
            "currentspeed",
        ].iloc[0]
        self.assertEqual(middle, 20.0)

    def test_build_gap_filled_observation_rows_marks_synthetic_sources(self) -> None:
        start = pd.Timestamp("2026-07-13 10:00:00")
        end = pd.Timestamp("2026-07-13 12:00:00")
        frame = pd.DataFrame(
            [
                {
                    "timestamp": start,
                    "collection_time": "2026-07-13T10:05:00+07:00",
                    "location_key": "location_a",
                    "province_key": "province",
                    "district_key": "district",
                    "district": "District",
                    "lat": 10.0,
                    "lon": 106.0,
                    "estimated_vehicles": 1000.0,
                    "area_km2": 10.0,
                    "population": 10000.0,
                    "density_person_km2": 1000.0,
                    "green_area_m2": 500.0,
                    "green_per_capita_m2": 0.05,
                    "temperature_2m": 30.0,
                    "relative_humidity_2m": 70.0,
                    "precipitation": 0.0,
                    "wind_speed_10m": 5.0,
                    "cloud_cover": 20.0,
                    "currentspeed": 30.0,
                    "freeflowspeed": 40.0,
                    "congestion_ratio": 0.75,
                    "traffic_density": 0.25,
                    "us_aqi": 80.0,
                    "pm10": 40.0,
                    "pm2_5": 20.0,
                    "carbon_monoxide": 100.0,
                    "nitrogen_dioxide": 10.0,
                    "sulphur_dioxide": 2.0,
                    "ozone": 30.0,
                    "traffic_source": "tomtom_flow_segment_live",
                    "aqi_source": "open_meteo_cams_global",
                    "weather_source": "open_meteo_forecast",
                }
            ]
        )

        filled = build_gap_filled_observation_rows(
            frame,
            [pd.Timestamp("2026-07-13 11:00:00")],
            start,
            end,
        )

        self.assertEqual(len(filled), 1)
        self.assertEqual(filled.iloc[0]["timestamp"], pd.Timestamp("2026-07-13 11:00:00"))
        self.assertEqual(filled.iloc[0]["traffic_source"], GAP_FILL_SOURCE)
        self.assertEqual(float(filled.iloc[0]["currentspeed"]), 30.0)


if __name__ == "__main__":
    unittest.main()
