# DEMO: MYR FX Forecast (60–90 s video script)

**Hook (0–5 s):** "I tested four forecasting models on the ringgit. The winner was 'tomorrow equals today', and that is the useful result."

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 5–18 s | Dashboard, USD/MYR, 5-year chart with red/green OPR markers. Hover the April 2024 peak. | "This pulls Bank Negara's official noon rates for 8 currencies every business day: 41,125 rows back to 2006. USD/MYR hit a record 4.79 in April 2024. Today it's 4.118." |
| 2 | 18–30 s | GitHub repo: `.github/workflows/daily_ingest.yml`, then the commit list of daily "data: BNM rates" commits. | "A GitHub Actions cron fetches, validates and upserts into DuckDB, skips Malaysian holidays, and commits CSV snapshots. Running it twice gives a byte-identical file. Zero hosting cost." |
| 3 | 30–45 s | Scroll to the forecast panel: USD/MYR 30-day band, then the backtest table. | "I backtested naive, ARIMA, SARIMA and Prophet over 24 walk-forward folds. Naive: 0.84% error. ARIMA ties it, t = 0.35, so no real difference. Prophet is twice as bad, and its 95% band only covered 59% of outcomes." |
| 4 | 45–55 s | Point at the band: RM3.96 to RM4.28 for 25 Dec. | "So the line isn't the product. The band is. It tells a student paying fees in dollars how much buffer to budget." |
| 5 | 55–68 s | Switch pair to SGD, show volatility panel and the "best day to convert" helper and converter. | "SGD is the calmest pair, 3.4% annual volatility vs 5% for USD. The helper doesn't predict. It shows where today's rate sits in its 90-day range and suggests splitting big payments." |
| 6 | 68–80 s | Notebook on GitHub: OPR event-study chart vs placebo. | "And OPR decisions? After 24 changes, the 20-day move is about 0.1%, inside the 1.8% noise of random days. No detectable effect." |

**Closing (80–88 s):** "Official data, an honest test, and a dashboard that tells you how uncertain the rate is, not just a guess. Link in the description."
