"""Backend CSV -> site-clock hourly weather -> 48 frontend-compatible predictions."""
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import logging
import math

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from .features import CONTEXT, HORIZON, WEATHER, features

REQUIRED = ['timestamp', 'phase', 'turbine_id', *WEATHER, 'weather_source']


def prepare_frame(frame, timezone):
    if frame.empty or not set(REQUIRED).issubset(frame.columns) or frame.columns.duplicated().any():
        raise ValueError('CSV must contain timestamp, phase, turbine_id, wind_speed_ms, temperature_c, weather_source')
    data = frame[REQUIRED].copy()  # Power/efficiency columns are never read.
    if data[REQUIRED[:3] + ['weather_source']].isna().any().any():
        raise ValueError('Missing timestamp, phase, turbine or weather source')
    turbines = data.turbine_id.unique()
    if len(turbines) != 1 or turbines[0] not in ['A', 'B']:
        raise ValueError('CSV must contain exactly one turbine, A or B')
    if not data.phase.isin(['history', 'forecast']).all():
        raise ValueError('phase must be history or forecast')
    # Require offsets before normalizing: pd.to_datetime(utc=True) alone would
    # silently treat timezone-naive input as UTC and shift model calendar features.
    if not data.timestamp.astype(str).map(lambda v: pd.Timestamp(v).tzinfo is not None).all():
        raise ValueError('Ticket timestamps must include a UTC offset')
    times = pd.DatetimeIndex(pd.to_datetime(data.timestamp, utc=True, format='mixed')).as_unit('ns')
    if times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError('Ticket timestamps must be unique and ascending')
    local = times.tz_convert(ZoneInfo(timezone))
    if (local.second != 0).any() or (local.microsecond != 0).any():
        raise ValueError('Timestamps must align to whole minutes')
    if (data.phase == 'forecast').sum() == 0:
        raise ValueError('Missing forecast window')
    origin = local[data.phase.to_numpy() == 'forecast'][0]
    if origin.minute != 0:
        raise ValueError('Forecast must start at a whole site-clock hour')
    if not np.array_equal(data.phase.to_numpy() == 'history', times < origin):
        raise ValueError('History must be strictly before the forecast origin')
    if (times >= origin + pd.Timedelta(hours=HORIZON)).any():
        raise ValueError('Weather extends beyond the 48-hour horizon')
    # infer backend sampling from the complete forecast grid, not a historical gap.
    forecast_times = times[data.phase.to_numpy() == 'forecast']
    deltas = np.diff(forecast_times.asi8)
    if not len(deltas) or len(set(deltas)) != 1:
        raise ValueError('Future rows must form a complete, uniform 48-hour grid')
    interval = int(deltas[0] // (60*10**9))
    if interval < 1 or interval > 60 or 60 % interval or deltas[0] != interval*60*10**9:
        raise ValueError('Input cadence must divide one hour exactly')
    expected = pd.date_range(origin, periods=HORIZON*(60//interval), freq=f'{interval}min').tz_convert('UTC')
    if not np.array_equal(forecast_times.asi8, expected.as_unit('ns').asi8):
        raise ValueError('CSV must cover the full 48-hour forecast, including the final hourly interval')
    if (local.minute % interval != 0).any():
        raise ValueError('History and forecast rows must use the same minute grid')
    for column in WEATHER:
        data[column] = pd.to_numeric(data[column], errors='raise')
    if np.isinf(data[WEATHER].to_numpy(dtype=float)).any() or (data.wind_speed_ms < 0).any():
        raise ValueError('Invalid weather: infinity or negative wind')
    data.index = local
    # Model was trained in naive source/site clock, not naive UTC.
    naive_origin = origin.tz_localize(None)
    if naive_origin < pd.Timestamp('2026-02-01'):
        logging.getLogger(__name__).warning(
            'Diagnostic forecast at %s uses a model trained through January 31, 2026; '
            'this is not an unbiased historical validation.', naive_origin)
    selected = data.loc[data.index >= origin-pd.Timedelta(hours=CONTEXT)]
    if selected.index.tz_localize(None).has_duplicates:
        raise ValueError('Ambiguous repeated site-clock hour; this model does not support DST fold windows')
    hourly = selected[WEATHER].resample('h').mean()
    counts = selected[WEATHER].resample('h').count()
    hourly = hourly.where(counts >= math.ceil((60//interval)*2/3))
    # Interpolated hourly NWP values are not additional observations. Use the
    # original whole-hour weather value when the entire bin comes from a provider.
    for hour, group in selected.groupby(pd.Grouper(freq='h')):
        if len(group) and not group.weather_source.str.contains('dataset', regex=False).any():
            at_hour = group.loc[group.index == hour, WEATHER]
            if len(at_hour):
                hourly.loc[hour, WEATHER] = at_hour.iloc[0]
    hourly.index = hourly.index.tz_localize(None)
    if hourly.index.has_duplicates:
        raise ValueError('Ambiguous site-clock weather hours')
    history = hourly.reindex(pd.date_range(naive_origin-pd.Timedelta(hours=CONTEXT), periods=CONTEXT, freq='h'))[WEATHER]
    future = hourly.reindex(pd.date_range(naive_origin, periods=HORIZON, freq='h'))[WEATHER]
    x, names = features(history.to_numpy(), future.to_numpy(), naive_origin)
    forecast_sources = sorted(set(data.loc[data.phase == 'forecast', 'weather_source']))
    return x, names, {'turbine_id': turbines[0], 'origin': origin, 'history': history, 'future': future,
        'forecast_sources': forecast_sources, 'input_interval_minutes': interval}


class ForecastPipeline:
    def __init__(self, model_dir=None, timezone='Asia/Almaty', threads=1):
        self.timezone = timezone
        ZoneInfo(timezone)
        self.threads = threads
        root = Path(model_dir) if model_dir else Path(__file__).parent / 'models'
        self.models = {}
        metadata = json.loads((root / 'manifest.json').read_text())
        _, names = features(np.ones((168, 2)), np.ones((48, 2)), pd.Timestamp('2026-02-01'))
        if metadata['features'] != names or metadata['historical_power_used'] is not False:
            raise ValueError('Model manifest does not match weather-only features')
        for key, number in [('A', 1), ('B', 2)]:
            path = root / f'turbine_{number}' / 'catboost.cbm'
            if hashlib.sha256(path.read_bytes()).hexdigest() != metadata['sha256'][key]:
                raise ValueError(f'Model checksum mismatch for turbine {key}')
            model = CatBoostRegressor()
            model.load_model(str(path))
            if len(model.feature_names_) != 80:
                raise ValueError('Model must have exactly 80 weather/calendar/horizon features')
            self.models[key] = model

    def infer(self, csv_path):
        # Only the public weather fields are loaded, even if someone adds power.
        data = pd.read_csv(csv_path, usecols=REQUIRED)
        x, _, info = prepare_frame(data, self.timezone)
        predicted = self.models[info['turbine_id']].predict(x, thread_count=self.threads).clip(0, 1)
        if len(predicted) != 48 or not np.isfinite(predicted).all():
            raise ValueError('Model returned invalid predictions')
        points = [{'hour': h, 'value': float(value)}
                  for h, value in enumerate(predicted)]
        return {'series': [{'id': 'agent-ctboost', 'name': 'Main forecast',
                            'color': '#157a65', 'points': points}]}
