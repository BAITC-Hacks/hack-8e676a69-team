"""Weather history + supplied future weather. Power is NEVER a context input."""
from pathlib import Path
import json
import warnings

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from weather_forecasting import CONTEXT, HORIZON, WEATHER, all_features

MODEL_NAME = 'catboost_weather_context_no_power'
STRATEGY = 'weather_context_no_power'


def valid_context(contexts):
    x = np.asarray(contexts)
    if x.ndim != 3 or x.shape[1:] != (CONTEXT, 2):
        raise ValueError('History must contain exactly 168 hours x 2 weather variables, no power')
    if np.isinf(x).any() or (x[:, :, 0] < 0).any():
        raise ValueError('Invalid historical weather: use nonnegative wind in m/s and no infinities')
    observed = np.isfinite(x)
    return (observed.sum(axis=1) >= 24).all(axis=1) & (observed[:, -24:].sum(axis=1) > 0).all(axis=1)


def history_matrix(contexts):
    x = np.asarray(contexts, dtype='float32')
    valid_context(x)  # Validate schema; caller handles coverage eligibility.
    entries = {}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        for j, name in enumerate(WEATHER):
            v = x[:, :, j]
            observed = np.isfinite(v)
            for age in [1, 2, 3, 6, 12, 24, 48, 72, 168]:
                entries[f'{name}_age_{age}h'] = v[:, -age]
            last = np.where(observed, np.arange(CONTEXT)[None, :], -1).max(axis=1)
            entries[f'{name}_last_observed'] = np.where(last >= 0, v[np.arange(len(v)), np.maximum(last, 0)], np.nan)
            entries[f'{name}_age_last_observed'] = np.where(last >= 0, CONTEXT-last, CONTEXT+1)
            for window in [6, 24, 72, 168]:
                chunk = v[:, -window:]
                for label, function in [('mean', np.nanmean), ('std', np.nanstd), ('min', np.nanmin), ('max', np.nanmax)]:
                    entries[f'{name}_{label}_{window}h'] = function(chunk, axis=1)
                entries[f'{name}_coverage_{window}h'] = np.isfinite(chunk).mean(axis=1)
    return np.column_stack(list(entries.values())).astype('float32'), list(entries)


def training_arrays(hourly, stride=6):
    # Target is read separately; it cannot influence context, coverage or features.
    values = hourly[WEATHER].to_numpy(dtype='float32')
    positions = np.arange(CONTEXT, len(hourly)-HORIZON+1, stride)
    contexts = np.stack([values[p-CONTEXT:p] for p in positions])
    ok = valid_context(contexts)
    positions, contexts = positions[ok], contexts[ok]
    future_weather = np.stack([values[p:p+HORIZON] for p in positions])
    labels = hourly['power'].to_numpy(dtype='float32')
    targets = np.stack([labels[p:p+HORIZON] for p in positions])
    hist, names = history_matrix(contexts)
    return hourly.index[positions], hist, names, future_weather, targets


def request_arrays(hourly, origins):
    # Works with a frame that has no power column at all.
    weather_frame = hourly[WEATHER]
    contexts = np.stack([weather_frame.reindex(pd.date_range(o-pd.Timedelta(hours=CONTEXT),
        periods=CONTEXT, freq='h')).to_numpy(dtype='float32') for o in origins])
    if not valid_context(contexts).all():
        raise ValueError('Need 24 observed hours of each historical weather variable, including one in the last day')
    future = np.stack([weather_frame.reindex(pd.date_range(o, periods=HORIZON, freq='h')).to_numpy(dtype='float32') for o in origins])
    hist, names = history_matrix(contexts)
    return hist, names, future


