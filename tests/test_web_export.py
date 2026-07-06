from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from web.export_web_data import (  # noqa: E402
    hourly_summary,
    select_latest_rows,
    summarize_predictions,
)


class WebExportTests(unittest.TestCase):
    def test_summarize_predictions_counts_aqi_categories(self) -> None:
        rows = [
            {
                "predicted_us_aqi": 40.0,
                "predicted_currentspeed": 30.0,
                "predicted_traffic_density": 0.2,
                "aqi_category": "Good",
            },
            {
                "predicted_us_aqi": 120.0,
                "predicted_currentspeed": 20.0,
                "predicted_traffic_density": 0.4,
                "aqi_category": "Unhealthy for sensitive groups",
            },
        ]

        summary = summarize_predictions(rows)

        self.assertEqual(summary["prediction_count"], 2)
        self.assertEqual(summary["avg_predicted_us_aqi"], 80.0)
        self.assertEqual(summary["max_predicted_us_aqi"], 120.0)
        self.assertEqual(summary["aqi_category_counts"]["Good"], 1)

    def test_hourly_summary_groups_predictions_by_target_hour(self) -> None:
        rows = [
            {
                "target_at": "2026-06-23T09:00:00",
                "province_key": "ho_chi_minh",
                "predicted_us_aqi": 70.0,
                "predicted_currentspeed": 30.0,
                "predicted_traffic_density": 0.2,
                "aqi_category": "Moderate",
            },
            {
                "target_at": "2026-06-23T10:00:00",
                "province_key": "ho_chi_minh",
                "predicted_us_aqi": 90.0,
                "predicted_currentspeed": 28.0,
                "predicted_traffic_density": 0.3,
                "aqi_category": "Moderate",
            },
        ]

        hours = hourly_summary(rows)

        self.assertEqual([row["target_at"] for row in hours], ["2026-06-23T10:00:00", "2026-06-23T09:00:00"])
        self.assertEqual(hours[0]["prediction_count"], 1)
        self.assertEqual(hours[0]["provinces"][0]["province_key"], "ho_chi_minh")

    def test_select_latest_rows_keeps_newest_generated_prediction(self) -> None:
        rows = [
            {
                "location_key": "ho_chi_minh__quan_1",
                "target_at": "2026-07-06 17:00:00",
                "generated_at": "2026-07-06 16:10:00",
                "predicted_us_aqi": 70.0,
            },
            {
                "location_key": "ho_chi_minh__quan_1",
                "target_at": "2026-07-06 17:00:00",
                "generated_at": "2026-07-06 16:44:00",
                "predicted_us_aqi": 75.0,
            },
        ]

        selected = select_latest_rows(rows, ("location_key", "target_at"), "generated_at")

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["predicted_us_aqi"], 75.0)


if __name__ == "__main__":
    unittest.main()
