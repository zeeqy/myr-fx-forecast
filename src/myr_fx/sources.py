"""Thin client for the Bank Negara Malaysia (BNM) Open API.

Docs: https://apikijangportal.bnm.gov.my/ . Every request needs the
`Accept: application/vnd.BNM.API.v1+json` header. We use the 12:00 (noon)
session: unlike the default 11:30 session it publishes a middle rate for every
currency (IDR and THB are missing at 11:30) and goes back to January 2006.
"""

from __future__ import annotations

import io
import time
from typing import Any

import pandas as pd
import requests

BNM_BASE = "https://api.bnm.gov.my/public"
HEADERS = {"Accept": "application/vnd.BNM.API.v1+json", "User-Agent": "myr-fx-forecast/0.1"}
CURRENCIES: tuple[str, ...] = ("USD", "SGD", "CNY", "EUR", "GBP", "JPY", "THB", "IDR")
SESSION = "1200"
FX_START = (2006, 1)
OPR_START_YEAR = 2004


def get_json(
    http: requests.Session, url: str, params: dict | None = None, retries: int = 4
) -> dict[str, Any]:
    """GET with retry/backoff. BNM answers 404 for 'no records', which we treat as empty."""
    for attempt in range(retries):
        try:
            r = http.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code == 404:
                return {"data": []}
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def parse_fx(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten an exchange-rate payload (single day or month) into rows."""
    data = payload.get("data") or []
    if not data:
        return []
    rates = data["rate"]
    if isinstance(rates, dict):  # the 'latest' endpoint returns one object, not a list
        rates = [rates]
    return [
        {
            "date": r["date"],
            "currency": data["currency_code"],
            "unit": int(data["unit"]),
            "buying": r.get("buying_rate"),
            "selling": r.get("selling_rate"),
            "middle": r.get("middle_rate"),
        }
        for r in rates
    ]


def parse_opr(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or []
    if isinstance(data, dict):
        data = [data]
    return [
        {
            "date": d["date"],
            "change_in_opr": d["change_in_opr"],
            "new_opr_level": d["new_opr_level"],
        }
        for d in data
    ]


def fetch_fx_month(http: requests.Session, currency: str, year: int, month: int) -> list[dict]:
    url = f"{BNM_BASE}/exchange-rate/{currency}/year/{year}/month/{month}"
    return parse_fx(get_json(http, url, {"session": SESSION, "quote": "rm"}))


def fetch_opr_year(http: requests.Session, year: int) -> list[dict]:
    return parse_opr(get_json(http, f"{BNM_BASE}/opr/year/{year}"))


# Context series for the "what drives MYR" analysis (FRED CSV download, no API key needed)
FRED_SERIES = {"DCOILBRENTEU": "brent_usd", "DFF": "fed_funds"}


def fetch_fred(http: requests.Session, series_id: str, start: str = "2006-01-01") -> list[dict]:
    r = http.get(
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        params={"id": series_id, "cosd": start},
        # FRED stalls on unknown custom User-Agents; the default requests UA is accepted
        timeout=60,
    )
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), na_values=["."])
    df.columns = ["date", "value"]
    df = df.dropna()
    return [
        {"date": d, "series": FRED_SERIES[series_id], "value": float(v)}
        for d, v in zip(df["date"], df["value"], strict=True)
    ]
