# XGBoost Multisource Next-Day Model

This model predicts current speed, traffic density, and US AQI for the same
location and hour on the following day.

## Inputs

- Target-day weather: temperature, humidity, precipitation, wind speed, and
  cloud cover.
- Historical traffic: speed, free-flow speed, congestion, and density.
- Historical air quality: US AQI, PM10, PM2.5, CO, NO2, SO2, and ozone.
- Population, vehicles, area, green space, coordinates, and calendar features.

Traffic targets use 24, 48, and 72-hour lags plus rolling statistics. AQI uses
the selected 43-feature multisource set because adding 48-72-hour features made
the temporal holdout worse.

## Temporal evaluation

- January-October 2025: early-stopping fit.
- November 2025: tree-count validation.
- January-November 2025: holdout model fit.
- December 2025: untouched test period.
- Full 2025: final production refit.

## Train

```powershell
python src\models\xgboost_multisource_next_day.py
```

The model never uses target-day traffic or AQI as input. Only target-day
weather and observations available at least 24 hours before the target are
used.
