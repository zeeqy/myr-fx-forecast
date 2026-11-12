import numpy as np
import pandas as pd
import pytest

from myr_fx import forecast as fc


def _series(n=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.Series(4 + np.cumsum(rng.normal(0, 0.01, n)), index=idx)


def test_naive_band_widens():
    out = fc.naive(_series(), 21)
    assert len(out) == 21
    assert (out["mean"] == out["mean"].iloc[0]).all()
    width = out["upper"] - out["lower"]
    assert width.is_monotonic_increasing


def test_fold_origins_no_leakage():
    origins = fc.fold_origins(n=1000, n_folds=5, step=21, h=21, min_train=250)
    assert origins[-1] == 1000 - 21  # last window ends at the final observation
    assert all(b - a == 21 for a, b in zip(origins, origins[1:], strict=False))


def test_backtest_and_score_on_random_walk():
    s = _series()
    res = fc.backtest(s, models={"naive": fc.naive}, n_folds=3, train_days=250)
    assert set(res["step"]) == set(range(1, 22))
    # test dates are always after the training window
    assert (res["date"] > res["origin"]).sum() == len(res) - 3  # step 1 date == origin
    tbl = fc.score(res)
    assert tbl.loc["naive", "MAE_vs_naive"] == pytest.approx(1.0)
    assert 0 <= tbl.loc["naive", "coverage95_%"] <= 100


def test_score_perfect_model():
    df = pd.DataFrame(
        {
            "model": "m",
            "step": [1, 2],
            "actual": [4.0, 4.1],
            "mean": [4.0, 4.1],
            "lower": [3.9, 4.0],
            "upper": [4.1, 4.2],
        }
    )
    t = fc.score(df)
    assert t.loc["m", "MAE"] == 0 and t.loc["m", "coverage95_%"] == 100


def test_future_dates_are_business_days():
    d = fc.future_dates(pd.Timestamp("2024-03-08"), 3)  # Friday
    assert list(d.strftime("%a")) == ["Mon", "Tue", "Wed"]
