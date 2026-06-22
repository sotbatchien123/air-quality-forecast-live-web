# 2025 Monthly Backtest Assessment

## Validation protocol

- Expanding-window monthly backtest from March through December 2025.
- Each test month is predicted only by models trained on earlier months.
- Total evaluated rows: 477,360 per target.
- Baseline: the next day is equal to the same hour one day earlier.

## Overall results

| Target | MAE | RMSE | R2 | Baseline MAE | Improvement | Within tolerance |
|---|---:|---:|---:|---:|---:|---:|
| Current speed | 2.589 | 3.474 | 0.913 | 3.575 | 27.59% | 86.61% within 5 km/h |
| Traffic density | 0.048 | 0.068 | 0.852 | 0.067 | 28.38% | 65.06% within 0.05 |
| US AQI | 13.838 | 18.958 | 0.643 | 14.834 | 6.71% | 77.05% within 20 AQI |

## Fit to collected data

### Traffic speed

The output fits the collected data well. The mean bias is +0.308 km/h and the
model beats persistence in every tested month. May is the weakest month with
MAE 3.506, indicating a seasonal or data-regime change.

### Traffic density

The output is generally suitable. Mean bias is -0.0077 and R2 is 0.852. The
model is slightly worse than persistence in May, so sudden traffic-regime
changes remain a risk. Ho Chi Minh City has the largest density MAE at 0.056.

### US AQI

The output is suitable as an indicative forecast, not as a high-stakes alert.
The model improves MAE by only 6.71% over persistence and loses to persistence
in March, April, and July. It underestimates variability: predicted standard
deviation is 26.39 versus actual 31.74. Long An has the largest AQI MAE at
15.70, while Ho Chi Minh City has low average R2 across monthly folds.

## Important limitations

- One Ho Chi Minh City weather series is reused for all five provinces.
- AQI is modeled CAMS Global data from Open-Meteo, not station observations.
- The model predicts the usual pattern better than abrupt peaks.
- Province-specific weather and monitoring-station AQI should be added before
  using the AQI prediction for public-health warnings.
