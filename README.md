# HackAlem — wind forecast backend

Team: Порнофильмы. Track: Энергетика.

The FastAPI backend prepares weather inputs for a separately implemented Python ML worker. It always prepares a 48-hour prediction window. Frontend controls the displayed horizon and stores user request history.

Planned frontend deployment: [HackAlem demo](https://hackalem-pornofilms.polandcentral.cloudapp.azure.com). Deployment has not been verified by the backend implementation checks.

## Architecture

```text
web/                 frontend, communicating through HTTP
back/                FastAPI, dataset/weather input preparation
ml/                  teammate's prediction worker
tickets/<id>/
    data.csv         backend publishes weather only
    response.json    ML publishes its frontend-facing result
```

Backend accepts a turbine, horizon start, number of history days, and step (samples per hour). It combines native turbine weather with internet weather where needed, atomically publishes data.csv, and returns response.json unchanged when available. No request.json or user-history database is used.

## Run the backend

From this directory:

```sh
python -m venv .venv
```

Activate the environment: .venv/Scripts/Activate.ps1 on PowerShell, or source .venv/bin/activate on Linux/macOS.

```sh
python -m pip install -r requirements.txt
python -m uvicorn back.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000/docs for interactive requests. Optionally copy .env.example to .env, edit it, and add --env-file .env to the command.

Locally, CSVs are discovered under ../tracks/Энергетика. On the VM, set DATASETS_DIR=/data/datasets and put both original turbine CSVs there. Their filenames must end in turbine 1.csv and turbine 2.csv.

TICKETS_DIR must resolve to the same directory for backend and ML. The ML teammate starts their worker separately. The backend serves web/dist if a built frontend exists; otherwise its root returns service information.

## Frontend calls

1. GET /api/bootstrap on page open: turbine options, dataset coverage, timezone, sampling options, limits, and defaults.
2. POST /api/tickets with the following body; receive HTTP 202 and a ticket ID.
3. Poll GET /api/tickets/{id}: HTTP 202 while preparing/pending, HTTP 200 with the worker's exact JSON when complete.
4. Store the result in frontend history and display the requested subset of its 48-hour timestamps.

```json
{
  "turbine_id": "A",
  "horizon_start": "2026-02-05",
  "history_days": 30,
  "step": 6
}
```

Do not send a prediction length: the model window is fixed at 48 hours.

[Full HTTP, weather, and file contract](back/README.md) · [ML worker handoff](ml/README.md)

## Input details

The CSV columns are timestamp, phase, turbine_id, wind_speed_ms, temperature_c, and weather_source. No power or MWh labels are sent.

Step=6 means six rows per hour, or ten-minute spacing. For a February 5 start with 30 history days, the history is January 6–February 4; the prediction window is February 5–6. This produces 4,320 history rows plus 288 forecast rows.

Native ten-minute measurements are preserved. Internet forecasts are hourly and are interpolated for finer input grids; provenance marks that explicitly. The default timezone Asia/Almaty is a location-based assumption that must be confirmed against the dataset.

Historical forecast windows can use observed CSV weather under the requested known-weather test mode. Set USE_DATASET_FOR_HORIZON=false for an archived-weather forecast backtest. Archived forecast selection uses a conservative availability margin; exact historical publication timestamps are not supplied by the chosen endpoint.

## Validation

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

Tests cover bootstrap defaults, the fixed 48-hour contract, ten-minute sampling, the February 5 window, no energy columns, forecast cutoff selection, HTTP polling, atomic file handoff, passthrough JSON, errors, restart recovery, and cleanup.

The February 5 example was also run with turbine A's actual CSV and Open-Meteo: 4,608 complete weather rows were produced. A fixture worker reply verified transport. No ML model was run by these backend checks.

## Deployment

The supplied systemd unit launches back.main:app on 127.0.0.1:8000 behind Caddy. The ML worker independently watches /data/app/tickets. Use one backend process for this prototype.

Key settings are documented in .env.example. Completed responses are retained for 30 minutes by default so frontend polling can retrieve them, then cleaned up. API credentials and local configuration belong in environment variables, not frontend bundles.

Third-party and pre-competition components are described in [DISCLOSURE.md](DISCLOSURE.md).
