# Training results

Four production models are saved under `problem/models/`: CatBoost and SARIMAX
for each turbine, trained using available data through January 31, 2026.

January evaluation used separate frozen models trained through December 31.
Hyperparameters were selected using December, before examining January results.
Each evaluation request supplied only its preceding 168 hours of measurements;
the models predicted the next 48 hours without future weather. The 30 daily
origins per turbine yield 1,440 origin/horizon pairs per model. Overlapping
forecasts are counted separately. All January scoring targets were observed.

| Turbine | Model | MAE, 1-48h | RMSE, 1-48h |
|---|---|---:|---:|
| 1 | CatBoost | 0.311916 | 0.349189 |
| 1 | SARIMAX | 0.304715 | 0.346199 |
| 1 | Past-week mean | 0.295151 | 0.348842 |
| 1 | Last-value persistence | 0.334498 | 0.457998 |
| 2 | CatBoost | 0.312586 | 0.351561 |
| 2 | SARIMAX | 0.302174 | 0.343242 |
| 2 | Past-week mean | 0.294005 | 0.347376 |
| 2 | Last-value persistence | 0.331670 | 0.455394 |

Errors are in normalized-power units, not relative percentages. An MAE of 0.30
means an average absolute error of 30 percentage points of the normalized scale.

SARIMAX has the lowest RMSE on both turbines. The past-week-mean baseline has the
lowest MAE; CatBoost did not beat it on either aggregate metric. These are working
history-only models, not evidence of high forecast accuracy. No post-hoc tuning
on the January holdout was performed to change that conclusion. Archived future
weather is a sensible next experiment and is required by the hackathon brief.

December selected 66 CatBoost trees for turbine 1 and 85 for turbine 2 (depth 6,
learning rate 0.04, L2 10, seed 42). Both turbines selected SARIMAX order (1,0,0)
over (2,0,1), with daily and annual Fourier seasonal regressors. All saved final
SARIMAX optimizers converged. These seasonal regressors are calendar values,
not unknown future weather.

Forward-fill uses past input values only. Filled values never serve as scoring
ground truth or CatBoost targets. SARIMAX training uses forward-filled power,
including the long turbine-1 outage, which can bias temporal persistence.

See `metrics.csv` for separate 1-24h and 25-48h scores, individual turbine
prediction CSVs for every forecast, and `training.log` for training progress.
The final February 1-2 example has no supplied truth and is not scored.
