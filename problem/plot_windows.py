"""Plot fixed January holdout windows from saved predictions (no retraining)."""
import argparse
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPORTS = BASE / "reports"
os.environ.setdefault("MPLCONFIGDIR", str(REPORTS / "matplotlib-cache"))
os.environ.setdefault("XDG_CACHE_HOME", str(REPORTS / "cache"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origins", nargs="+", default=["2026-01-08", "2026-01-22"])
    args = parser.parse_args()
    origins = [pd.Timestamp(value) for value in args.origins]
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False})
    fig, axes = plt.subplots(2, len(origins), figsize=(7 * len(origins), 7.8),
                             sharey=True, squeeze=False)
    colors = {"actual": "#17212b", "catboost": "#2176d2", "sarimax": "#dc7726"}
    errors = []
    for row, turbine in enumerate([1, 2]):
        data = pd.read_csv(REPORTS / f"turbine_{turbine}_holdout_predictions.csv",
                           parse_dates=["forecast_origin", "timestamp"])
        for col, origin in enumerate(origins):
            ax = axes[row, col]
            window = data[data.forecast_origin == origin]
            actual = window[window.model == "catboost"].sort_values("timestamp")
            if len(actual) != 48 or actual.timestamp.nunique() != 48:
                raise ValueError(f"Missing complete 48h window for turbine {turbine}, {origin}")
            ax.plot(actual.timestamp, actual.actual_power, color=colors["actual"],
                    linewidth=2.4, label="Actual", zorder=4)
            annotation = []
            for name in ["catboost", "sarimax"]:
                prediction = window[window.model == name].sort_values("timestamp")
                if not prediction.timestamp.equals(actual.timestamp.reset_index(drop=True)):
                    # Compare values, since different model blocks have different row indices.
                    if not np.array_equal(prediction.timestamp.to_numpy(), actual.timestamp.to_numpy()):
                        raise ValueError("Prediction timestamps are misaligned")
                np.testing.assert_allclose(prediction.actual_power, actual.actual_power, equal_nan=True)
                ax.plot(prediction.timestamp, prediction.predicted_power, color=colors[name],
                        linewidth=2, linestyle="--" if name == "sarimax" else "-",
                        label="CatBoost" if name == "catboost" else "SARIMAX")
                error = prediction.predicted_power - prediction.actual_power
                mae = float(error.abs().mean())
                annotation.append(f"{name}: MAE {mae:.3f}")
                errors.append({"turbine_id": turbine, "forecast_origin": str(origin),
                               "model": name, "mae": mae,
                               "rmse": float(np.sqrt((error ** 2).mean()))})
            ax.set_title(f"Turbine {turbine}  |  {origin:%b %d}–{origin + pd.Timedelta(days=1):%d}",
                         loc="left", fontweight="bold", pad=10)
            ax.set_ylim(-0.035, 1.09)
            ax.set_xlim(origin, origin + pd.Timedelta(hours=47))
            ax.axvline(origin + pd.Timedelta(hours=24), color="#9da7b1", linestyle=":", linewidth=1)
            ax.grid(axis="y", color="#e3e7ec", linewidth=0.8)
            ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d\n%H:%M"))
            ax.text(0.02, 0.97, "  |  ".join(annotation), transform=ax.transAxes,
                    va="top", fontsize=9, color="#435266",
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85})
            if col == 0:
                ax.set_ylabel("Normalized power (0–1)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.97, 0.955),
               ncol=3, frameon=False)
    fig.suptitle("48-hour forecasts vs actual power", x=0.065, y=0.98,
                 ha="left", fontsize=19, fontweight="bold")
    fig.text(0.065, 0.918, "January holdout • Fixed models trained before January • Past 168h only • No future weather",
             fontsize=10, color="#526174")
    fig.subplots_adjust(left=0.065, right=0.975, bottom=0.10, top=0.845, hspace=0.43, wspace=0.16)
    fig.text(0.065, 0.02, "Each panel is one forecast issued at 00:00; the dotted line separates day 1 and day 2. Source/site time.",
             fontsize=9, color="#526174")
    output = REPORTS / "holdout_windows.png"
    fig.savefig(output, dpi=170, facecolor="white")
    plt.close(fig)
    pd.DataFrame(errors).to_csv(REPORTS / "holdout_windows_metrics.csv", index=False)
    print(pd.DataFrame(errors).to_string(index=False))
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
