"""Contract tests: causal features, forward-fill, and stateless model inference."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import numpy as np
import pandas as pd

from forecasting import (CONTEXT, VALUES, DirectCatBoost, calendar, context_at, features,
                         predict_csv, read_context_csv, sarimax_model, sarimax_predict)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.origin = pd.Timestamp("2026-02-01")
        index = pd.date_range(self.origin - pd.Timedelta(hours=200), periods=250, freq="h")
        self.history = pd.DataFrame({
            "power": 0.5 + 0.2 * np.sin(np.arange(250) / 8),
            "wind_speed": np.arange(250) / 50 + 5,
            "temperature": np.cos(np.arange(250) / 24),
        }, index=index)

    def test_future_and_outside_window_do_not_affect_features(self):
        original = features(context_at(self.history, self.origin), self.origin)
        changed = self.history.copy()
        changed.loc[changed.index >= self.origin, VALUES] = 9999
        changed.loc[changed.index < self.origin - pd.Timedelta(hours=CONTEXT), VALUES] = -9999
        actual = features(context_at(changed, self.origin), self.origin)
        pd.testing.assert_frame_equal(original, actual)

    def test_missing_values_remain_nan_and_preserve_observation_mask(self):
        missing = self.origin - pd.Timedelta(hours=3)
        self.history.loc[missing, "power"] = np.nan
        context = context_at(self.history, self.origin)
        self.assertTrue(pd.isna(context.loc[missing, "power"]))
        self.assertFalse(context.loc[missing, "power_observed"])

    def test_legacy_forward_fill_is_explicit(self):
        missing = self.origin - pd.Timedelta(hours=3)
        previous = self.history.loc[missing - pd.Timedelta(hours=1), "power"]
        self.history.loc[missing, "power"] = np.nan
        context = context_at(self.history, self.origin, gap_policy="forward_fill")
        self.assertEqual(context.loc[missing, "power"], previous)
        self.assertFalse(context.loc[missing, "power_observed"])

    def test_sarimax_does_not_turn_missing_observations_into_training_labels(self):
        self.history.loc[self.origin - pd.Timedelta(hours=48):self.origin - pd.Timedelta(hours=12), "power"] = np.nan
        context = context_at(self.history, self.origin)
        model = sarimax_model(context.power, (1, 0, 0))
        np.testing.assert_array_equal(np.isnan(model.endog[:, 0]), context.power.isna().to_numpy())
        self.assertEqual(int(np.isnan(model.endog).sum()), 37)

    def test_missing_rows_and_explicit_nan_rows_are_equivalent(self):
        timestamp = self.origin - pd.Timedelta(hours=5)
        explicit = self.history.copy()
        explicit.loc[timestamp, VALUES] = np.nan
        pd.testing.assert_frame_equal(context_at(explicit, self.origin),
                                      context_at(self.history.drop(timestamp), self.origin))

    def test_leading_gaps_are_not_backfilled(self):
        short = self.history.loc[self.history.index >= self.origin - pd.Timedelta(hours=48)]
        context = context_at(short, self.origin)
        self.assertTrue(context[VALUES].iloc[:120].isna().all().all())
        self.assertEqual(features(context, self.origin).shape[0], 48)

    def test_features_have_no_future_target_lags(self):
        context = context_at(self.history, self.origin)
        x = features(context, self.origin)
        self.assertEqual(x.power_age_1h.nunique(), 1)
        self.assertAlmostEqual(float(x.power_age_1h.iloc[-1]), context.power.iloc[-1], places=6)
        self.assertEqual(x.horizon.tolist(), list(range(1, 49)))

    def test_reject_duplicate_input(self):
        data = self.history.iloc[:2].reset_index(names="timestamp")
        data["turbine_id"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.csv"
            pd.concat([data, data]).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                read_context_csv(path)

    def test_sarimax_filter_does_not_train_or_depend_on_previous_call(self):
        context = context_at(self.history, self.origin)
        model = sarimax_model(context.power, (1, 0, 0))
        params = np.zeros(len(model.param_names))
        params[model.param_names.index("constant")] = 0.5
        params[model.param_names.index("ar.L1")] = 0.8
        params[model.param_names.index("sigma2")] = 0.02
        artifact = {"order": [1, 0, 0], "param_names": model.param_names,
                    "params": params.tolist(), "gap_policy": "preserve"}
        first = sarimax_predict(context, self.origin, artifact)
        other = context.copy()
        other["power"] = 0.1
        sarimax_predict(other, self.origin, artifact)
        np.testing.assert_array_equal(first, sarimax_predict(context, self.origin, artifact))
        self.assertEqual(first.shape, (48,))
        self.assertTrue(np.isfinite(first).all())

    def test_direct_adapter_routes_correct_row_to_each_horizon(self):
        bundle = DirectCatBoost.__new__(DirectCatBoost)
        bundle.models = [Mock() for _ in range(48)]
        for i, model in enumerate(bundle.models):
            model.predict.return_value = np.array([i / 48])
        x = features(context_at(self.history, self.origin), self.origin)
        result = bundle.predict(x)
        np.testing.assert_array_equal(result, np.arange(48) / 48)
        for i, model in enumerate(bundle.models):
            model.predict.assert_called_once()
            supplied = model.predict.call_args.args[0]
            pd.testing.assert_frame_equal(supplied, x.drop(columns="horizon").iloc[[i]])
        with self.assertRaisesRegex(ValueError, "ordered by horizon"):
            bundle.predict(x.iloc[::-1])


class TrainedModelTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).parent / "models_direct_missing/turbine_2/metadata.json").exists(),
                         "Missing-aware direct models have not been generated yet")
    def test_missing_aware_production_handles_gaps_without_filling(self):
        base = Path(__file__).parent
        data = pd.read_csv(base / "examples/context.csv")
        data = data.drop(data.index[::11]).copy()
        data.loc[data.index[::13], "power"] = np.nan
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.csv"
            data.to_csv(path, index=False)
            first = predict_csv(path, base / "models_direct_missing", pd.Timestamp("2026-02-01"))
            second = predict_csv(path, base / "models_direct_missing", pd.Timestamp("2026-02-01"))
        pd.testing.assert_frame_equal(first, second)
        self.assertEqual(len(first), 192)
        self.assertTrue(first.predicted_power.between(0, 1).all())
        self.assertEqual(set(first.model), {"catboost_direct_missing", "sarimax_direct_missing"})
        for turbine in [1, 2]:
            folder = base / f"models_direct_missing/turbine_{turbine}"
            self.assertEqual(len(list(folder.glob("catboost_h*.cbm"))), 48)
            for name in ["metadata.json", "sarimax.json"]:
                artifact = json.loads((folder / name).read_text())
                self.assertEqual(artifact["gap_policy"], "preserve")
            self.assertTrue(artifact["converged"])

    @unittest.skipUnless((Path(__file__).parent / "models_direct/turbine_2/metadata.json").exists(),
                         "Direct models have not been generated yet")
    def test_direct_production_roundtrip_and_sarimax_unchanged(self):
        base = Path(__file__).parent
        direct = predict_csv(base / "examples/context.csv", base / "models_direct")
        original = predict_csv(base / "examples/context.csv", base / "models")
        self.assertEqual(len(direct), 192)
        self.assertEqual(set(direct.model), {"catboost_direct", "sarimax"})
        self.assertTrue(direct.predicted_power.between(0, 1).all())
        np.testing.assert_array_equal(direct[direct.model == "sarimax"].predicted_power.to_numpy(),
                                      original[original.model == "sarimax"].predicted_power.to_numpy())
        for turbine in [1, 2]:
            self.assertEqual(len(list((base / f"models_direct/turbine_{turbine}").glob("catboost_h*.cbm"))), 48)

    @unittest.skipUnless((Path(__file__).parent / "models/turbine_2/catboost.cbm").exists(),
                         "Training artifacts have not been generated yet")
    def test_production_roundtrip_without_training_data(self):
        base = Path(__file__).parent
        result = predict_csv(base / "examples/context.csv", base / "models")
        self.assertEqual(len(result), 2 * 2 * 48)
        self.assertEqual(result.groupby(["turbine_id", "model"]).size().tolist(), [48] * 4)
        self.assertTrue(result.predicted_power.between(0, 1).all())
        self.assertEqual(result.timestamp.min(), pd.Timestamp("2026-02-01"))
        self.assertEqual(result.timestamp.max(), pd.Timestamp("2026-02-02 23:00:00"))
        for turbine in [1, 2]:
            artifact = json.loads((base / f"models/turbine_{turbine}/sarimax.json").read_text())
            self.assertTrue(artifact["converged"])

    @unittest.skipUnless((Path(__file__).parent / "models/turbine_2/catboost.cbm").exists(),
                         "Training artifacts have not been generated yet")
    def test_saved_models_handle_missing_hours_and_repeatable_requests(self):
        base = Path(__file__).parent
        data = pd.read_csv(base / "examples/context.csv")
        origin = pd.Timestamp("2026-02-01")
        # Remove internal rows and leave explicit NaNs; retain recent real readings.
        data = data.drop(data.index[::11]).copy()
        data.loc[data.index[::13], "power"] = np.nan
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context.csv"
            data.to_csv(path, index=False)
            first = predict_csv(path, base / "models", origin)
            second = predict_csv(path, base / "models", origin)
        pd.testing.assert_frame_equal(first, second)
        self.assertEqual(len(first), 192)
        self.assertTrue(np.isfinite(first.predicted_power).all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
