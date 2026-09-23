# CatBoost ticket worker — integrated with `back/`

One bundled CatBoost per turbine (A → turbine 1, B → turbine 2), shared across
48 forecast hours. **No historical power/efficiency values are inputs.** Features
use only weather history, supplied future weather, calendar, and horizon.
The worker performs no training, NVIDIA calls, or weather downloads.

## Start for frontend testing

From the repository root:

```bash
source ./venv/bin/activate
python -m pip install -r back/requirements.txt
python -m uvicorn back.main:app --host 127.0.0.1 --port 8000
```

Add `--env-file back/.env` if configured. The existing `back/run.sh` and
`back/run.ps1` launchers use `back/.venv` instead, and load `back/.env` automatically.
**The backend now starts the worker automatically** (`INFERENCE_ENABLED=true`).
No second terminal/process is required. The frontend endpoints and POST schema
are unchanged: create a ticket, then poll until HTTP 200.

Before testing, place both original turbine CSVs in `back/data/` (filenames ending
in `turbine 1.csv` and `turbine 2.csv`), or set `DATASETS_DIR` to their directory.
Without those files, `/api/bootstrap` cannot load the turbine dataset catalog.
Models are shipped here under `models/`; `problem/` is not a runtime dependency.
Deploy the two `.cbm` files **and** `manifest.json`; SHA-256 is verified on startup.

## Shared folder and lifecycle

Default exchange: `tickets/<ticket_id>/data.csv` → `response.json`. It is not
`requests/` and needs no `request.json`. To use `requests/`, set
`TICKETS_DIR=../requests` in `back/.env`; both components read the same setting.
Relative environment paths resolve from `back/`.

Backend atomically publishes a completed `data.csv`. The worker ignores `.tmp`
inputs, takes an OS file lock, checks for an existing response, runs inference,
writes `response.json.tmp`, flushes/fsyncs it, then atomically renames it.
Locks release on process exit/crash; the `.inference.lock` file can safely remain.
Multiple worker processes do not intentionally process the same ticket twice.
Completed responses are not overwritten; existing backend TTL cleanup still applies.

For an independent worker, set `INFERENCE_ENABLED=false` in the backend and run:

```bash
python -m inference.main --watch --env-file back/.env
```

Omit `--env-file` if absent. Options: `--tickets-dir`, `--model-dir`, `--timezone`,
`--interval`. Without `--watch`, it drains ready tickets once and exits.
Use the **same timezone and ticket directory** as the API. `python inference/main.py`
is also supported. No API key is required for model inference.

## Exact model window and input alignment

The backend CSV contract remains:

```csv
timestamp,phase,turbine_id,wind_speed_ms,temperature_c,weather_source
```

No power field is written; any extra power/efficiency field is ignored by the
worker. IDs are A or B. Timestamp offsets are required. Wind is m/s and
temperature is Celsius. The earliest `forecast` timestamp is origin `T`.

- Context: weather from **T−168 hours, inclusive, to T, exclusive**.
- Future: weather from **T, inclusive, to T+48 hours, exclusive**.
- Example T = February 5, 2026 00:00 site time: context January 29–February 4;
  prediction/weather horizon February 5–6. Output hour 0 is February 5 00:00;
  hour 47 is February 6 23:00. There is no hour 48 prediction.
- Frontend `history_days` remains 1–90. Requests below seven days are expanded
  to seven; the POST response's input metadata reports the effective range.
  Longer CSV history is permitted but only the last seven days enter features.
- `ML_STEP=6` (default) sends ten-minute rows: at least 1,008 history + 288 future
  rows. These are converted to 168 + 48 hourly feature slots. Output is hourly
  regardless of input cadence; it does not contain 288 model predictions.
- Native ten-minute measurement hours are arithmetic means; fewer than four
  valid weather samples leave that hourly feature missing. For other input
  cadences the same two-thirds coverage rule is applied to the provided samples.
  Interpolated fine grids do not create independent measurements; native
  ten-minute input is recommended for alignment with training.
- Whole-hour weather-provider values are used directly for entirely provider-
  sourced hours. Synthetic sub-hourly interpolation is not averaged back into
  a different hourly weather forecast. Mixed measurement/provider hours are
  averaged and retain source labels in `data.csv`.
- Missing historical hours remain NaN (not forward-filled). Each weather
  variable needs at least 24 valid history hours, including one in the last day.
  All 48 future hourly intervals must be represented. Partially missing future
  values can remain NaN; an entirely missing variable is rejected.
- Offset-bearing input is converted to `TURBINE_TIMEZONE` **before removing the
  timezone for model features**, preserving the source/site calendar. The
  original source timezone still needs confirmation; Asia/Almaty is provisional.

Final models were trained through January 31, 2026. Earlier origins are allowed
for diagnostic/demo predictions, with a warning in the worker logs. They are
not unbiased historical validation because the model has seen that period in
training. The frontend JSON stays unchanged. After restarting the backend,
submit a new ticket; already-written error responses are not overwritten.

## Exact success response

```json
{
  "series": [
    {
      "id": "agent-ctboost",
      "name": "Main forecast",
      "color": "#157a65",
      "points": [{ "hour": 0, "value": 0.31 }]
    }
  ]
}
```

The example shows only one point; real responses always contain **48 points,
hours 0–47**. Values are finite normalized active power in [0,1], **not MW, MWh,
or measured turbine efficiency**. No additional success wrapper is added.
The backend forwards the exact bytes and the current frontend parser accepts
this shape unchanged. Failure JSON is `{"error":{"code":"inference_failed",
"message":"..."}}`, which the existing frontend handles as an error.

## Verification and limitations

```bash
python -m pip install -r back/requirements-dev.txt
python -m pytest -c back/pytest.ini back/tests -q
```

Tests execute the actual saved CatBoost models for both turbines with synthetic
offline weather, including embedded and standalone workers, HTTP POST/poll,
timestamp conversion, cutoff/window checks, hourly aggregation, strict output
schema, missing inputs, no-power invariance, partial files, locks, and restarts.
This validates integration, not live weather-provider availability or accuracy.

Training used **recorded future weather**. Real forecast skill is not validated;
the configured weather wind height (default 100 m) must be checked against the
turbine measurement height. `USE_DATASET_FOR_HORIZON=true` permits recorded
weather for known-weather diagnostic runs; `false` requires forecast inputs.
The backend's existing weather retrieval/source labels remain in place.
