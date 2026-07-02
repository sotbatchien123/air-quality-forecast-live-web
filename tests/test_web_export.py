from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from web.export_web_data import hourly_summary, summarize_predictions  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
