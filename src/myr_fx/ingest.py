"""Fetch BNM exchange rates + OPR, validate, upsert into DuckDB, export CSV snapshots.

Idempotent: re-running fetches from the latest stored month onward and upserts on the
(date, currency) primary key, so the result is identical however many times it runs.

    uv run python -m myr_fx.ingest              # incremental
    uv run python -m myr_fx.ingest --full       # refetch everything since 2006
    uv run python -m myr_fx.ingest --business-day-only   # used by the daily cron
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from myr_fx import db, sources
from myr_fx.bizdays import is_my_business_day
from myr_fx.validate import flag_bad_history, validate_fx, validate_opr

log = logging.getLogger("ingest")


def months_between(start: tuple[int, int], end: tuple[int, int]) -> Iterator[tuple[int, int]]:
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def run(
    db_path: Path | str = db.DB_PATH,
    data_dir: Path = db.DATA_DIR,
    full: bool = False,
    today: date | None = None,
    fetch_fx: Callable[..., list[dict]] = sources.fetch_fx_month,
    fetch_opr: Callable[..., list[dict]] = sources.fetch_opr_year,
    fetch_macro: Callable[..., list[dict]] | None = sources.fetch_fred,
    pause: float = 0.15,
) -> dict[str, int]:
    today = today or date.today()
    con = db.connect(db_path)
    if not full and db.count(con, "fx_rates") == 0:
        db.load_csv(con, data_dir)
    before_fx, before_opr = db.count(con, "fx_rates"), db.count(con, "opr")

    http = requests.Session()
    for ccy in sources.CURRENCIES:
        last = db.scalar(con, "SELECT max(date) FROM fx_rates WHERE currency = ?", [ccy])
        start = sources.FX_START if (full or last is None) else (last.year, last.month)
        rows: list[dict] = []
        for y, m in months_between(start, (today.year, today.month)):
            rows += fetch_fx(http, ccy, y, m)
            time.sleep(pause)
        clean = validate_fx(rows, today=today)
        db.upsert_fx(con, clean)
        log.info("%s: fetched %d rows from %d-%02d", ccy, len(clean), *start)

    # cross-row checks need the whole history, not just this batch
    db.delete_fx(con, flag_bad_history(con.execute("SELECT * FROM fx_rates").df()))

    last_opr = db.scalar(con, "SELECT max(date) FROM opr")
    first_year = sources.OPR_START_YEAR if (full or last_opr is None) else last_opr.year
    opr_rows: list[dict] = []
    for y in range(first_year, today.year + 1):
        opr_rows += fetch_opr(http, y)
        time.sleep(pause)
    db.upsert_opr(con, validate_opr(opr_rows))

    # macro context is best-effort: a FRED outage must not block the BNM update
    if fetch_macro is not None:
        for sid in sources.FRED_SERIES:
            try:
                rows = pd.DataFrame(fetch_macro(http, sid))
                if not rows.empty:
                    rows["date"] = pd.to_datetime(rows["date"]).dt.date
                    db.upsert_macro(con, rows)
            except Exception as exc:  # noqa: BLE001
                log.warning("FRED %s failed: %s", sid, exc)

    summary = {
        "fx_rows": db.count(con, "fx_rates"),
        "fx_new": db.count(con, "fx_rates") - before_fx,
        "opr_rows": db.count(con, "opr"),
        "opr_new": db.count(con, "opr") - before_opr,
    }
    db.export_csv(con, data_dir)
    con.close()
    log.info("done: %s", summary)
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--full", action="store_true", help="refetch full history")
    p.add_argument(
        "--business-day-only",
        action="store_true",
        help="exit early on Malaysian weekends/public holidays",
    )
    p.add_argument("--db", default=str(db.DB_PATH))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.business_day_only and not is_my_business_day(date.today()):
        log.info("not a Malaysian business day; skipping")
        return
    run(db_path=args.db, full=args.full)


if __name__ == "__main__":
    main()
