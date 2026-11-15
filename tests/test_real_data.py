"""Kiểm thử trên DỮ LIỆU THẬT của SSI (trích từ kho, tests/fixtures/ssi_adjusted_sample.csv).

Nến SSI là giá đã điều chỉnh theo sự kiện quyền, còn giá tham chiếu/trần/sàn là giá gốc. Các bài này
bắt đúng lỗi từng có: tính lợi suất bằng close / ref_px trộn hai thang giá.
"""

from pathlib import Path

import pandas as pd
import pytest

from liquisense.finance import adjusted_returns, amihud_series, calculate_symbol_history, limit_flags, price_scale

SAMPLE = Path(__file__).parent / "fixtures" / "ssi_adjusted_sample.csv"


def _symbol(symbol: str) -> pd.DataFrame:
    frame = pd.read_csv(SAMPLE, parse_dates=["date"])
    frame["date"] = frame["date"].dt.date
    return frame[frame["symbol"] == symbol].sort_values("date").reset_index(drop=True)


def _on(frame: pd.DataFrame, series: pd.Series, day: str) -> float:
    return float(series[frame["date"].astype(str) == day].iloc[0])


def test_fpt_2021_adjusted_close_is_not_divided_by_raw_reference():
    fpt = _symbol("FPT")
    row = fpt[fpt["date"].astype(str) == "2021-11-16"].iloc[0]
    assert row["close"] / row["ref_px"] - 1 < -0.5               # cách tính cũ: −54%, sai
    returns = adjusted_returns(fpt)
    assert _on(fpt, returns, "2021-11-16") == pytest.approx(44742.513 / 44287.35 - 1, rel=1e-9)  # +1,03%
    assert returns.abs().max() < 0.07                            # HOSE biên độ ±7%: không có ngày nào vượt


def test_pmj_return_on_2026_10_23_is_minus_7_percent():
    pmj = _symbol("PMJ")
    returns = adjusted_returns(pmj)
    assert _on(pmj, returns, "2026-10-23") == pytest.approx(-0.0714, abs=5e-4)   # thực tế −7%, không phải −44%
    amihud = amihud_series(pmj)
    assert amihud.dropna().ge(0).all() and _on(pmj, amihud, "2026-10-23") > 0


def test_limit_days_found_on_adjusted_prices_with_raw_band():
    anv = _symbol("ANV")
    scale = price_scale(anv)
    assert _on(anv, scale, "2026-10-02") == pytest.approx(0.9459, abs=2e-3)     # k = giá điều chỉnh / giá gốc
    at_ceiling, at_floor = limit_flags(anv)
    assert _on(anv, at_ceiling, "2026-10-02") and _on(anv, at_ceiling, "2026-10-08")   # 16.080/0,9459 = 17.000 = trần
    assert not _on(anv, at_ceiling, "2026-10-05")
    assert not at_floor.any()
    assert not (anv["close"] == anv["ceil_px"]).any()            # so trực tiếp sẽ bỏ sót cả hai phiên trần


def test_history_volatility_uses_adjusted_returns():
    fpt = _symbol("FPT")
    history = calculate_symbol_history(fpt)
    assert history["daily_volatility"].dropna().iloc[-1] < 0.03  # σ thật của FPT ~1,3%; cách cũ cho ~0,5–1,0
