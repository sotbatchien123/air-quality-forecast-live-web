"""Replay prediction cho mot gio da co observation live.

Muc luc:
1. Doc observation da luu trong `data/live/hourly_observations.csv`.
2. Lay weather tai gio dich va history tai gio truoc do.
3. Goi lai `build_inference()` va `predict()` cua live predictor.
4. Tuy chon so sanh voi file forecast live da ton tai.

Dung script nay khi muon tai hien nhanh mot du bao cu ma khong train lai model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
for source_dir in (ROOT_DIR / "src", ROOT_DIR / "src" / "models"):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))

from database.live_database import model_version  # noqa: E402
from live.live_hourly_predictor import (  # noqa: E402
    DEFAULT_OBSERVATIONS_FILE,
    DEFAULT_PREDICTIONS_DIR,
    MODEL_FILE,
    WEATHER_COLUMNS,
    build_inference,
    predict,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay an hourly prediction from saved live observations"
    )
    parser.add_argument(
        "--target-timestamp",
        required=True,
        help="Prediction target hour, for example: 2026-06-23 09:00:00",
    )
    parser.add_argument(
        "--observations-file",
        type=Path,
        default=DEFAULT_OBSERVATIONS_FILE,
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Defaults to data/live/predictions/replay_traffic_aqi_live_forecast_YYYY-MM-DD_HH00.csv",
    )
    parser.add_argument("--compare-existing", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target = pd.Timestamp(args.target_timestamp).floor("h")
    current = target - pd.Timedelta(hours=1)
    output_file = args.output_file or (
        DEFAULT_PREDICTIONS_DIR
        / f"replay_traffic_aqi_live_forecast_{target:%Y-%m-%d_%H00}.csv"
    )

    observations = pd.read_csv(args.observations_file, encoding="utf-8-sig")
    observations["timestamp"] = pd.to_datetime(
        observations["timestamp"],
        errors="raise",
    )
    target_rows = observations[observations["timestamp"] == target]
    if target_rows.empty:
        raise SystemExit(f"Missing saved weather rows for target hour: {target}")
    target_weather = {
        column: float(target_rows[column].astype(float).mean())
        for column in WEATHER_COLUMNS
    }

    bundle = joblib.load(MODEL_FILE)
    version = model_version(bundle)
    inference = build_inference(observations, current, target_weather, bundle)
    if inference is None:
        raise SystemExit(f"Not enough saved observations to predict {target}")

    result = predict(inference, bundle, output_file, version)
    print(f"Saved replay forecast: {output_file}")
    print(f"target={target}; rows={len(result)}; locations={result['location_key'].nunique()}")

    if args.compare_existing:
        existing_file = (
            DEFAULT_PREDICTIONS_DIR
            / f"traffic_aqi_live_forecast_{target:%Y-%m-%d_%H00}.csv"
        )
        if not existing_file.is_file():
            print(f"No existing forecast to compare: {existing_file}")
            return
        existing = pd.read_csv(existing_file, encoding="utf-8-sig")
        merged = result.merge(existing, on="location_key", suffixes=("_replay", "_old"))
        for column in [
            "predicted_currentspeed",
            "predicted_traffic_density",
            "predicted_us_aqi",
        ]:
            merged[f"abs_diff_{column}"] = (
                merged[f"{column}_replay"] - merged[f"{column}_old"]
            ).abs()
        print("Absolute difference vs existing forecast:")
        print(
            merged[
                [
                    "abs_diff_predicted_currentspeed",
                    "abs_diff_predicted_traffic_density",
                    "abs_diff_predicted_us_aqi",
                ]
            ]
            .describe()
            .to_string()
        )


if __name__ == "__main__":
    main()
