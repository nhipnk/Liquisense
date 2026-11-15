"""Tình huống đặt lệnh lớn, độ nhạy trọng số Score và chèn phiên không có nến (dữ liệu tổng hợp)."""
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from liquisense.finance import WEIGHT_SCENARIOS, score_metrics, score_weight_sensitivity
from liquisense.scenario import order_scenario, scenario_summary
from liquisense.snapshot import fill_missing_sessions


def _row(adv=1_000_000.0):
    return pd.Series({"symbol": "AAA", "close": 20_000.0, "adv_volume": adv, "spread": 0.004,
                      "daily_volatility": 0.02})


def test_large_order_is_split_and_cheaper_per_session():
    sc = order_scenario(_row(), 500_000, side="Bán")
    plans = sc.plans.set_index("plan")
    assert plans.loc["Dồn trong 1 phiên", "sessions"] == 1
    assert plans.loc["Cơ sở · 20% ADV", "sessions"] == 3          # 500k / 200k = 2,5 → 3 phiên
    assert plans.loc["Thận trọng · 10% ADV", "sessions"] == 5
    assert plans.loc["Cơ sở · 20% ADV", "last_session"] == "T+2"
    assert plans.loc["Cơ sở · 20% ADV", "settled"] == "T+4"
    # Chia nhỏ rẻ hơn dồn một phiên, nhưng rủi ro giá khi chờ lớn hơn.
    assert plans.loc["Thận trọng · 10% ADV", "base_pct"] < plans.loc["Dồn trong 1 phiên", "base_pct"]
    assert plans.loc["Thận trọng · 10% ADV", "price_risk"] > plans.loc["Dồn trong 1 phiên", "price_risk"]
    impact = 0.02 * math.sqrt(0.2)
    assert plans.loc["Cơ sở · 20% ADV", "base_pct"] == pytest.approx(0.002 + impact + 0.0015 + 0.001)
    text = scenario_summary(sc)
    assert "500.000" in text and "3 phiên" in text and "T+4" in text


def test_small_order_single_session():
    sc = order_scenario(_row(10_000_000), 500_000)
    assert len(sc.plans) == 1 and "phiên T" in scenario_summary(sc)


def test_scenario_rejects_missing_data():
    row = _row(); row["adv_volume"] = np.nan
    with pytest.raises(ValueError):
        order_scenario(row, 500_000)
    with pytest.raises(ValueError):
        order_scenario(_row(), 0)


def _universe(n=60, seed=1):
    rng = np.random.default_rng(seed)
    size = rng.lognormal(0, 1.5, n)
    return pd.DataFrame({
        "symbol": [f"M{i:02d}" for i in range(n)], "status": "Du du lieu",
        "spread": 0.01 / size * rng.uniform(0.7, 1.3, n), "amihud": 1 / size * rng.uniform(0.7, 1.3, n),
        "adv_value": size * 1e9, "zero_days": np.where(size < 0.3, 0.2, 0.0),
    })


def test_weight_sensitivity_reports_every_scenario():
    result = score_weight_sensitivity(_universe())
    assert list(result["scenario"]) == list(WEIGHT_SCENARIOS)
    current = result.iloc[0]
    assert current["spearman"] == pytest.approx(1.0) and current["top_overlap"] == 1.0
    assert (result["spearman"] > 0.8).all()        # các chỉ số cùng phản ánh "quy mô" nên xếp hạng bền


def test_custom_weights_change_score():
    frame = _universe()
    a = score_metrics(frame).set_index("symbol")["score"]
    b = score_metrics(frame, {"spread": 1, "amihud": 0, "adv_value": 0, "zero_days": 0}).set_index("symbol")["score"]
    assert not np.allclose(a.sort_index(), b.sort_index())


def test_fill_missing_sessions_marks_no_trade_days():
    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(5)]
    calendar = pd.Index(days)
    bars = pd.DataFrame({"date": [days[0], days[2], days[4]], "symbol": "AAA", "board": "HOSE",
                         "icb_name": "Ngành", "close": [10.0, 11.0, 12.0], "volume": [100.0, 200.0, 300.0],
                         "value": [1e3, 2e3, 3e3], "event_flag": False})
    full = fill_missing_sessions(bars, calendar)
    assert len(full) == 5
    assert full["no_bar"].tolist() == [False, True, False, True, False]
    assert full.loc[full["no_bar"], "volume"].eq(0).all()
    assert full["symbol"].eq("AAA").all() and full["event_flag"].dtype == bool
    assert full.loc[1, "close"] != full.loc[1, "close"]   # không nội suy giá (NaN)


def test_limit_locked_symbol_is_separate_status_and_red_alert():
    from liquisense.snapshot import alerts_at, build_history_table, metrics_at
    days = list(pd.bdate_range("2026-01-05", periods=30).date)
    rows = []
    for name, locked in (("KKK", True), ("NNN", False)):
        price = 10_000.0
        for i, d in enumerate(days):
            ref = price
            floor = round(ref * 0.93, -1)
            if locked and i >= 15:          # 15 phiên cuối đóng cửa ở giá sàn, giá cao = giá thấp
                price = floor
                high = low = price
            else:
                price = ref * (1.01 if i % 2 else 0.99)
                high, low = price * 1.01, price * 0.99
            rows.append({"date": d, "symbol": name, "board": "HOSE", "icb_name": "Ngành", "open": price,
                         "high": high, "low": low, "close": price, "volume": 100_000.0, "value": 1e9,
                         "ref_px": ref, "ceil_px": round(ref * 1.07, -1), "floor_px": floor, "event_flag": False})
    table = build_history_table(pd.DataFrame(rows))
    m = metrics_at(table, days[-1]).set_index("symbol")
    assert m.loc["KKK", "status"] == "Tran san lien tuc" and np.isnan(m.loc["KKK", "score"])
    assert m.loc["KKK", "floor_days"] >= 14
    assert m.loc["NNN", "status"] == "Du du lieu"
    alerts = alerts_at(table, days[-1])
    lock = alerts[alerts["type"].eq("Ket tran san")]
    assert list(lock["symbol"]) == ["KKK"] and lock["severity"].eq("Do").all()
    assert "giá sàn" in lock["reason"].iloc[0]
