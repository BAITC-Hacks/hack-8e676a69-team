# Current model: weather context, no power inputs

One CatBoost per turbine predicts the next 48 hourly normalized-power values.
The same model is shared across all horizons. **Power is used only as a
supervised training label and for scoring, never to create context or features.**

Inputs:

- Historical context: last 168 hourly slots of wind speed and temperature only.
- Forecast horizon: next 48 hourly wind-speed and temperature values.
- Known timestamps/calendar and forecast horizon.

The 80 features include weather lags, weather rolling summaries, weather
coverage/staleness, calendar, horizon, supplied future weather and derived
weather features. There are no power lags, power statistics, power coverage,
efficiency columns, or power-dependent context eligibility checks. Historical
weather is still used; this is not a future-weather-only model.

## CSV and inference

Required columns: `turbine_id,timestamp,wind_speed,temperature`.
There is **no required power column**. If an older CSV contains power or
efficiency columns, the new reader ignores them entirely. Per turbine, supply
168 historical slots and all 48 future hourly rows: up to 216 rows, or 432 for
two turbines. Output is 48 predictions per turbine, 96 total for both.

Wind is m/s; temperature is Celsius. Preserve source/site timestamps without
guessing a timezone conversion. `--origin` is the first predicted hour.
Historical missing rows/cells remain NaN. Each historical weather variable needs
24 observed hours in the week and at least one in the last day. Missing future
weather cells remain NaN; wholly absent variables are rejected. Accuracy under
large weather gaps has not been established. No filling or interpolation.

```bash
source ./venv/bin/activate
python problem/predict.py \
  --input problem/examples/weather_context_no_power.csv \
  --output problem/examples/predictions_weather_context_no_power.csv \
  --origin '2026-01-22 00:00:00' \
  --weather-source recorded_oracle \
  --model-dir problem/evaluation_models_weather_context_no_power
```

`predict.py` now defaults to `models_weather_context_no_power/`, the final
bundle fitted through January 31. It accepts origins from February 1 onward.
The January example must use the pre-January evaluation bundle shown above.
`predict_weather.py` is a dedicated entry point for the same new model.
Python entry point: `weather_context_forecasting.predict_csv(...)`;
`WeatherContextCatBoost.predict(history_weather, origins, future_weather)`
accepts arrays shaped N×168×2 and N×48×2 and returns N×48 predictions.

## Retraining and verification

```bash
source ./venv/bin/activate
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=4 PYTHONDONTWRITEBYTECODE=1 python -u problem/train_weather.py
python problem/plot_weather.py
python -m unittest discover -s problem -p 'test_*.py'
```

All data are local. The experiment uses **actual recorded future weather**, not
archived meteorological forecasts; these oracle-input metrics are optimistic
for deployment. Supplying real forecasts requires subsequent validation against
their errors. The target is normalized active power, not a separate measured
efficiency ratio. Source power remains necessary as the training target.

Tree-count selection: December 2025. Evaluation: 30 January daily origins, full
48-hour windows, same labels as prior comparisons. January is a development
set already inspected previously. Entire training windows end before validation
and test boundaries. Final models are refitted through January 31.

| Turbine | Previous, with power history: MAE / RMSE | New, without power history: MAE / RMSE |
|---|---|---|
| 1 | 0.027368 / 0.050430 | 0.027007 / 0.050716 |
| 2 | 0.031305 / 0.066365 | 0.031501 / 0.066348 |

Performance is essentially unchanged under recorded-weather inputs. This does
not establish that power history would be unhelpful with noisy real forecasts.

New artifacts: `models_weather_context_no_power/`,
`evaluation_models_weather_context_no_power/`,
`reports/weather_context_no_power/{training.log,comparison_metrics.csv,comparison_predictions.csv,comparison_windows.png,run_summary.json}`.
Old bundles and reports are retained. `train_weather.py --include-power-history`
explicitly reproduces the previous weather-oracle model; it is not the default.

Tests verify zero power features, independence of context eligibility/features
from all power values, weather-history sensitivity, missing-value preservation,
and identical saved-model predictions with no power column versus arbitrary
power/efficiency columns. Exactly one saved CatBoost exists per new turbine bundle.
