"""Tests for one-model, direct 48h forecasting with supplied future weather."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from weather_forecasting import (WeatherCatBoost, all_features, history_matrix,
    predict_csv, request_arrays, training_arrays, weather_features)


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.origin = pd.Timestamp('2026-01-22')
        rng = np.random.default_rng(51)
        self.data = pd.DataFrame(rng.random((216, 3)),
            columns=['power', 'wind_speed', 'temperature'],
            index=pd.date_range(self.origin-pd.Timedelta(hours=168), periods=216, freq='h'))
        self.context = self.data.iloc[:168].to_numpy()[None, :]
        self.weather = self.data.iloc[168:][['wind_speed', 'temperature']].to_numpy()[None, :]
        self.origins = pd.DatetimeIndex([self.origin])

    def test_future_power_cannot_affect_features(self):
        first = request_arrays(self.data, self.origins)
        changed = self.data.copy()
        changed.loc[self.origin:, 'power'] = 9999
        second = request_arrays(changed, self.origins)
        np.testing.assert_array_equal(all_features(*first[:2], self.origins, first[2])[0],
                                      all_features(*second[:2], self.origins, second[2])[0])

    def test_horizons_and_weather_alignment(self):
        hist, names = history_matrix(np.repeat(self.context, 2, axis=0))
        origins = pd.DatetimeIndex([self.origin, self.origin+pd.Timedelta(days=1)])
        weather = np.repeat(self.weather, 2, axis=0)
        x, schema = all_features(hist, names, origins, weather)
        self.assertEqual(x.shape, (96, 111))
        np.testing.assert_array_equal(x[:, schema.index('horizon')], np.tile(np.arange(1,49), 2))
        np.testing.assert_allclose(x[:, schema.index('future_wind_speed')], weather[:, :, 0].ravel())
        self.assertFalse(any('future_power' in name for name in schema))

    def test_gaps_remain_nan(self):
        context, weather = self.context.copy(), self.weather.copy()
        context[:, -1, 0] = np.nan
        weather[:, 12, 0] = np.nan
        hist, names = history_matrix(context)
        x, schema = weather_features(hist, names, self.origins, weather, 13)
        self.assertTrue(np.isnan(x[0, schema.index('power_age_1h')]))
        self.assertTrue(np.isnan(x[0, schema.index('future_wind_speed')]))

    def test_labels_and_weather_are_separated(self):
        origins, hist, names, weather, targets = training_arrays(self.data)
        self.assertEqual(len(origins), 1)
        self.assertEqual(origins[0], self.origin)
        np.testing.assert_allclose(weather, self.weather, rtol=1e-6)
        np.testing.assert_allclose(targets[0], self.data.power.iloc[168:], rtol=1e-6)

    def test_rejects_future_power_in_unified_csv(self):
        frame = self.data.reset_index(names='timestamp')
        frame.insert(0, 'turbine_id', 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.csv'
            frame.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, 'Future power must be empty'):
                predict_csv(path, Path(tmp), self.origin, 'recorded_oracle')

    def test_single_model_roundtrip_stateless_and_csv(self):
        hist, names = history_matrix(self.context)
        x, schema = all_features(hist, names, self.origins, self.weather)
        model = CatBoostRegressor(iterations=5, depth=2, thread_count=2,
                                 allow_writing_files=False, verbose=False)
        model.fit(x, self.data.power.iloc[168:].to_numpy())
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'turbine_1'
            folder.mkdir()
            model.save_model(str(folder / 'catboost.cbm'))
            (folder / 'metadata.json').write_text(json.dumps({
                'strategy': 'pooled_direct_with_future_weather', 'features': schema,
                'trained_until_exclusive': '2026-01-01', 'weather_source': 'recorded_oracle'}))
            adapter = WeatherCatBoost(folder)
            result = adapter.predict(self.context, self.origins, self.weather)
            self.assertEqual(result.shape, (1,48))
            np.testing.assert_allclose(result[0], model.predict(x).clip(0,1))
            changed = self.context.copy()
            changed[:, :, 0] = 0
            adapter.predict(changed, self.origins, self.weather)
            np.testing.assert_array_equal(result, adapter.predict(self.context, self.origins, self.weather))
            frame = self.data.copy()
            frame.loc[self.origin:, 'power'] = np.nan
            frame = frame.reset_index(names='timestamp')
            frame.insert(0, 'turbine_id', 1)
            path = Path(tmp) / 'input.csv'
            frame.to_csv(path, index=False)
            csv_result = predict_csv(path, Path(tmp), self.origin, 'recorded_oracle')
            np.testing.assert_allclose(csv_result.predicted_power, result[0])
            self.assertEqual(len(list(folder.glob('*.cbm'))), 1)
            with self.assertRaisesRegex(ValueError, 'training cutoff'):
                adapter.predict(self.context, pd.DatetimeIndex(['2025-12-01']), self.weather)


if __name__ == '__main__':
    unittest.main()
