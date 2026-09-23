# Backend

Everything specific to the Python backend lives in this folder: source, dependencies, .env configuration, tests, local datasets, cache, launchers, and deployment files. The shared tickets/ directory is a sibling of back/, frontend/, and ml/.

## Setup and configuration

From the repository root, create back/.venv and install back/requirements.txt using that environment's Python. Run back/run.ps1 on Windows or bash back/run.sh on Linux. Both launchers accept --reload and automatically load back/.env if present.

For direct startup from the repository root, with the backend environment active:

```sh
python -m uvicorn back.main:app --env-file back/.env --host 127.0.0.1 --port 8000
```

Omit --env-file if no .env has been created. Interactive API: http://127.0.0.1:8000/docs.

Copy .env.example to .env in this folder. All relative configuration paths resolve from back/, independent of the launch directory.

| Setting | Default | Meaning |
| --- | --- | --- |
| ML_STEP | 6 | Samples per hour, controlled by backend/ML |
| TURBINE_TIMEZONE | Asia/Almaty | Provisional dataset timezone; confirm with data owner |
| DATASETS_DIR | back/data | Original turbine CSVs |
| TICKETS_DIR | root tickets/ | Shared worker exchange |
| WEATHER_CACHE_DIR | back/.cache/weather | Weather response cache |
| WEATHER_MODEL | gfs_global | Online forecast model |
| WEATHER_WIND_VARIABLE | wind_speed_100m | Configurable weather predictor height |
| USE_DATASET_FOR_HORIZON | true | Permit observed CSV weather for historical known-weather tests |
| FORECAST_AVAILABILITY_MARGIN_HOURS | 12 | Conservative archived forecast availability allowance |
| TICKET_TIMEOUT_SECONDS | 1800 | Worker response deadline |
| RESULT_TTL_SECONDS | 1800 | Finished-result retrieval window |
| MAX_ACTIVE_TICKETS | 32 | Submission limit |
| CORS_ORIGINS | * | Allowed frontend origins |

ML_STEP must be a positive divisor of 60: 1 means hourly, 3 every 20 minutes, 6 every 10 minutes, and 12 every 5 minutes. Set it in back/.env and restart backend when the ML teammate changes their input requirements. Frontend neither sends nor selects it.

Place the two supplied CSVs under data/, with filenames ending in turbine 1.csv and turbine 2.csv. CSVs are ignored by Git; copy them separately when deploying. An absolute DATASETS_DIR may point to another dataset location.

## Frontend HTTP contract

### GET /api/bootstrap

Call once when the page opens. Returns:

- prediction_hours: always 48.
- timezone: explicit timezone for naive input dates.
- turbines: A/B, coordinates, source dataset coverage, and suggested horizon start.
- defaults: only turbine_id, horizon_start, and history_days. This object can be posted directly.
- limits.history_days: minimum 1, maximum 90.
- poll_interval_ms: 1000.

Each turbine's suggested start is midnight after its last dataset day. Bootstrap only reads metadata; it does not start a prediction. Frontend can POST defaults if it wants an automatic initial forecast.

No sampling selector or step value is exposed in bootstrap.

### POST /api/tickets

```json
{
  "turbine_id": "A",
  "horizon_start": "2026-02-05",
  "history_days": 30
}
```

- turbine_id: A or B; 1/2 are accepted aliases.
- horizon_start: date or whole-hour ISO datetime. A date means midnight in TURBINE_TIMEZONE. An explicit offset is accepted.
- history_days: 1–90, default 30.

The prediction horizon is always 48 hours. Extra fields, including step and horizon_hours, return HTTP 422.

HTTP 202 returns ticket_id, status=preparing, poll_url, and descriptive input metadata. Frontend retains its own request history.

### GET /api/tickets/{ticket_id}

- 202 preparing: backend is collecting weather/building input.
- 202 pending: data.csv exists and response.json is not ready.
- 200: exact response.json bytes, with application/json content type.
- 404: unknown or expired ticket.
- 422/502/503: input, provider, or configuration failure.
- 504: worker response timed out.

Error bodies contain error.code and error.message. Poll approximately once a second. A pending state does not claim that ML execution has started; the file interface does not provide that signal.

GET /api/turbines also exposes the turbine catalog. GET /health checks the backend process, not the independent worker.

## ML file interface

```text
tickets/<id>/
    data.csv
    response.json
```

The backend publishes data.csv using a temporary file and atomic rename. The worker must do the same for response.json. No request.json is created.

CSV columns:

```csv
timestamp,phase,turbine_id,wind_speed_ms,temperature_c,weather_source
```

Timestamps include UTC offsets, are ascending, and use the backend-configured interval. phase is history before the horizon and forecast at/after it. Units are m/s and Celsius. No power/MWh columns are included. ML handles training, prediction units, and the response schema.

Backend returns valid standard JSON unchanged. Frontend and ML should agree on output timestamps so a shorter display window does not depend on the model's output cadence. [Worker instructions](../ml/README.md).

## Example and weather sources

For February 5, 30 history days, and ML_STEP=6:

| Portion | Interval | Rows |
| --- | --- | --- |
| Turbine history | January 6–31 | 3,744 |
| Internet history | February 1–4 | 576 |
| Forecast inputs | February 5–6 | 288 |
| Total | January 6 to February 7, exclusive | 4,608 |

This exact example was verified with the real turbine A data and weather API. Internal gaps in other windows are filled from online weather as well.

Native ten-minute measurements are preserved. Coarser grids aggregate observations; finer grids interpolate between adjacent observations. Online weather is hourly, so finer grids use linear interpolation and mark it in weather_source. Interpolation does not add independent meteorological observations.

Historical internet inputs use Open-Meteo Previous Runs with explicit GFS selection. Upcoming points can use its live Forecast API. The configured wind height must be agreed with ML. Source labels distinguish dataset measurements, aggregation/interpolation, archived lead offsets, and live forecasts. [Previous Runs documentation](https://open-meteo.com/en/docs/previous-runs-api), [Forecast documentation](https://open-meteo.com/en/docs).

Archived offsets are relative to individual target hours. Backend selects older offsets with the configured availability margin, including both interpolation endpoints. This is a conservative policy assumption, not a verification of exact historical publication timestamps.

Observed CSV weather inside the forecast horizon is a known-weather diagnostic. Set USE_DATASET_FOR_HORIZON=false on the backend for archived-weather forecasting backtests.

## Lifecycle, tests, and deployment

No user-history database is used. Active preparation state is in memory; published CSV/results survive restart. Interrupted preparation before CSV publication must be resubmitted. Finished results remain temporarily for frontend retrieval and are then cleaned up.

With the backend virtual environment active, from the repository root:

```sh
python -m pip install -r back/requirements-dev.txt
python -m pytest -c back/pytest.ini -q
```

Tests cover server-controlled sampling, rejection of frontend overrides, bootstrap defaults, exact windows, weather-only input, interpolation, cutoff selection, polling, atomic publication, JSON passthrough, timeouts, recovery, and cleanup.

Deployment assets live in deploy/. The systemd service runs /data/app/back/.venv/bin/python, reads /data/app/back/.env, and exposes localhost:8000 behind Caddy. ML watches /data/app/tickets independently. Use one backend process for this prototype.
