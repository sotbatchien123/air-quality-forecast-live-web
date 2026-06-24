"""Train cac bien the XGBoost next-day va weather-only.

Muc luc:
1. Tao XGBRegressor va ham tinh feature importance.
2. `train_variant()`: chia tap theo thoi gian, early stopping, luu artifact.
3. `train_all()`: train XGBoost next-day 43 feature va weather-only 19 feature.
4. `forecast_weather_period()`: du bao nhieu ngay khi chi co file weather.
5. CLI: `train-all` va `forecast-weather-period`.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from next_day_traffic_aqi import (
    FEATURE_COLUMNS,
    MODEL_DIR,
    ROOT_DIR,
    STATIC_COLUMNS,
    TARGET_COLUMNS,
    TARGET_TOLERANCES,
    WEATHER_COLUMNS,
    WEATHER_ONLY_FEATURE_COLUMNS,
    add_periodic_features,
    build_supervised_frame,
    build_weather_only_frame,
    clip_predictions,
    comparison_metrics,
    load_joined_history,
    regression_metrics,
    require_columns,
)


XGBOOST_DIR = MODEL_DIR / "xgboost"
DEFAULT_TEST_START = "2025-12-01"
DEFAULT_VALIDATION_START = "2025-11-01"
MAX_ESTIMATORS = 700


def create_xgboost_model(
    n_estimators: int = MAX_ESTIMATORS,
    early_stopping_rounds: int | None = None,
) -> XGBRegressor:
    return XGBRegressor(
        objective="reg:squarederror",
        n_estimators=n_estimators,
        learning_rate=0.05,
        max_depth=8,
        min_child_weight=20,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_alpha=0.05,
        reg_lambda=2.0,
        gamma=0.0,
        tree_method="hist",
        max_bin=256,
        n_jobs=min(8, max(1, (os.cpu_count() or 2) - 1)),
        random_state=42,
        eval_metric="mae",
        early_stopping_rounds=early_stopping_rounds,
    )


def gain_importance(model: XGBRegressor, features: list[str]) -> pd.DataFrame:
    scores = model.get_booster().get_score(importance_type="gain")
    return pd.DataFrame(
        {
            "feature": features,
            "gain": [float(scores.get(feature, 0.0)) for feature in features],
        }
    ).sort_values("gain", ascending=False)


def train_variant(
    name: str,
    frame: pd.DataFrame,
    feature_columns: list[str] | dict[str, list[str]],
    test_start: str,
    validation_start: str,
    output_dir: Path,
    include_persistence_baseline: bool,
    baseline_features: dict[str, str] | None = None,
) -> None:
    if isinstance(feature_columns, dict):
        feature_columns_by_target = feature_columns
        all_feature_columns = list(
            dict.fromkeys(
                feature
                for target in TARGET_COLUMNS
                for feature in feature_columns_by_target[target]
            )
        )
    else:
        feature_columns_by_target = {
            target: feature_columns for target in TARGET_COLUMNS
        }
        all_feature_columns = feature_columns

    test_timestamp = pd.Timestamp(test_start)
    validation_timestamp = pd.Timestamp(validation_start)
    if validation_timestamp >= test_timestamp:
        raise ValueError("validation-start must be before test-start")

    fit_mask = frame["target_timestamp"] < validation_timestamp
    validation_mask = (
        (frame["target_timestamp"] >= validation_timestamp)
        & (frame["target_timestamp"] < test_timestamp)
    )
    pretest_mask = frame["target_timestamp"] < test_timestamp
    test_mask = frame["target_timestamp"] >= test_timestamp
    if not fit_mask.any() or not validation_mask.any() or not test_mask.any():
        raise ValueError(
            f"Invalid temporal split for {name}: fit={int(fit_mask.sum())}, "
            f"validation={int(validation_mask.sum())}, test={int(test_mask.sum())}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_rows: list[dict[str, object]] = []
    importance_frames: list[pd.DataFrame] = []
    production_models: dict[str, XGBRegressor] = {}
    best_tree_counts: dict[str, int] = {}
    production_training_rows: dict[str, int] = {}
    predictions = frame.loc[
        test_mask,
        [
            "target_timestamp",
            "province_key",
            "district_key",
            "district",
            *TARGET_COLUMNS,
        ],
    ].copy()

    print(
        f"{name}: rows={len(frame):,}; fit={int(fit_mask.sum()):,}; "
        f"validation={int(validation_mask.sum()):,}; test={int(test_mask.sum()):,}"
    )
    selected_baselines = baseline_features or TARGET_COLUMNS
    for target in TARGET_COLUMNS:
        baseline_feature = selected_baselines[target]
        target_features = feature_columns_by_target[target]
        valid_mask = frame[[*target_features, target]].notna().all(axis=1)
        target_fit_mask = fit_mask & valid_mask
        target_validation_mask = validation_mask & valid_mask
        target_pretest_mask = pretest_mask & valid_mask
        target_test_mask = test_mask & valid_mask
        if not (
            target_fit_mask.any()
            and target_validation_mask.any()
            and target_test_mask.any()
        ):
            raise ValueError(f"No complete temporal partitions for {name}/{target}")

        print(f"Training {name}/{target} with early stopping...")
        model = create_xgboost_model(early_stopping_rounds=35)
        model.fit(
            frame.loc[target_fit_mask, target_features],
            frame.loc[target_fit_mask, target],
            eval_set=[
                (
                    frame.loc[target_validation_mask, target_features],
                    frame.loc[target_validation_mask, target],
                )
            ],
            verbose=False,
        )
        best_trees = int(model.best_iteration) + 1
        best_tree_counts[target] = best_trees

        evaluation_model = create_xgboost_model(n_estimators=best_trees)
        evaluation_model.fit(
            frame.loc[target_pretest_mask, target_features],
            frame.loc[target_pretest_mask, target],
            verbose=False,
        )

        actual = frame.loc[target_test_mask, target].to_numpy()
        predicted = clip_predictions(
            target,
            evaluation_model.predict(frame.loc[target_test_mask, target_features]),
        )
        scores = regression_metrics(actual, predicted)
        row: dict[str, object] = {
            "variant": name,
            "target": target,
            "fit_rows": int(target_fit_mask.sum()),
            "validation_rows": int(target_validation_mask.sum()),
            "test_rows": int(target_test_mask.sum()),
            "best_trees": best_trees,
            **scores,
            **comparison_metrics(
                actual,
                predicted,
                TARGET_TOLERANCES[target],
            ),
        }
        if include_persistence_baseline:
            baseline = clip_predictions(
                target,
                frame.loc[target_test_mask, baseline_feature].to_numpy(),
            )
            baseline_scores = regression_metrics(actual, baseline)
            row.update(
                {
                    "baseline_mae": baseline_scores["mae"],
                    "baseline_rmse": baseline_scores["rmse"],
                    "baseline_r2": baseline_scores["r2"],
                    "mae_improvement_pct": (
                        100
                        * (baseline_scores["mae"] - scores["mae"])
                        / baseline_scores["mae"]
                        if baseline_scores["mae"]
                        else 0.0
                    ),
                }
        )
        metrics_rows.append(row)
        prediction_column = f"predicted_{target.removeprefix('target_')}"
        predictions[prediction_column] = np.nan
        predictions.loc[target_test_mask[test_mask], prediction_column] = predicted

        importance = gain_importance(evaluation_model, target_features)
        importance.insert(0, "target", target)
        importance.insert(0, "variant", name)
        importance_frames.append(importance)

        print(
            f"  best_trees={best_trees}; MAE={scores['mae']:.4f}; "
            f"RMSE={scores['rmse']:.4f}; R2={scores['r2']:.4f}"
        )

        print(f"  Refitting {target} on all 2025 rows...")
        production_model = create_xgboost_model(n_estimators=best_trees)
        production_model.fit(
            frame.loc[valid_mask, target_features],
            frame.loc[valid_mask, target],
            verbose=False,
        )
        production_models[target] = production_model
        production_training_rows[target] = int(valid_mask.sum())

    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(
        output_dir / f"{name}_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    predictions.sort_values(
        ["target_timestamp", "province_key", "district_key"]
    ).to_csv(
        output_dir / f"{name}_holdout_predictions.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.concat(importance_frames, ignore_index=True).to_csv(
        output_dir / f"{name}_feature_importance.csv",
        index=False,
        encoding="utf-8-sig",
    )

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "algorithm": "XGBRegressor",
        "xgboost_version": __import__("xgboost").__version__,
        "variant": name,
        "fit_scope": "all_available_2025_rows",
        "training_rows": len(frame),
        "training_target_start": str(frame["target_timestamp"].min()),
        "training_target_end": str(frame["target_timestamp"].max()),
        "validation_start": str(validation_timestamp),
        "test_start": str(test_timestamp),
        "feature_count": len(all_feature_columns),
        "features": all_feature_columns,
        "feature_count_by_target": {
            target: len(features)
            for target, features in feature_columns_by_target.items()
        },
        "features_by_target": feature_columns_by_target,
        "targets": list(TARGET_COLUMNS),
        "best_tree_counts": best_tree_counts,
        "production_training_rows_by_target": production_training_rows,
        "parameters": production_models[next(iter(TARGET_COLUMNS))].get_params(),
        "weather_scope_note": (
            "The current project supplies Ho Chi Minh City weather for all five provinces."
        ),
        "aqi_source_note": (
            "Open-Meteo CAMS Global modeled AQI, not monitoring-station observations."
        ),
    }
    (output_dir / f"{name}_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    joblib.dump(
        {
            "models": production_models,
            "feature_columns": all_feature_columns,
            "feature_columns_by_target": feature_columns_by_target,
            "target_columns": list(TARGET_COLUMNS),
            "metadata": metadata,
        },
        output_dir / f"{name}_full.joblib",
        compress=3,
    )
    print(f"Saved {name} XGBoost artifacts to: {output_dir}")


def train_all(
    test_start: str,
    validation_start: str,
    output_dir: Path,
) -> None:
    history = load_joined_history()
    train_variant(
        name="xgboost_next_day",
        frame=build_supervised_frame(history),
        feature_columns=FEATURE_COLUMNS,
        test_start=test_start,
        validation_start=validation_start,
        output_dir=output_dir,
        include_persistence_baseline=True,
    )
    train_variant(
        name="xgboost_weather_only",
        frame=build_weather_only_frame(history),
        feature_columns=WEATHER_ONLY_FEATURE_COLUMNS,
        test_start=test_start,
        validation_start=validation_start,
        output_dir=output_dir,
        include_persistence_baseline=False,
    )


def forecast_weather_period(
    weather_file: Path,
    model_dir: Path,
    output_file: Path,
) -> None:
    bundle = joblib.load(model_dir / "xgboost_weather_only_full.joblib")
    weather = pd.read_csv(weather_file, encoding="utf-8-sig")
    require_columns(weather, ["date", "hour", *WEATHER_COLUMNS], weather_file)
    weather["target_timestamp"] = pd.to_datetime(
        weather["date"].astype(str) + " " + weather["hour"].astype(str),
        errors="raise",
    )
    weather = weather[["target_timestamp", *WEATHER_COLUMNS]].copy()
    if weather["target_timestamp"].duplicated().any() or weather.isna().any().any():
        raise ValueError("Weather period contains duplicate timestamps or missing values")

    expected = pd.date_range(
        weather["target_timestamp"].min(),
        weather["target_timestamp"].max(),
        freq="h",
    )
    if len(weather) != len(expected) or not np.array_equal(
        weather["target_timestamp"].sort_values().to_numpy(),
        expected.to_numpy(),
    ):
        raise ValueError("Weather period must contain one continuous row per hour")

    history = load_joined_history()
    locations = history.sort_values("timestamp").drop_duplicates(
        "location_key",
        keep="last",
    )[
        [
            "location_key",
            "province_key",
            "district_key",
            "district",
            *STATIC_COLUMNS,
        ]
    ]
    inference = locations.merge(weather, how="cross")
    for column in WEATHER_COLUMNS:
        inference[f"forecast_{column}"] = inference[column]
    add_periodic_features(inference)
    for column in bundle["feature_columns"]:
        inference[column] = pd.to_numeric(inference[column], errors="raise").astype(
            "float32"
        )

    result = inference[
        ["target_timestamp", "province_key", "district_key", "district"]
    ].copy()
    x = inference[bundle["feature_columns"]]
    for target, model in bundle["models"].items():
        result[f"predicted_{target.removeprefix('target_')}"] = clip_predictions(
            target,
            model.predict(x),
        )
    result = result.sort_values(
        ["target_timestamp", "province_key", "district_key"]
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_file, index=False, encoding="utf-8-sig")

    daily = result.assign(date=result["target_timestamp"].dt.strftime("%Y-%m-%d"))
    daily = daily.groupby(["date", "province_key"], as_index=False).agg(
        location_count=("district_key", "nunique"),
        predicted_currentspeed_mean=("predicted_currentspeed", "mean"),
        predicted_traffic_density_mean=("predicted_traffic_density", "mean"),
        predicted_us_aqi_mean=("predicted_us_aqi", "mean"),
    )
    daily_output = output_file.with_name(f"{output_file.stem}_daily_by_province.csv")
    daily.to_csv(daily_output, index=False, encoding="utf-8-sig")
    print(f"Saved {len(result):,} hourly XGBoost forecasts to: {output_file}")
    print(f"Saved {len(daily):,} daily summaries to: {daily_output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train XGBoost traffic and AQI models")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train-all")
    train_parser.add_argument("--test-start", default=DEFAULT_TEST_START)
    train_parser.add_argument("--validation-start", default=DEFAULT_VALIDATION_START)
    train_parser.add_argument("--output-dir", type=Path, default=XGBOOST_DIR)

    forecast_parser = subparsers.add_parser("forecast-weather-period")
    forecast_parser.add_argument("--weather-file", type=Path, required=True)
    forecast_parser.add_argument("--model-dir", type=Path, default=XGBOOST_DIR)
    forecast_parser.add_argument("--output-file", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.command == "train-all":
        train_all(
            args.test_start,
            args.validation_start,
            args.output_dir.resolve(),
        )
    else:
        forecast_weather_period(
            args.weather_file.resolve(),
            args.model_dir.resolve(),
            args.output_file.resolve(),
        )
