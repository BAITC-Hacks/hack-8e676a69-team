"""Plot the local-recorded-weather experiment, clearly labeled as oracle inputs."""
import os
import argparse
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.environ.setdefault('MPLCONFIGDIR', str(BASE / 'reports/matplotlib-cache'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', choices=['weather_oracle', 'weather_context_no_power'], default='weather_context_no_power')
    args = parser.parse_args()
    root = BASE / 'reports' / args.tag
    data = pd.read_csv(root / 'comparison_predictions.csv', parse_dates=['timestamp', 'forecast_origin'])
    methods = {'catboost_direct_missing': ('History only, 48 models', '#8191a4'),
               'catboost_weather_oracle': ('Single model + recorded weather', '#1977c2')}
    if args.tag == 'weather_context_no_power':
        methods = {'catboost_weather_oracle': ('Previous: includes power history', '#8191a4'),
                   'catboost_weather_context_no_power': ('New: weather context only', '#1977c2')}
    current = list(methods)[-1]
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharey=True)
    for row, turbine in enumerate([1, 2]):
        for col, date in enumerate(['2026-01-08', '2026-01-22']):
            origin = pd.Timestamp(date)
            ax = axes[row, col]
            subset = data[(data.turbine_id == turbine) & (data.forecast_origin == origin)]
            truth = subset[subset.model == current].sort_values('horizon')
            ax.plot(truth.timestamp, truth.actual_power, color='#161e26', linewidth=2.2, label='Actual power')
            for method, (label, color) in methods.items():
                sample = subset[subset.model == method].sort_values('horizon')
                ax.plot(sample.timestamp, sample.predicted_power, color=color, label=label,
                        linewidth=1.7, linestyle='--' if method != current else '-')
            ax.set(title=f'Turbine {turbine} | {date}', ylim=(-.03, 1.04), ylabel='Normalized power')
            ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%H:%M'))
            ax.grid(alpha=.2)
    title = 'Weather history + future weather: no power inputs' if args.tag == 'weather_context_no_power' else 'Single CatBoost per turbine: recorded future weather supplied'
    fig.suptitle(title, fontsize=16)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(.5,.94), ncol=3, frameon=False)
    fig.text(.05, .025, 'ORACLE WEATHER TEST: actual future wind/temperature, not internet forecasts. Future power never supplied. January development windows.', fontsize=9)
    fig.tight_layout(rect=(0,.06,1,.88))
    fig.savefig(root / 'comparison_windows.png', dpi=160)
    plt.close(fig)
    print(root / 'comparison_windows.png')


if __name__ == '__main__':
    main()
