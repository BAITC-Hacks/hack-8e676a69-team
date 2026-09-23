# FastAPI backend contract

The backend builds a weather-only CSV, publishes it in a ticket directory, and returns the ML worker's JSON through HTTP. It does not train a model or keep a user-history database.

## Run

From the repository root, with the virtual environment active:

```sh
python -m uvicorn back.main:app --host 127.0.0.1 --port 8000 --reload
```

Interactive API: http://127.0.0.1:8000/docs. If using a local .env file, add --env-file .env. The systemd service reads /data/app/.env directly.

Copy .env.example to .env to customize paths and settings. Confirm TURBINE_TIMEZONE with the data owner. Asia/Almaty is a location-based default: UTC+5 in February 2026; the CSV files do not declare a timezone. All exported timestamps include their UTC offset.

## HTTP

### GET /api/bootstrap — call once when the site opens

Returns turbine options and dataset coverage, the configured timezone, a ready-to-submit defaults object, history-day limits, step/interval options, prediction_hours=48, and poll_interval_ms=1000. Each turbine includes its own suggested start date: midnight after its last dataset day.

The frontend can populate its controls directly from this response. To show an initial forecast automatically, POST the defaults object to /api/tickets, then poll the returned poll_url. No weather/model job is started merely by fetching bootstrap metadata.

### POST /api/tickets

```json
{
  "turbine_id": "A",
  "horizon_start": "2026-02-05",
  "history_days": 30,
  "step": 6
}
```

- turbine_id: A or B, mapped to the supplied turbine 1/2 CSVs. 1 and 2 are accepted aliases.
- horizon_start: a date or an ISO datetime. A date means midnight in TURBINE_TIMEZONE. Explicit offsets are accepted.
- Prediction is always 48 hours. Do not send horizon_hours; the frontend applies its chosen display window to the returned prediction timestamps.
- history_days: 1–90; default 30. The history is the exact preceding duration, including internet-filled gaps.
- step: samples per hour, default 6. Interval in minutes = 60 / step. It must divide 60: 1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, or 60.
- Dataset use in historical prediction windows is a backend setting: USE_DATASET_FOR_HORIZON=true by default. Set it false on the backend for archived-weather backtests. It is not a frontend request field.

The start must align to the chosen interval. Unknown fields and invalid inputs return HTTP 422.

HTTP 202 response:

```json
{
  "ticket_id": "a_generated_32_character_hex_id",
  "status": "preparing",
  "poll_url": "/api/tickets/a_generated_32_character_hex_id",
  "input": {
    "turbine_id": "A",
    "history_start": "2026-01-06T00:00:00+05:00",
    "horizon_start": "2026-02-05T00:00:00+05:00",
    "horizon_end_exclusive": "2026-02-07T00:00:00+05:00",
    "step": 6,
    "interval_minutes": 10,
    "history_rows": 4320,
    "forecast_rows": 288,
    "prediction_hours": 48,
    "timezone": "Asia/Almaty",
    "use_dataset_for_horizon": true
  }
}
```

The frontend keeps this request metadata in its own history.

### GET /api/tickets/{ticket_id}

- HTTP 202, status preparing: weather/input preparation is still running.
- HTTP 202, status pending: data.csv is published; response.json is not available yet. This does not claim that the ML worker has started.
- HTTP 200: the exact contents of response.json, with application/json content type. There is no backend wrapper or unit conversion.
- HTTP 404: unknown or expired ticket.
- HTTP 422/502/503: input/provider/configuration failure; JSON contains error.code and error.message.
- HTTP 504: no ML response before the processing timeout.

Pending responses include poll_after_ms=1000 and Retry-After: 1. The frontend can poll once per second and save the completed JSON locally. No ticket-list/history endpoint is needed.

### GET /api/turbines

Returns A/B, coordinates, dataset coverage, timezone, and the native ten-minute interval. GET /health checks that the backend is running; it does not claim the external ML worker is healthy.

## Filesystem handoff

```text
web/
back/
ml/
tickets/
  <ticket-id>/
    data.csv
    response.json
```

