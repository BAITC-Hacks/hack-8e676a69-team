# Third-party component disclosure

Hackathon team: Порнофильмы.

## Prepared before the competition

The initial project contained generic FastAPI/SQLite/React/Vite infrastructure, image-upload and CV stubs, and Caddy/systemd deployment configuration. It contained no track-specific prediction model. Obsolete image/CV/SQLite code has been removed from the active repository.

## Implemented during the competition

- back/: weather-only input preparation, Open-Meteo retrieval and caching, server-controlled sampling, bootstrap/ticket HTTP endpoints, and the data.csv / response.json filesystem interface.
- tickets/: temporary backend/ML exchange; no user-history database.
- Backend unit tests use fixture replies; integration tests also execute the bundled CatBoost models on offline weather fixtures. These verify the protocol and runtime, not real-weather forecast accuracy.
- inference/: embedded/standalone ticket worker and two team-trained CatBoost model files, with SHA-256 and feature metadata in inference/models/manifest.json. Weather-only features are used; no power history is consumed at inference.
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

## Active frontend components

Versions below were verified against the installed packages and frontend/package-lock.json.

| Component | Checked version | Declared license | Purpose |
| --- | --- | --- | --- |
| Vue | 3.5.43 | MIT | User interface |
| Vite | 8.3.0 | MIT | Development server and build |
| @vitejs/plugin-vue | 6.0.9 | MIT | Vue compilation |
| Leaflet | 1.9.4 | BSD-2-Clause | Map interaction |
| ECharts | 6.1.0 | Apache-2.0 | Forecast charts |
| vue-echarts | 8.3.0 | MIT | Vue chart integration |
| @lucide/vue | 1.47.0 | ISC | Interface icons |

## Active ML runtime components

| Component | Version | Declared license | Purpose |
| --- | --- | --- | --- |
| CatBoost | 1.2.10 | Apache-2.0 | Team-trained normalized-power regressors |
| NumPy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Numerical arrays; expression declared by the installed distribution |
| pandas | 3.0.6 | BSD-3-Clause | Weather time-series preparation |
| python-dotenv | >=1,<2 | BSD-3-Clause | Runtime environment configuration |

The model files are trained on organizer data rather than downloaded pretrained task solutions. Training uses recorded future weather; reported experimental metrics must not be presented as measured performance with real forecast weather. Training scripts, dependencies, and experimental artifacts are under problem/; the runtime dependencies are pinned in inference/requirements.txt.

## Data sources and transformations

Turbine datasets are provided by the organizers. Both original CSVs are included under back/data/ for independent reproduction; their contents match the datasets already committed to this repository's ML development branch. Backend exports only weather inputs, never training power/MWh labels. DATASETS_DIR can select another local data location.

Missing weather uses Open-Meteo GFS forecasts. Finer sampling interpolated from hourly forecasts is explicitly labeled. Source documentation: [Previous Runs](https://open-meteo.com/en/docs/previous-runs-api), [Forecast API](https://open-meteo.com/en/docs).

## AI assistance

Codex was used for track analysis, backend implementation, documentation, and checks. The team reports unrestricted AI coding assistance during the event. Team members should record additional tools/models used for their frontend and ML work.

The team also reported using ChatGPT (Astra Max) for coding assistance. These development tools are not runtime dependencies of the implemented backend/frontend.
