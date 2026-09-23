# Third-party component disclosure

Hackathon team: Порнофильмы.

## Prepared before the competition

The initial project contained generic FastAPI/SQLite/React/Vite infrastructure, image-upload and CV stubs, and Caddy/systemd deployment configuration. It contained no track-specific prediction model. Obsolete image/CV/SQLite code has been removed from the active repository.

## Implemented during the competition

- back/: weather-only input preparation, Open-Meteo retrieval and caching, server-controlled sampling, bootstrap/ticket HTTP endpoints, and the data.csv / response.json filesystem interface.
- tickets/: temporary backend/ML exchange; no user-history database.
- Tests verify input preparation and transport using fixture worker replies. They do not claim a trained model's forecasting accuracy.
- Frontend and ML implementations are separate team responsibilities; their additional dependencies and AI tools must be recorded as introduced.

## Active backend components

| Component | Version range | License | Purpose |
| --- | --- | --- | --- |
| FastAPI | >=0.115,<1 | MIT | HTTP endpoints and validation integration |
| Uvicorn | >=0.32,<1 | BSD-3-Clause | ASGI server |
| Pydantic | >=2.9,<3 | MIT | Request validation |
| HTTPX | >=0.27,<1 | BSD-3-Clause | Weather API calls |
| tzdata | >=2025.2 | Apache-2.0 | IANA timezone definitions |
| pytest | >=8,<10 | MIT | Development-only checks |

See back/requirements.txt and back/requirements-dev.txt. Existing frontend dependencies are declared in frontend/package.json.

## Data sources and transformations

Turbine datasets are provided by the organizers and kept outside Git under back/data/ or a configured DATASETS_DIR. Backend exports only weather inputs, never training power/MWh labels.

Missing weather uses Open-Meteo GFS forecasts. Finer sampling interpolated from hourly forecasts is explicitly labeled. Source documentation: [Previous Runs](https://open-meteo.com/en/docs/previous-runs-api), [Forecast API](https://open-meteo.com/en/docs).

## AI assistance

Codex was used for track analysis, backend implementation, documentation, and checks. The team reports unrestricted AI coding assistance during the event. Team members should record additional tools/models used for their frontend and ML work.
