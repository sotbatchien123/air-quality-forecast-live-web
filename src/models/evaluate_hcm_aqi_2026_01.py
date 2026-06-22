from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from next_day_traffic_aqi import ROOT_DIR, district_key


DEFAULT_FORECAST = (
    ROOT_DIR
    / "data"
    / "processed"
    / "model_predictions"
    / "traffic_aqi_forecast_2026_01_xgboost.csv"
)
DEFAULT_ACTUAL = (
    ROOT_DIR
    / "data"
    / "raw"
    / "AQI"
    / "open_meteo_aqi_2026_01_hcm_output"
    / "aqi_ho_chi_minh_2026-01-01_to_2026-01-31_open_meteo.csv"
)
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "processed" / "model_evaluation"
AQI_BINS = [-np.inf, 50, 100, 150, 200, 300, np.inf]
AQI_LABELS = [
    "Good",
    "Moderate",
    "Unhealthy_for_sensitive_groups",
    "Unhealthy",
    "Very_unhealthy",
    "Hazardous",
]


def aqi_category(values: pd.Series | np.ndarray) -> pd.Categorical:
    return pd.cut(values, bins=AQI_BINS, labels=AQI_LABELS)


def metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    actual = frame["actual_us_aqi"].to_numpy(dtype=float)
    predicted = frame["predicted_us_aqi"].to_numpy(dtype=float)
    error = predicted - actual
    absolute_error = np.abs(error)
    return {
        "rows": len(frame),
        "actual_mean": float(actual.mean()),
        "predicted_mean": float(predicted.mean()),
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(math.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)),
        "mean_bias": float(error.mean()),
        "pearson_correlation": float(np.corrcoef(actual, predicted)[0, 1]),
        "median_absolute_error": float(np.median(absolute_error)),
        "p95_absolute_error": float(np.percentile(absolute_error, 95)),
        "max_absolute_error": float(absolute_error.max()),
        "within_10_aqi_pct": float(100 * np.mean(absolute_error <= 10)),
        "within_20_aqi_pct": float(100 * np.mean(absolute_error <= 20)),
        "aqi_category_accuracy_pct": float(
            100
            * np.mean(
                aqi_category(actual).astype(str)
                == aqi_category(predicted).astype(str)
            )
        ),
    }


def grouped_metrics(frame: pd.DataFrame, group_column: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group_value, group in frame.groupby(group_column, sort=True):
        rows.append({group_column: group_value, **metrics(group)})
    return pd.DataFrame(rows)


def evaluate(
    forecast_file: Path,
    actual_file: Path,
    output_dir: Path,
) -> None:
    forecast = pd.read_csv(forecast_file, encoding="utf-8-sig")
    forecast = forecast[forecast["province_key"] == "ho_chi_minh"].copy()
    forecast["target_timestamp"] = pd.to_datetime(
        forecast["target_timestamp"],
        errors="raise",
    )
    forecast["district_key"] = forecast["district_key"].map(district_key)
    if forecast.duplicated(["target_timestamp", "district_key"]).any():
        raise ValueError("Forecast contains duplicate timestamp/location keys")

    actual = pd.read_csv(actual_file, encoding="utf-8-sig")
    actual["target_timestamp"] = pd.to_datetime(actual["datetime"], errors="raise")
    actual["district_key"] = actual["location_name"].map(district_key)
    actual = actual.rename(columns={"us_aqi": "actual_us_aqi"})
    if actual.duplicated(["target_timestamp", "district_key"]).any():
        raise ValueError("Actual AQI contains duplicate timestamp/location keys")

    comparison = forecast.merge(
        actual[
            [
                "target_timestamp",
                "district_key",
                "location_name",
                "lat",
                "lon",
                "source_model",
                "pm10",
                "pm2_5",
                "actual_us_aqi",
            ]
        ],
        on=["target_timestamp", "district_key"],
        how="inner",
        validate="one_to_one",
    )
    if len(comparison) != len(forecast) or len(comparison) != len(actual):
        raise ValueError(
            f"Incomplete comparison join: forecast={len(forecast)}, "
            f"actual={len(actual)}, joined={len(comparison)}"
        )
    if comparison.isna().any().any():
        raise ValueError("Comparison contains missing values")

    comparison["date"] = comparison["target_timestamp"].dt.strftime("%Y-%m-%d")
    comparison["hour"] = comparison["target_timestamp"].dt.strftime("%H:%M")
    comparison["error"] = (
        comparison["predicted_us_aqi"] - comparison["actual_us_aqi"]
    )
    comparison["absolute_error"] = comparison["error"].abs()
    comparison["squared_error"] = comparison["error"] ** 2
    comparison["actual_aqi_category"] = aqi_category(
        comparison["actual_us_aqi"]
    ).astype(str)
    comparison["predicted_aqi_category"] = aqi_category(
        comparison["predicted_us_aqi"]
    ).astype(str)
    comparison["aqi_category_match"] = (
        comparison["actual_aqi_category"]
        == comparison["predicted_aqi_category"]
    )

    summary = pd.DataFrame([{"scope": "ho_chi_minh_2026_01", **metrics(comparison)}])
    daily = grouped_metrics(comparison, "date")
    district = grouped_metrics(comparison, "district_key")
    confusion = pd.crosstab(
        comparison["actual_aqi_category"],
        comparison["predicted_aqi_category"],
        rownames=["actual_aqi_category"],
        colnames=["predicted_aqi_category"],
        dropna=False,
    ).reset_index()

    output_dir.mkdir(parents=True, exist_ok=True)
    forecast.sort_values(["target_timestamp", "district_key"]).to_csv(
        output_dir / "hcm_traffic_aqi_forecast_2026_01_xgboost.csv",
        index=False,
        encoding="utf-8-sig",
    )
    comparison.sort_values(["target_timestamp", "district_key"]).to_csv(
        output_dir / "hcm_aqi_actual_vs_predicted_2026_01_xgboost.csv",
        index=False,
        encoding="utf-8-sig",
    )
    summary.to_csv(
        output_dir / "hcm_aqi_evaluation_summary_2026_01_xgboost.csv",
        index=False,
        encoding="utf-8-sig",
    )
    daily.to_csv(
        output_dir / "hcm_aqi_evaluation_by_date_2026_01_xgboost.csv",
        index=False,
        encoding="utf-8-sig",
    )
    district.to_csv(
        output_dir / "hcm_aqi_evaluation_by_district_2026_01_xgboost.csv",
        index=False,
        encoding="utf-8-sig",
    )
    confusion.to_csv(
        output_dir / "hcm_aqi_category_confusion_2026_01_xgboost.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print("AQI evaluation summary:")
    print(summary.to_string(index=False))
    print(f"Saved evaluation files to: {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare January 2026 HCMC XGBoost AQI forecasts with archived AQI"
    )
    parser.add_argument("--forecast-file", type=Path, default=DEFAULT_FORECAST)
    parser.add_argument("--actual-file", type=Path, default=DEFAULT_ACTUAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    evaluate(
        args.forecast_file.resolve(),
        args.actual_file.resolve(),
        args.output_dir.resolve(),
    )
