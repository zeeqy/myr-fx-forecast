# LEARN: MYR FX Forecast

## 1. What it does (3 sentences)
A daily GitHub Actions job pulls Bank Negara Malaysia's official exchange rates for 8 currencies (back to 2006) and its policy-rate decisions, cleans them, and stores them in DuckDB with CSV snapshots in git.
A notebook analyses what moves the ringgit (oil, the US–Malaysia rate gap, OPR decisions), and a backtest compares four forecasting models against a naive "tomorrow = today" baseline.
A Streamlit dashboard shows the rates, OPR events, volatility, the 30-day forecast band, a converter and a "best day to convert" helper.

## 2. Major decisions
| Decision | Alternative | Why |
|---|---|---|
| BNM **noon (12:00) session** | default 11:30 session | 11:30 has no IDR/THB and only goes back to 2021. Noon covers all 8 currencies from 2006, with a middle rate. Found by testing the API, not from the docs. |
| No backfill source | Frankfurter/ECB for pre-2021 | Once noon history went back to 2006 it wasn't needed, and mixing sources would add level breaks (ECB and BNM fix at different times). |
| **CSV snapshots in git**, DuckDB rebuilt from them | commit `fx.duckdb`, or a release asset | Binary DB rewritten daily = bloated, unreadable git history. CSVs give one-line-per-day diffs. Rebuilding takes under 1 s. |
| Idempotent **upsert on (date, currency)** + refetch from last stored month | append-only | Reruns, retries and BNM revisions can't create duplicates. Proven by a test that runs ingest twice and checks the CSV is byte-identical. |
| Clean on the **full history** after each run | validate only the new batch | Spikes are defined relative to neighbours (rolling median), which needs context outside the batch. |
| **Walk-forward backtest**, 24 non-overlapping folds, rolling 3-year window | single train/test split | One split = one lucky or unlucky month. Non-overlapping folds give 24 roughly independent scores, so a paired t-test is valid. |
| Horizon = **21 business days** | 30 calendar days | BNM only publishes on business days. 21 ≈ 30 calendar days. |
| Report **MAE, MAPE, interval coverage, paired t vs naive** | MAE/MAPE only | Coverage shows Prophet's bands are overconfident (59% vs 95%). The t-stat shows whether "ARIMA is 0.3% better" is real (it isn't). |
| Forecasts **precomputed** by CI, read by the app | fit models inside Streamlit | Prophet/pmdarima are heavy installs and slow fits. The app uses a slim `app/requirements.txt` that Streamlit Cloud reads before the root `uv.lock`. |
| "Best day to convert" = **percentile of today's rate in its 90-day range** | use the forecast to time conversions | The backtest proves the forecast can't time the market. A descriptive heuristic is honest. |
| matplotlib in the notebook, Plotly in the app | Plotly everywhere | GitHub doesn't render Plotly outputs in notebooks. Recruiters read it on GitHub. |

## 3. Concepts to understand
- **Log returns** (`insights.py`): `ln(P_t / P_{t-1})`. They add up over time and are symmetric for up and down moves, the standard unit for volatility.
- **Annualised volatility** (`insights.rolling_vol`): std of daily log returns × √252 trading days. 5% = a typical one-year move of about ±5%.
- **Random walk / naive forecast** (`forecast.naive`): best guess of tomorrow = today. Its uncertainty grows with √(steps), which is why the band widens like a funnel.
- **ARIMA(p,d,q)** (`forecast.arima`): AR = regress on past values, I = difference d times to remove trend, MA = regress on past errors. `auto_arima` picks p, d, q by AIC. For FX it usually lands near (0,1,0), which *is* a random walk.
- **SARIMA** (`forecast.sarima`): ARIMA plus seasonal terms at lag m. m = 5 tests a day-of-week pattern. None found.
- **Prophet** (`forecast.prophet`): additive trend + seasonality curve fit. Good for business series with strong calendar patterns, bad for FX (no stable seasonality, so it extrapolates noise).
- **Walk-forward validation** (`forecast.backtest`): repeatedly train on the past and test on the next window, never letting the model see the future (no leakage).
- **MAE / MAPE**: mean absolute error in MYR / in % of the actual rate. MAPE lets you compare USD (≈4.08) and SGD (≈3.18).
- **Interval coverage** (`forecast.score`): the share of actuals inside the 95% band. It should be about 95%. Below that = overconfident.
- **Paired t-test across folds** (`forecast.vs_naive_t`): mean of (model MAE − naive MAE) per fold ÷ its standard error. |t| < 2 = no detectable difference.
- **Event study** (`insights.event_window`): line up the price around each event day, rebase to 0, average. Compare with a **placebo** of random days to see what "no effect" looks like.
- **Geometric-mean basket index** (`insights.strength_index`): averages log changes so a currency's price level (IDR vs GBP) doesn't set its weight.
- **Idempotency** (`ingest.run`, `db.upsert_*`): running twice gives the same state. Essential for cron jobs that can retry.
- **HAC standard errors** (notebook section 5): regression errors corrected for autocorrelation, so t-stats on monthly FX data aren't inflated.

