# Next-Day Traffic and AQI Model

This model predicts the same hour on the following day for every location.

## Targets

- `target_currentspeed`
- `target_traffic_density`
- `target_us_aqi`

## Features

- Next-day weather for the target hour
- Traffic and AQI from the same hour one day earlier
- Rolling 24-hour traffic and AQI statistics
- Population, vehicle count, area, and tree/green-area features
- Target-hour and calendar seasonality

The model does not use `pollution_index_scaled` as an input feature.

## Train

```powershell
python src\models\next_day_traffic_aqi.py train
```

The default temporal holdout is December 2025. Training targets end on
November 30, 2025.

Training creates two bundles:

- `model_bundle.joblib`: holdout-safe model trained before December, used for
  evaluation and historical prediction.
- `model_bundle_full.joblib`: production model refit on all available labeled
  rows through December 31, used by the `forecast` command.

## Historical prediction

```powershell
python src\models\next_day_traffic_aqi.py predict --target-date 2025-12-31
```

The command uses observations from the previous day and weather for the target
day, then writes predictions to `data/processed/model_predictions`.

## Monthly backtest

```powershell
python src\models\next_day_traffic_aqi.py backtest `
  --first-test-month 2025-03 `
  --last-test-month 2025-12
```

Each month is tested only with models trained on earlier months. Reports include
monthly metrics, per-province metrics, actual-vs-predicted distributions, and a
combined summary.

## Next-day forecast

For a backtest where next-day weather already exists in project history:

```powershell
python src\models\next_day_traffic_aqi.py forecast --current-date 2025-12-30
```

For a real future date, provide a 24-row weather forecast CSV:

```powershell
python src\models\next_day_traffic_aqi.py forecast `
  --current-date 2025-12-31 `
  --weather-file path\to\weather_forecast_2026-01-01.csv
```

The weather CSV must contain `date`, `hour`, `temperature_2m`,
`relative_humidity_2m`, `precipitation`, `wind_speed_10m`, and `cloud_cover`.

## Important assumptions

- Current project weather is the Ho Chi Minh City weather series reused for all
  five provinces.
- AQI is Open-Meteo CAMS Global modeled data, not monitoring-station data.
- The saved model is trained only on targets before December 2025 so December
  remains a clean temporal holdout.
