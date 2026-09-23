# Disclosure of Third-Party Components

Per hackathon rule 5.4.4 (disclosure of third-party components).

## Prepared before the competition

The following were scaffolded before the competition start, under rule
5.4.4.2: generic infrastructure containing no task-specific logic.

- FastAPI/SQLite/Vite project skeleton (`api/`, `cv/`, `shared/`, `web/`):
  two-process boilerplate, stub endpoints returning fixed placeholder data,
  empty React app shell. No task logic.
- systemd units (`deploy/hackalem.service`, `deploy/hackalem-cv.service`)
- Caddy reverse-proxy config (`deploy/Caddyfile`)
- Deploy script (`deploy/deploy.sh`)

TODO: team must list any additional pre-competition preparation here.

## Implemented during the competition

- back/: FastAPI bootstrap/ticket endpoints, weather-only CSV preparation, configurable sampling, Open-Meteo retrieval/cache, and the filesystem handoff to the separate ML worker.
- tickets/: temporary job exchange using data.csv and response.json; no user-history database.
- Input/HTTP tests use fixture replies to verify transport. They do not implement or claim a trained prediction model.
- Open-Meteo GFS weather data is used for missing weather and forecasts. Subhourly values interpolated from hourly data are explicitly labeled. Source: https://open-meteo.com/en/docs/previous-runs-api and https://open-meteo.com/en/docs.
- tzdata (Apache-2.0) supplies IANA timezone definitions, including on Windows.
- pytest (MIT) is a development-only test dependency.

## Open-source dependencies

| Component | Version | License | Purpose |
|---|---|---|---|
| fastapi | >=0.115 | MIT | web framework (api + cv processes) |
| uvicorn[standard] | >=0.32 | BSD-3-Clause | ASGI server |
| pydantic | >=2.9 | MIT | request/response validation |
| httpx | >=0.27,<1 | BSD-3-Clause | async weather API requests in the active backend |
| tzdata | >=2025.2 | Apache-2.0 | IANA timezone definitions |
| python-multipart | >=0.0.12 | Apache-2.0 | multipart/form-data parsing (file upload) |
| aiofiles | >=24.1 | Apache-2.0 | async file writes |
| react | ^18.3.1 | MIT | frontend UI library |
| react-dom | ^18.3.1 | MIT | React DOM renderer |
| vite | ^5.4.0 | MIT | frontend build tool / dev server |
| @vitejs/plugin-react | ^4.3.1 | MIT | Vite React plugin |

TODO: team must add every additional dependency introduced while building
the actual task (e.g. an ML framework, an image processing library).

## AI tools used

TODO: team must list AI tools used during the competition (e.g. code
assistants, model providers) here.