TICKETS_DIR must point to the same filesystem location for backend and worker. Backend writes data.csv.tmp, flushes/closes it, and atomically renames it to data.csv. The worker must wait for data.csv, then publish response.json using the same temporary-file-and-rename pattern. No request.json is created.

The worker owns the response schema. It must be valid JSON, including finite JSON numbers. The backend checks syntax and returns the original bytes. See [the ML handoff](../ml/README.md).

## CSV schema and timing

```csv
timestamp,phase,turbine_id,wind_speed_ms,temperature_c,weather_source
2026-01-06T00:00:00+05:00,history,A,5.04,0.36,dataset
```

- Every timestamp is explicit and timezone-aware.
- phase is history for timestamps strictly before horizon_start and forecast at/after it.
- Units are m/s and degrees Celsius.
- No power, energy, MWh, or target columns are read into this interface.
- The worker can infer the interval, history length, horizon, and turbine from this one file.
- Rows are ascending and evenly spaced; incomplete weather preparation produces an error instead of a partial data.csv.

For February 5, 30 prior days, a 48-hour horizon, and step=6:

| Portion | Interval | Rows |
| --- | --- | --- |
| Dataset history | January 6 00:00–January 31 23:50 | 3,744 |
| Internet history | February 1 00:00–February 4 23:50 | 576 |
| Forecast inputs | February 5 00:00–February 6 23:50 | 288 |
| Total | January 6 to February 7, exclusive | 4,608 |

This exact example was verified against turbine A's real CSV and the weather API. Other windows can have internal missing dataset observations, which are also filled from the internet.

Native ten-minute dataset values are preserved with step=6. Coarser bins average available measurements. Finer grids interpolate only between adjacent native measurements, and are labeled dataset_interpolated; missing observations are not silently bridged.

## Weather fetching

The backend uses Open-Meteo with explicit coordinates, GFS model selection, UTC API timestamps, m/s, and Celsius. The wind predictor defaults to 100 m and is configurable; confirm the appropriate predictor height with ML.

For a historical replay, missing history and forecast inputs come from archived forecasts. For upcoming dates, past gaps use the archive and future points can use the live forecast endpoint. Future requests outside the provider's available range fail clearly. Local measurements take priority in history; USE_DATASET_FOR_HORIZON controls their use in the forecast horizon.

Source labels distinguish dataset, dataset_aggregated, dataset_interpolated, open_meteo_archive_d1/d2/d3, and open_meteo_live. Subhourly internet values are linearly interpolated from hourly endpoints and carry an _interpolated suffix. These are not newly measured ten-minute weather observations.

Archived lead offsets are relative to each target hour, not a single common forecast issuance. The backend chooses older offsets separately for both endpoints needed for interpolation, using a configurable 12-hour availability margin. This is a conservative policy assumption, not an audit of exact historical publication timestamps. Dataset weather in the forecast horizon is an observed-weather diagnostic, not an end-to-end weather-forecast backtest. [Previous Runs documentation](https://open-meteo.com/en/docs/previous-runs-api), [Forecast documentation](https://open-meteo.com/en/docs).

Responses are cached under WEATHER_CACHE_DIR: archived queries for 24 hours, live queries for five minutes. Provider retries are bounded. Missing/null weather is reported as an error.

## Lifetime and deployment

Active preparation state is in memory. Published tickets survive backend restarts because data.csv and response.json remain on disk. Preparation interrupted before data.csv publication must be resubmitted.

Default worker timeout is 30 minutes. Completed results remain for 30 minutes after response.json is written; a background cleanup removes expired generated ticket folders. Retention is transport reliability, not user history. Cache and TTL settings are configurable in .env.example.

Use one backend process for this prototype. The ML worker runs independently and watches tickets/. The backend serves web/dist when present and Caddy can proxy localhost:8000. CORS is configurable for a separately hosted frontend.

## Checks

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

The tests cover the exact February 5 window, native sampling, interpolation, no energy columns, archived cutoff selection, HTTP polling, atomic handoff, error/timeout behavior, restart recovery, and scoped cleanup. ML prediction quality is outside these transport/input checks.
