# ML worker handoff

Implemented in [`../inference/`](../inference/README.md). The backend starts this
worker automatically by default. The concrete success format is one `series`
entry with id `agent-ctboost`, name `Main forecast`, color `#157a65`, and 48 points
`{"hour":0..47,"value":normalized_power}`. Power is never a model input.

The Python worker is implemented in inference/; this folder documents the shared interface. Backend and worker use the same root tickets/ directory.

## Input

Wait for tickets/<id>/data.csv. Temporary files are not ready. There is no request.json.

```csv
timestamp,phase,turbine_id,wind_speed_ms,temperature_c,weather_source
```

- timestamp: ISO time with UTC offset, ascending.
- phase: history or forecast; the first forecast timestamp is the horizon start.
- turbine_id: A = supplied turbine 1; B = turbine 2.
- Numeric inputs: wind speed in m/s and temperature in Celsius.
- weather_source identifies measurements, forecasts, and interpolation.
- No power/MWh training labels are sent.

Prediction input always spans 48 hours. Sampling is configured by backend/ML using ML_STEP in back/.env: 6 means ten-minute rows. Restart backend after changing it. Frontend has no sampling control.

Native ten-minute measurements are preserved. Online weather is interpolated from hourly forecasts for finer grids and marked accordingly. Confirm TURBINE_TIMEZONE and the online wind predictor height with the backend owner.

## Output

Write the frontend-facing JSON to response.json.tmp, flush and close it, then rename to response.json. Use valid finite JSON numbers. Backend returns the exact bytes without wrapping or unit conversion.

Agree on prediction timestamps with frontend so it can show a selected portion of the complete 48-hour response. Input sampling does not dictate the frontend's output cadence.

On model failure, write the error schema agreed with frontend as response.json. If no response arrives, backend eventually returns an HTTP timeout. Claim jobs internally to prevent duplicate processing. Backend expires completed ticket folders after a retrieval window.

[Backend contract](../back/README.md).
