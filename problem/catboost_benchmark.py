"""Controlled CatBoost-only, history-only forecasting hypothesis benchmark."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import warnings

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from forecasting import load_raw

BASE = Path(__file__).resolve().parent
HORIZON = 48
CONTEXT = 720
COLS = ["power", "wind_speed", "temperature"]
FOLDS = ["2025-04-01", "2025-08-01", "2026-01-01"]
VARIANTS = ["direct_base", "direct_power", "direct_rich", "direct_long",
            "multioutput", "recursive_power", "recursive_joint"]


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


class Tee:
    def __init__(self, stream, file):
        self.stream, self.file = stream, file

    def write(self, text):
        self.stream.write(text)
        self.file.write(text)
        self.file.flush()

    def flush(self):
        self.stream.flush()
        self.file.flush()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def calendar(times):
    times = pd.DatetimeIndex(times)
    year = (times.dayofyear.to_numpy() - 1 + times.hour.to_numpy() / 24) / np.where(times.is_leap_year, 366, 365)
    day = times.hour.to_numpy() / 24
    return np.column_stack([times.month, np.sin(2*np.pi*year), np.cos(2*np.pi*year),
                            np.sin(4*np.pi*year), np.cos(4*np.pi*year),
                            np.sin(2*np.pi*day), np.cos(2*np.pi*day)]).astype("float32")


def historical_features(contexts, mode="base"):
    """Batch of n x context x 3. Does not access any future measurements."""
    x = np.asarray(contexts, dtype="float32")
    if x.ndim != 3 or x.shape[1] < 168 or x.shape[2] != 3:
        raise ValueError("Expected n x at-least-168 x 3 history array")
    if mode == "long" and x.shape[1] < 720:
        raise ValueError("Long-context features require 720 hourly slots")
    entries = {}
    columns = [0] if mode == "power" else [0, 1, 2]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # All-missing summaries intentionally remain NaN.
        for j in columns:
            name = COLS[j]
            v = x[:, -168:, j]
            observed = np.isfinite(v)
            for age in [1, 2, 3, 6, 12, 24, 48, 72, 168]:
                entries[f"{name}_age_{age}h"] = v[:, -age]
            last = np.where(observed, np.arange(168)[None, :], -1).max(axis=1)
            entries[f"{name}_last_observed"] = np.where(last >= 0, v[np.arange(len(v)), np.maximum(last, 0)], np.nan)
            entries[f"{name}_age_last_observed"] = np.where(last >= 0, 168-last, 169)
            for window in [6, 24, 72, 168]:
                chunk = v[:, -window:]
                for label, func in [("mean", np.nanmean), ("std", np.nanstd), ("min", np.nanmin), ("max", np.nanmax)]:
                    entries[f"{name}_{label}_{window}h"] = func(chunk, axis=1)
                entries[f"{name}_coverage_{window}h"] = np.isfinite(chunk).mean(axis=1)
            if mode in ["rich", "long"]:
                for age in range(1, 25):
                    entries[f"{name}_age_{age}h"] = v[:, -age]
                for hours in [1, 3, 6, 12, 24]:
                    entries[f"{name}_change_{hours}h"] = v[:, -1] - v[:, -1-hours]
                for window in [6, 24]:
                    chunk = v[:, -window:]
                    ok = np.isfinite(chunk)
                    t = np.broadcast_to(np.arange(window), chunk.shape)
                    count = ok.sum(axis=1)
                    tm = np.divide((t*ok).sum(axis=1), count, out=np.zeros(len(v)), where=count > 0)
                    ym = np.nanmean(chunk, axis=1)
                    numerator = np.nansum((t-tm[:, None])*(chunk-ym[:, None]), axis=1)
                    denominator = (((t-tm[:, None])**2)*ok).sum(axis=1)
                    entries[f"{name}_slope_{window}h"] = np.divide(numerator, denominator,
                        out=np.full(len(v), np.nan), where=(count >= 3) & (denominator > 0))
                for day in range(1, 8):
                    chunk = v[:, -24*day:None if day == 1 else -24*(day-1)]
                    entries[f"{name}_day_{day}_mean"] = np.nanmean(chunk, axis=1)
                    entries[f"{name}_day_{day}_coverage"] = np.isfinite(chunk).mean(axis=1)
            if mode == "long":
                for window in [336, 720]:
                    chunk = x[:, -window:, j]
                    entries[f"{name}_mean_{window}h"] = np.nanmean(chunk, axis=1)
                    entries[f"{name}_std_{window}h"] = np.nanstd(chunk, axis=1)
                    entries[f"{name}_q10_{window}h"] = np.nanquantile(chunk, .1, axis=1)
                    entries[f"{name}_q90_{window}h"] = np.nanquantile(chunk, .9, axis=1)
                    entries[f"{name}_coverage_{window}h"] = np.isfinite(chunk).mean(axis=1)
                    entries[f"{name}_recent_vs_{window}h"] = np.nanmean(v[:, -24:], axis=1) - np.nanmean(chunk, axis=1)
        if mode in ["rich", "long"]:
            wind = x[:, -168:, 1]
            for label, condition in [("calm", wind < 3), ("high", wind >= 10)]:
                for window in [24, 168]:
                    ok = np.isfinite(wind[:, -window:])
                    entries[f"wind_{label}_fraction_{window}h"] = np.divide(
                        (condition[:, -window:] & ok).sum(axis=1), ok.sum(axis=1),
                        out=np.full(len(x), np.nan), where=ok.sum(axis=1) > 0)
                # A gap breaks a run; it is never counted as calm or high wind.
                entries[f"wind_{label}_current_run"] = np.cumprod(condition[:, ::-1], axis=1).sum(axis=1)
    return np.column_stack(list(entries.values())).astype("float32"), list(entries)


def valid_context(contexts):
    power = contexts[:, -168:, 0]
    return (np.isfinite(power).sum(axis=1) >= 24) & (np.isfinite(power[:, -24:]).sum(axis=1) > 0)


def matrices(hourly, stride=6):
    values = hourly[COLS].to_numpy(dtype="float32")
    positions = np.arange(CONTEXT, len(values)-HORIZON+1, stride)
    contexts = np.stack([values[p-CONTEXT:p] for p in positions])
    valid = valid_context(contexts)
    positions, contexts = positions[valid], contexts[valid]
    targets = np.stack([values[p:p+HORIZON, 0] for p in positions])
    future_one = values[positions]
    origins = hourly.index[positions]
    hist = {}
    names = {}
    for mode in ["base", "power", "rich", "long"]:
        hist[mode], names[mode] = historical_features(contexts, mode)
    return origins, hist, names, targets, future_one


def request_contexts(hourly, origins):
    """Construct requests once; forecasting functions get no future dataframe."""
    values = hourly[COLS].to_numpy(dtype="float32")
    positions = hourly.index.get_indexer(origins)
    if (positions < CONTEXT).any():
        raise ValueError("Insufficient historical grid")
    contexts = np.stack([values[p-CONTEXT:p] for p in positions])
    ok = valid_context(contexts)
    origins, positions, contexts = origins[ok], positions[ok], contexts[ok]
    targets = np.stack([values[p:p+HORIZON, 0] for p in positions])
    return origins, contexts, targets


def design(history_features, origins, horizon=1):
    return np.column_stack([history_features, calendar(origins + pd.Timedelta(hours=horizon-1))]).astype("float32")


def cat(iterations, args, multi=False):
    return CatBoostRegressor(iterations=iterations, depth=6, learning_rate=.04,
                            l2_leaf_reg=10, random_seed=42, thread_count=args.threads,
                            allow_writing_files=False,
                            loss_function="MultiRMSEWithMissingValues" if multi else "RMSE")


def errors(actual, prediction):
    ok = np.isfinite(actual)
    if not np.isfinite(prediction).all():
        raise ValueError("Nonfinite forecasts")
    diff = (prediction-actual)[ok]
    return float(np.mean(np.abs(diff))), float(np.sqrt(np.mean(diff**2)))


def recursive(model, contexts, origins, joint=False, scale=None, trees=0):
    # Predictions extend an internal simulated state, never the observed input.
    state = contexts[:, -168:, :].copy()
    output = np.empty((len(state), HORIZON))
    for h in range(HORIZON):
        hist, _ = historical_features(state, "base" if joint else "power")
        x = design(hist, origins + pd.Timedelta(hours=h))
        prediction = np.asarray(model.predict(x, ntree_end=trees))
        if joint:
            prediction = prediction * scale[1] + scale[0]
            prediction[:, 0] = prediction[:, 0].clip(0, 1)
            prediction[:, 1] = prediction[:, 1].clip(0)
            next_row = prediction
        else:
            next_row = np.full((len(state), 3), np.nan)
            next_row[:, 0] = prediction.clip(0, 1)
        output[:, h] = next_row[:, 0]
        state = np.concatenate([state[:, 1:], next_row[:, None, :]], axis=1)
    return output


def evaluate_variant(variant, origins, hist, targets, next_values, train, validation, refit,
                     val_origins, val_contexts, val_targets, test_origins, test_contexts, args, folder):
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    settings = []
    if variant.startswith("direct_"):
        mode = {"direct_base": "base", "direct_power": "power", "direct_rich": "rich", "direct_long": "long"}[variant]
        test_hist, feature_names = historical_features(test_contexts, mode)
        output = np.empty((len(test_origins), HORIZON))
        for h in range(1, HORIZON+1):
            x = design(hist[mode], origins, h)
            y = targets[:, h-1]
            tr, va, re = train & np.isfinite(y), validation & np.isfinite(y), refit & np.isfinite(y)
            tuned = cat(args.iterations, args)
            tuned.fit(x[tr], y[tr], eval_set=(x[va], y[va]), early_stopping_rounds=80, verbose=False)
            ntrees = tuned.tree_count_
            model = cat(ntrees, args)
            model.fit(x[re], y[re], verbose=False)
            model.save_model(str(folder / f"h{h:02d}.cbm"))
            output[:, h-1] = model.predict(design(test_hist, test_origins, h)).clip(0, 1)
            settings.append({"horizon": h, "trees": ntrees, "validation_rmse": tuned.best_score_["validation"]["RMSE"]})
            if h % 12 == 0:
                log(f"    {variant}: {h}/48 horizons ({time.monotonic()-started:.0f}s)")
    elif variant == "multioutput":
        x = design(hist["base"], origins)
        y = targets
        tr = train & np.isfinite(y).any(axis=1)
        va = validation & np.isfinite(y).any(axis=1)
        re = refit & np.isfinite(y).any(axis=1)
        tuned = cat(args.iterations, args, multi=True)
        tuned.fit(x[tr], y[tr], eval_set=(x[va], y[va]), early_stopping_rounds=80, verbose=False)
        model = cat(tuned.tree_count_, args, multi=True)
        model.fit(x[re], y[re], verbose=False)
        model.save_model(str(folder / "multioutput.cbm"))
        test_hist, feature_names = historical_features(test_contexts, "base")
        output = model.predict(design(test_hist, test_origins)).clip(0, 1)
        settings.append({"trees": tuned.tree_count_, "validation_multirmse": tuned.best_score_["validation"]["MultiRMSEWithMissingValues"]})
    else:
        joint = variant == "recursive_joint"
        mode = "base" if joint else "power"
        x = design(hist[mode], origins)
        if joint:
            tr = train & np.isfinite(next_values).any(axis=1)
            re = refit & np.isfinite(next_values).any(axis=1)
            center = np.nanmean(next_values[tr], axis=0)
            std = np.maximum(np.nanstd(next_values[tr], axis=0), 1e-6)
            y = (next_values-center)/std
            scale = (center, std)
        else:
            y = next_values[:, 0]
            tr, re = train & np.isfinite(y), refit & np.isfinite(y)
            scale = None
        # Choose complexity using full recursive 48h rollouts, not one-step validation.
        checkpoints = sorted(set([min(100, args.iterations), min(250, args.iterations), args.iterations]))
        tuned = cat(args.iterations, args, multi=joint)
        tuned.fit(x[tr], y[tr], verbose=False)
        candidates = []
        for trees in checkpoints:
            prediction = recursive(tuned, val_contexts, val_origins, joint, scale, trees)
            mae, rmse = errors(val_targets, prediction)
            candidates.append({"trees": trees, "validation_mae": mae, "validation_rmse": rmse})
        chosen = min(candidates, key=lambda v: v["validation_rmse"])
        log(f"    {variant}: full-rollout validation selects {chosen['trees']} trees, RMSE {chosen['validation_rmse']:.4f}")
        model = cat(chosen["trees"], args, multi=joint)
        # Keep scaling fixed from training subset, not from test or validation targets.
        model.fit(x[re], y[re], verbose=False)
        model.save_model(str(folder / "recursive.cbm"))
        output = recursive(model, test_contexts, test_origins, joint, scale)
        feature_names = historical_features(test_contexts[:1], mode)[1]
        settings = candidates
        if joint:
            save_json(folder / "target_scaling.json", {"mean": center.tolist(), "std": std.tolist()})
    save_json(folder / "metadata.json", {"variant": variant, "settings": settings,
              "history_features": feature_names, "calendar_features": ["month", "year_sin", "year_cos", "year_sin2", "year_cos2", "day_sin", "day_cos"],
              "context_hours": 720 if variant == "direct_long" else 168,
              "horizon_hours": HORIZON, "gap_policy": "preserve", "training_seconds": time.monotonic()-started,
              "trained_until_exclusive": str(test_origins.min()), "inference_requires_future_weather": False})
    return output, time.monotonic()-started


def prediction_rows(turbine, fold, variant, origins, truth, forecast):
    return pd.DataFrame({"turbine_id": turbine, "fold": fold, "variant": variant,
                         "origin": np.repeat(origins.to_numpy(), HORIZON),
                         "horizon": np.tile(np.arange(1, HORIZON+1), len(origins)),
                         "timestamp": np.concatenate([pd.date_range(o, periods=HORIZON, freq="h").to_numpy() for o in origins]),
                         "actual": truth.ravel(), "prediction": forecast.ravel()})


def summarize(frame):
    rows = []
    for (turbine, fold, variant), group in frame.groupby(["turbine_id", "fold", "variant"]):
        for name, low, high in [("1h",1,1),("1-6h",1,6),("7-12h",7,12),("13-24h",13,24),("25-48h",25,48),("1-48h",1,48)]:
            part = group[group.horizon.between(low,high)].dropna(subset=["actual"])
            mae, rmse = errors(part.actual.to_numpy(), part.prediction.to_numpy())
            rows.append({"turbine_id": turbine, "fold": fold, "variant": variant, "horizon": name,
                         "n":len(part), "mae":mae, "rmse":rmse})
    return pd.DataFrame(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations",type=int,default=500)
    parser.add_argument("--threads",type=int,default=4)
    parser.add_argument("--stride",type=int,default=6)
    parser.add_argument("--folds",nargs="+",default=FOLDS)
    parser.add_argument("--variants",nargs="+",choices=VARIANTS,default=VARIANTS)
    parser.add_argument("--resume",action="store_true")
    args=parser.parse_args()
    root=BASE/"experiments/catboost_hypotheses"
    root.mkdir(parents=True,exist_ok=True)
    config_path=root/"configuration.json"
    config={"iterations":args.iterations,"threads":args.threads,"stride":args.stride,
            "folds":args.folds,"variants":args.variants,"seed":42,"context":CONTEXT}
    if args.resume and config_path.exists():
        if json.loads(config_path.read_text()) != config:
            raise ValueError("Resume configuration differs from the saved experiment")
    save_json(config_path,config)
    original_stdout=sys.stdout
    started=time.monotonic()
    all_rows=[]
    with (root/"progress.log").open("a" if args.resume else "w",buffering=1) as logfile:
        sys.stdout=Tee(sys.stdout,logfile)
        try:
            for turbine in [1,2]:
                path,=BASE.glob(f"*turbine {turbine}.csv")
                hourly,audit=load_raw(path)
                log(f"Turbine {turbine}: building common contexts (no filling)")
                origins,hist,names,targets,next_values=matrices(hourly,args.stride)
                save_json(root/f"turbine_{turbine}_data.json",audit)
                for fold in args.folds:
                    start=pd.Timestamp(fold)
                    stop=start+pd.offsets.MonthBegin(1)
                    val_start=start-pd.offsets.MonthBegin(1)
                    train=origins+pd.Timedelta(hours=HORIZON)<=val_start
                    validation=(origins>=val_start)&(origins+pd.Timedelta(hours=HORIZON)<=start)
                    refit=origins+pd.Timedelta(hours=HORIZON)<=start
                    assert not np.any(train & validation)
                    assert (origins[refit]+pd.Timedelta(hours=47)<start).all()
                    test_origins,test_contexts,test_targets=request_contexts(hourly,pd.date_range(start,stop-pd.Timedelta(hours=HORIZON),freq="24h"))
                    val_origins,val_contexts,val_targets=request_contexts(hourly,pd.date_range(val_start,start-pd.Timedelta(hours=HORIZON),freq="24h"))
                    log(f"Turbine {turbine}, {fold}: train origins={train.sum()}, validation={validation.sum()}, test={len(test_origins)}")
                    if not len(test_origins) or not len(val_origins):
                        raise ValueError("Fold lacks eligible contexts")
                    for variant in args.variants:
                        folder=root/"models"/f"turbine_{turbine}"/fold/variant
                        prediction_path=root/f"predictions_t{turbine}_{fold}_{variant}.csv"
                        if args.resume and prediction_path.exists():
                            log(f"  Reusing completed {variant}")
                            rows=pd.read_csv(prediction_path)
                        else:
                            log(f"  START {variant}")
                            prediction,seconds=evaluate_variant(variant,origins,hist,targets,next_values,train,validation,refit,
                                val_origins,val_contexts,val_targets,test_origins,test_contexts,args,folder)
                            rows=prediction_rows(turbine,fold,variant,test_origins,test_targets,prediction)
                            rows.to_csv(prediction_path,index=False)
                            mae,rmse=errors(test_targets,prediction)
                            log(f"  DONE {variant}: MAE={mae:.4f}, RMSE={rmse:.4f}, {seconds:.1f}s")
                        all_rows.append(rows)
                    p=test_contexts[:,-168:,0]
                    last=np.array([row[np.flatnonzero(np.isfinite(row))[-1]] for row in p])
                    means=np.nanmean(p,axis=1)
                    seasonal=np.tile(p[:,-24:],(1,2))
                    seasonal=np.where(np.isfinite(seasonal),seasonal,means[:,None])
                    for name,pred in [("persistence",np.repeat(last[:,None],48,axis=1)),
                                      ("context_mean",np.repeat(means[:,None],48,axis=1)),
                                      ("seasonal_24h",seasonal)]:
                        all_rows.append(prediction_rows(turbine,fold,name,test_origins,test_targets,pred))
                    # Checkpoint reports after each completed turbine/month fold.
                    partial=pd.concat(all_rows,ignore_index=True)
                    summarize(partial).to_csv(root/"metrics.csv",index=False)
            all_predictions=pd.concat(all_rows,ignore_index=True)
            all_predictions.to_csv(root/"predictions.csv",index=False)
            metric=summarize(all_predictions)
            metric.to_csv(root/"metrics.csv",index=False)
            ranking=metric[metric.horizon=="1-48h"].groupby("variant")[["mae","rmse"]].mean().sort_values("rmse")
            ranking.to_csv(root/"ranking.csv")
            log("COMPLETE — equal-weight mean across turbine/month folds:\n"+ranking.to_string())
            save_json(root/"completion.json",{"seconds":time.monotonic()-started,"configuration":config,
                "evaluation_note":"Blocked historical development benchmark. January has been inspected previously; no claim of a fresh untouched final test.",
                "model_classes_trained":["CatBoostRegressor"],"production_models_modified":False})
        finally:
            sys.stdout=original_stdout


if __name__=="__main__":
    main()
