from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from database.tidb_import_utils import recommend_csv_import  # noqa: E402


class ImportRecommendationTests(unittest.TestCase):
    def test_location_manifest_maps_to_model_locations(self) -> None:
        recommendation = recommend_csv_import(
            ROOT_DIR / "data" / "raw" / "AQI" / "locations_5_provinces_old_boundaries.csv",
            ["province", "province_slug", "location_name", "lat", "lon"],
        )
        self.assertEqual(recommendation.target_table, "model_locations")

    def test_raw_aqi_csv_stays_in_raw_staging(self) -> None:
        recommendation = recommend_csv_import(
            ROOT_DIR
            / "data"
            / "raw"
            / "AQI"
            / "open_meteo_aqi_2025_output"
            / "aqi_ho_chi_minh_2025_open_meteo.csv",
            ["province_slug", "location_name", "lat", "lon", "pm10", "us_aqi"],
        )
        self.assertEqual(recommendation.target_table, "raw_csv_import_rows")

    def test_processed_forecast_maps_to_predictions(self) -> None:
        recommendation = recommend_csv_import(
            ROOT_DIR
            / "data"
            / "processed"
            / "model_predictions"
            / "traffic_aqi_forecast_2026_01.csv",
            [
                "target_timestamp",
                "province_key",
                "district_key",
                "predicted_currentspeed",
                "predicted_traffic_density",
                "predicted_us_aqi",
            ],
        )
        self.assertEqual(recommendation.target_table, "live_hourly_predictions")

    def test_holdout_predictions_stay_in_raw_staging(self) -> None:
        recommendation = recommend_csv_import(
            ROOT_DIR
            / "models"
            / "next_day_traffic_aqi"
            / "xgboost"
            / "xgboost_next_day_holdout_predictions.csv",
            [
                "target_timestamp",
                "target_currentspeed",
                "target_traffic_density",
                "target_us_aqi",
                "predicted_currentspeed",
                "predicted_traffic_density",
                "predicted_us_aqi",
            ],
        )
        self.assertEqual(recommendation.target_table, "raw_csv_import_rows")


if __name__ == "__main__":
    unittest.main()
