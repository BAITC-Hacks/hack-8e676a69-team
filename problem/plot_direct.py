"""Compare original and horizon-specific models on fixed January windows."""
import os
import argparse
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(BASE / "reports/matplotlib-cache"))
os.environ.setdefault("XDG_CACHE_HOME", str(BASE / "reports/cache"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", choices=["direct", "direct_missing"], default="direct_missing")
    args = parser.parse_args()
    REPORTS = BASE / "reports" / args.tag
    new_cat = f"catboost_{args.tag}"
    new_sar = "sarimax" if args.tag == "direct" else f"sarimax_{args.tag}"
    data = pd.read_csv(REPORTS / "comparison_predictions.csv",
                       parse_dates=["forecast_origin", "timestamp"])
    colors = {"catboost": "#8d9aab", new_cat: "#2079cb", new_sar: "#db8227"}
    labels = {"catboost": "Original CatBoost", new_cat: "48 separate CatBoost models",
              new_sar: "SARIMAX (missing preserved)" if args.tag == "direct_missing" else "SARIMAX (unchanged)"}
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharey=True)
    for row, turbine in enumerate([1, 2]):
        for col, date in enumerate(["2026-01-08", "2026-01-22"]):
            origin = pd.Timestamp(date)
            ax = axes[row, col]
            window = data[(data.turbine_id == turbine) & (data.forecast_origin == origin)]
            actual = window[window.model == new_cat].sort_values("horizon")
            ax.plot(actual.timestamp, actual.actual_power, label="Actual", color="#17212b", linewidth=2.3)
            for model in ["catboost", new_cat, new_sar]:
                sample = window[window.model == model].sort_values("horizon")
                ax.plot(sample.timestamp, sample.predicted_power, color=colors[model],
                        label=labels[model], linewidth=1.9,
                        linestyle="--" if model != new_cat else "-")
            ax.set(title=f"Turbine {turbine} | {origin:%b %d}–{origin + pd.Timedelta(days=1):%d}",
                   ylim=(-0.035, 1.05), xlim=(origin, origin + pd.Timedelta(hours=47)))
            ax.axvline(origin + pd.Timedelta(hours=24), color="#aeb7c2", linestyle=":", linewidth=1)
            ax.grid(axis="y", color="#e6e9ee")
            ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d\n%H:%M"))
            if col == 0:
                ax.set_ylabel("Normalized power (0–1)")
    handles, names = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, names, loc="upper center", bbox_to_anchor=(0.51, 0.923), ncol=4, frameon=False)
    fig.suptitle("Does separating the 48 forecast horizons help?", fontsize=18, fontweight="bold", y=0.98)
    fig.text(0.065, 0.025, "Same 168h context and January forecast origins; no future weather. January is now a development comparison, not a fresh test.",
             color="#546170", fontsize=9)
    fig.subplots_adjust(top=0.81, bottom=0.11, left=0.065, right=0.98, hspace=0.42, wspace=0.15)
    fig.savefig(REPORTS / "comparison_windows.png", dpi=160, facecolor="white")
    plt.close(fig)

    per_horizon = pd.read_csv(REPORTS / "metrics_by_horizon.csv")
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True)
    for turbine, ax in zip([1, 2], axes):
        for model in ["catboost", new_cat, new_sar]:
            sample = per_horizon[(per_horizon.turbine_id == turbine) & (per_horizon.model == model)]
            ax.plot(sample.horizon, sample.mae, color=colors[model], label=labels[model], linewidth=1.9)
        ax.set(title=f"Turbine {turbine}", xlabel="Forecast horizon (hours)", ylabel="MAE; lower is better", xlim=(1, 48))
        ax.grid(color="#e6e9ee")
    handles, names = axes[0].get_legend_handles_labels()
    fig.legend(handles, names, loc="lower center", ncol=3, frameon=False)
    fig.suptitle("January error by forecast horizon — 30 daily origins", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0.10, 1, 0.92))
    fig.savefig(REPORTS / "mae_by_horizon.png", dpi=160, facecolor="white")
    plt.close(fig)
    print(f"Saved comparison_windows.png and mae_by_horizon.png in {REPORTS}")


if __name__ == "__main__":
    main()
