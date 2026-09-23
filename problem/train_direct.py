"""Train 48 independent CatBoost horizons per turbine; preserve original models."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from forecasting import DirectCatBoost, HORIZON, load_raw
from train import (BASE, FINAL_END, TEST_START, VALID_START, Tee, evaluate,
                   examples, fit_sar, log, metrics, write_json)


def fit(x, y, iterations, threads, validation=None):
    model = CatBoostRegressor(iterations=iterations, depth=6, learning_rate=0.04,
                             l2_leaf_reg=10, loss_function="RMSE", random_seed=42,
                             thread_count=threads, allow_writing_files=False)
    kwargs = {"verbose": False}
    if validation is not None:
        kwargs.update(eval_set=validation, early_stopping_rounds=100, use_best_model=True)
    model.fit(x, y, **kwargs)
    return model


def summarize(predictions):
    rows = []
    for (turbine, model), group in predictions.groupby(["turbine_id", "model"]):
        for label, lo, hi in [("1h", 1, 1), ("1-6h", 1, 6), ("7-12h", 7, 12),
                              ("13-24h", 13, 24), ("25-48h", 25, 48), ("1-48h", 1, 48)]:
            sample = group[group.horizon.between(lo, hi)].dropna(subset=["actual_power"])
            error = sample.predicted_power - sample.actual_power
            rows.append({"turbine_id": turbine, "model": model, "horizon": label,
                         "n": len(sample), "mae": float(error.abs().mean()),
                         "rmse": float(np.sqrt((error ** 2).mean()))})
    return pd.DataFrame(rows)


def save_manifest(original, destination, settings, feature_names, sar, gap_policy, tag):
    metadata = json.loads((original / "metadata.json").read_text())
    metadata.update(catboost_strategy="direct_per_horizon", features=feature_names,
                    catboost_trees_by_horizon={str(s["horizon"]): s["trees"] for s in settings},
                    gap_policy=gap_policy,
                    gap_fill="No filling; preserve missing measurements" if gap_policy == "preserve" else "causal forward-fill",
                    catboost_output_name=f"catboost_{tag}", sarimax_output_name=f"sarimax_{tag}",
                    selection={"validation_period": "December 2025", "horizons": settings,
                               "sarimax_order": sar["order"]})
    metadata.pop("catboost_trees", None)
    write_json(destination / "metadata.json", metadata)
    write_json(destination / "sarimax.json", sar)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=800)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--stride", type=int, default=6)
    parser.add_argument("--tag", choices=["direct", "direct_missing"], default="direct_missing")
    parser.add_argument("--gap-policy", choices=["preserve", "forward_fill"], default="preserve")
    args = parser.parse_args()
    reports = BASE / "reports" / args.tag
    reports.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (reports / "training.log").open("w", buffering=1) as logfile:
        original_stdout = sys.stdout
        sys.stdout = Tee(sys.stdout, logfile)
        try:
            comparisons, all_settings = [], {}
            for turbine in [1, 2]:
                log(f"TURBINE {turbine}: preparing unchanged 168h context and 48h targets")
                path, = BASE.glob(f"*turbine {turbine}.csv")
                hourly, _ = load_raw(path)
                x, y, meta = examples(hourly, args.stride, gap_policy=args.gap_policy)
                x = x.drop(columns="horizon")
                before_valid = meta.origin + pd.Timedelta(hours=HORIZON) <= VALID_START
                validation = ((meta.origin >= VALID_START)
                              & (meta.origin + pd.Timedelta(hours=HORIZON) <= TEST_START))
                before_test = meta.origin + pd.Timedelta(hours=HORIZON) <= TEST_START
                final = meta.origin + pd.Timedelta(hours=HORIZON) <= FINAL_END
                assert (meta.loc[before_valid, "target_time"] < VALID_START).all()
                assert (meta.loc[before_test, "target_time"] < TEST_START).all()
                evaluation_dir = BASE / f"evaluation_models_{args.tag}/turbine_{turbine}"
                production_dir = BASE / f"models_{args.tag}/turbine_{turbine}"
                evaluation_dir.mkdir(parents=True, exist_ok=True)
                production_dir.mkdir(parents=True, exist_ok=True)
                settings = []
                for horizon in range(1, HORIZON + 1):
                    hstart = time.monotonic()
                    selected = meta.horizon == horizon
                    train, val = before_valid & selected, validation & selected
                    pretest, full = before_test & selected, final & selected
                    tuned = fit(x.loc[train], y.loc[train], args.iterations, args.threads,
                                (x.loc[val], y.loc[val]))
                    trees = tuned.tree_count_
                    setting = {"horizon": horizon, "trees": trees,
                               "december_rmse": float(tuned.best_score_["validation"]["RMSE"]),
                               "train_rows": int(train.sum()), "validation_rows": int(val.sum()),
                               "evaluation_train_rows": int(pretest.sum()), "final_train_rows": int(full.sum())}
                    evaluation = fit(x.loc[pretest], y.loc[pretest], trees, args.threads)
                    evaluation.save_model(str(evaluation_dir / f"catboost_h{horizon:02d}.cbm"))
                    production = fit(x.loc[full], y.loc[full], trees, args.threads)
                    production.save_model(str(production_dir / f"catboost_h{horizon:02d}.cbm"))
                    settings.append(setting)
                    completed = (turbine - 1) * HORIZON + horizon
                    log(f"{completed}/96 ({completed/96:.0%}) | turbine {turbine}, horizon {horizon:02d} | "
                        f"{trees} trees | Dec RMSE {setting['december_rmse']:.4f} | "
                        f"{time.monotonic()-hstart:.1f}s (selection + evaluation + production fits)")
                log(f"TURBINE {turbine}: selecting SARIMAX with gap_policy={args.gap_policy}")
                candidates = []
                for order in [(1, 0, 0), (2, 0, 1)]:
                    candidate = fit_sar(hourly, VALID_START, order, gap_policy=args.gap_policy)
                    score = metrics(evaluate(hourly, VALID_START, TEST_START, turbine,
                                             sar=candidate, gap_policy=args.gap_policy))
                    rmse = float(score[(score.model == "sarimax") & (score.horizon == "1-48h")].iloc[0].rmse)
                    log(f"  December SARIMAX{order}: RMSE {rmse:.5f}")
                    if candidate["converged"]:
                        candidates.append((rmse, candidate))
                if not candidates:
                    raise RuntimeError("No converged SARIMAX candidate")
                _, chosen = min(candidates, key=lambda item: item[0])
                evaluation_sar = fit_sar(hourly, TEST_START, chosen["order"], chosen["params"], args.gap_policy)
                production_sar = fit_sar(hourly, FINAL_END, chosen["order"], evaluation_sar["params"], args.gap_policy)
                if not evaluation_sar["converged"] or not production_sar["converged"]:
                    raise RuntimeError("SARIMAX refit did not converge")
                save_manifest(BASE / f"evaluation_models/turbine_{turbine}", evaluation_dir, settings,
                              list(x.columns), evaluation_sar, args.gap_policy, args.tag)
                save_manifest(BASE / f"models/turbine_{turbine}", production_dir, settings,
                              list(x.columns), production_sar, args.gap_policy, args.tag)
                all_settings[turbine] = settings
                direct = evaluate(hourly, TEST_START, FINAL_END, turbine, cat=DirectCatBoost(evaluation_dir),
                                  sar=evaluation_sar, gap_policy=args.gap_policy)
                direct = direct[direct.model.isin(["catboost", "sarimax"])].copy()
                direct["model"] = direct.model.map({"catboost": f"catboost_{args.tag}",
                                                    "sarimax": f"sarimax_{args.tag}"})
                direct.to_csv(reports / f"turbine_{turbine}_holdout_predictions.csv", index=False)
                old = pd.read_csv(BASE / f"reports/turbine_{turbine}_holdout_predictions.csv",
                                  parse_dates=["timestamp", "forecast_origin"])
                old_direct_path = BASE / f"reports/direct/turbine_{turbine}_holdout_predictions.csv"
                if args.tag != "direct" and old_direct_path.exists():
                    prior_direct = pd.read_csv(old_direct_path, parse_dates=["timestamp", "forecast_origin"])
                    old = pd.concat([old, prior_direct[prior_direct.model == "catboost_direct"]], ignore_index=True)
                combined = pd.concat([old, direct], ignore_index=True)
                # Exact same labels and origin/horizon pairs as the previous model.
                old_cat = old[old.model == "catboost"].sort_values(["forecast_origin", "horizon"])
                new_cat = direct[direct.model == f"catboost_{args.tag}"].sort_values(["forecast_origin", "horizon"])
                np.testing.assert_array_equal(old_cat.timestamp.to_numpy(), new_cat.timestamp.to_numpy())
                np.testing.assert_allclose(old_cat.actual_power, new_cat.actual_power, equal_nan=True)
                comparisons.append(combined)
                score = summarize(combined)
                log(f"TURBINE {turbine}: January comparison\n" + score[
                    score.model.isin(["catboost", "catboost_direct", f"catboost_{args.tag}", f"sarimax_{args.tag}"]) & score.horizon.isin(["1h", "1-6h", "1-48h"])
                ].to_string(index=False))
            combined = pd.concat(comparisons, ignore_index=True)
            combined.to_csv(reports / "comparison_predictions.csv", index=False)
            summary = summarize(combined)
            summary.to_csv(reports / "comparison_metrics.csv", index=False)
            metrics(combined).to_csv(reports / "metrics.csv", index=False)
            by_horizon = []
            for keys, group in combined.groupby(["turbine_id", "model", "horizon"]):
                error = group.predicted_power - group.actual_power
                by_horizon.append({"turbine_id": keys[0], "model": keys[1], "horizon": keys[2],
                                   "mae": float(error.abs().mean()), "rmse": float(np.sqrt((error**2).mean()))})
            pd.DataFrame(by_horizon).to_csv(reports / "metrics_by_horizon.csv", index=False)
            write_json(reports / "run_summary.json", {"elapsed_seconds": time.monotonic()-started,
                "settings": all_settings, "arguments": vars(args),
                "evaluation_note": "January was previously inspected; this is a development comparison, not a new untouched test.",
                "context_hours": 168, "future_weather": False, "gap_policy": args.gap_policy,
                "sarimax_changed": True})
            log(f"COMPLETE: 96 direct production models saved, elapsed {time.monotonic()-started:.1f}s")
        finally:
            sys.stdout = original_stdout


if __name__ == "__main__":
    main()
