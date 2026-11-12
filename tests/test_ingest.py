import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from myr_fx import db, ingest, sources
from myr_fx.bizdays import is_my_business_day
from myr_fx.validate import flag_bad_history, validate_fx, validate_opr

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_parse_fx_month_list():
    rows = sources.parse_fx(load("fx_usd_month.json"))
    assert len(rows) > 10
    assert rows[0]["currency"] == "USD" and rows[0]["unit"] == 1
    assert rows[0]["date"] == "2021-01-04"


def test_parse_fx_latest_single_object_and_unit_100():
    rows = sources.parse_fx(load("fx_idr_latest.json"))
    assert len(rows) == 1 and rows[0]["unit"] == 100


def test_parse_fx_empty():
    assert sources.parse_fx(load("fx_empty.json")) == []
    assert sources.parse_fx({"data": []}) == []


def test_parse_opr():
    rows = sources.parse_opr(load("opr_2020.json"))
    assert {r["new_opr_level"] for r in rows} >= {1.75, 2.75}


def test_validate_fx_rules():
    raw = [
        {
            "date": "2024-01-02",
            "currency": "USD",
            "unit": 1,
            "buying": 4.6,
            "selling": 4.62,
            "middle": None,
        },  # fill middle
        {
            "date": "2024-01-02",
            "currency": "USD",
            "unit": 1,
            "buying": 4.6,
            "selling": 4.62,
            "middle": 4.61,
        },  # duplicate
        {
            "date": "2024-01-03",
            "currency": "USD",
            "unit": 1,
            "buying": -1,
            "selling": -1,
            "middle": -1,
        },  # negative
        {
            "date": "2024-01-04",
            "currency": "USD",
            "unit": 1,
            "buying": 4.7,
            "selling": 4.6,
            "middle": 4.65,
        },  # crossed
        {
            "date": "2099-01-01",
            "currency": "USD",
            "unit": 1,
            "buying": 4,
            "selling": 4,
            "middle": 4,
        },  # future
        {
            "date": "not a date",
            "currency": "USD",
            "unit": 1,
            "buying": 4,
            "selling": 4,
            "middle": 4,
        },
    ]
    out = validate_fx(raw, today=date(2024, 6, 1))
    assert len(out) == 1
    assert out.loc[0, "middle"] == pytest.approx(4.61)


def test_validate_fx_missing_columns():
    with pytest.raises(ValueError):
        validate_fx(pd.DataFrame({"date": ["2024-01-01"]}))


def test_validate_opr_drops_bad_level():
    out = validate_opr(
        [
            {"date": "2020-01-22", "change_in_opr": -0.25, "new_opr_level": 2.75},
            {"date": "2020-02-01", "change_in_opr": 0, "new_opr_level": 99},
        ]
    )
    assert len(out) == 1


def test_months_between_crosses_year():
    assert list(ingest.months_between((2023, 11), (2024, 2))) == [
        (2023, 11),
        (2023, 12),
        (2024, 1),
        (2024, 2),
    ]


def test_business_days():
    assert not is_my_business_day(date(2024, 8, 31))  # Merdeka (Saturday anyway)
    assert not is_my_business_day(date(2025, 3, 31))  # Hari Raya Aidilfitri
    assert not is_my_business_day(date(2024, 2, 1))  # Federal Territory Day (KL only)
    assert is_my_business_day(date(2024, 3, 5))


def _fake_fx(http, ccy, y, m):
    days = [f"{y}-{m:02d}-{d:02d}" for d in (2, 3)]
    unit = 100 if ccy in ("JPY", "THB", "IDR") else 1
    return [
        {"date": d, "currency": ccy, "unit": unit, "buying": 1.0, "selling": 1.2, "middle": 1.1}
        for d in days
    ]


def _fake_opr(http, y):
    return [{"date": f"{y}-01-20", "change_in_opr": 0.0, "new_opr_level": 3.0}]


def test_run_is_idempotent_and_csv_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "FX_START", (2024, 1))
    monkeypatch.setattr(sources, "OPR_START_YEAR", 2024)
    kw = dict(
        today=date(2024, 3, 15),
        fetch_fx=_fake_fx,
        fetch_opr=_fake_opr,
        pause=0,
        fetch_macro=lambda http, sid: [{"date": "2024-01-02", "series": sid, "value": 80.0}],
    )

    first = ingest.run(db_path=tmp_path / "a.duckdb", data_dir=tmp_path, **kw)
    # fake days are the 2nd+3rd of Jan-Mar 2024; only 3 of those 6 are weekdays
    assert first["fx_rows"] == 8 * 3 and first["opr_rows"] == 1
    csv_1 = (tmp_path / db.FX_CSV).read_text()

    second = ingest.run(db_path=tmp_path / "a.duckdb", data_dir=tmp_path, **kw)
    assert second["fx_new"] == 0 and second["opr_new"] == 0
    assert (tmp_path / db.FX_CSV).read_text() == csv_1

    # a fresh DB seeded from CSV gives the same table
    con = db.ensure_db(tmp_path / "b.duckdb", data_dir=tmp_path)
    assert db.count(con, "fx_rates") == first["fx_rows"]
    assert db.count(con, "macro") == len(sources.FRED_SERIES)
    jpy = db.scalar(con, "SELECT rate FROM fx_daily WHERE currency='JPY' LIMIT 1")
    assert jpy == pytest.approx(0.011)  # per-100 quote normalised to per-unit


def test_flag_bad_history_catches_weekend_and_two_day_spike():
    dates = pd.bdate_range("2006-12-18", "2007-01-12")
    df = pd.DataFrame({"date": dates.date, "currency": "JPY", "middle": 2.97})
    df.loc[df["date"].astype(str).isin(["2007-01-01", "2007-01-02"]), "middle"] = 0.0297
    sat = pd.DataFrame({"date": [date(2006, 12, 30)], "currency": ["JPY"], "middle": [2.97]})
    bad = flag_bad_history(pd.concat([df, sat], ignore_index=True))
    assert sorted(map(str, bad["date"])) == ["2006-12-30", "2007-01-01", "2007-01-02"]


def test_flag_bad_history_keeps_real_moves():
    dates = pd.bdate_range("2024-07-22", periods=20)
    mid = [4.6] * 10 + [4.4] * 10  # a sharp but genuine 4% level shift
    df = pd.DataFrame({"date": dates.date, "currency": "USD", "middle": mid})
    assert flag_bad_history(df).empty


def test_flag_bad_history_snap_back_print():
    dates = pd.bdate_range("2007-02-26", periods=10)
    mid = [9.9] * 10
    mid[5] = 10.59  # +7% for one day, then straight back
    df = pd.DataFrame({"date": dates.date, "currency": "THB", "middle": mid})
    assert list(flag_bad_history(df)["date"]) == [dates[5].date()]
