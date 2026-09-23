# Separate horizons and preserved missing measurements

Current bundle: `problem/models_direct_missing/`. Inference defaults to this
bundle. It contains 96 CatBoost models (48 horizons x two turbines) and two
refitted SARIMAX models. No missing measurements are forward-filled in these
models. All 14 contract/integration tests passed, including inference with
omitted rows, explicit NaNs, repeatability, and preservation of SARIMAX missing
observations. Both final SARIMAX optimizers converged.

Comparison uses the same 30 January origins as previous runs. January was
previously inspected, so this is a development comparison, not a fresh test.
Errors are normalized-power units. First-hour scores use 30 samples per turbine;
48-hour scores use 1,440 origin/horizon pairs with overlapping target windows.

| Turbine | Model | First-hour MAE | 48-hour MAE | 48-hour RMSE |
|---|---|---:|---:|---:|
| 1 | Original shared CatBoost, filled inputs | 0.187946 | 0.311916 | 0.349189 |
| 1 | Separate horizons, filled inputs | 0.101540 | 0.301430 | 0.343737 |
| 1 | Separate horizons, missing preserved | 0.100889 | 0.303481 | 0.346286 |
| 1 | SARIMAX, missing preserved | 0.106871 | 0.302318 | 0.343886 |
| 1 | Past-week mean baseline | 0.305383 | 0.295151 | 0.348842 |
| 2 | Original shared CatBoost, filled inputs | 0.196080 | 0.312586 | 0.351561 |
| 2 | Separate horizons, filled inputs | 0.097258 | 0.297360 | 0.339614 |
| 2 | Separate horizons, missing preserved | 0.099177 | 0.300536 | 0.343610 |
| 2 | SARIMAX, missing preserved | 0.106704 | 0.301996 | 0.343048 |
| 2 | Past-week mean baseline | 0.302439 | 0.294005 | 0.347376 |

Separate horizons greatly improve first-hour CatBoost predictions, but the
48-hour improvement is modest. Removing filling avoids fabricated flat training
segments; it does NOT independently improve all metrics. Indeed the no-fill
CatBoost bundles have slightly worse aggregate January errors than the filled
separate-horizon comparison. Missing-aware SARIMAX slightly improves aggregate
errors over its original filled version (see comparison_metrics.csv).

The past-week mean still has lower 48-hour MAE than either learned method. The
models still miss large wind-driven swings, and no strong 48-hour accuracy claim
is justified. The chart windows themselves had no missing inputs or labels, so
gap handling could not be the direct cause of their previous flat predictions.
More jagged independent-horizon predictions should not be mistaken for accuracy.

The input contract remains one CSV and 168 hours per turbine. No 30-day context
or external weather inputs were added. New example output has 192 predictions
for February 1–2; no supplied February ground truth exists for scoring it.
