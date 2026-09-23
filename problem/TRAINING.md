# Turbine forecasting: CatBoost and SARIMAX

Current default: see [DIRECT_MODELS.md](DIRECT_MODELS.md). The latest models use
48 separate CatBoost horizons and refitted SARIMAX with missing measurements
preserved, not forward-filled. `predict.py` defaults to `models_direct_missing/`.
The results and forward-fill description below document the original baseline;
its saved artifacts remain in `models/` and can be selected with `--model-dir`.
The shared `train.py` code now defaults to preserving gaps if explicitly rerun.

Both models are trained offline. Each inference request supplies only an hourly
CSV containing past measurements. No database, saved previous request state,
retraining, internet access, API key, or future weather is required.

## Run from the repository root

```bash
source ./venv/bin/activate
python -m pip install -r problem/requirements-training.txt
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=4 python -u problem/train.py
python problem/predict.py --model-dir problem/models --input problem/examples/context.csv --output problem/examples/predictions.csv
python -m unittest discover -s problem -p 'test_*.py' -v
```

Training progress appears in the terminal and `problem/reports/training.log`.
CatBoost prints progress every 50 trees; SARIMAX prints every 10 optimizer steps.
Defaults: four CatBoost CPU threads, at most 800 trees during tuning, training
forecast origins every six hours. Use `python problem/train.py --help` for flags.
A repeated training run replaces generated artifacts, never the source CSVs.

## Shared backend CSV contract

```csv
turbine_id,timestamp,power,wind_speed,temperature
1,2026-01-25 00:00:00,0.31,7.2,-2.1
1,2026-01-25 01:00:00,0.35,7.6,-2.0
```

- `turbine_id`: 1 or 2. A request may contain one or both turbines.
- `timestamp`: start of a completed hourly interval, on a whole-hour grid.
- `power`: hourly mean normalized active power, in [0, 1].
- `wind_speed`: hourly mean m/s; `temperature`: hourly mean degrees Celsius.
- Use the SAME source/site clock as training. The source files do not specify
  their timezone. No UTC conversion is guessed; timezone-aware inputs are rejected.
- The forecast origin is the first predicted hour. By default it is the latest
  timestamp in the combined CSV plus one hour. Use `--origin '2026-02-01 00:00:00'`
  to specify it explicitly, especially when trailing rows are absent.
- All supplied timestamps must be strictly before the origin. Future rows are
  rejected. Both turbines use the same origin.
- Default context is 168 consecutive hours (one week), ending one hour before
  origin: up to 168 rows per turbine / 336 for two turbines. Earlier rows are ignored.
- Missing hours and missing numeric inputs are forward-filled inside this window,
  using only earlier supplied values. Leading missing values remain NaN. Keep
  missing values blank in the CSV; the ML adapter performs filling so it can track
  original observation coverage and staleness.
- At least 24 genuinely observed power hours in the window and at least one in
  its final 24 hours are required. Insufficient/stale context raises a clear error;
  it is not silently converted into fake telemetry. A full week is recommended.
- Each model returns 48 predictions per turbine: 192 rows for both methods and
  both turbines. Outputs are clipped to [0, 1], matching the observed normalization.
- Production models were trained through January 31, 2026, so the CLI rejects
  origins before February 1. Use `--model-dir problem/evaluation_models` for the
  January evaluation model version, trained only through December 31.

```csv
turbine_id,forecast_origin,timestamp,horizon,model,predicted_power
1,2026-02-01 00:00:00,2026-02-01 00:00:00,1,catboost,0.28
```

The first prediction is the interval [origin, origin+1h); horizon 48 starts at
origin+47h. The same feature-building code is used during training and inference.

## Model design

CatBoost uses one multi-horizon regressor per turbine. Each row combines context
lags and rolling summaries, missing-observation coverage, staleness, horizon
(1..48), month, and annual/daily Fourier features. History is anchored at the
request origin for every horizon. No recursively predicted power is required.
Training excludes missing target values. Early stopping selects the number of
trees on December validation; later fits use that fixed tree count.

SARIMAX uses a separate parameter set per turbine. Orders (1,0,0) and (2,0,1) are
compared on December rolling-origin RMSE. Annual seasonality is represented with
two Fourier harmonics and daily seasonality with one harmonic, supplied as
deterministic exogenous variables. The seasonal ARIMA order is (0,0,0,0): this is
seasonal regression with ARMA errors inside SARIMAX, not a huge 8,760-hour seasonal
AR process. No future measured weather is needed. At inference, a fresh model
filters the supplied context using fixed learned parameters and forecasts 48h.
There is no optimizer call and no dependence on the last request. JSON artifacts
contain the parameters and specification, not the training series or its state.

Forward-fill is also applied to SARIMAX training inputs, as requested. In
particular, turbine 1 has a very long historical outage (~41.6 days), which
creates a long constant segment after filling and may bias dynamics. CatBoost
does not use imputed targets. Evaluation for both models uses only observed
targets, never a forward-filled ground truth.

## Data preparation and honest evaluation

1. Verify the source timestamps and normalized power. Reindex to an hourly grid.
2. Hourly values are averages of available 10-minute measurements. Hours with
   fewer than four observations are marked missing; no target interpolation.
3. Tune using data before December 1, 2025, with December as validation. Entire
   48-hour training target windows must end before the validation boundary.
4. Lock settings and refit through December 31. Evaluate 30 daily origins,
   January 1 through January 30; each predicts 48h, ending no later than Jan 31.
   Models remain fixed. For each origin, only its supplied past-week context is
   used. Later January contexts can include newly observed January telemetry,
   exactly as in the intended production workflow.
5. Report MAE/RMSE over horizons 1-24, 25-48 and 1-48, alongside last-value
   persistence and past-week-mean baselines. Overlapping forecasts are counted
   as distinct origin/horizon pairs, not independent samples.
6. Refit production models through January 31 using the already selected settings.
   Their in-sample fit is NOT reported as holdout performance.

The supplied data contain no February labels. The example February 1-2 output
is an unscored production forecast. Daily restarts throughout February would
require new measured context. Model outputs must not be mislabeled as observations.

These artifacts implement the requested history-only deployment. The original
hackathon case additionally requires archived weather forecasts available at
each origin; that weather acquisition/conditioning is NOT implemented here.

## Artifacts

- `models/turbine_{1,2}/catboost.cbm`: production CatBoost models.
- `models/turbine_{1,2}/sarimax.json`: production SARIMAX parameters.
- `models/turbine_{1,2}/metadata.json`: cutoff, feature schema, versions, selection.
- `evaluation_models/`: frozen pre-January models for holdout reproduction.
- `prepared/turbine_{1,2}_hourly.csv`: hourly observations, unfilled targets, counts.
- `reports/metrics.csv`: measured January errors, including baselines.
- `reports/turbine_*_holdout_predictions.csv`: origin/horizon predictions and truth.
- `reports/holdout_metrics.png`, `reports/holdout_first_forecast.png`: evaluation plots.
- `reports/turbine_*_feature_importance.csv`: CatBoost feature importance.
- `reports/data_audit.json`, `reports/run_summary.json`, `reports/training.log`.
- `examples/context.csv`: common backend input from the final available week.
- `examples/predictions.csv`: generated separately with `predict.py`.

To deploy, copy `forecasting.py`, `predict.py`, `models/`, and the pinned
requirements. Source datasets and the training script are not needed for inference.
