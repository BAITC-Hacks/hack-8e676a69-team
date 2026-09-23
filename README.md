# HackAlem — wind forecasting

Team: Порнофильмы. Selected track: Энергетика.

```text
frontend/  Vue frontend
back/      FastAPI, dependencies, configuration, tests, data, and deployment
ml/        prediction worker
tickets/   shared data.csv → response.json exchange
```

The backend always prepares a 48-hour prediction window. Frontend chooses which part to display and stores user request history. The ML teammate controls sampling through backend configuration.

## Frontend API

1. GET /api/bootstrap when the site opens: turbines, dataset coverage, timezone, history-day limits, and ready-to-submit defaults.
2. POST /api/tickets to request a forecast.
3. Poll GET /api/tickets/{id}: 202 while preparing/pending, then 200 with the worker's unchanged JSON.

The POST body contains only:

```json
{
  "turbine_id": "A",
  "horizon_start": "2026-02-05",
  "history_days": 30
}
```

Sampling and prediction length are server-controlled. ML_STEP=6 in back/.env means one input row every ten minutes. Changing it requires no frontend change.

## Start the backend

From the repository root:

```sh
python -m venv back/.venv
```

On Windows:

```powershell
.\back\.venv\Scripts\python.exe -m pip install -r back\requirements.txt
.\back\run.ps1 --reload
```

On Linux/macOS:

```sh
back/.venv/bin/python -m pip install -r back/requirements.txt
bash back/run.sh --reload
```

Put the two original turbine CSVs in back/data/, or configure DATASETS_DIR in back/.env. Copy back/.env.example to back/.env for configuration. Relative configured paths resolve from back/. Confirm the source timestamps' timezone; the provisional default is Asia/Almaty.

Interactive API: http://127.0.0.1:8000/docs.

[Backend setup and API contract](back/README.md) · [ML handoff](ml/README.md)

## File interface and validation

Each tickets/<id>/ folder contains data.csv from backend and response.json from ML. The CSV has weather only; no power/MWh labels or request.json. Backend atomically publishes complete input, validates output JSON syntax, and forwards it without a wrapper.

Native ten-minute measurements are preserved. Internet weather is interpolated from hourly forecasts when finer sampling is required, with explicit source labels. Frontend can filter output timestamps without depending on input sampling.

Backend tests and dependencies live under back/. Run them using its virtual environment:

```sh
python -m pip install -r back/requirements-dev.txt
python -m pytest -c back/pytest.ini -q
```

The real turbine-A / February-5 example was checked against Open-Meteo: 30 history days plus 48 forecast hours produced 4,608 rows at ML_STEP=6. Fixture JSON verified the handoff; these checks do not claim ML prediction accuracy.

## Deployment

Backend deployment files are in back/deploy/. The service uses back/.venv, reads back/.env, and listens on localhost:8000 behind Caddy. ML runs independently against the root tickets/ directory.

Planned frontend URL: [HackAlem demo](https://hackalem-pornofilms.polandcentral.cloudapp.azure.com). Deployment has not been verified by these local checks.

See [DISCLOSURE.md](DISCLOSURE.md) for component disclosure.
