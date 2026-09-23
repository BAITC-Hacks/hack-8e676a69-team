"""Shared, stateless 168-hour context -> 48-hour forecasting contract."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from statsmodels.tsa.statespace.sarimax import SARIMAX

CONTEXT = 168
HORIZON = 48
VALUES = ["power", "wind_speed", "temperature"]
LAGS = [0, 1, 2, 5, 11, 23, 47, 71, 167]
WINDOWS = [6, 24, 72, 168]
RENAME = {
    "Статистическое время": "timestamp",
    "Средняя скорость ветра(m/s)": "wind_speed",
    "Нормализованная активная мощность": "power",
    "Средняя температура окружающей среды(°C)": "temperature",
}


def calendar(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Deterministic covariates, available even without future weather."""
    year = ((index.dayofyear.to_numpy() - 1 + index.hour.to_numpy() / 24)
            / np.where(index.is_leap_year, 366, 365))
    day = index.hour.to_numpy() / 24
    return pd.DataFrame({
        "constant": np.ones(len(index)),
        "year_sin": np.sin(2 * np.pi * year),
        "year_cos": np.cos(2 * np.pi * year),
        "year_sin2": np.sin(4 * np.pi * year),
        "year_cos2": np.cos(4 * np.pi * year),
        "day_sin": np.sin(2 * np.pi * day),
        "day_cos": np.cos(2 * np.pi * day),
    }, index=index)


def load_raw(path: Path) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(path).rename(columns=RENAME)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"])
    if raw["timestamp"].duplicated().any():
        raise ValueError(f"Duplicate timestamps in {path}")
    raw = raw.set_index("timestamp").sort_index()[VALUES]
    if not np.isfinite(raw.to_numpy()).all():
        raise ValueError(f"Nonfinite source measurements in {path}")
    if (raw.index.minute % 10 != 0).any() or (raw.index.second != 0).any():
        raise ValueError("Expected source data on a 10-minute grid")
    if not raw.power.between(0, 1).all():
        raise ValueError("Expected normalized power in [0, 1]")
    hourly = raw.resample("h").mean()
    counts = raw.power.resample("h").count()
    # An hour with less than 2/3 coverage is not a reliable training label.
    hourly.loc[counts < 4, VALUES] = np.nan
    hourly["measurements_count"] = counts
    audit = {
        "source": path.name, "raw_rows": len(raw),
        "first_measurement": str(raw.index.min()), "last_measurement": str(raw.index.max()),
        "hourly_slots": len(hourly), "valid_hourly_power": int(hourly.power.notna().sum()),
        "hours_below_four_measurements": int((counts < 4).sum()),
        "missing_10minute_slots": int((raw.index.max() - raw.index.min()).total_seconds() / 600 + 1 - len(raw)),
    }
    return hourly, audit


def context_at(history: pd.DataFrame, origin: pd.Timestamp,
               gap_policy: str = "preserve") -> pd.DataFrame:
    """Only completed hourly intervals strictly before the forecast origin."""
    grid = pd.date_range(origin - pd.Timedelta(hours=CONTEXT), periods=CONTEXT, freq="h")
    context = history[VALUES].reindex(grid)
    observed = context.notna()
    if gap_policy == "forward_fill":
        context = context.ffill()
    elif gap_policy != "preserve":
        raise ValueError(f"Unknown gap policy: {gap_policy}")
    for column in VALUES:
        context[f"{column}_observed"] = observed[column]
    return context


def check_context(context: pd.DataFrame) -> None:
    if len(context) != CONTEXT:
        raise ValueError(f"Expected a {CONTEXT}-hour grid")
    observed = context["power_observed"] if "power_observed" in context else context.power.notna()
    if observed.sum() < 24:
        raise ValueError("At least 24 observed power hours in the last 168 hours are required")
    if observed.iloc[-24:].sum() == 0:
        raise ValueError("At least one observed power hour in the last 24 hours is required")


def features(context: pd.DataFrame, origin: pd.Timestamp) -> pd.DataFrame:
    """All history features are anchored at origin, never at future target time."""
    check_context(context)
    stats = {}
    for column in VALUES:
        series = context[column]
        for lag in LAGS:
            # age_1h = last completed hour; age_168h = earliest context hour.
            stats[f"{column}_age_{lag + 1}h"] = series.iloc[-lag - 1]
        observed = context[f"{column}_observed"]
        valid = np.flatnonzero(observed.to_numpy())
        stats[f"{column}_last_observed"] = series.iloc[valid[-1]] if len(valid) else np.nan
        stats[f"{column}_age_last_observed"] = CONTEXT - valid[-1] if len(valid) else CONTEXT + 1
        for window in WINDOWS:
            chunk = series.iloc[-window:]
            stats[f"{column}_mean_{window}h"] = chunk.mean()
            stats[f"{column}_std_{window}h"] = chunk.std(ddof=0)
            stats[f"{column}_min_{window}h"] = chunk.min()
            stats[f"{column}_max_{window}h"] = chunk.max()
            stats[f"{column}_coverage_{window}h"] = observed.iloc[-window:].mean()
    future = pd.date_range(origin, periods=HORIZON, freq="h")
    result = pd.DataFrame([stats] * HORIZON, index=future)
    result["horizon"] = np.arange(1, HORIZON + 1)
    result["month"] = future.month
    result = pd.concat([result, calendar(future).drop(columns="constant")], axis=1)
    return result.astype("float32")


