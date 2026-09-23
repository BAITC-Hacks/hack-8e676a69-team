"""Causality, missing-data, and rollout tests for the experiment."""
import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from catboost_benchmark import (COLS, cat, historical_features, matrices,
                               recursive, request_contexts)


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame(
            np.random.default_rng(42).random((900, 3)),
            columns=COLS, index=pd.date_range('2025-01-01', periods=900, freq='h'))

    def test_future_changes_labels_not_features(self):
        origin = self.data.index[750]
        origins = pd.DatetimeIndex([origin])
        _, context, actual = request_contexts(self.data, origins)
        changed = self.data.copy()
        changed.loc[origin:] = 99
        _, other, new_actual = request_contexts(changed, origins)
        np.testing.assert_array_equal(context, other)
        self.assertFalse(np.array_equal(actual, new_actual))
        np.testing.assert_array_almost_equal(actual[0], self.data.power.iloc[750:798])

    def test_training_alignment(self):
        origins, hist, names, targets, next_values = matrices(self.data)
        self.assertEqual(origins[0], self.data.index[720])
        np.testing.assert_array_almost_equal(targets[0], self.data.power.iloc[720:768])
        np.testing.assert_array_almost_equal(next_values[0], self.data.iloc[720])
        self.assertAlmostEqual(hist['base'][0, names['base'].index('power_age_1h')], self.data.power.iloc[719])

    def test_gaps_not_imputed_and_long_window_is_distinct(self):
        contexts = self.data.iloc[:720].to_numpy()[None, :].copy()
        contexts[0, -1, 0] = np.nan
        features, names = historical_features(contexts)
        self.assertTrue(np.isnan(features[0, names.index('power_age_1h')]))
        self.assertEqual(features[0, names.index('power_age_last_observed')], 2)
        changed = contexts.copy()
        changed[:, :500] = 10
        np.testing.assert_array_equal(features, historical_features(changed)[0])
        self.assertFalse(np.array_equal(historical_features(contexts, 'long')[0],
                                       historical_features(changed, 'long')[0], equal_nan=True))

    def test_recursive_uses_predictions_without_mutating_context(self):
        class Model:
            def predict(self, x, ntree_end=0):
                return x[:, 0] * .9
        contexts = self.data.iloc[:720].to_numpy()[None, :]
        original = contexts.copy()
        prediction = recursive(Model(), contexts, pd.DatetimeIndex([self.data.index[720]]))
        expected = contexts[0, -1, 0] * .9 ** np.arange(1, 49)
        np.testing.assert_allclose(prediction[0], expected, rtol=2e-6)
        np.testing.assert_array_equal(contexts, original)

    def test_catboost_handles_missing_multioutput_labels(self):
        rng = np.random.default_rng(123)
        x, y = rng.random((40, 5)), rng.random((40, 48))
        x[0, 0] = np.nan
        y[::2, 0] = np.nan
        model = cat(3, SimpleNamespace(threads=2), multi=True)
        model.fit(x, y, verbose=False)
        result = model.predict(x[:2])
        self.assertEqual(result.shape, (2, 48))
        self.assertTrue(np.isfinite(result).all())


if __name__ == '__main__':
    unittest.main()
