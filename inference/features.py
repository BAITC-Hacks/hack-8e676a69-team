"""Frozen 80-feature schema: past and future WEATHER only, never power."""
import warnings
import numpy as np
import pandas as pd

CONTEXT = 168
HORIZON = 48
WEATHER = ['wind_speed_ms', 'temperature_c']


def features(history, future, origin):
    past = np.asarray(history, dtype='float32')
    weather = np.asarray(future, dtype='float32')
    if past.shape != (CONTEXT, 2) or weather.shape != (HORIZON, 2):
        raise ValueError('Expected 168 historical and 48 future hours, each with wind and temperature only')
    if np.isinf(past).any() or np.isinf(weather).any() or (past[:, 0] < 0).any() or (weather[:, 0] < 0).any():
        raise ValueError('Weather cannot contain infinity or negative wind')
    if (np.isfinite(past).sum(axis=0) < 24).any() or (np.isfinite(past[-24:]).sum(axis=0) == 0).any():
        raise ValueError('Each historical weather variable needs 24 observed hours, including one in the last day')
    if (np.isfinite(weather).sum(axis=0) == 0).any():
        raise ValueError('Each future weather variable needs at least one value')
    stats = {}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        for j, name in enumerate(['wind_speed', 'temperature']):
            v = past[:, j]
            for age in [1, 2, 3, 6, 12, 24, 48, 72, 168]:
                stats[f'{name}_age_{age}h'] = v[-age]
            valid = np.flatnonzero(np.isfinite(v))
            stats[f'{name}_last_observed'] = v[valid[-1]] if len(valid) else np.nan
            stats[f'{name}_age_last_observed'] = CONTEXT-valid[-1] if len(valid) else CONTEXT+1
            for window in [6, 24, 72, 168]:
                chunk = v[-window:]
                for label, fn in [('mean', np.nanmean), ('std', np.nanstd), ('min', np.nanmin), ('max', np.nanmax)]:
                    stats[f'{name}_{label}_{window}h'] = fn(chunk)
                stats[f'{name}_coverage_{window}h'] = np.isfinite(chunk).mean()
    dates = pd.date_range(origin, periods=HORIZON, freq='h')
    year = (dates.dayofyear.to_numpy()-1+dates.hour.to_numpy()/24) / np.where(dates.is_leap_year, 366, 365)
    day = dates.hour.to_numpy()/24
    calendar = np.column_stack([dates.month, np.sin(2*np.pi*year), np.cos(2*np.pi*year),
        np.sin(4*np.pi*year), np.cos(4*np.pi*year), np.sin(2*np.pi*day), np.cos(2*np.pi*day)]).astype('float32')
    previous = weather[np.maximum(np.arange(48)-1, 0)]
    following = weather[np.minimum(np.arange(48)+1, 47)]
    extra = np.column_stack([np.arange(1, 49), weather, previous, following,
        following-previous, weather[:, 0]**2, weather[:, 0]**3])
    history_features = np.tile(np.asarray(list(stats.values()), dtype='float32'), (48, 1))
    names = list(stats) + ['month', 'year_sin', 'year_cos', 'year_sin2', 'year_cos2', 'day_sin', 'day_cos',
        'horizon', 'future_wind_speed', 'future_temperature', 'future_wind_previous',
        'future_temperature_previous', 'future_wind_next', 'future_temperature_next',
        'future_wind_change', 'future_temperature_change', 'future_wind_squared', 'future_wind_cubed']
    return np.column_stack([history_features, calendar, extra]).astype('float32'), names
