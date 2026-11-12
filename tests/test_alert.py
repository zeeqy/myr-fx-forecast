import pandas as pd

from myr_fx.alert import last_move, message


def test_alert_threshold():
    s = pd.Series([4.00, 4.05], index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    day, rate, chg = last_move(s)
    assert round(chg, 4) == 0.0125
    assert "weakened" in message("USD/MYR", day, rate, chg)
    assert message("USD/MYR", day, rate, 0.004) is None
