"""Analysis helpers shared by the EDA notebook and the Streamlit app.

Convention: rates are MYR per 1 unit of foreign currency, so a RISING rate means a
WEAKER ringgit (you pay more MYR for the same USD).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def log_returns(wide: pd.DataFrame) -> pd.DataFrame:
    return np.log(wide).diff()


def rolling_vol(wide: pd.DataFrame, window: int = 21) -> pd.DataFrame:
    """Annualised rolling volatility of daily log returns, in percent."""
    return (
        log_returns(wide).rolling(window, min_periods=window // 2).std()
        * np.sqrt(TRADING_DAYS)
        * 100
    )


def strength_index(wide: pd.DataFrame, base: str | pd.Timestamp | None = None) -> pd.Series:
    """Equal-weight MYR strength vs the basket, = 100 on the base date. Above 100 = stronger MYR.

    Geometric mean of (rate_base / rate_t) across currencies, so each currency counts
    equally regardless of its price level (IDR vs GBP).
    """
    w = wide.dropna()
    base_row = w.iloc[0] if base is None else w.loc[w.index >= pd.Timestamp(base)].iloc[0]
    return np.exp(np.log(base_row / w).mean(axis=1)) * 100


def opr_changes(opr: pd.DataFrame) -> pd.DataFrame:
    """Only meetings where the OPR actually moved."""
    return opr[opr["change_in_opr"] != 0].reset_index(drop=True)


def event_window(series: pd.Series, dates, before: int = 10, after: int = 20) -> pd.DataFrame:
    """Cumulative % move of `series` around each event, rebased to 0 on the event day.

    Rows: relative business day (-before..after). Columns: event date.
    Events too close to the edges of the data are skipped.
    """
    s = series.dropna()
    out = {}
    for d in pd.to_datetime(list(dates)):
        i = s.index.searchsorted(d)
        if i - before < 0 or i + after >= len(s):
            continue
        win = s.iloc[i - before : i + after + 1]
        out[d] = (win / win.iloc[before] - 1).to_numpy() * 100
    return pd.DataFrame(out, index=pd.RangeIndex(-before, after + 1, name="rel_day"))


def convert_advice(series: pd.Series, lookback: int = 90) -> dict:
    """'Best day to convert' heuristic for someone paying a foreign bill in MYR.

    Forecasts don't beat a random walk (see reports/), so we don't predict. We tell the
    user where today's rate sits in its recent range: a low percentile means MYR is
    relatively strong (cheap to buy foreign currency) versus the last `lookback` days.
    """
    s = series.dropna().iloc[-lookback:]
    today = float(s.iloc[-1])
    pct = float((s < today).mean() * 100)
    if pct <= 25:
        label, text = (
            "good",
            "Rate is in the cheapest quarter of the last {n} days. Converting now is reasonable.",
        )
    elif pct >= 75:
        label, text = (
            "poor",
            "Rate is in the most expensive quarter of the last {n} days. "
            "If the deadline allows, convert in tranches over the coming weeks.",
        )
    else:
        label, text = (
            "neutral",
            "Rate is mid-range for the last {n} days. "
            "Splitting the amount into 2-4 conversions averages out timing risk.",
        )
    return {
        "rate": today,
        "percentile": pct,
        "low": float(s.min()),
        "high": float(s.max()),
        "label": label,
        "text": text.format(n=lookback),
    }


def weekday_effect(series: pd.Series) -> pd.DataFrame:
    """Mean and t-stat of daily % change by weekday: checks the 'convert on a Monday' myth."""
    r = series.dropna().pct_change().dropna() * 100
    g = r.groupby(r.index.day_name())
    out = pd.DataFrame({"mean_%": g.mean(), "std_%": g.std(), "n": g.size()})
    out["t_stat"] = out["mean_%"] / (out["std_%"] / np.sqrt(out["n"]))
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    return out.reindex([d for d in order if d in out.index])
