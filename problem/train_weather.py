"""Train one CatBoost per turbine: weather history + future weather, no power inputs."""
import argparse
import sys
import time

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from forecasting import load_raw
from train import BASE, FINAL_END, TEST_START, VALID_START, Tee, log, write_json
from train_direct import summarize
from weather_forecasting import CONTEXT, HORIZON, WEATHER, all_features


def fit(x, y, iterations, threads, validation=None):
    model = CatBoostRegressor(iterations=iterations, depth=6, learning_rate=.04,
        l2_leaf_reg=10, loss_function='RMSE', random_seed=42, thread_count=threads,
        allow_writing_files=False)
    options = dict(verbose=100)
    if validation is not None:
        options.update(eval_set=validation, early_stopping_rounds=100)
    model.fit(x, y, **options)
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=800)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--stride', type=int, default=6)
    parser.add_argument('--include-power-history', action='store_true', help='Reproduce the earlier model, not the current default')
    args = parser.parse_args()
    if args.include_power_history:
        from weather_forecasting import MODEL_NAME, request_arrays, training_arrays
        tag, strategy = 'weather_oracle', 'pooled_direct_with_future_weather'
    else:
        from weather_context_forecasting import MODEL_NAME, STRATEGY, request_arrays, training_arrays
        tag, strategy = 'weather_context_no_power', STRATEGY
    reports = BASE / 'reports' / tag
    reports.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    original_stdout = sys.stdout
    comparisons, example_parts, settings = [], [], {}
    with (reports / 'training.log').open('w', buffering=1) as logfile:
        sys.stdout = Tee(sys.stdout, logfile)
        try:
            log('LOCAL DATA ONLY. Recorded future weather is an oracle input, not a weather forecast.')
            log(f'Historical power features enabled: {args.include_power_history}')
            for turbine in [1, 2]:
                log(f'TURBINE {turbine}/2: preparing one shared model for all 48 horizons')
                path, = BASE.glob(f'*turbine {turbine}.csv')
                hourly, audit = load_raw(path)
                origins, hist, history_names, weather, targets = training_arrays(hourly, args.stride)
                x, schema = all_features(hist, history_names, origins, weather)
                if not args.include_power_history:
                    assert not any('power' in name or 'efficiency' in name for name in schema)
                y = targets.ravel()
                row_origins = np.repeat(origins.to_numpy(), HORIZON)
                window_end = row_origins + np.timedelta64(HORIZON, 'h')
                usable = np.isfinite(y)
                train = usable & (window_end <= VALID_START.to_datetime64())
                val = usable & (row_origins >= VALID_START.to_datetime64()) & (window_end <= TEST_START.to_datetime64())
                pretest = usable & (window_end <= TEST_START.to_datetime64())
                final = usable & (window_end <= FINAL_END.to_datetime64())
                log(f'  {x.shape[1]} features; {train.sum()} train rows, {val.sum()} validation rows')
                log('  [1/3] Tree-count selection on December 2025')
                tuned = fit(x[train], y[train], args.iterations, args.threads, (x[val], y[val]))
                trees = tuned.tree_count_
                setting = {'trees': trees, 'validation_rmse': tuned.best_score_['validation']['RMSE'],
                           'train_rows': int(train.sum()), 'validation_rows': int(val.sum())}
                log(f'  [2/3] Evaluation refit before January: {trees} trees')
                evaluation = fit(x[pretest], y[pretest], trees, args.threads)
                log('  [3/3] Final offline refit through January 31')
                production = fit(x[final], y[final], trees, args.threads)
                for parent, model, cutoff in [(f'evaluation_models_{tag}', evaluation, TEST_START),
                                               (f'models_{tag}', production, FINAL_END)]:
                    folder = BASE / parent / f'turbine_{turbine}'
                    folder.mkdir(parents=True, exist_ok=True)
                    model.save_model(str(folder / 'catboost.cbm'))
                    write_json(folder / 'metadata.json', {'strategy': strategy,
                        'turbine_id': turbine, 'model_count': 1, 'context_hours': CONTEXT,
                        'historical_power_used': args.include_power_history,
                        'context_columns': ['power', *WEATHER] if args.include_power_history else WEATHER,
                        'horizon_hours': HORIZON, 'features': schema, 'weather_columns': WEATHER,
                        'weather_source': 'recorded_oracle', 'gap_policy': 'preserve',
                        'trained_until_exclusive': str(cutoff), 'selection': setting,
                        'target': 'normalized_active_power', 'source_audit': audit,
                        'warning': 'Recorded future weather benchmark. Not validated on real weather forecasts.'})
                test_origins = pd.date_range(TEST_START, FINAL_END-pd.Timedelta(hours=HORIZON), freq='24h')
                th, tn, tw = request_arrays(hourly, test_origins)
                tx, _ = all_features(th, tn, test_origins, tw)
                forecast = evaluation.predict(tx).reshape(-1, HORIZON).clip(0, 1)
                rows = []
                for origin, prediction in zip(test_origins, forecast):
                    grid = pd.date_range(origin, periods=HORIZON, freq='h')
                    rows.append(pd.DataFrame({'turbine_id': turbine, 'forecast_origin': origin,
                        'timestamp': grid, 'horizon': np.arange(1,49), 'model': MODEL_NAME,
                        'actual_power': hourly.power.reindex(grid).to_numpy(), 'predicted_power': prediction}))
                new = pd.concat(rows, ignore_index=True)
                new.to_csv(reports / f'turbine_{turbine}_holdout_predictions.csv', index=False)
                old = pd.read_csv(BASE / 'reports/direct_missing/comparison_predictions.csv',
                                  parse_dates=['forecast_origin', 'timestamp'])
                old = old[(old.turbine_id == turbine) & old.model.isin(['catboost', 'catboost_direct_missing', 'context_mean', 'persistence'])]
                previous_path = BASE / f'reports/weather_oracle/turbine_{turbine}_holdout_predictions.csv'
                if not args.include_power_history and previous_path.exists():
                    old = pd.concat([old, pd.read_csv(previous_path, parse_dates=['forecast_origin', 'timestamp'])], ignore_index=True)
                # Compare exactly the same real target hours as the prior pipeline.
                reference = old[old.model == 'catboost_direct_missing'].sort_values(['forecast_origin', 'horizon'])
                ordered = new.sort_values(['forecast_origin', 'horizon'])
                np.testing.assert_array_equal(reference.timestamp, ordered.timestamp)
                np.testing.assert_allclose(reference.actual_power, ordered.actual_power, equal_nan=True)
                combined = pd.concat([old, new], ignore_index=True)
                comparisons.append(combined)
                log('  January results:\n' + summarize(combined).query("horizon == '1-48h'").to_string(index=False))
                settings[turbine] = setting
                origin = pd.Timestamp('2026-01-22')
                example = hourly.loc[origin-pd.Timedelta(hours=CONTEXT):origin+pd.Timedelta(hours=HORIZON-1),
                                     ['power', *WEATHER]].copy()
                example.loc[example.index >= origin, 'power'] = np.nan
                if not args.include_power_history:
                    example = example[WEATHER]
                example = example.reset_index(names='timestamp')
                example.insert(0, 'turbine_id', turbine)
                example_parts.append(example)
                summarize(pd.concat(comparisons, ignore_index=True)).to_csv(reports / 'comparison_metrics.csv', index=False)
            combined = pd.concat(comparisons, ignore_index=True)
            combined.to_csv(reports / 'comparison_predictions.csv', index=False)
            example_name = 'context_with_weather.csv' if args.include_power_history else 'weather_context_no_power.csv'
            pd.concat(example_parts, ignore_index=True).to_csv(BASE / 'examples' / example_name, index=False)
            write_json(reports / 'run_summary.json', {'seconds': time.monotonic()-started,
                'arguments': vars(args), 'settings': settings, 'models_per_turbine': 1,
                'historical_power_used': args.include_power_history,
                'weather_source': 'recorded_oracle', 'network_used': False,
                'evaluation_note': 'January development comparison with actual future weather. Not an operational forecast accuracy estimate.'})
            log(f'COMPLETE: 2 single-model production bundles; {time.monotonic()-started:.1f}s')
        finally:
            sys.stdout = original_stdout


if __name__ == '__main__':
    main()
