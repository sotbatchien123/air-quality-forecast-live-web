# XGBoost Traffic and AQI Models

This directory contains two production XGBoost bundles trained on all available
2025 rows for 65 locations across five provinces.

## Models

- `xgboost_next_day_full.joblib`: 43-feature next-day model using target-day
  weather, previous-day traffic/AQI, rolling statistics, calendar, population,
  vehicles, location, and green-space features.
- `xgboost_weather_only_full.joblib`: 19-feature multi-day model using weather,
  calendar, population, vehicles, location, and green-space features. It does
  not require future traffic or AQI observations.

Each bundle contains three independent `XGBRegressor` models for current speed,
traffic density, and US AQI.

## Temporal evaluation

- January-October 2025: fit early-stopping candidates.
- November 2025: select the number of boosting trees.
- January-November 2025: refit the evaluation model.
- December 2025: untouched temporal holdout.
- January-December 2025: refit the final production model.

## Train

```powershell
python src\models\xgboost_traffic_aqi.py train-all
```

## Forecast a weather period

```powershell
python src\models\xgboost_traffic_aqi.py forecast-weather-period `
  --weather-file data\raw\weather\hcm_weather_2026_01.csv `
  --output-file data\processed\model_predictions\traffic_aqi_forecast_2026_01_xgboost.csv
```

AQI values in the project come from Open-Meteo CAMS Global modeled data, and
the same Ho Chi Minh City weather series is currently reused for all provinces.
