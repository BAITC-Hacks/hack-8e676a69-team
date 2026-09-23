"""Rebuild figures and paired comparisons from completed benchmark predictions."""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent / 'experiments/catboost_hypotheses'
LABELS = {
    'direct_base': 'Direct: existing features',
    'direct_power': 'Direct: power history only',
    'direct_rich': 'Direct: richer 7-day history',
    'direct_long': 'Direct: richer 30-day history',
    'multioutput': 'One model, 48 outputs',
    'recursive_power': 'Recursive: power only',
    'recursive_joint': 'Recursive: power + weather',
    'context_mean': 'Past 7-day mean',
    'persistence': 'Last observed value',
    'seasonal_24h': 'Repeat previous day',
}


def main():
    predictions = pd.read_csv(BASE / 'predictions.csv', parse_dates=['origin', 'timestamp'])
    metrics = pd.read_csv(BASE / 'metrics.csv')
    full = metrics[metrics.horizon == '1-48h']
    ranking = full.groupby('variant')[['mae', 'rmse']].mean().sort_values('rmse')
    methods = ranking.index.tolist()
    paired = []
    for reference in ['direct_base', 'context_mean']:
        baseline = metrics[metrics.variant == reference].drop(columns='variant')
        comparison = metrics.merge(baseline, on=['turbine_id', 'fold', 'horizon'], suffixes=('', '_reference'))
        for (variant, horizon), group in comparison.groupby(['variant', 'horizon']):
            paired.append({'reference': reference, 'variant': variant, 'horizon': horizon,
                'folds': len(group), 'rmse_wins': int((group.rmse < group.rmse_reference).sum()),
                'mae_wins': int((group.mae < group.mae_reference).sum()),
                'mean_rmse_change': (group.rmse - group.rmse_reference).mean(),
                'mean_mae_change': (group.mae - group.mae_reference).mean(),
                'rmse_change_percent': 100 * (group.rmse.mean() / group.rmse_reference.mean() - 1),
                'mae_change_percent': 100 * (group.mae.mean() / group.mae_reference.mean() - 1)})
    pd.DataFrame(paired).to_csv(BASE / 'paired_comparisons.csv', index=False)
    metrics.groupby(['variant', 'horizon'])[['mae', 'rmse']].mean().to_csv(BASE / 'horizon_summary.csv')
    full.pivot(index=['turbine_id', 'fold'], columns='variant', values='rmse').to_csv(BASE / 'rmse_by_fold.csv')
    full.pivot(index=['turbine_id', 'fold'], columns='variant', values='mae').to_csv(BASE / 'mae_by_fold.csv')

    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    colors = ['#9aa3ad' if v in ['context_mean', 'persistence', 'seasonal_24h'] else '#3176ac' for v in methods]
    for ax, metric in zip(axes, ['mae', 'rmse']):
        ax.barh(np.arange(len(methods)), ranking[metric], color=colors)
        for i, value in enumerate(ranking[metric]):
            ax.text(value + .004, i, f'{value:.4f}', va='center', fontsize=9)
        ax.set_yticks(np.arange(len(methods)), [LABELS[v] for v in methods])
        ax.set_xlim(0, ranking[metric].max() * 1.18)
        ax.set_xlabel(f'{metric.upper()} — lower is better')
        ax.grid(axis='x', alpha=.2)
    axes[0].invert_yaxis()
    fig.suptitle('48-hour forecasts without future weather\nEqual-weight average: 2 turbines × 3 historical months')
    fig.tight_layout()
    fig.savefig(BASE / 'comparison.png', dpi=160)
    plt.close(fig)

    models = [v for v in methods if v not in ['context_mean', 'persistence', 'seasonal_24h']]
    selected = list(dict.fromkeys(['direct_base', *models[:3], 'context_mean']))
    valid = predictions.dropna(subset=['actual']).copy()
    valid['absolute_error'] = (valid.prediction - valid.actual).abs()
    valid['squared_error'] = (valid.prediction - valid.actual)**2
    by_horizon = valid.groupby(['turbine_id', 'fold', 'variant', 'horizon'])[['absolute_error', 'squared_error']].mean()
    by_horizon['rmse'] = np.sqrt(by_horizon.squared_error)
    by_horizon = by_horizon.groupby(['variant', 'horizon'])[['absolute_error', 'rmse']].mean()
    by_horizon.to_csv(BASE / 'metrics_each_hour.csv')
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.6))
    for ax, metric, title in zip(axes, ['absolute_error', 'rmse'], ['MAE', 'RMSE']):
        for method in selected:
            values = by_horizon.loc[method]
            ax.plot(values.index, values[metric], label=LABELS[method])
        ax.set(xlabel='Forecast horizon (hours)', ylabel=title, title=f'{title} by horizon')
        ax.grid(alpha=.2)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(BASE / 'errors_by_horizon.png', dpi=160)
    plt.close(fig)

    # Fixed dates, not windows selected for favourable model performance.
    fig, axes = plt.subplots(2, 3, figsize=(18, 8), sharey=True)
    for j, fold in enumerate(sorted(predictions.fold.unique())):
        origin = pd.Timestamp(fold) + pd.Timedelta(days=7)
        for i, turbine in enumerate([1, 2]):
            ax = axes[i, j]
            subset = predictions[(predictions.turbine_id == turbine) & (predictions.origin == origin)]
            actual = subset[subset.variant == 'direct_base'].sort_values('horizon')
            ax.plot(actual.horizon, actual.actual, color='#171a20', linewidth=2.2, label='Observed power')
            for method in selected:
                values = subset[subset.variant == method].sort_values('horizon')
                ax.plot(values.horizon, values.prediction, linewidth=1.1, alpha=.85, label=LABELS[method])
            ax.set(title=f'Turbine {turbine} · {origin:%Y-%m-%d}', xlabel='Forecast horizon (hours)', ylim=(-.03, 1.04))
            ax.grid(alpha=.2)
    axes[0, 0].set_ylabel('Normalized power')
    axes[1, 0].set_ylabel('Normalized power')
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=3, fontsize=9)
    fig.suptitle('Predicted vs observed: fixed 48-hour windows, no future weather supplied')
    fig.tight_layout(rect=(0, .10, 1, .96))
    fig.savefig(BASE / 'forecast_windows.png', dpi=160)
    plt.close(fig)
    print(ranking.to_string())


if __name__ == '__main__':
    main()
