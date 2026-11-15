import numpy as np
import pandas as pd

from liquisense.insights import (
    THRESHOLDS,
    cost_insights,
    market_insights,
    portfolio_insights,
    split_scenario,
    stock_insights,
)

BUY_SELL_WORDS = ("nên mua", "nên bán", "khuyến nghị mua", "khuyến nghị bán")


def _metrics(n=40):
    rng = np.random.default_rng(1)
    return pd.DataFrame({
        "symbol": [f"M{i:02d}" for i in range(n)],
        "board": ["HOSE"] * (n // 2) + ["HNX"] * (n - n // 2),
        "sector": ["Ngân hàng"] * n,
        "score": np.r_[rng.uniform(60, 90, n // 2), rng.uniform(20, 50, n - n // 2)],
        "spread": rng.uniform(0.001, 0.02, n),
        "zero_days": [0.0] * n,
        "status": ["Du du lieu"] * n,
    })


def _text(items):
    return " ".join(i.text for i in items).lower()


def test_market_insights_describe_activity_and_board_gap():
    metrics = _metrics()
    alerts = pd.DataFrame({"symbol": ["M01", "M02", "M03"], "severity": ["Do"] * 3})
    items = market_insights(metrics, alerts, scope="toàn thị trường", day_ratio=1.26)
    text = _text(items)
    assert "cao hơn bình thường" in text
    assert "hnx kém thanh khoản hơn hose" in text
    assert "ngân hàng" in text
    assert not any(word in text for word in BUY_SELL_WORDS)


def test_stock_insights_flag_top_group_and_unreliable_spread():
    metrics = _metrics()
    best = metrics.loc[metrics["score"].idxmax()]
    history = pd.DataFrame({
        "spread_daily": [0.0] * 15 + [0.01] * 5,
        "value": [1e9] * 20, "volume": [1000] * 20,
    })
    text = _text(stock_insights(best["symbol"], best, metrics, history, "Do"))
    assert "tốt nhất" in text
    assert "kém tin cậy" in text
    assert "cảnh báo đỏ" in text


def test_split_scenario_reduces_cost_for_large_orders():
    k, before, after = split_scenario(0.35, half=0.002, sigma=0.02, fixed=0.0015)
    assert k == 4 and after < before
    items = cost_insights(symbol="AAA", ratio=0.35, half=0.002, sigma=0.02, fixed=0.0015,
                          base_total=before, impact=0.02 * 0.35 ** 0.5, window=20,
                          window_costs={10: 0.015, 20: 0.0135, 60: 0.012})
    text = _text(items)
    assert "4 phiên" in text and "tác động giá" in text and "dao động" in text


def test_portfolio_insights_find_stuck_positions():
    book = pd.DataFrame({
        "symbol": ["AAA", "BBB"], "qty": [150, 1000], "market": [1e8, 5e8],
        "d20": [0.5, 6.0],
    })
    text = _text(portfolio_insights(book, {"BBB": "Do"}))
    assert f"hơn {THRESHOLDS['stuck_days']} phiên" in text
    assert "bbb" in text and "lô lẻ" in text and "mã đỏ" in text


def test_sector_monthly_flow_and_insights():
    from datetime import date

    import pandas as pd

    from liquisense.insights import sector_flow_insights
    from liquisense.sector_flow import sector_monthly, sector_trend

    days = pd.bdate_range("2026-08-03", "2026-10-30")
    rows = []
    for d in days:
        for sym, sector, base in (("AAA", "Ngân hàng", 100.0), ("BBB", "Thép", 50.0)):
            boost = 2.0 if (sector == "Ngân hàng" and d.month == 10) else 1.0
            rows.append({"date": d.date(), "symbol": sym, "board": "HOSE", "sector": sector,
                         "value": base * boost, "spread_daily": 0.01})
    table = pd.DataFrame(rows)
    result = sector_monthly(table, date(2026, 10, 30), months=12)
    assert list(result["flow"].index) == ["Ngân hàng", "Thép"]
    assert abs(result["flow"].loc["Ngân hàng"].iloc[-1] - 1.5) < 1e-9     # 200 / TB(100,100,200)
    assert abs(result["flow"].loc["Thép"].iloc[-1] - 1.0) < 1e-9
    texts = " ".join(i.text for i in sector_flow_insights(result))
    assert "Ngân hàng" in texts
    trend = sector_trend(table, "Thép", date(2026, 10, 30))
    assert len(trend) == 3 and abs(trend["spread"].iloc[-1] - 0.01) < 1e-12


def test_alert_detail_is_concrete():
    from liquisense.analytics import alert_detail

    text = alert_detail("spread", 0.0085, 0.0032, 2.84)
    assert "0,85%" in text and "0,32%" in text and "gấp 2,7 lần" in text and "2,8σ" in text
    adv = alert_detail("adv_value", 4e8, 1e9, -3.1)
    assert "400 triệu/phiên" in adv and "giảm 60%" in adv
