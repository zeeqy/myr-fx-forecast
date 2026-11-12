"""DuckDB storage. CSV snapshots in data/ are the committed source of truth;
the .duckdb file is a local cache rebuilt from them (binary files make noisy git history)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "fx.duckdb"
FX_CSV = "fx_rates.csv"
OPR_CSV = "opr.csv"
MACRO_CSV = "macro.csv"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fx_rates (
    date     DATE    NOT NULL,
    currency VARCHAR NOT NULL,
    unit     INTEGER NOT NULL,
    buying   DOUBLE,
    selling  DOUBLE,
    middle   DOUBLE  NOT NULL,
    PRIMARY KEY (date, currency)
);
CREATE TABLE IF NOT EXISTS opr (
    date          DATE PRIMARY KEY,
    change_in_opr DOUBLE,
    new_opr_level DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS macro (
    date   DATE    NOT NULL,
    series VARCHAR NOT NULL,
    value  DOUBLE  NOT NULL,
    PRIMARY KEY (date, series)
);
-- MYR per 1 unit of foreign currency (BNM quotes JPY/THB/IDR per 100 units)
CREATE OR REPLACE VIEW fx_daily AS
SELECT date, currency, middle / unit AS rate, buying / unit AS buying, selling / unit AS selling
FROM fx_rates;
"""


def connect(path: Path | str = DB_PATH, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA).fetchall()
    return con


def upsert_fx(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    if df.empty:
        return
    con.register("incoming_fx", df)
    con.execute(
        "INSERT OR REPLACE INTO fx_rates "
        "SELECT date, currency, unit, buying, selling, middle FROM incoming_fx"
    ).fetchall()
    con.unregister("incoming_fx")


def upsert_opr(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    if df.empty:
        return
    con.register("incoming_opr", df)
    con.execute(
        "INSERT OR REPLACE INTO opr SELECT date, change_in_opr, new_opr_level FROM incoming_opr"
    ).fetchall()
    con.unregister("incoming_opr")


def upsert_macro(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    if df.empty:
        return
    con.register("incoming_macro", df)
    con.execute(
        "INSERT OR REPLACE INTO macro SELECT date, series, value FROM incoming_macro"
    ).fetchall()
    con.unregister("incoming_macro")


def delete_fx(con: duckdb.DuckDBPyConnection, keys: pd.DataFrame) -> None:
    if keys.empty:
        return
    con.register("bad_keys", keys)
    con.execute(
        "DELETE FROM fx_rates USING bad_keys "
        "WHERE fx_rates.date = bad_keys.date AND fx_rates.currency = bad_keys.currency"
    ).fetchall()
    con.unregister("bad_keys")


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    """First value of a query. Uses fetchall(): DuckDB 2.x keeps a connection busy until
    a result is fully consumed, so fetchone() would block the next statement."""
    return con.execute(sql, params or []).fetchall()[0][0]


def count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return scalar(con, f"SELECT count(*) FROM {table}")


def load_csv(con: duckdb.DuckDBPyConnection, data_dir: Path = DATA_DIR) -> None:
    """Seed the database from committed CSV snapshots (if present)."""
    fx, opr = data_dir / FX_CSV, data_dir / OPR_CSV
    if fx.exists():
        upsert_fx(con, pd.read_csv(fx, parse_dates=["date"]).assign(date=lambda d: d.date.dt.date))
    macro = data_dir / MACRO_CSV
    if macro.exists():
        upsert_macro(
            con, pd.read_csv(macro, parse_dates=["date"]).assign(date=lambda d: d.date.dt.date)
        )
    if opr.exists():
        upsert_opr(
            con, pd.read_csv(opr, parse_dates=["date"]).assign(date=lambda d: d.date.dt.date)
        )


def export_csv(con: duckdb.DuckDBPyConnection, data_dir: Path = DATA_DIR) -> None:
    """Write sorted snapshots so daily runs produce small, append-only git diffs."""
    data_dir.mkdir(parents=True, exist_ok=True)
    con.execute("SELECT * FROM fx_rates ORDER BY currency, date").df().to_csv(
        data_dir / FX_CSV, index=False, float_format="%.6f", lineterminator="\n"
    )
    con.execute("SELECT * FROM macro ORDER BY series, date").df().to_csv(
        data_dir / MACRO_CSV, index=False, lineterminator="\n"
    )
    con.execute("SELECT * FROM opr ORDER BY date").df().to_csv(
        data_dir / OPR_CSV, index=False, lineterminator="\n"
    )


def ensure_db(path: Path | str = DB_PATH, data_dir: Path = DATA_DIR) -> duckdb.DuckDBPyConnection:
    """Open the DB, seeding from CSV when empty. Used by the app and notebook."""
    con = connect(path)
    if count(con, "fx_rates") == 0:
        load_csv(con, data_dir)
    return con


def fx_wide(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Rates as a date-indexed frame, one column per currency (MYR per 1 unit)."""
    df = con.execute("SELECT date, currency, rate FROM fx_daily").df()
    wide = df.pivot(index="date", columns="currency", values="rate").sort_index()
    wide.index = pd.to_datetime(wide.index)
    return wide


def opr_frame(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.execute("SELECT * FROM opr ORDER BY date").df()
    df["date"] = pd.to_datetime(df["date"])
    return df


def macro_wide(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.execute("SELECT * FROM macro").df()
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot(index="date", columns="series", values="value").sort_index()
    wide.index = pd.to_datetime(wide.index)
    return wide
