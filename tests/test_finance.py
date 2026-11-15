import numpy as np
import pandas as pd
import pytest

from liquisense.analytics import latest_alerts
from liquisense.data.sample import make_sample_bars
from liquisense.finance import (
    amihud_series,
    calculate_symbol_history,
    corwin_schultz_series,
    days_to_liquidate,
    estimate_cost,
    latest_metrics,
    robust_zscore,
)


def test_corwin_schultz_constant_range_is_zero_after_first_observation():
    bars = pd.DataFrame({
        "high": [10.0, 10.0, 10.0],
        "low": [10.0, 10.0, 10.0],
        "close": [10.0, 10.0, 10.0],
        "volume": [100, 100, 100],
    })
    result = corwin_schultz_series(bars)
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == pytest.approx(0.0)
    assert result.iloc[2] == pytest.approx(0.0)


def test_corwin_schultz_does_not_treat_no_trade_day_as_zero_spread():
    bars = pd.DataFrame({
        "high": [10.0, 10.0, 10.0],
        "low": [10.0, 10.0, 10.0],
        "close": [10.0, 10.0, 10.0],
        "volume": [0, 100, 100],
    })
    result = corwin_schultz_series(bars)
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == pytest.approx(0.0)


def test_corwin_schultz_excludes_limit_and_corporate_action_days():
    bars = pd.DataFrame({
        "high": [10.5, 10.6, 10.8, 10.9],
        "low": [9.5, 9.6, 9.8, 9.9],
        "close": [10.0, 10.5, 10.1, 10.2],
        "ref_px": [None, 10.0, None, None],
        "ceil_px": [None, 10.5, None, None],     # biên độ +5%, phiên 2 tăng đúng 5% → chạm trần
        "floor_px": [None, 9.5, None, None],
        "event_flag": [False, False, True, False],
        "volume": [100, 100, 100, 100],
    })
    result = corwin_schultz_series(bars)
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])
    assert pd.isna(result.iloc[3])


def test_amihud_uses_value_in_vnd_and_skips_zero_value_and_corporate_action():
    bars = pd.DataFrame({
        "close": [100.0, 110.0, 100.0, 105.0],
        "ref_px": [100.0, 100.0, 100.0, 100.0],      # ref_px không còn được dùng để tính lợi suất
        "value": [1_000_000_000.0, 1_000_000_000.0, 0.0, 1_000_000_000.0],
        "event_flag": [False, False, False, True],
    })
    result = amihud_series(bars)
    assert pd.isna(result.iloc[0])                   # phiên đầu chưa có giá hôm trước
    assert result.iloc[1] == pytest.approx(0.1)      # |110/100 − 1| / 1 tỷ đồng
    assert pd.isna(result.iloc[2])                   # giá trị giao dịch = 0
    assert pd.isna(result.iloc[3])                   # ngày sự kiện quyền


def test_cost_scenario_includes_sell_tax_only_for_sell():
    common = {
        "quantity": 20_000,
        "price": 20_000,
        "spread": 0.01,
        "daily_volatility": 0.02,
        "adv_volume": 1_000_000,
        "fee_rate": 0.0015,
        "tax_rate": 0.001,
    }
    buy = estimate_cost(**common, side="Mua")
    sell = estimate_cost(**common, side="Bán")
    assert buy["scenarios"][0]["tax_pct"] == 0
    assert sell["scenarios"][0]["tax_pct"] == pytest.approx(0.001)
    assert sell["scenarios"][0]["total_pct"] > buy["scenarios"][0]["total_pct"]
    assert buy["warning"] == "Thap"


def test_cost_accepts_odd_lot_quantity():
    result = estimate_cost(
        quantity=101,
        price=10_000,
        spread=0.01,
        daily_volatility=0.02,
        adv_volume=100_000,
        side="Mua",
        fee_rate=0.0015,
        tax_rate=0.001,
    )
    assert result["quantity"] == 101
    assert result["scenarios"][1]["total_pct"] > 0


def test_robust_zscore_requires_30_observations_and_nonzero_mad():
    assert robust_zscore(3.0, [1.0] * 29) is None
    assert robust_zscore(3.0, [1.0] * 40) is None
    values = np.linspace(1.0, 2.0, 40)
    assert robust_zscore(2.5, values) is not None


def test_sample_generates_metrics_and_scores_without_assigning_zero_to_missing():
    bars = make_sample_bars(days=80)
    metrics = latest_metrics(bars)
    assert len(metrics) == 6
    assert metrics["score"].dropna().between(0, 100).all()
    sample_history = calculate_symbol_history(bars[bars["symbol"] == "AAA"])
    assert sample_history["adv_volume"].notna().sum() > 0


def test_alerts_are_separate_from_activity_notices():
    bars = make_sample_bars(days=90)
    alerts = latest_alerts(bars)
    if not alerts.empty:
        assert set(alerts["type"]).issubset({"Suy giam thanh khoan", "Giao dich bat thuong"})
        assert not any(alerts["severity"].eq("Do") & alerts["type"].eq("Giao dich bat thuong"))


@pytest.mark.parametrize("adv, expected", [(0, None), (None, None), (1000, 20.0)])
def test_days_to_liquidate_handles_zero_adv(adv, expected):
    result = days_to_liquidate(2_000, adv)
    if expected is None:
        assert result["10%"] is None
    else:
        assert result["10%"] == pytest.approx(expected)


def test_overnight_adjustment_removes_gap_from_two_day_range():
    # Ngày 2 mở cửa nhảy vọt lên trên giá đóng cửa ngày 1: không điều chỉnh thì biên độ hai ngày
    # bị phóng đại (ước lượng âm -> 0); điều chỉnh qua đêm cho ra spread dương.
    bars = pd.DataFrame({
        "high": [102.0, 111.0], "low": [98.0, 109.0], "close": [100.0, 110.0],
        "volume": [1000, 1000],
    })
    raw = corwin_schultz_series(bars).iloc[1]
    adjusted = corwin_schultz_series(bars, adjust_overnight=True).iloc[1]
    assert raw == 0
    assert adjusted > 0


def test_spread_uses_mean_of_daily_estimates():
    days = 20
    bars = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=days),
        "high": [101.0, 102.5] * (days // 2), "low": [99.0, 100.5] * (days // 2),
        "close": [100.0, 101.5] * (days // 2), "volume": [1000] * days,
        "value": [1e8] * days, "ref_px": [100.0, 100.0] * (days // 2),
    })
    history = calculate_symbol_history(bars)
    assert history["spread"].iloc[-1] == pytest.approx(history["spread_daily"].tail(20).mean())


def test_score_rank_ties_share_rank():
    from liquisense.finance import score_rank

    ranks = score_rank(pd.Series([10.0, 9.2, 8.8, 8.0, None]))
    assert ranks.tolist()[:4] == [1, 2, 2, 4] and pd.isna(ranks.iloc[4])
