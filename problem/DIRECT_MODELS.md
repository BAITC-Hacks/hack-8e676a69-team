# Current forecasting models

The default inference bundle is `models_direct_missing/`. Each turbine has
48 independent CatBoost regressors (one for each forecast hour) and one SARIMAX.
All models are trained offline. Requests need only the supplied historical CSV;
no future weather, database, previous request state, or retraining is required.

## Run from the repository root

```bash
source ./venv/bin/activate
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=4 python -u problem/train_direct.py
python problem/predict.py --input problem/examples/context.csv --output problem/examples/predictions_direct_missing.csv
python problem/plot_direct.py
python -m unittest discover -s problem -p 'test_*.py' -v
```

Training progress is in the terminal and `reports/direct_missing/training.log`.
The current models retain 168 hours of context. A 30-day window is not part of
this experiment.

## CSV contract

```csv
turbine_id,timestamp,power,wind_speed,temperature
1,2026-01-25 00:00:00,0.31,7.2,-2.1
1,2026-01-25 01:00:00,,,
1,2026-01-25 02:00:00,0.35,7.6,-2.0
```

- One row is a completed hourly interval, timestamped at its start.
- Power is normalized to [0,1]; wind speed is m/s; temperature is Celsius.
- Use the source/site clock, without a timezone suffix. The source timezone is
  unknown, so the pipeline does not guess a UTC conversion.
- Supply the last 168 hourly slots per turbine, up to 336 rows for both.
  Earlier rows are ignored. One-turbine requests are also supported.
- Origin is the first predicted hour; by default it is the latest timestamp
  across the input plus one hour. Specify `--origin '2026-02-01 00:00:00'` if
  trailing hours are absent. Both turbines share the same origin.
- Future rows, duplicate turbine/timestamp pairs, and off-grid times are rejected.
- At least 24 observed power hours in the context, including one in the last
  24 hours, are required. Missing or stale context produces a clear error.
- Production bundles require origins on or after February 1, 2026. To reproduce
  January inference, select `--model-dir problem/evaluation_models_direct_missing`.

## Missing measurements remain missing

Leave gaps blank or omit the missing rows; the adapter restores the hourly grid.
Do not forward-fill upstream: the model cannot distinguish artificial values
from real observations once that information is lost.

CatBoost receives NaN for missing lags. Rolling summaries use only observed
values, alongside observation-coverage features. Last-observed value and its age
are separate features; they do not fill the time series.

SARIMAX retains NaN power values during both training and inference. Its Kalman
filter propagates the state without a measurement update during a gap. It does
not learn fabricated constant observations. Calendar inputs are always known.

Missing targets are never replaced: CatBoost skips missing labels, SARIMAX
handles them in its likelihood, and evaluation excludes them. The existing
hourly quality rule remains: fewer than four of six expected 10-minute samples
makes the hourly aggregate missing. Original source CSVs are unchanged.

## Training and validation

All 48 CatBoost models use the same past context. They independently predict
their target hour; predictions are not fed into subsequent horizons. Calendar
features encode annual/daily seasonality. The constant horizon column is removed
from individual models.

Each horizon selects its tree count on December 2025 with depth 6, learning rate
0.04, L2 10, seed 42, and at most 800 trees. Forecast origins are sampled every
six hours. Entire training target windows end before validation boundaries.

SARIMAX compares orders (1,0,0) and (2,0,1) on December with gaps preserved.
Annual and daily Fourier regressors provide seasonality. Evaluation bundles are
refitted through December 31 and remain fixed across 30 January forecast origins.
Production bundles are then refitted through January 31 with selected settings.

January was inspected before this experiment. These are development comparisons,
not a fresh untouched test. Flat long-horizon predictions may remain because
future wind is unknown. Independent horizons can produce jagged trajectories;
visual complexity is not proof of accuracy.

## Output and deployment

The default request returns 192 rows for two turbines: 48 hours x two methods
x two turbines. Columns:
`turbine_id,forecast_origin,timestamp,horizon,model,predicted_power`.

Model names are `catboost_direct_missing` and `sarimax_direct_missing`.
Use `--model catboost` or `--model sarimax` to select one method.

For Python, call `predict_csv(path, model_dir, origin)` with
`models_direct_missing`. The manifest selects the correct preprocessing policy.
A service may cache `DirectCatBoost(folder)` to avoid loading all models on each
request; use `context_at(history, origin, gap_policy='preserve')` and
`features(...)` to build its inputs.

Deploy `forecasting.py`, `predict.py`, the model bundle, and dependencies in
`requirements-training.txt`. Training CSVs are not needed for inference.

## Artifacts and retained comparisons

- `models_direct_missing/`: current production bundle.
- `evaluation_models_direct_missing/`: current pre-January evaluation bundle.
- `reports/direct_missing/training.log`: all training progress.
- `reports/direct_missing/comparison_metrics.csv`: versions and baselines.
- `reports/direct_missing/metrics_by_horizon.csv`: errors for individual hours.
- `reports/direct_missing/comparison_predictions.csv`: January truth/predictions.
- `reports/direct_missing/comparison_windows.png`, `mae_by_horizon.png`: charts.
- `examples/predictions_direct_missing.csv`: unscored February 1–2 output.
- `models/`: original shared CatBoost and SARIMAX using forward-fill.
- `models_direct/`: intermediate separate-horizon CatBoost using forward-fill.

Old bundles remain selectable with `--model-dir problem/models` or
`--model-dir problem/models_direct`. Their original preprocessing is preserved
by their manifests for reproducible comparison. They are not the new default.
