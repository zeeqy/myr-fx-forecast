"""Data-quality rules applied before anything touches the database."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

log = logging.getLogger(__name__)

FX_COLUMNS = ["date", "currency", "unit", "buying", "selling", "middle"]
OPR_COLUMNS = ["date", "change_in_opr", "new_opr_level"]


def validate_fx(rows: list[dict] | pd.DataFrame, today: date | None = None) -> pd.DataFrame:
    """Return a clean frame; drop (and log) rows that break the rules.

    Rules: required columns present, date parses and is not in the future,
    rates positive, buying <= selling, one row per (date, currency).
    A missing middle rate is filled with (buying + selling) / 2.
    """
    df = pd.DataFrame(rows, columns=FX_COLUMNS) if not isinstance(rows, pd.DataFrame) else rows
    missing = set(FX_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    df = df[FX_COLUMNS].copy()
    if df.empty:
        return df.astype({"unit": "int64"})

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for c in ("buying", "selling", "middle", "unit"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["middle"] = df["middle"].fillna((df["buying"] + df["selling"]) / 2)

    today = today or date.today()
    ok = (
        df["date"].notna()
        & (df["date"] <= today)
        & df["currency"].str.fullmatch(r"[A-Z]{3}").fillna(False)
        & (df["unit"] > 0)
        & (df["middle"] > 0)
        & ~((df["buying"] > df["selling"]) & df["buying"].notna() & df["selling"].notna())
    )
    if (~ok).any():
        log.warning("dropping %d invalid FX rows", int((~ok).sum()))
    df = df[ok].drop_duplicates(["date", "currency"], keep="last")
    return df.astype({"unit": "int64"}).reset_index(drop=True)


def validate_opr(rows: list[dict] | pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=OPR_COLUMNS) if not isinstance(rows, pd.DataFrame) else rows
    df = df[OPR_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["new_opr_level"] = pd.to_numeric(df["new_opr_level"], errors="coerce")
    df["change_in_opr"] = pd.to_numeric(df["change_in_opr"], errors="coerce").fillna(0.0)
    ok = df["date"].notna() & df["new_opr_level"].between(0, 20)
    if (~ok).any():
        log.warning("dropping %d invalid OPR rows", int((~ok).sum()))
    return df[ok].drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
