# 03 MYR FX Forecast

Build an automated MYR exchange rate tracker, analysis and forecasting dashboard.
Tracks shown: data analysis, ML (time series), cloud automation, fintech.

## Data
- Bank Negara Malaysia Open API (api.bnm.gov.my), exchange rate endpoints. Check the current docs for required headers and history limits.
- Currencies: USD, SGD, CNY, EUR, GBP, JPY, THB, IDR vs MYR.
- Also pull BNM OPR (policy rate) history for event annotations.
- If BNM history is too short, backfill from another free source and document it in the README.

## Build
1. `src/ingest.py`: fetch + validate + upsert into DuckDB (`data/fx.duckdb`). Idempotent.
2. GitHub Actions cron (daily, Malaysia business days): run ingest, commit updated data or push to a release asset.
3. `notebooks/01_eda.ipynb`: trends, volatility (rolling std), MYR strength index vs basket, correlation between pairs, impact around OPR changes. Write the insights in markdown.
4. `src/forecast.py`: forecast USD/MYR and SGD/MYR 30 days ahead. Compare naive baseline, ARIMA/SARIMA and Prophet with walk-forward backtesting. Report MAE and MAPE in a table. Be honest if the naive baseline wins (it often does for FX) and explain why.
5. `app/streamlit_app.py`: pair selector, date range, chart with OPR event markers, volatility panel, forecast with confidence band, MYR converter. Deploy to Streamlit Community Cloud.

## Extras if time allows
- Telegram alert when USD/MYR moves more than 1% in a day.
- "Best day to convert" heuristic for students paying overseas fees.

## README must answer
What drives MYR moves in the data, how good the forecast really is, and the pipeline architecture (Mermaid).
