# AGENTS.md

## Project

Frontend for an Agentic AI wind power forecasting system.

The application should stay focused on one clear workflow:

1. Select wind turbine or power plant.
2. Select forecast dates.
3. View plant locations on the map.
4. Inspect hourly production forecasts for the next 24-48 hours.
5. Support Kazakh, Russian, and English UI labels.

## Technical Notes

- Use Vue 3 and Vite.
- Keep the frontend as a single-page app unless the project requirements change.
- Prefer simple, readable Vue components over premature abstractions.
- Keep `App.vue` as an orchestration shell only. Put UI sections in `src/components`, localization in `src/i18n`, domain/mock API data in `src/data`, reusable calculations in `src/utils`, and component-specific styles in scoped component styles.
- Use open map providers such as OpenStreetMap/Leaflet unless the team adds a paid map key.
- Keep all user-facing strings ready for localization in `kk`, `ru`, and `en`.
- Do not hard-code new user-facing strings inside components unless they are already represented in the i18n message map.
- Do not commit generated folders such as `node_modules` or `dist`.

## Agentic AI Context

The frontend should present the result of an agentic forecasting pipeline:

- weather forecast retrieval;
- data preparation;
- model execution;
- hourly forecast generation;
- result analysis;
- recalculation when new input data becomes available.

When adding UI features, keep the hackathon evaluation criteria in mind: task fit, technical quality, documentation, reproducibility, practical value, scalability, and originality.