## 4. Interview questions (with honest answers)
1. **Why did your fancy models lose to a naive forecast?** FX is a liquid, efficient market. Predictable patterns get arbitraged away, so a random walk is the benchmark to beat (Meese and Rogoff, 1983). My job was to test that honestly. ARIMA ties it (t = 0.35), Prophet is significantly worse (t = 4.1).
2. **Then what's the point of the forecast?** The uncertainty band. ±1.2% over 30 days tells a student how much buffer to budget. I also show *coverage*, so users know the band is honest (96–98% for naive, 59% for Prophet).
3. **How do you know there's no data leakage in the backtest?** Each fold trains only on data before the fold's origin (`iloc[o - train_days : o]`). Tests check that origins don't overlap and that the last window ends at the final observation.
4. **What data problems did you hit?** The default API session lacked two currencies and had only 5 years. I found the noon session by probing. The history had weekend repeats and bad prints (EUR/GBP cross rates on 1 Jan 2007, JPY 100x off), which I catch with a rolling-median rule plus a snap-back rule, tested on those exact cases.
5. **How does the pipeline stay correct if it runs twice or fails halfway?** Upserts on a primary key plus a refetch from the last stored month. A test proves a second run produces a byte-identical CSV.
6. **What drives the ringgit?** In this data: the US–Malaysia rate gap explains the level (ρ = 0.49). Oil helps a little (10% Brent ≈ 0.2% MYR). Together they explain only about 2% of monthly moves. OPR decisions show no detectable effect.
7. **Why doesn't the OPR move MYR when theory says it should?** The moves are small (25 bp), markets anticipate them, and US rates swung far more. Also only 24 changes since 2005, so the test is low-powered. I'd say "no detectable effect", not "no effect".
8. **Why DuckDB and not Postgres/SQLite?** It's analytical (columnar), embedded (no server, free) and reads pandas frames directly. With 41k rows Postgres would be over-engineering. SQLite would work but is slower for aggregations.
9. **How would you scale this to 100 currencies or intraday data?** Partition storage by currency and month (Parquet on object storage), run fetches concurrently within BNM's rate limits, and move the cron to an orchestrator (Prefect or Dagster) with retries and alerting.
10. **What would you do with more time?** Add a GARCH model to forecast volatility, since *volatility* is forecastable even when price isn't. Use intraday or end-of-day data for better EUR/GBP alignment. Run a proper causal design for the OPR effect (surprise component of each decision vs expectations).

## 5. Weaknesses and how to say them
- **"The forecast doesn't beat a random walk."** Say: *"That's the finding, not a failure. I built the evaluation to detect it, and I show coverage so the uncertainty is honest."*
- **Correlational drivers analysis.** Say: *"Oil, US rates and the dollar share the global cycle, so I report associations and say so. I didn't claim causation."*
- **Small samples:** 24 OPR changes and 24 backtest folds (about 2 years). Say: *"The event study is low-powered, and a different regime could rank models differently. The naive-wins result is consistent with decades of FX research, though."*
- **Noon fix only, IDR coarse.** Say: *"One official fix a day is right for a retail-conversion use case but not for trading. I documented the IDR precision issue."*
- **Dashboard is single-user and read-only, with no auth.** It's a portfolio demo, not a product.

## 6. Resume bullets
- **[data]** Built an automated BNM exchange-rate pipeline (Python, DuckDB, GitHub Actions) ingesting 41,000+ daily rates for 8 currencies since 2006, with idempotent upserts and data-quality rules that caught 346 bad source rows.
- **[data]** Analysed 20 years of MYR data to quantify drivers: the US–Malaysia rate gap tracks USD/MYR levels (ρ = 0.49), while an event study of 24 OPR changes found no detectable effect against a random-day placebo.
- **[ML]** Designed a 24-fold walk-forward backtest of naive, ARIMA, SARIMA and Prophet 30-day FX forecasts; showed no model beats the random walk (paired t = 0.35) and that Prophet's 95% intervals covered only 59% of outcomes.
- **[SWE]** Shipped a tested Python package (25 pytest tests, ruff, CI) and a Streamlit dashboard with OPR event markers, volatility, forecast bands and a currency converter, deployed on free tiers.
- **[cloud]** Automated a daily business-day cron on GitHub Actions (Malaysian holiday-aware) that refreshes data and forecasts and commits append-only CSV snapshots, at zero hosting cost.
