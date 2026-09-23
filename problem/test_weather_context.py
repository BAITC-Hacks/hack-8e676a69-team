"""Prove that power is excluded from every inference/context path."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from weather_context_forecasting import (WEATHER, all_features, history_matrix,
    predict_csv, request_arrays, training_arrays, valid_context)


class WeatherContextTests(unittest.TestCase):
    def setUp(self):
        self.origin = pd.Timestamp('2026-01-22')
        self.origins = pd.DatetimeIndex([self.origin])
        self.data = pd.DataFrame(np.random.default_rng(51).random((240, 3)),
            columns=['power', *WEATHER], index=pd.date_range(
                self.origin-pd.Timedelta(hours=168), periods=240, freq='h'))

    def test_no_power_column_needed_for_request(self):
        first = request_arrays(self.data, self.origins)
        no_power = request_arrays(self.data.drop(columns='power'), self.origins)
        for a, b in zip(first, no_power):
            np.testing.assert_array_equal(a, b)
        x, names = all_features(first[0], first[1], self.origins, first[2])
        self.assertEqual(x.shape, (48, 80))
        self.assertFalse(any('power' in n or 'efficiency' in n for n in names))

    def test_changing_every_power_value_does_not_change_features_or_eligibility(self):
        before = training_arrays(self.data)
        changed = self.data.copy()
        changed['power'] = np.nan
        after = training_arrays(changed)
        for a, b in zip(before[:4], after[:4]):
            np.testing.assert_array_equal(a, b)
        self.assertTrue(np.isnan(after[4]).all())  # labels only

    def test_history_weather_really_is_used(self):
        first = request_arrays(self.data, self.origins)[0]
        changed = self.data.copy()
        changed.loc[self.origin-pd.Timedelta(hours=1), WEATHER] = [20, -10]
        second = request_arrays(changed, self.origins)[0]
        self.assertFalse(np.array_equal(first, second))

    def test_gaps_preserved_and_coverage_weather_only(self):
        context = self.data[WEATHER].iloc[:168].to_numpy()[None, :].copy()
        context[:, -1, 0] = np.nan
        features, names = history_matrix(context)
        self.assertTrue(np.isnan(features[0, names.index('wind_speed_age_1h')]))
        self.assertTrue(valid_context(context)[0])
        context[:, -24:, 0] = np.nan
        self.assertFalse(valid_context(context)[0])

    def test_rejects_power_channel_in_context_array(self):
        with self.assertRaisesRegex(ValueError, 'no power'):
            history_matrix(self.data.iloc[:168].to_numpy()[None, :])


class SavedModelTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).parent / 'evaluation_models_weather_context_no_power/turbine_2/metadata.json').exists(), 'Train models first')
    def test_saved_models_ignore_arbitrary_power_columns(self):
        base = Path(__file__).parent
        data = pd.read_csv(base / 'examples/weather_context_no_power.csv')
        self.assertNotIn('power', data.columns)
        model_dir = base / 'evaluation_models_weather_context_no_power'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'context.csv'
            data.to_csv(path, index=False)
            first = predict_csv(path, model_dir, '2026-01-22', 'recorded_oracle')
            data['power'] = np.arange(len(data)) * 12345
            data['efficiency'] = 'ignored'
            data.to_csv(path, index=False)
            second = predict_csv(path, model_dir, '2026-01-22', 'recorded_oracle')
        pd.testing.assert_frame_equal(first, second)
        self.assertEqual(len(first), 96)
        self.assertTrue(first.predicted_power.between(0, 1).all())
        for turbine in [1, 2]:
            folder = base / f'models_weather_context_no_power/turbine_{turbine}'
            manifest = json.loads((folder / 'metadata.json').read_text())
            self.assertFalse(manifest['historical_power_used'])
            self.assertEqual(manifest['context_columns'], WEATHER)
            self.assertEqual(len(manifest['features']), 80)
            self.assertFalse(any('power' in n for n in manifest['features']))
            self.assertEqual(len(list(folder.glob('*.cbm'))), 1)


if __name__ == '__main__':
    unittest.main()
