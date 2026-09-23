# ML worker handoff

The ML teammate implements the worker here. Backend and worker share the repository's sibling tickets/ directory, or the same configured absolute TICKETS_DIR.

## Input

Watch tickets/<id>/data.csv. Process a ticket only after this final filename exists. Backend temporary files are not ready for reading.

```csv
timestamp,phase,turbine_id,wind_speed_ms,temperature_c,weather_source
```

- timestamp: ISO datetime with UTC offset, in ascending order.
- phase: history or forecast. The first forecast row is the requested horizon start.
- turbine_id: A = supplied turbine 1; B = supplied turbine 2.
- wind_speed_ms and temperature_c: the only numeric weather features supplied by the backend.
- weather_source: provenance; select the actual feature columns rather than treating every column as a model feature.
- There are no power/MWh labels in this file. Model training and output units belong to the ML component.
- The requested step is samples per hour. step=6 produces ten-minute rows; infer it from adjacent timestamps.
- The prediction portion always spans 48 hours. Frontend display preferences do not change the backend/ML horizon.
- Native dataset ten-minute measurements are preserved. Subhourly internet weather is interpolated from hourly forecasts and labeled accordingly; it is not additional observed meteorological detail.

No request.json is used. All required input context is in the CSV. The default timezone is Asia/Almaty; confirm the dataset's actual timezone and configure TURBINE_TIMEZONE if different. The default online wind predictor is 100 m; this is also configurable and should be agreed with ML.

## Output

Write any agreed frontend-facing JSON schema to tickets/<id>/response.json.tmp, flush and close it, then rename it to response.json on the same filesystem. Use standard finite JSON numbers; no NaN or Infinity. Backend returns the exact JSON bytes without adding a wrapper or converting MWh values.

Agree prediction timestamps with frontend so it can display a shorter interval from the full 48-hour response. Input sampling frequency does not require frontend to assume the model's output frequency.

On a model failure, publish the error representation agreed with frontend as valid response.json. If no response is produced, backend eventually returns an HTTP timeout. Mark/claim jobs internally so a published data.csv is not processed repeatedly or by multiple workers simultaneously. Do not modify data.csv.

The backend retains responses briefly for retrieval, then cleans expired ticket directories. It does not implement or launch a placeholder prediction model. See [the backend contract](../back/README.md) for HTTP details and the verified February 5 example.