def sarimax_model(power: pd.Series, order: list | tuple,
                  gap_policy: str = "preserve") -> SARIMAX:
    # Seasonal variation is represented by annual/daily Fourier regressors.
    # No observed weather exog: future observations do not exist at inference.
    if gap_policy == "forward_fill":
        power = power.ffill()
    elif gap_policy != "preserve":
        raise ValueError(f"Unknown gap policy: {gap_policy}")
    return SARIMAX(power, exog=calendar(power.index), order=tuple(order),
                   seasonal_order=(0, 0, 0, 0), trend="n",
                   enforce_stationarity=True, enforce_invertibility=True)


def sarimax_predict(context: pd.DataFrame, origin: pd.Timestamp, artifact: dict) -> np.ndarray:
    check_context(context)
    # Artifacts created before the gap-policy change used forward-fill.
    model = sarimax_model(context.power, artifact["order"],
                          gap_policy=artifact.get("gap_policy", "forward_fill"))
    if model.param_names != artifact["param_names"]:
        raise ValueError("SARIMAX parameter schema mismatch")
    # Fresh filter/state for each request. No fit(), stored training state, or DB.
    filtered = model.filter(np.asarray(artifact["params"]), cov_type="none")
    future = pd.date_range(origin, periods=HORIZON, freq="h")
    pred = np.asarray(filtered.forecast(HORIZON, exog=calendar(future)))
    if not np.isfinite(pred).all():
        raise ValueError("Nonfinite SARIMAX prediction")
    return pred.clip(0, 1)


def read_context_csv(path: Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    required = {"turbine_id", "timestamp", *VALUES}
    if not required.issubset(data.columns):
        raise ValueError(f"Missing columns: {sorted(required - set(data.columns))}")
    data["timestamp"] = pd.to_datetime(data.timestamp)
    if data.timestamp.isna().any():
        raise ValueError("Missing timestamps")
    # Source timezone is not provided: contract deliberately preserves naive site time.
    if data.timestamp.dt.tz is not None:
        raise ValueError("Use timezone-naive source/site timestamps; source timezone is unconfirmed")
    if (data.timestamp != data.timestamp.dt.floor("h")).any():
        raise ValueError("Input must be hourly, with timestamps at the start of each hour")
    if data.duplicated(["turbine_id", "timestamp"]).any():
        raise ValueError("Duplicate turbine/timestamp pairs")
    if not data.turbine_id.isin([1, 2]).all() or data.empty:
        raise ValueError("turbine_id must be 1 or 2 and input must not be empty")
    for column in VALUES:
        data[column] = pd.to_numeric(data[column], errors="raise")
        if np.isinf(data[column]).any():
            raise ValueError(f"Infinite values in {column}")
    if not data.power.dropna().between(0, 1).all():
        raise ValueError("power must be normalized to [0, 1]")
    return data


class DirectCatBoost:
    """One independently trained regressor for each prediction horizon."""

    def __init__(self, folder: Path):
        self.models = []
        for horizon in range(1, HORIZON + 1):
            model = CatBoostRegressor()
            model.load_model(str(folder / f"catboost_h{horizon:02d}.cbm"))
            self.models.append(model)

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        if len(x) != HORIZON or not np.array_equal(x.horizon.to_numpy(), np.arange(1, HORIZON + 1)):
            raise ValueError("Direct CatBoost requires exactly 48 rows ordered by horizon 1..48")
        # Constant horizon feature is excluded from each individual model.
        inputs = x.drop(columns="horizon")
        return np.asarray([model.predict(inputs.iloc[[i]])[0]
                           for i, model in enumerate(self.models)])


def predict_csv(path: Path, model_dir: Path, origin: pd.Timestamp | None = None,
                selected: str = "both") -> pd.DataFrame:
    data = read_context_csv(path)
    if origin is None:
        # Keep both turbines aligned even when one has missing trailing readings.
        origin = data.timestamp.max() + pd.Timedelta(hours=1)
    if origin.tz is not None or origin != origin.floor("h"):
        raise ValueError("origin must be a timezone-naive whole hour")
    if (data.timestamp >= origin).any():
        raise ValueError("Context contains future/uncompleted hours at or after origin")
    outputs = []
    for turbine, group in data.groupby("turbine_id"):
        folder = model_dir / f"turbine_{int(turbine)}"
        manifest = json.loads((folder / "metadata.json").read_text())
        context = context_at(group.set_index("timestamp"), origin,
                             gap_policy=manifest.get("gap_policy", "forward_fill"))
        check_context(context)
        if origin < pd.Timestamp(manifest["trained_until_exclusive"]):
            raise ValueError("Forecast origin precedes the model training cutoff; use evaluation artifacts")
        predictions = {}
        if selected in ("both", "catboost"):
            if manifest.get("catboost_strategy") == "direct_per_horizon":
                cat = DirectCatBoost(folder)
                name = manifest.get("catboost_output_name", "catboost_direct")
            else:
                cat = CatBoostRegressor()
                cat.load_model(str(folder / "catboost.cbm"))
                name = "catboost"
            predictions[name] = cat.predict(features(context, origin)).clip(0, 1)
        if selected in ("both", "sarimax"):
            artifact = json.loads((folder / "sarimax.json").read_text())
            name = manifest.get("sarimax_output_name", "sarimax")
            predictions[name] = sarimax_predict(context, origin, artifact)
        for name, pred in predictions.items():
            if not np.isfinite(pred).all():
                raise ValueError(f"Nonfinite {name} output")
            outputs.append(pd.DataFrame({
                "turbine_id": int(turbine), "forecast_origin": origin,
                "timestamp": pd.date_range(origin, periods=HORIZON, freq="h"),
                "horizon": np.arange(1, HORIZON + 1), "model": name,
                "predicted_power": pred,
            }))
    return pd.concat(outputs, ignore_index=True)