class WeatherContextCatBoost:
    def __init__(self, folder):
        folder = Path(folder)
        self.metadata = json.loads((folder / 'metadata.json').read_text())
        if self.metadata['strategy'] != STRATEGY:
            raise ValueError('Wrong model bundle')
        self.model = CatBoostRegressor()
        self.model.load_model(str(folder / 'catboost.cbm'))

    def predict(self, history_weather, origins, future_weather):
        origins = pd.DatetimeIndex(origins)
        if len(origins) != len(history_weather) or not valid_context(history_weather).all():
            raise ValueError('Insufficient weather context or mismatched origins')
        if (origins < pd.Timestamp(self.metadata['trained_until_exclusive'])).any():
            raise ValueError('Origin precedes training cutoff; select evaluation models')
        hist, names = history_matrix(history_weather)
        x, schema = all_features(hist, names, origins, future_weather)
        if schema != self.metadata['features'] or any('power' in name or 'efficiency' in name for name in schema):
            raise ValueError('Invalid feature schema: no power-derived features permitted')
        result = self.model.predict(x).reshape(len(origins), HORIZON).clip(0, 1)
        if not np.isfinite(result).all():
            raise ValueError('Nonfinite predictions')
        return result


def predict_csv(path, model_dir, origin, weather_source):
    if weather_source not in ['recorded_oracle', 'forecast']:
        raise ValueError('Declare weather_source: recorded_oracle or forecast')
    origin = pd.Timestamp(origin)
    if pd.isna(origin) or origin.tz is not None or origin != origin.floor('h'):
        raise ValueError('Origin must be a timezone-naive whole hour in source/site time')
    # Read ONLY allowlisted inputs; any power/efficiency column is ignored entirely.
    required = ['turbine_id', 'timestamp', *WEATHER]
    data = pd.read_csv(path, usecols=required)
    data['timestamp'] = pd.to_datetime(data.timestamp)
    if data.empty or not data.turbine_id.isin([1, 2]).all():
        raise ValueError('Nonempty input with turbine_id 1 or 2 required')
    if data.timestamp.isna().any() or data.timestamp.dt.tz is not None or (data.timestamp != data.timestamp.dt.floor('h')).any():
        raise ValueError('Timestamps must be timezone-naive whole hours')
    if data.duplicated(['turbine_id', 'timestamp']).any():
        raise ValueError('Duplicate turbine/timestamp pairs')
    for column in WEATHER:
        data[column] = pd.to_numeric(data[column], errors='raise')
    if np.isinf(data[WEATHER].to_numpy()).any() or (data.wind_speed < 0).any():
        raise ValueError('Invalid weather: negative wind or infinite values')
    grid = pd.date_range(origin, periods=HORIZON, freq='h')
    if (data.timestamp > grid[-1]).any():
        raise ValueError('Rows beyond the 48-hour weather horizon')
    rows = []
    for turbine, group in data.groupby('turbine_id'):
        indexed = group.set_index('timestamp')
        if not grid.isin(indexed.index).all():
            raise ValueError('Supply all 48 hourly future weather rows; use blank cells for gaps')
        future = indexed.reindex(grid)[WEATHER]
        if future.isna().all(axis=0).any():
            raise ValueError('Each future weather variable needs at least one value')
        past_grid = pd.date_range(origin-pd.Timedelta(hours=CONTEXT), periods=CONTEXT, freq='h')
        context = indexed.reindex(past_grid)[WEATHER].to_numpy(dtype='float32')[None, :]
        model = WeatherContextCatBoost(Path(model_dir) / f'turbine_{int(turbine)}')
        prediction = model.predict(context, pd.DatetimeIndex([origin]), future.to_numpy(dtype='float32')[None, :])[0]
        rows.append(pd.DataFrame({'turbine_id': int(turbine), 'forecast_origin': origin,
            'timestamp': grid, 'horizon': np.arange(1, 49), 'model': MODEL_NAME,
            'predicted_power': prediction, 'weather_source': weather_source,
            'weather_missing': future.isna().any(axis=1).to_numpy(),
            'trained_weather_source': model.metadata['weather_source']}))
    return pd.concat(rows, ignore_index=True)
