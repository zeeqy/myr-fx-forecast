"""30-day forecasts for USD/MYR and SGD/MYR with walk-forward backtesting.

Models: naive (random walk), ARIMA (auto order by AIC), SARIMA (weekly m=5), Prophet.
BNM only publishes on business days, so "30 days ahead" = 21 business-day steps.

    uv run python -m myr_fx.forecast            # backtest + write reports/ and data/forecast.csv
    uv run python -m myr_fx.forecast --forecast-only   # daily refresh, no backtest
"""

from __future__ import annotations

import argparse
import logging
import warnings
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from myr_fx import db

log = logging.getLogger("forecast")

HORIZON = 21  # business days ~ 30 calendar days
TRAIN_DAYS = 756  # ~3 years of business days
Z95 = 1.959964
PAIRS = ("USD", "SGD")
REPORTS = db.ROOT / "reports"
FORECAST_CSV = db.DATA_DIR / "forecast.csv"

Forecaster = Callable[[pd.Series, int], pd.DataFrame]


def _frame(mean, lower, upper) -> pd.DataFrame:
    return pd.DataFrame(
        {"mean": np.asarray(mean), "lower": np.asarray(lower), "upper": np.asarray(upper)}
    )


def naive(train: pd.Series, h: int) -> pd.DataFrame:
    """Random walk: tomorrow = today. Band widens with sqrt(steps) x std of daily changes."""
    last = float(train.iloc[-1])
    sigma = float(train.diff().dropna().std())
    width = Z95 * sigma * np.sqrt(np.arange(1, h + 1))
    return _frame(np.full(h, last), last - width, last + width)


def arima(train: pd.Series, h: int) -> pd.DataFrame:
    import pmdarima as pm

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = pm.auto_arima(
            train.to_numpy(),
            seasonal=False,
            d=None,
            max_p=3,
            max_q=3,
            stepwise=True,
            suppress_warnings=True,
            error_action="ignore",
        )
        mean, ci = m.predict(n_periods=h, return_conf_int=True, alpha=0.05)
    return _frame(mean, ci[:, 0], ci[:, 1])


def sarima(train: pd.Series, h: int) -> pd.DataFrame:
    """SARIMA(1,1,1)(1,0,1,5): tests whether a day-of-week pattern adds anything."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = SARIMAX(train.to_numpy(), order=(1, 1, 1), seasonal_order=(1, 0, 1, 5)).fit(
            disp=False
        )
        fc = res.get_forecast(h)
        ci = fc.conf_int(alpha=0.05)
    return _frame(fc.predicted_mean, ci[:, 0], ci[:, 1])


def prophet(train: pd.Series, h: int) -> pd.DataFrame:
    from prophet import Prophet

    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
    df = pd.DataFrame({"ds": train.index, "y": train.to_numpy()})
    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.95,
    )
    m.fit(df)
    future = pd.DataFrame({"ds": future_dates(train.index[-1], h)})
    out = m.predict(future)
    return _frame(out["yhat"], out["yhat_lower"], out["yhat_upper"])


MODELS: dict[str, Forecaster] = {
    "naive": naive,
    "arima": arima,
    "sarima": sarima,
    "prophet": prophet,
}


def future_dates(last: pd.Timestamp, h: int) -> pd.DatetimeIndex:
    return pd.bdate_range(last + pd.offsets.BDay(1), periods=h)


def fold_origins(n: int, n_folds: int, step: int, h: int, min_train: int) -> list[int]:
    """Indices where each test window starts; latest window ends at the last observation."""
    last = n - h
    origins = [last - k * step for k in range(n_folds)]
    return sorted(o for o in origins if o >= min_train)


def backtest(
    series: pd.Series,
    models: dict[str, Forecaster] | None = None,
    n_folds: int = 24,
    step: int = HORIZON,
    h: int = HORIZON,
    train_days: int = TRAIN_DAYS,
) -> pd.DataFrame:
    """Walk-forward: refit each model at every origin on the trailing window, score the next h."""
    models = models or MODELS
    s = series.dropna()
    rows = []
    for o in fold_origins(len(s), n_folds, step, h, min_train=min(train_days, 250)):
        train, test = s.iloc[max(0, o - train_days) : o], s.iloc[o : o + h]
        for name, fn in models.items():
            fc = fn(train, h)
            rows.append(
                pd.DataFrame(
                    {
                        "model": name,
                        "origin": s.index[o],
                        "step": np.arange(1, h + 1),
                        "date": test.index,
                        "actual": test.to_numpy(),
                        "mean": fc["mean"].to_numpy(),
                        "lower": fc["lower"].to_numpy(),
                        "upper": fc["upper"].to_numpy(),
                    }
                )
            )
        log.info("fold %s done", s.index[o].date())
    return pd.concat(rows, ignore_index=True)


def score(results: pd.DataFrame) -> pd.DataFrame:
    """MAE, MAPE (all 21 steps), MAPE at day 21, and 95% interval coverage per model."""
    r = results.assign(
        abs_err=(results["actual"] - results["mean"]).abs(),
        inside=results["actual"].between(results["lower"], results["upper"]),
    )
    r["ape"] = r["abs_err"] / r["actual"]
    g = r.groupby("model")
    out = pd.DataFrame(
        {
            "MAE": g["abs_err"].mean(),
            "MAPE_%": g["ape"].mean() * 100,
            "MAPE_day21_%": r[r["step"] == r["step"].max()].groupby("model")["ape"].mean() * 100,
            "coverage95_%": g["inside"].mean() * 100,
        }
    )
    base = out.loc["naive", "MAE"] if "naive" in out.index else np.nan
    out["MAE_vs_naive"] = out["MAE"] / base
    return out.sort_values("MAE")


def make_forecasts(
    wide: pd.DataFrame,
    models: dict[str, Forecaster] | None = None,
    h: int = HORIZON,
    train_days: int = TRAIN_DAYS,
) -> pd.DataFrame:
    models = models or MODELS
    frames = []
    for pair in PAIRS:
        s = wide[pair].dropna().iloc[-train_days:]
        dates = future_dates(s.index[-1], h)
        for name, fn in models.items():
            fc = fn(s, h)
            fc.insert(0, "date", dates)
            fc.insert(0, "model", name)
            fc.insert(0, "pair", pair)
            frames.append(fc)
    return pd.concat(frames, ignore_index=True)


def write_report(summaries: dict[str, pd.DataFrame], path: Path) -> None:
    lines = ["# Walk-forward backtest (24 folds x 21 business days, 3-year rolling train)\n"]
    for pair, tbl in summaries.items():
        lines.append(f"\n## {pair}/MYR\n")
        lines.append(tbl.round(4).to_markdown())
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--forecast-only", action="store_true")
    p.add_argument("--folds", type=int, default=24)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    con = db.ensure_db()
    wide = db.fx_wide(con)
    con.close()

    if not args.forecast_only:
        REPORTS.mkdir(exist_ok=True)
        summaries = {}
        for pair in PAIRS:
            res = backtest(wide[pair], n_folds=args.folds)
            res.to_csv(REPORTS / f"backtest_{pair.lower()}.csv", index=False)
            summaries[pair] = score(res)
            print(f"\n{pair}/MYR\n{summaries[pair].round(4)}")
        write_report(summaries, REPORTS / "backtest_summary.md")

    fc = make_forecasts(wide)
    fc.to_csv(FORECAST_CSV, index=False, float_format="%.6f", lineterminator="\n")
    log.info("wrote %s", FORECAST_CSV)


if __name__ == "__main__":
    main()
