# XGBoost Multisource Hourly Model

This model predicts current speed, traffic density, and US AQI one hour ahead
for every project location.

## Inputs

- Weather for the target hour.
- Weather, traffic, AQI, and pollutant lags at 1, 2, 3, 6, and 12 hours.
- Rolling means and standard deviations over 3, 6, and 12 hours.
- Population, vehicles, green space, coordinates, and calendar features.

The model uses 123 features and never uses target-hour traffic or AQI as input.

## Train

```powershell
python src\models\xgboost_multisource_hourly.py train
```

## Forecast the next hour

```powershell
python src\models\xgboost_multisource_hourly.py forecast-next-hour `
  --current-timestamp "2025-12-31 23:00" `
  --weather-file data\raw\weather\hcm_weather_2026_01.csv `
  --output-file data\processed\model_predictions\traffic_aqi_forecast_2026-01-01_00_xgboost_hourly.csv
```

Forecasting requires complete observations for the preceding 12 hours and one
weather row for the target hour.
