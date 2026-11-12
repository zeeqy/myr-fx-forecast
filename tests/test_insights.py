import numpy as np
import pandas as pd
import pytest

from myr_fx import insights as ins

IDX = pd.bdate_range("2024-01-01", periods=60)


def test_strength_index_direction():
    # USD rate rises 10% (MYR weakens), SGD flat -> index = 100 / sqrt(1.1)
    wide = pd.DataFrame({"USD": np.linspace(4.0, 4.4, 60), "SGD": 3.0}, index=IDX)
    idx = ins.strength_index(wide)
    assert idx.iloc[0] == pytest.approx(100)
    assert idx.iloc[-1] == pytest.approx(100 / np.sqrt(1.1))


def test_rolling_vol_zero_for_constant():
    wide = pd.DataFrame({"USD": 4.0}, index=IDX)
    assert ins.rolling_vol(wide).dropna()["USD"].eq(0).all()


def test_event_window_rebases_to_zero():
    s = pd.Series(np.arange(1, 61, dtype=float), index=IDX)
    w = ins.event_window(s, [IDX[30], IDX[1]], before=5, after=5)  # IDX[1] is too early
    assert list(w.columns) == [IDX[30]]
    assert w.loc[0].iloc[0] == 0
    assert w.loc[5].iloc[0] > 0


def test_convert_advice_labels():
    falling = pd.Series(np.linspace(5, 4, 90), index=pd.bdate_range("2024-01-01", periods=90))
    assert ins.convert_advice(falling)["label"] == "good"
    assert ins.convert_advice(falling[::-1].set_axis(falling.index))["label"] == "poor"


def test_opr_changes_filters_holds():
    opr = pd.DataFrame({"date": IDX[:3], "change_in_opr": [0, -0.25, 0], "new_opr_level": 3})
    assert len(ins.opr_changes(opr)) == 1


def test_weekday_effect_has_five_days():
    s = pd.Series(np.random.default_rng(1).normal(4, 0.01, 60), index=IDX)
    assert len(ins.weekday_effect(s)) == 5
