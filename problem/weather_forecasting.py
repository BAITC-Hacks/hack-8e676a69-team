"""Direct CatBoost with observed history and a separately supplied weather horizon.

The bundled experiment uses recorded future weather as an oracle input, NOT an
operational weather forecast. Future power is never an input feature.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from catboost_benchmark import calendar, historical_features, valid_context
from forecasting import VALUES, read_context_csv

CONTEXT = 168
HORIZON = 48
WEATHER = ['wind_speed', 'temperature']
MODEL_NAME = 'catboost_weather_oracle'


def history_matrix(contexts):
    return historical_features(contexts, 'base')


def weather_features(history, history_names, origins, weather, horizon):
    """Batched features for one horizon; weather has ONLY two non-target columns."""
    weather = np.asarray(weather, dtype='float32')
    if weather.shape != (len(history), HORIZON, 2):
        raise ValueError('Weather must have shape n x 48 x 2 (wind_speed, temperature)')
    if not 1 <= horizon <= HORIZON:
        raise ValueError('Horizon must be 1..48')
    if np.isinf(weather).any():
        raise ValueError('Infinite weather values')
    if (weather[:, :, 0] < 0).any():
        raise ValueError('Wind speed must be nonnegative, in m/s')
    h = horizon - 1
    target = weather[:, h, :]
    # All weather values in this array are supplied at request time. They are
    # not targets predicted and fed back by this model.
    previous = weather[:, max(0, h-1), :]
    following = weather[:, min(HORIZON-1, h+1), :]
    extra = np.column_stack([np.full(len(history), horizon), target, previous, following,
                             following-previous, target[:, 0]**2, target[:, 0]**3])
    names = list(history_names) + ['month', 'year_sin', 'year_cos', 'year_sin2', 'year_cos2', 'day_sin', 'day_cos']
    names += ['horizon', 'future_wind_speed', 'future_temperature', 'future_wind_previous',
              'future_temperature_previous', 'future_wind_next', 'future_temperature_next',
              'future_wind_change', 'future_temperature_change', 'future_wind_squared', 'future_wind_cubed']
    x = np.column_stack([history, calendar(origins + pd.Timedelta(hours=h)), extra]).astype('float32')
    return x, names


def all_features(history, history_names, origins, weather):
    """One row per (forecast origin, horizon), for a single shared regressor."""
    arrays = []
    for h in range(1, HORIZON+1):
        x, names = weather_features(history, history_names, origins, weather, h)
        arrays.append(x)
    return np.stack(arrays, axis=1).reshape(-1, len(names)), names


def training_arrays(hourly, stride=6):
    values = hourly[VALUES].to_numpy(dtype='float32')
    positions = np.arange(CONTEXT, len(hourly)-HORIZON+1, stride)
    contexts = np.stack([values[p-CONTEXT:p] for p in positions])
    ok = valid_context(contexts)
    positions, contexts = positions[ok], contexts[ok]
    future = np.stack([values[p:p+HORIZON] for p in positions])
    hist, names = history_matrix(contexts)
    return hourly.index[positions], hist, names, future[:, :, 1:], future[:, :, 0]


def request_arrays(hourly, origins):
    grid = [pd.date_range(o-pd.Timedelta(hours=CONTEXT), periods=CONTEXT, freq='h') for o in origins]
    contexts = np.stack([hourly[VALUES].reindex(g).to_numpy(dtype='float32') for g in grid])
    if not valid_context(contexts).all():
        raise ValueError('Insufficient observed history')
    future_grid = [pd.date_range(o, periods=HORIZON, freq='h') for o in origins]
    weather = np.stack([hourly[WEATHER].reindex(g).to_numpy(dtype='float32') for g in future_grid])
    hist, names = history_matrix(contexts)
    return hist, names, weather


class WeatherCatBoost:
    def __init__(self, folder):
        folder = Path(folder)
        self.metadata = json.loads((folder / 'metadata.json').read_text())
        if self.metadata['strategy'] != 'pooled_direct_with_future_weather':
            raise ValueError('Wrong model bundle')
        self.model = CatBoostRegressor()
        self.model.load_model(str(folder / 'catboost.cbm'))

    def predict(self, contexts, origins, weather):
        origins = pd.DatetimeIndex(origins)
        if len(contexts) != len(origins) or not valid_context(contexts).all():
            raise ValueError('Insufficient observed history or mismatched origins')
        if (origins < pd.Timestamp(self.metadata['trained_until_exclusive'])).any():
            raise ValueError('Origin precedes training cutoff; select evaluation models')
        hist, names = history_matrix(contexts)
        x, schema = all_features(hist, names, origins, weather)
        if schema != self.metadata['features']:
            raise ValueError('Model feature schema mismatch')
        result = self.model.predict(x).reshape(len(origins), HORIZON).clip(0, 1)
        if not np.isfinite(result).all():
            raise ValueError('Nonfinite predictions')
        return result


def predict_csv(path, model_dir, origin, weather_source):
    """One CSV: past rows with power, next 48 rows with weather and empty power."""
    if weather_source not in ['recorded_oracle', 'forecast']:
        raise ValueError('Declare weather_source: recorded_oracle or forecast')
    origin = pd.Timestamp(origin)
    if pd.isna(origin) or origin.tz is not None or origin != origin.floor('h'):
        raise ValueError('Origin must be a timezone-naive whole hour in source/site time')
    data = read_context_csv(Path(path))
    grid = pd.date_range(origin, periods=HORIZON, freq='h')
    if (data.timestamp > grid[-1]).any():
        raise ValueError('Rows beyond the 48-hour weather horizon')
    if data.loc[data.timestamp >= origin, 'power'].notna().any():
        raise ValueError('Future power must be empty; it is the unknown target')
    rows = []
    for turbine, group in data.groupby('turbine_id'):
        indexed = group.set_index('timestamp')
        future = indexed.reindex(grid)[WEATHER]
        # Require the full 48-row horizon, but permit individual missing cells.
        if not grid.isin(indexed.index).all():
            raise ValueError('Supply exactly 48 hourly future rows; use blank cells for missing weather')
        if future.isna().all(axis=0).any():
            raise ValueError('Both wind and temperature need at least one supplied future value')
        context_grid = pd.date_range(origin-pd.Timedelta(hours=CONTEXT), periods=CONTEXT, freq='h')
        context = indexed.reindex(context_grid)[VALUES].to_numpy(dtype='float32')[None, :]
        model = WeatherCatBoost(Path(model_dir) / f'turbine_{int(turbine)}')
        pred = model.predict(context, pd.DatetimeIndex([origin]), future.to_numpy(dtype='float32')[None, :])[0]
        rows.append(pd.DataFrame({'turbine_id': int(turbine), 'forecast_origin': origin,
            'timestamp': grid, 'horizon': np.arange(1,49), 'model': MODEL_NAME,
            'predicted_power': pred, 'weather_source': weather_source,
            'weather_missing': future.isna().any(axis=1).to_numpy(),
            'trained_weather_source': model.metadata['weather_source']}))
    return pd.concat(rows, ignore_index=True)
