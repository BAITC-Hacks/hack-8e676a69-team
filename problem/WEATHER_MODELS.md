# Previous model: power history plus supplied future weather

**Superseded:** the current default excludes power from historical context.
See [WEATHER_CONTEXT_MODELS.md](WEATHER_CONTEXT_MODELS.md) for the latest model,
four-column CSV contract, commands, and results. This document describes the
retained earlier `models_weather_oracle/` bundle, which requires explicit selection.

Earlier bundle: `models_weather_oracle/`. There are
**two models total: one CatBoost for each turbine**, not 48 per turbine. The
same model predicts all 48 hourly values in one batch. Each input row includes
the forecast horizon, known calendar, historical context, and supplied weather.
No recursive feedback, online fitting, retained request state, or network calls.

## What changed

- Kept the missing-aware 168-hour context, coverage/staleness features, seasonal
  calendar features, and normalized-power target.
- Replaced 48 horizon-specific regressors with one horizon-conditioned regressor
  per turbine (111 numerical features, including horizon).
- Added future wind speed and ambient temperature from the existing local CSVs.
  Adjacent supplied weather hours, weather changes, and wind squared/cubed are
  additional features. There are no pressure/humidity/direction columns in the
  source, so none were invented. Future target power is never a feature.
- Training, validation and inference preserve NaNs. Missing labels are excluded.
  Hourly means still require at least four of six 10-minute measurements.

**Important:** source weather is recorded actual weather, not an archived
meteorological forecast. This is a perfect-weather-input (oracle) development
benchmark. The metrics do not estimate deployment accuracy with noisy forecasts.
Before operational use, retrain/evaluate with forecasts actually available at
each historical origin. Merely labeling the same inputs `forecast` does not
make the model forecast-calibrated. The target is normalized active power;
the dataset does not contain a separate turbine-efficiency measurement.

## One CSV in, 96 predictions out

Columns remain `turbine_id,timestamp,power,wind_speed,temperature`.
For each turbine supply 168 historical hourly slots and 48 future hourly rows:

| Rows | Power | Wind and temperature |
|---|---|---|
| Before origin | Observed, or blank if missing | Observed, or blank |
| Origin through origin + 47 h | Must be blank | Supplied weather inputs |

Up to 216 rows per turbine, 432 rows for two turbines. Missing historical rows
are restored as NaN. All 48 future rows must be present; individual weather
cells may be blank, but a wholly absent weather variable is rejected. Partial
missing weather is flagged in output and was not separately accuracy-benchmarked.
Wind is m/s; temperature is Celsius. Preserve source/site clock consistently.
Do not append measured future power. The adapter rejects it explicitly.

The origin must be supplied explicitly because the CSV now extends into the
future. Output is 48 rows per turbine with `predicted_power` in [0,1], source
labels, forecast origin, timestamp and horizon. No SARIMAX is run by default.

## Run the provided January example

```bash
source ./venv/bin/activate
python problem/predict.py \
  --input problem/examples/context_with_weather.csv \
  --output problem/examples/predictions_weather_oracle.csv \
  --origin '2026-01-22 00:00:00' \
  --weather-source recorded_oracle \
  --model-dir problem/evaluation_models_weather_oracle
```

`predict_weather.py` is an equivalent dedicated entry point. Python entry point:
`weather_forecasting.predict_csv(path, model_dir, origin, weather_source)`.

Evaluation models were fitted strictly before January 1. The default final
bundle was fitted through January 31, and only accepts origins on/after
February 1. Future February weather is not in the supplied raw dataset, so
there is no fabricated February example or claimed February accuracy.

For deployment, supply real forecast weather and declare `--weather-source
forecast`; this model can execute that input but has not been validated for its
distribution. Cache `WeatherCatBoost` instances in a service if needed. Deploy
`weather_forecasting.py`, `forecasting.py`, `catboost_benchmark.py` (shared batch
feature helpers), model directories, and `requirements-training.txt` dependencies.

## Training and results

```bash
source ./venv/bin/activate
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=4 PYTHONDONTWRITEBYTECODE=1 python -u problem/train_weather.py
python problem/plot_weather.py
python -m unittest discover -s problem -p 'test_*.py'
```

Training origins every six hours; windows do not cross partition boundaries.
Select tree count on December 2025, refit pre-January for evaluation, then refit
through January for the final bundle. January evaluation covers 30 daily origins
and the full 48-hour horizon, matching earlier comparisons. January was already
inspected, so it is a development set, not a new untouched final test.

| Turbine | History-only direct MAE / RMSE | Single model + actual weather MAE / RMSE | Trees |
|---|---|---|---:|
| 1 | 0.30348 / 0.34629 | 0.02737 / 0.05043 | 98 |
| 2 | 0.30054 / 0.34361 | 0.03130 / 0.06636 | 89 |

These gains involve both a model-structure change and new information. They
do not isolate the effect of simplifying the model alone. They demonstrate
strong mapping from concurrent recorded weather to output, not that future
weather can be predicted this accurately.

Artifacts: `reports/weather_oracle/training.log`, `comparison_metrics.csv`,
`comparison_predictions.csv`, `comparison_windows.png`, `run_summary.json`;
`models_weather_oracle/turbine_{1,2}/catboost.cbm` and matching metadata;
pre-January models under `evaluation_models_weather_oracle/`.

Earlier history-only bundles remain untouched. To use the old 48-model and
SARIMAX pipeline, explicitly select `--model-dir problem/models_direct_missing`
with a historical-only CSV. The multi-method history-only benchmark was stopped
when the task changed; its partial artifacts are not a completed ranking.
