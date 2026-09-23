"""Train, evaluate, then export two stateless forecasting models per turbine."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import warnings

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from forecasting import (CONTEXT, HORIZON, VALUES, calendar, check_context,
                         context_at, features, load_raw, sarimax_model, sarimax_predict)

BASE = Path(__file__).resolve().parent
VALID_START = pd.Timestamp("2025-12-01")
TEST_START = pd.Timestamp("2026-01-01")
FINAL_END = pd.Timestamp("2026-02-01")


class Tee:
    def __init__(self, stream, file):
        self.stream, self.file = stream, file

    def write(self, value):
        self.stream.write(value)
        self.file.write(value)
        self.file.flush()

    def flush(self):
        self.stream.flush()
        self.file.flush()


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def examples(hourly, stride, gap_policy="preserve"):
    first = hourly.index.min() + pd.Timedelta(hours=CONTEXT)
    last = hourly.index.max() - pd.Timedelta(hours=HORIZON - 1)
    origins = pd.date_range(first, last, freq=f"{stride}h")
    xs, ys, metas = [], [], []
    skipped = 0
    for i, origin in enumerate(origins):
        context = context_at(hourly, origin, gap_policy=gap_policy)
        try:
            x = features(context, origin)
        except ValueError:
            skipped += 1
            continue
        y = hourly.power.reindex(x.index)
        keep = y.notna()
        if not keep.any():
            skipped += 1
            continue
        xs.append(x.loc[keep])
        ys.append(y.loc[keep])
        metas.append(pd.DataFrame({"origin": origin, "target_time": x.index[keep],
                                   "horizon": x.loc[keep, "horizon"].to_numpy()}))
        if i % 500 == 0:
            log(f"  Feature windows {i + 1}/{len(origins)} ({(i+1)/len(origins):.0%})")
    log(f"  Feature windows complete; skipped {skipped} insufficient-context/target windows")
    return (pd.concat(xs, ignore_index=True), pd.concat(ys, ignore_index=True),
            pd.concat(metas, ignore_index=True))


def fit_cat(x, y, iterations, threads, valid=None):
    cat = CatBoostRegressor(iterations=iterations, depth=6, learning_rate=0.04,
                            loss_function="RMSE", l2_leaf_reg=10, random_seed=42,
                            thread_count=threads, allow_writing_files=False)
    options = dict(verbose=50)
    if valid is not None:
        options.update(eval_set=valid, early_stopping_rounds=100, use_best_model=True)
    started = time.monotonic()
    cat.fit(x, y, **options)
    log(f"  CatBoost done: {cat.tree_count_} trees, {time.monotonic()-started:.1f}s")
    return cat


def fit_sar(hourly, cutoff, order, initial=None, gap_policy="preserve"):
    power = hourly.loc[hourly.index < cutoff, "power"]
    model = sarimax_model(power, order, gap_policy=gap_policy)
    started = time.monotonic()
    count = [0]

    def progress(_):
        count[0] += 1
        if count[0] % 10 == 0:
            log(f"  SARIMAX{tuple(order)} optimizer iteration {count[0]}, {time.monotonic()-started:.1f}s")

    log(f"  Fitting SARIMAX{tuple(order)} on {len(power)} hourly slots, cutoff {cutoff}")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = model.fit(start_params=initial, maxiter=180, disp=False,
                           callback=progress, cov_type="none")
        if not result.mle_retvals.get("converged", False):
            log("  Optimizer has not converged; retrying from fitted parameters (up to 250 iterations)")
            result = model.fit(start_params=result.params, maxiter=250, disp=False,
                               callback=progress, cov_type="none")
    if not np.isfinite(result.params).all():
        raise RuntimeError("SARIMAX produced nonfinite parameters")
    artifact = {
        "gap_policy": gap_policy,
        "order": list(order), "seasonal_order": [0, 0, 0, 0],
        "seasonality": "Two annual Fourier harmonics and one daily harmonic in exog",
        "param_names": list(model.param_names), "params": result.params.tolist(),
        "exog_columns": list(calendar(power.index).columns),
        "trained_until_exclusive": str(cutoff),
        "converged": bool(result.mle_retvals.get("converged", False)),
        "optimizer_iterations": int(result.mle_retvals.get("iterations", count[0])),
        "aic": float(result.aic), "training_seconds": time.monotonic() - started,
        "warnings": list(dict.fromkeys(str(w.message) for w in caught)),
    }
    log(f"  SARIMAX done: converged={artifact['converged']}, {artifact['training_seconds']:.1f}s")
    return artifact


def evaluate(hourly, start, stop, turbine, cat=None, sar=None, gap_policy="preserve"):
    rows = []
    last_origin = stop - pd.Timedelta(hours=HORIZON)
    for origin in pd.date_range(start, last_origin, freq="24h"):
        context = context_at(hourly, origin, gap_policy=gap_policy)
        try:
            check_context(context)
        except ValueError:
            continue
        future = pd.date_range(origin, periods=HORIZON, freq="h")
        truth = hourly.power.reindex(future).to_numpy()
        predictions = {
            "persistence": np.repeat(context.power.dropna().iloc[-1], HORIZON),
            "context_mean": np.repeat(context.power.mean(), HORIZON),
        }
        if cat is not None:
            predictions["catboost"] = cat.predict(features(context, origin)).clip(0, 1)
        if sar is not None:
            predictions["sarimax"] = sarimax_predict(context, origin, sar)
        for name, pred in predictions.items():
            if not np.isfinite(pred).all():
                raise ValueError(f"Nonfinite {name} prediction at {origin}")
            rows.append(pd.DataFrame({"turbine_id": turbine, "forecast_origin": origin,
                                      "timestamp": future, "horizon": np.arange(1, HORIZON + 1),
                                      "model": name, "actual_power": truth, "predicted_power": pred}))
    return pd.concat(rows, ignore_index=True)


def metrics(predictions):
    rows = []
    for (turbine, name), group in predictions.groupby(["turbine_id", "model"]):
        for label, keep in [("1-48h", group.horizon > 0),
                            ("1-24h", group.horizon <= 24), ("25-48h", group.horizon > 24)]:
            valid = group.loc[keep].dropna(subset=["actual_power"])
            error = valid.predicted_power - valid.actual_power
            rows.append({"turbine_id": turbine, "model": name, "horizon": label,
                         "n": len(valid), "origins": valid.forecast_origin.nunique(),
                         "mae": float(error.abs().mean()),
                         "rmse": float(np.sqrt((error ** 2).mean()))})
    return pd.DataFrame(rows)


def save_models(folder, cat, sar, cutoff, audit, selection):
    folder.mkdir(parents=True, exist_ok=True)
    cat.save_model(str(folder / "catboost.cbm"))
    write_json(folder / "sarimax.json", sar)
    write_json(folder / "metadata.json", {
        "context_hours": CONTEXT, "forecast_hours": HORIZON,
        "trained_until_exclusive": str(cutoff), "timezone": "naive source/site time, unknown offset",
        "requires_future_weather": False, "gap_policy": "preserve",
        "gap_fill": "None: retain NaN; numeric missing handling for CatBoost, Kalman prediction-only steps for SARIMAX",
        "features": cat.feature_names_, "catboost_trees": cat.tree_count_,
        "selection": selection, "data": audit,
        "versions": {p: importlib.metadata.version(p) for p in
                     ["numpy", "pandas", "catboost", "statsmodels", "scipy"]},
    })


def plots(predictions, scores, report_dir):
    os.environ.setdefault("MPLCONFIGDIR", str(report_dir / "matplotlib-cache"))
    os.environ.setdefault("XDG_CACHE_HOME", str(report_dir / "cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4), constrained_layout=True)
    for turbine, ax in zip([1, 2], axes):
        group = scores[(scores.turbine_id == turbine) & (scores.horizon == "1-48h")]
        ax.bar(group.model, group.mae)
        ax.set(title=f"Turbine {turbine}: January holdout", ylabel="MAE (normalized power)")
        ax.tick_params(axis="x", rotation=15)
    fig.savefig(report_dir / "holdout_metrics.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), constrained_layout=True)
    for turbine, ax in zip([1, 2], axes):
        group = predictions[(predictions.turbine_id == turbine)
                            & (predictions.forecast_origin == TEST_START)]
        for name in ["catboost", "sarimax", "persistence"]:
            sample = group[group.model == name]
            ax.plot(sample.timestamp, sample.predicted_power, label=name)
        sample = group[group.model == "catboost"]
        ax.plot(sample.timestamp, sample.actual_power, color="black", linewidth=2, label="actual")
        ax.set(title=f"Turbine {turbine}: first 48-hour holdout forecast", ylabel="Normalized power")
        ax.legend(ncol=4)
    fig.savefig(report_dir / "holdout_first_forecast.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=800)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--stride", type=int, default=6, help="Training forecast origins every N hours")
    args = parser.parse_args()
    report_dir = BASE / "reports"
    report_dir.mkdir(exist_ok=True)
    log_file = (report_dir / "training.log").open("w", buffering=1)
    sys.stdout = Tee(sys.stdout, log_file)
    started = time.monotonic()
    datasets, audits, evaluations, selections = {}, {}, [], {}
    for turbine in [1, 2]:
        path, = BASE.glob(f"*turbine {turbine}.csv")
        hourly, audit = load_raw(path)
        datasets[turbine], audits[turbine] = hourly, audit
        prepared = BASE / "prepared"
        prepared.mkdir(exist_ok=True)
        hourly.to_csv(prepared / f"turbine_{turbine}_hourly.csv", index_label="timestamp")
        log(f"TURBINE {turbine}: {audit['raw_rows']:,} raw rows -> {len(hourly):,} hourly slots; "
            f"{audit['valid_hourly_power']:,} reliable observed targets")
        log(f"TURBINE {turbine}: generating 168h-context / 48h-horizon training examples")
        x, y, meta = examples(hourly, args.stride)
        # Entire forecast horizon stays before split, preventing overlapping-label leakage.
        train = meta.origin + pd.Timedelta(hours=HORIZON) <= VALID_START
        valid = ((meta.origin >= VALID_START)
                 & (meta.origin + pd.Timedelta(hours=HORIZON) <= TEST_START))
        pretest = meta.origin + pd.Timedelta(hours=HORIZON) <= TEST_START
        final = meta.origin + pd.Timedelta(hours=HORIZON) <= FINAL_END
        assert (meta.loc[train, "target_time"] < VALID_START).all()
        assert (meta.loc[pretest, "target_time"] < TEST_START).all()
        log(f"TURBINE {turbine}: CatBoost tuning ({train.sum():,} train / {valid.sum():,} validation rows)")
        tuned = fit_cat(x.loc[train], y.loc[train], args.iterations, args.threads,
                        (x.loc[valid], y.loc[valid]))
        iterations = tuned.tree_count_
        sar_candidates = []
        for order in [(1, 0, 0), (2, 0, 1)]:
            candidate = fit_sar(hourly, VALID_START, order)
            score = metrics(evaluate(hourly, VALID_START, TEST_START, turbine, sar=candidate))
            score = score[(score.model == "sarimax") & (score.horizon == "1-48h")].iloc[0]
            log(f"TURBINE {turbine}: December SARIMAX{order}: MAE={score.mae:.5f}, RMSE={score.rmse:.5f}")
            sar_candidates.append((float(score.rmse), candidate))
        converged = [item for item in sar_candidates if item[1]["converged"]]
        if not converged:
            raise RuntimeError("No converged SARIMAX candidate; inspect training.log")
        _, chosen = min(converged, key=lambda item: item[0])
        selection = {"catboost_iterations": iterations, "sarimax_order": chosen["order"],
                     "validation_period": "2025-12-01 through 2025-12-31",
                     "sarimax_candidates": [{"order": a["order"], "rmse": score,
                                              "converged": a["converged"]} for score, a in sar_candidates]}
        selections[turbine] = selection
        log(f"TURBINE {turbine}: settings locked; refitting through December for January holdout")
        evaluation_cat = fit_cat(x.loc[pretest], y.loc[pretest], iterations, args.threads)
        evaluation_sar = fit_sar(hourly, TEST_START, chosen["order"], chosen["params"])
        save_models(BASE / "evaluation_models" / f"turbine_{turbine}", evaluation_cat,
                    evaluation_sar, TEST_START, audit, selection)
        prediction = evaluate(hourly, TEST_START, FINAL_END, turbine, evaluation_cat, evaluation_sar)
        evaluations.append(prediction)
        score = metrics(prediction)
        log(f"TURBINE {turbine}: JANUARY HOLDOUT\n" + score[score.horizon == "1-48h"].to_string(index=False))
        prediction.to_csv(report_dir / f"turbine_{turbine}_holdout_predictions.csv", index=False)
        log(f"TURBINE {turbine}: fitting production models on all available data through January")
        final_cat = fit_cat(x.loc[final], y.loc[final], iterations, args.threads)
        final_sar = fit_sar(hourly, FINAL_END, chosen["order"], evaluation_sar["params"])
        if not evaluation_sar["converged"] or not final_sar["converged"]:
            raise RuntimeError("SARIMAX refit did not converge; inspect training.log")
        save_models(BASE / "models" / f"turbine_{turbine}", final_cat, final_sar,
                    FINAL_END, audit, selection)
        pd.DataFrame({"feature": final_cat.feature_names_,
                      "importance": final_cat.feature_importances_}).sort_values(
                          "importance", ascending=False).to_csv(
                              report_dir / f"turbine_{turbine}_feature_importance.csv", index=False)
        log(f"TURBINE {turbine}: production models saved")

    combined = pd.concat(evaluations, ignore_index=True)
    scores = metrics(combined)
    scores.to_csv(report_dir / "metrics.csv", index=False)
    write_json(report_dir / "data_audit.json", audits)
    write_json(report_dir / "run_summary.json", {
        "elapsed_seconds": time.monotonic() - started, "arguments": vars(args),
        "selection": selections, "metrics": scores.to_dict(orient="records"),
        "holdout": "30 daily origins per turbine, Jan 1-30; targets through Jan 31",
        "notes": ["Fixed model parameters throughout January; only supplied context updates.",
                  "No future weather. Missing input and target measurements are not filled.",
                  "January observations may enter later January contexts, as in production.",
                  "Overlapping 48h forecasts are distinct origin/horizon pairs, not independent observations."]})
    plots(combined, scores, report_dir)
    example_frames = []
    for turbine, hourly in datasets.items():
        context = hourly.loc[(hourly.index >= FINAL_END - pd.Timedelta(hours=CONTEXT))
                             & (hourly.index < FINAL_END), VALUES].copy()
        context.insert(0, "turbine_id", turbine)
        example_frames.append(context.reset_index(names="timestamp"))
    example_dir = BASE / "examples"
    example_dir.mkdir(exist_ok=True)
    pd.concat(example_frames, ignore_index=True).to_csv(example_dir / "context.csv", index=False)
    log(f"COMPLETE: four production models saved; total elapsed {time.monotonic()-started:.1f}s")
    sys.stdout = sys.stdout.stream
    log_file.close()


if __name__ == "__main__":
    main()
