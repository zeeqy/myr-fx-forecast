"""MYR FX dashboard: BNM noon rates, OPR events, volatility, 30-day forecast, converter."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from myr_fx import db, insights  # noqa: E402
from myr_fx.forecast import score  # noqa: E402

st.set_page_config(page_title="MYR FX Tracker", page_icon="💱", layout="wide")

NAMES = {
    "USD": "US dollar",
    "SGD": "Singapore dollar",
    "CNY": "Chinese yuan",
    "EUR": "Euro",
    "GBP": "British pound",
    "JPY": "Japanese yen",
    "THB": "Thai baht",
    "IDR": "Indonesian rupiah",
}
PER_100 = {"JPY", "THB", "IDR"}  # quoted per 100 units, as BNM and Malaysian banks do
HIKE, CUT = "#c0392b", "#2471a3"


@st.cache_data(ttl=3600)
def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    con = db.ensure_db(":memory:")  # seeded from the committed CSV snapshots
    wide, opr = db.fx_wide(con), db.opr_frame(con)
    spread = con.execute(
        "SELECT date, currency, buying, selling FROM fx_daily "
        "WHERE date = (SELECT max(date) FROM fx_daily)"
    ).df()
    con.close()
    return wide, opr, spread


@st.cache_data(ttl=3600)
def load_forecasts() -> tuple[pd.DataFrame | None, dict[str, pd.DataFrame]]:
    fc_path = db.DATA_DIR / "forecast.csv"
    fc = pd.read_csv(fc_path, parse_dates=["date"]) if fc_path.exists() else None
    scores = {}
    for pair in ("USD", "SGD"):
        p = ROOT / "reports" / f"backtest_{pair.lower()}.csv"
        if p.exists():
            scores[pair] = score(pd.read_csv(p))
    return fc, scores


wide, opr, spread = load()
fc, scores = load_forecasts()
changes = insights.opr_changes(opr)

# ---------------- sidebar ----------------
st.sidebar.title("💱 MYR FX Tracker")
ccy = st.sidebar.selectbox("Currency", list(NAMES), format_func=lambda c: f"{c}/MYR · {NAMES[c]}")
mult = 100 if ccy in PER_100 else 1
unit_label = f"MYR per {mult} {ccy}"
lo, hi = wide.index.min().date(), wide.index.max().date()
picked = st.sidebar.date_input(
    "Date range",
    value=((pd.Timestamp(hi) - pd.DateOffset(years=5)).date(), hi),
    min_value=lo,
    max_value=hi,
)
# while the user is mid-selection Streamlit returns a 1-tuple
start, end = (picked[0], picked[1]) if len(picked) == 2 else (picked[0], hi)
show_opr = st.sidebar.checkbox("Show OPR changes", value=True)
st.sidebar.caption(
    f"Source: Bank Negara Malaysia Open API, 12:00 middle rate. Data to {hi:%d %b %Y}. "
    "Rising line = weaker ringgit."
)

series = wide[ccy].dropna() * mult
view = series.loc[str(start) : str(end)]

# ---------------- header metrics ----------------
st.title(f"{ccy}/MYR")
last, prev = series.iloc[-1], series.iloc[-2]
yr = series.loc[: series.index[-1] - pd.DateOffset(years=1)].iloc[-1]
c1, c2, c3, c4 = st.columns(4)
c1.metric(unit_label, f"{last:.4f}", f"{(last / prev - 1):+.2%} d/d", delta_color="inverse")
c2.metric("1-year change", f"{(last / yr - 1):+.2%}", delta_color="off")
c3.metric("Range in view", f"{view.min():.3f} – {view.max():.3f}")
c4.metric("OPR now", f"{opr['new_opr_level'].iloc[-1]:.2f}%")

# ---------------- price chart ----------------
fig = go.Figure(go.Scatter(x=view.index, y=view, name=f"{ccy}/MYR", line=dict(width=1.6)))
if show_opr:
    ev = changes[(changes["date"] >= pd.Timestamp(start)) & (changes["date"] <= pd.Timestamp(end))]
    for _, r in ev.iterrows():
        color = HIKE if r["change_in_opr"] > 0 else CUT
        fig.add_vline(x=r["date"], line=dict(color=color, width=1, dash="dot"))
    if not ev.empty:
        y_at = series.reindex(ev["date"], method="nearest")
        fig.add_trace(
            go.Scatter(
                x=ev["date"],
                y=y_at.to_numpy(),
                mode="markers",
                name="OPR change",
                marker=dict(
                    color=[HIKE if c > 0 else CUT for c in ev["change_in_opr"]],
                    size=9,
                    symbol=[
                        "triangle-up" if c > 0 else "triangle-down" for c in ev["change_in_opr"]
                    ],
                ),
                customdata=ev[["change_in_opr", "new_opr_level"]].to_numpy(),
                hovertemplate="%{x|%d %b %Y}<br>OPR %{customdata[0]:+.2f} → %{customdata[1]:.2f}%"
                "<extra></extra>",
            )
        )
fig.update_layout(
    height=420,
    margin=dict(l=10, r=10, t=30, b=10),
    yaxis_title=unit_label,
    hovermode="x unified",
    legend=dict(orientation="h", y=1.08),
)
st.plotly_chart(fig, use_container_width=True)
st.caption("▲ red = OPR hike, ▼ blue = OPR cut (BNM Monetary Policy Committee decisions).")

# ---------------- volatility ----------------
left, right = st.columns([3, 2])
with left:
    st.subheader("Volatility")
    vol = insights.rolling_vol(wide[[ccy]], 21)[ccy].loc[str(start) : str(end)]
    vfig = go.Figure(
        go.Scatter(x=vol.index, y=vol, fill="tozeroy", name="21-day vol", line=dict(width=1))
    )
    vfig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="annualised %")
    st.plotly_chart(vfig, use_container_width=True)
    st.caption(
        f"Long-run median: {insights.rolling_vol(wide[[ccy]])[ccy].median():.1f}%. "
        f"Latest: {vol.iloc[-1]:.1f}%."
    )

# ---------------- converter ----------------
with right:
    st.subheader("Converter")
    direction = st.radio("Direction", [f"MYR → {ccy}", f"{ccy} → MYR"], horizontal=True)
    amount = st.number_input("Amount", min_value=0.0, value=1000.0, step=100.0)
    rate1 = float(wide[ccy].dropna().iloc[-1])  # MYR per 1 unit
    if direction.startswith("MYR"):
        st.metric(f"{ccy} you get (mid rate)", f"{amount / rate1:,.2f}")
    else:
        st.metric("MYR needed (mid rate)", f"{amount * rate1:,.2f}")
    sp = spread[spread["currency"] == ccy]
    if not sp.empty and pd.notna(sp["selling"].iloc[0]):
        b, s = sp["buying"].iloc[0] * mult, sp["selling"].iloc[0] * mult
        st.caption(
            f"BNM interbank buying/selling: {b:.4f} / {s:.4f}. "
            "Banks and remittance apps add their own margin on top."
        )

    adv = insights.convert_advice(wide[ccy] * mult, lookback=90)
    icon = {"good": "🟢", "neutral": "🟡", "poor": "🔴"}[adv["label"]]
    st.markdown(
        f"**Best day to convert?** {icon} Today is at the **{adv['percentile']:.0f}th "
        f"percentile** of the last 90 days ({adv['low']:.4f} – {adv['high']:.4f}). "
        f"{adv['text']}"
    )

# ---------------- forecast ----------------
st.subheader("30-day forecast")
if ccy not in ("USD", "SGD") or fc is None:
    st.info("Forecasts are built for USD/MYR and SGD/MYR. Pick one of those in the sidebar.")
else:
    tbl = scores.get(ccy)
    models = list(tbl.index) if tbl is not None else sorted(fc["model"].unique())
    model = st.selectbox(
        "Model",
        models,
        format_func=lambda m: (
            f"{m} (best backtest MAE)" if tbl is not None and m == models[0] else m
        ),
    )
    f = fc[(fc["pair"] == ccy) & (fc["model"] == model)]
    hist = series.iloc[-126:]
    ffig = go.Figure(
        [
            go.Scatter(x=hist.index, y=hist, name="actual", line=dict(width=1.6)),
            go.Scatter(
                x=f["date"],
                y=f["upper"] * mult,
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            ),
            go.Scatter(
                x=f["date"],
                y=f["lower"] * mult,
                fill="tonexty",
                line=dict(width=0),
                name="95% band",
                fillcolor="rgba(36,113,163,0.18)",
            ),
            go.Scatter(
                x=f["date"], y=f["mean"] * mult, name=f"{model} forecast", line=dict(dash="dash")
            ),
        ]
    )
    ffig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title=unit_label,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08),
    )
    st.plotly_chart(ffig, use_container_width=True)
    if tbl is not None:
        st.markdown(
            "**How good is it really?** Walk-forward backtest, 24 monthly folds, "
            "21 business days ahead, refit on a rolling 3-year window:"
        )
        st.dataframe(
            tbl.style.format("{:.4f}", subset=["MAE"]).format(
                "{:.2f}", subset=["MAPE_%", "MAPE_day21_%", "coverage95_%", "MAE_vs_naive"]
            ),
            use_container_width=True,
        )
        st.caption(
            "MAE_vs_naive < 1 means the model beats 'tomorrow = today'. "
            "coverage95 should be ~95 if the band is honest."
        )
