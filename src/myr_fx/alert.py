"""Telegram alert when USD/MYR moves more than a threshold between the last two BNM fixes.

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (see .env.example). No-ops without them.
"""

from __future__ import annotations

import os

import pandas as pd
import requests

from myr_fx import db

THRESHOLD = 0.01


def last_move(rates: pd.Series) -> tuple[pd.Timestamp, float, float]:
    """Return (date, latest rate, % change vs previous fix) for a date-indexed series."""
    s = rates.dropna()
    return s.index[-1], float(s.iloc[-1]), float(s.iloc[-1] / s.iloc[-2] - 1)


def message(pair: str, day: pd.Timestamp, rate: float, change: float) -> str | None:
    if abs(change) < THRESHOLD:
        return None
    direction = "weakened" if change > 0 else "strengthened"
    return (
        f"MYR alert {day:%Y-%m-%d}: {pair} {rate:.4f} ({change:+.2%}). "
        f"Ringgit {direction} more than {THRESHOLD:.0%} vs the previous BNM noon fix."
    )


def main() -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    con = db.ensure_db()
    day, rate, change = last_move(db.fx_wide(con)["USD"])
    text = message("USD/MYR", day, rate, change)
    print(text or f"USD/MYR {change:+.2%} on {day:%Y-%m-%d}: below threshold")
    if text and token and chat:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text},
            timeout=20,
        )
        r.raise_for_status()


if __name__ == "__main__":
    main()
