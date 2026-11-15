"""Kiểm định ngoài mẫu trên dữ liệu tổng hợp: thanh khoản mỗi mã ổn định theo thời gian, nên
Score tại t phải xếp đúng thanh khoản của 20 phiên sau."""
import numpy as np
import pandas as pd
import pytest

from liquisense.snapshot import build_history_table
from liquisense.validation import (
    alert_follow_up, liquidation_check, score_out_of_sample, summarize_alerts, summarize_liquidation,
)


@pytest.fixture(scope="module")
def table():
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2025-01-02", periods=130).date
    rows = []
    for i in range(40):
        size = np.exp(rng.normal(0, 1.2))                  # quy mô thanh khoản cố định của mã
        price = 20_000.0
        for d in dates:
            ret = rng.normal(0, 0.02 / np.sqrt(size))
            price *= 1 + ret
            volume = max(0.0, rng.lognormal(np.log(200_000 * size), 0.4))
            half = price * (0.004 / np.sqrt(size) + abs(ret))
            rows.append({"date": d, "symbol": f"M{i:02d}", "board": "HOSE", "icb_name": "Ngành",
                         "open": price, "high": price + half, "low": price - half, "close": price,
                         "volume": volume, "value": volume * price, "event_flag": False})
    return build_history_table(pd.DataFrame(rows))


def test_score_predicts_future_liquidity(table):
    result = score_out_of_sample(table)
    assert len(result) >= 3
    assert result["rho_score"].mean() > 0.7
    assert result["rho_adv"].mean() > 0.7
    assert (result["spread_top"] < result["spread_bottom"]).all()


def test_liquidation_check_counts_sessions(table):
    detail = liquidation_check(table, sizes=(0.5,))
    assert set(detail["predicted"]) == {3}               # 50% ADV / 20% mỗi phiên = 2,5 → 3 phiên
    summary = summarize_liquidation(detail)
    assert summary["median_realized"].between(2, 4).all()
    assert summary["on_time"].between(0, 1).all()


def test_alert_follow_up_runs_and_summarizes(table):
    detail = alert_follow_up(table, baseline=40)
    assert not detail.empty and set(detail["level"]) <= {"Đỏ", "Vàng", "Bất thường", "Không cảnh báo"}
    summary = summarize_alerts(detail)
    assert "Không cảnh báo" in set(summary["level"])
    assert summary.set_index("level").loc["Không cảnh báo", "lift"] == pytest.approx(1.0)


def test_alert_follow_up_handles_several_alerts_per_symbol(table, monkeypatch):
    import liquisense.validation as v
    fake = pd.DataFrame({"symbol": ["M00", "M00", "M01"], "severity": ["Vang", "Do", "Thong bao"]})
    monkeypatch.setattr(v, "alerts_at", lambda _t, _d: fake)
    detail = v.alert_follow_up(table, baseline=40)
    first = detail[detail["origin"].eq(detail["origin"].min())].set_index("symbol")["level"]
    assert first["M00"] == "Đỏ" and first["M01"] == "Bất thường"
