from datetime import date

import numpy as np
import pandas as pd

from liquisense.report import ReportContext, build_stock_report, cost_table


def _data():
    dates = pd.bdate_range("2026-06-01", periods=80)
    rng = np.random.default_rng(1)
    history = pd.DataFrame({
        "date": dates, "symbol": "AAA", "close": 20000.0,
        "volume": rng.integers(50_000, 150_000, 80).astype(float),
        "spread_daily": rng.uniform(0, 0.02, 80), "amihud_daily": rng.uniform(1e-4, 1e-3, 80),
    })
    history["value"] = history["volume"] * 20000
    history["spread"] = history["spread_daily"].rolling(20, min_periods=10).mean()
    history["amihud"] = history["amihud_daily"].rolling(20, min_periods=10).mean()
    history["adv_value"] = history["value"].rolling(20, min_periods=10).mean()
    history["adv_volume"] = history["volume"].rolling(20, min_periods=10).mean()
    rows = []
    for i, sym in enumerate(["AAA", "BBB", "CCC", "DDD"]):
        rows.append({"symbol": sym, "board": "HOSE", "sector": "Ngân hàng", "status": "Du du lieu",
                     "score": 80 - i * 15, "spread": 0.005 + i * 0.003, "amihud": 1e-4 * (i + 1),
                     "adv_value": 2e10 / (i + 1), "adv_volume": 1e6 / (i + 1), "daily_volatility": 0.02,
                     "zero_days": 0.0, "turnover": 0.002, "close": 20000.0})
    return history, pd.DataFrame(rows)


def test_cost_table_grows_with_size():
    _, metrics = _data()
    table = cost_table(metrics.iloc[0], ReportContext("AAA", "x", date(2026, 6, 1), date(2026, 9, 18), date(2026, 9, 18)))
    assert list(table["pct_adv"]) == [0.01, 0.05, 0.10, 0.20, 0.50]
    assert table["base"].is_monotonic_increasing


def test_build_pdf_vietnamese():
    history, metrics = _data()
    ctx = ReportContext("AAA", "cửa sổ 20 phiên đến 18/09/2026", date(2026, 6, 1), date(2026, 9, 18), date(2026, 9, 18))
    pdf = build_stock_report(metrics.iloc[0], metrics, history, "Vang", ctx)
    assert pdf.startswith(b"%PDF") and len(pdf) > 20_000

