from datetime import date, timedelta

import numpy as np
import pandas as pd

from liquisense.analytics import latest_alerts
from liquisense.finance import latest_metrics
from liquisense.snapshot import alerts_at, build_history_table, metrics_at, metrics_for_range


def _bars(days=90, symbols=("AAA", "BBB", "CCC", "DDD")):
    rng = np.random.default_rng(7)
    rows = []
    start = date(2026, 1, 1)
    for s_i, symbol in enumerate(symbols):
        price = 10_000 + 2_000 * s_i
        for d in range(days):
            day = start + timedelta(days=d)
            if day.weekday() >= 5:
                continue
            ref = price
            price = max(1_000, price * (1 + rng.normal(0, 0.02)))
            volume = 0 if (symbol == "DDD" and d % 9 == 0) else int(rng.integers(10_000, 500_000))
            rows.append({
                "date": day, "symbol": symbol, "board": "HOSE", "icb_name": "Ngành A",
                "open": price, "high": price * 1.01, "low": price * 0.99, "close": price,
                "volume": volume, "value": volume * price, "listed_shares": 1_000_000,
                "ref_px": ref, "ceil_px": ref * 1.07, "floor_px": ref * 0.93, "event_flag": False,
            })
    return pd.DataFrame(rows)


def test_fast_snapshot_matches_direct_computation():
    bars = _bars()
    table = build_history_table(bars)
    as_of = sorted(set(bars["date"]))[-5]
    fast = metrics_at(table, as_of).set_index("symbol")
    slow = latest_metrics(bars[bars["date"] <= as_of]).set_index("symbol")
    for column in ("score", "spread", "amihud", "adv_value", "zero_days"):
        assert np.allclose(fast[column], slow.loc[fast.index, column], rtol=1e-4, equal_nan=True)
    fast_alerts = alerts_at(table, as_of)
    slow_alerts = latest_alerts(bars[bars["date"] <= as_of])
    if not slow_alerts.empty:
        slow_alerts = slow_alerts[pd.to_datetime(slow_alerts["date"]).dt.date == as_of]
    assert len(fast_alerts) == len(slow_alerts)


def test_range_metrics_use_only_the_selected_window():
    bars = _bars()
    table = build_history_table(bars)
    dates = sorted(set(bars["date"]))
    start, end = dates[-25], dates[-1]
    result = metrics_for_range(table, start, end).set_index("symbol")
    window = bars[(bars["date"] >= start) & (bars["date"] <= end)]
    expected = window.groupby("symbol")["volume"].mean()
    assert np.allclose(result.loc[expected.index, "adv_volume"], expected, rtol=1e-4)
    assert result["status"].eq("Du du lieu").all()
