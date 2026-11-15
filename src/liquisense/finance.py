"""Các phép đo thanh khoản; đầu vào chỉ là dữ liệu giá/khối lượng SSI."""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


# Mã đóng cửa ở trần hoặc sàn từ 8/20 phiên trở lên = "kẹt trần/sàn": lệnh bên kia gần như không khớp được.
LIMIT_LOCK_SHARE = 0.4
LIMIT_TOLERANCE = 0.0004  # 0,04%: nhỏ hơn một bước giá (≥ 0,1%) nhưng đủ hấp thụ sai số làm tròn


def adjusted_returns(bars: pd.DataFrame) -> pd.Series:
    """Lợi suất ngày trên CHUỖI GIÁ ĐÃ ĐIỀU CHỈNH: close_t / close_{t-1} − 1.

    Nến SSI (get_ohlc_all) là giá đã điều chỉnh theo sự kiện quyền, còn ref_px/ceil_px/floor_px
    trong master data là giá gốc của ngày đó. Vì vậy KHÔNG được chia giá đóng cửa cho ref_px
    (ví dụ FPT 15/11/2021: close điều chỉnh 44.287 so với tham chiếu gốc 98.000 → lợi suất −55% sai).
    Ngày có sự kiện quyền vẫn bị loại: dữ liệu tải từng ngày được lưu ở giá gốc của thời điểm tải,
    nên quanh ngày giao dịch không hưởng quyền có thể có một bước nhảy không phải biến động thật.
    """
    close = _numeric(bars, "close")
    previous = close.shift(1)
    returns = close.div(previous).sub(1).where((close > 0) & (previous > 0))
    if "event_flag" in bars:
        returns = returns.where(~bars["event_flag"].fillna(False).astype(bool))
    return returns


def price_scale(bars: pd.DataFrame) -> pd.Series:
    """Hệ số điều chỉnh k_t = giá đã điều chỉnh / giá gốc của từng phiên.

    Giá tham chiếu phiên sau là giá gốc của phiên trước (HOSE, HNX: giá đóng cửa; UPCoM: giá bình quân,
    gần giá đóng cửa), nên close_điều_chỉnh_t / ref_px_{t+1} ước lượng k_t. Giữa hai sự kiện quyền k không
    đổi, nên lấy trung vị trượt trong từng đoạn để khử nhiễu (UPCoM) và sai số làm tròn.
    """
    close = _numeric(bars, "close")
    ref_next = _numeric(bars, "ref_px").shift(-1)
    event = (bars["event_flag"].fillna(False).astype(bool) if "event_flag" in bars
             else pd.Series(False, index=bars.index))
    ratio = close.div(ref_next).where((close > 0) & (ref_next > 0) & ~event.shift(-1, fill_value=False))
    segment = event.cumsum()
    # Trung vị trượt (9 phiên, giữa cửa sổ) trong từng đoạn: vẫn đúng khi có một lần điều chỉnh mà dữ liệu
    # sự kiện quyền không đánh dấu (k đổi giữa đoạn).
    smooth = ratio.groupby(segment).transform(lambda r: r.rolling(9, center=True, min_periods=1).median())
    return smooth.groupby(segment).transform(lambda r: r.ffill().bfill())


def limit_flags(bars: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(chạm trần, chạm sàn) so trên CÙNG thang giá gốc.

    Nến SSI là giá đã điều chỉnh, trần/sàn là giá gốc: quy giá đóng cửa về giá gốc bằng hệ số k_t
    (price_scale) rồi mới so với trần/sàn. Phiên không ước lượng được k thì so trực tiếp
    (đúng cho dữ liệu chưa bị điều chỉnh).
    """
    close = _numeric(bars, "close")
    ceil = _numeric(bars, "ceil_px")
    floor = _numeric(bars, "floor_px")
    scale = price_scale(bars)
    scale = scale.where(scale.between(1e-3, 1e3)).fillna(1.0)
    raw_close = close.div(scale)
    at_ceiling = (ceil > 0) & (raw_close >= ceil * (1 - LIMIT_TOLERANCE))
    at_floor = (floor > 0) & (raw_close <= floor * (1 + LIMIT_TOLERANCE))
    return at_ceiling.fillna(False), at_floor.fillna(False)


def corwin_schultz_series(bars: pd.DataFrame, adjust_overnight: bool = False) -> pd.Series:
    """Ước tính spread theo Corwin–Schultz cho từng ngày, chỉ dùng ngày t-1 và t.

    ``adjust_overnight=True`` áp dụng bước điều chỉnh khoảng nhảy giá qua đêm của bài báo gốc
    (Corwin & Schultz, 2012): nếu giá thấp nhất ngày t cao hơn giá đóng cửa ngày t-1 (nhảy lên),
    hoặc giá cao nhất ngày t thấp hơn giá đóng cửa ngày t-1 (nhảy xuống), thì dịch cả high và low
    của ngày t một khoảng bằng phần chênh đó trước khi tính. Bước này loại phần biến động qua đêm
    khỏi biên độ hai ngày nên làm giảm số ước lượng âm.
    """
    high = _numeric(bars, "high")
    low = _numeric(bars, "low")
    close = _numeric(bars, "close")
    volume = _numeric(bars, "volume")

    valid_range = (high > 0) & (low > 0) & (high >= low)
    log_range = np.log(high.where(valid_range) / low.where(valid_range))
    high_t, low_t = high, low
    if adjust_overnight:
        previous_close = close.shift(1)
        gap_up = (low - previous_close).where(low > previous_close, 0.0).fillna(0.0)
        gap_down = (previous_close - high).where(high < previous_close, 0.0).fillna(0.0)
        shift = gap_down - gap_up
        high_t, low_t = high + shift, low + shift
        adjusted_ok = (high_t > 0) & (low_t > 0)
        log_range_t = np.log(high_t.where(valid_range & adjusted_ok) / low_t.where(valid_range & adjusted_ok))
    else:
        log_range_t = log_range
    beta = log_range.shift(1).pow(2) + log_range_t.pow(2)
    two_day_high = pd.concat([high.shift(1), high_t], axis=1).max(axis=1)
    two_day_low = pd.concat([low.shift(1), low_t], axis=1).min(axis=1)
    gamma = np.log(two_day_high / two_day_low).pow(2)
    denominator = 3 - 2 * math.sqrt(2)
    alpha = (
        (np.sqrt(2 * beta) - np.sqrt(beta)) / denominator
        - np.sqrt(gamma / denominator)
    )
    estimate = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))

    # Ngày chạm trần/sàn làm biên độ bị chặn, không dùng để ước tính spread.
    at_ceiling, at_floor = limit_flags(bars)
    at_limit = at_ceiling | at_floor
    prior_limit = at_limit.shift(1, fill_value=False)
    traded = volume.gt(0)
    event = (
        bars["event_flag"].fillna(False).astype(bool)
        if "event_flag" in bars
        else pd.Series(False, index=bars.index)
    )
    prior_event = event.shift(1, fill_value=False)
    return estimate.clip(lower=0).where(
        valid_range & traded & traded.shift(1, fill_value=False)
        & ~at_limit & ~prior_limit & ~event & ~prior_event
    )


def amihud_series(bars: pd.DataFrame) -> pd.Series:
    """ILLIQ theo ngày, đơn vị: biến động giá / một tỷ đồng giao dịch."""
    value = _numeric(bars, "value")
    returns = adjusted_returns(bars).abs()          # đã loại ngày sự kiện quyền
    return (returns.div(value) * 1_000_000_000).where(value > 0)


def rolling_valid_mean(series: pd.Series, window: int = 20, minimum: int = 10) -> pd.Series:
    """Trung bình trượt, chỉ tính khi có đủ số quan sát hợp lệ."""
    return series.rolling(window=window, min_periods=minimum).mean()


def rolling_valid_median(
    series: pd.Series, window: int = 20, minimum: int = 10
) -> pd.Series:
    """Trung vị trượt, dùng làm mượt ước tính spread."""
    return series.rolling(window=window, min_periods=minimum).median()


def calculate_symbol_history(bars: pd.DataFrame) -> pd.DataFrame:
    """Tính các chỉ số theo ngày cho một mã, giữ dữ liệu thiếu là NaN."""
    if bars.empty:
        return pd.DataFrame(index=bars.index)

    ordered = bars.sort_values("date").copy()
    volume = _numeric(ordered, "volume")
    value = _numeric(ordered, "value")
    listed_shares = _numeric(ordered, "listed_shares")
    valid_trading_day = volume.notna() & (volume >= 0)

    result = pd.DataFrame(index=ordered.index)
    result["spread_daily"] = corwin_schultz_series(ordered)
    # Theo khuyến nghị của Corwin & Schultz (2012): đặt ước lượng âm về 0 rồi lấy TRUNG BÌNH
    # (không phải trung vị) — trung vị cho ra 0 với gần 40% số mã vì hơn nửa số ngày bị cắt về 0.
    result["spread"] = rolling_valid_mean(result["spread_daily"])
    # Kiểm tra độ bền: cùng công thức nhưng có điều chỉnh khoảng nhảy giá qua đêm.
    result["spread_daily_adj"] = corwin_schultz_series(ordered, adjust_overnight=True)
    result["spread_adj"] = rolling_valid_mean(result["spread_daily_adj"])
    result["amihud_daily"] = amihud_series(ordered)
    result["amihud"] = rolling_valid_mean(result["amihud_daily"])
    result["amihud_n"] = result["amihud_daily"].rolling(20, min_periods=1).count()
    daily_return = adjusted_returns(ordered).where(volume > 0)
    result["daily_return"] = daily_return
    result["daily_volatility"] = daily_return.rolling(20, min_periods=10).std()
    result["adv_volume"] = volume.where(valid_trading_day).rolling(20, min_periods=10).mean()
    result["adv_value"] = value.where(valid_trading_day).rolling(20, min_periods=10).mean()
    result["turnover"] = result["adv_volume"].div(listed_shares.where(listed_shares > 0))
    previous_adv = volume.where(valid_trading_day).shift(1).rolling(20, min_periods=10).mean()
    at_ceiling, at_floor = limit_flags(ordered)
    traded = volume.gt(0)
    # Số phiên đóng cửa đúng giá trần / sàn trong 20 phiên (phiên không có nến không tính).
    result["ceil_flag"] = (at_ceiling & traded).astype("float64")
    result["floor_flag"] = (at_floor & traded).astype("float64")
    result["ceil_days"] = result["ceil_flag"].rolling(20, min_periods=1).sum()
    result["floor_days"] = result["floor_flag"].rolling(20, min_periods=1).sum()
    floor_low_liquidity = at_floor & volume.lt(0.2 * previous_adv)
    floor_observations = floor_low_liquidity.astype("float64").where(previous_adv.notna())
    result["floor_low_liq_days"] = floor_observations.rolling(20, min_periods=10).sum()
    observed_days = valid_trading_day.rolling(20, min_periods=10).sum()
    zero_days = ((volume == 0) & valid_trading_day).rolling(20, min_periods=10).sum()
    result["zero_days"] = zero_days.div(observed_days.where(observed_days > 0))
    return result.set_axis(ordered.index)


def latest_metrics(bars: pd.DataFrame) -> pd.DataFrame:
    """Tổng hợp chỉ số mới nhất mỗi mã và tính điểm xếp hạng tương đối."""
    records: list[dict[str, object]] = []
    for symbol, group in bars.groupby("symbol", sort=True):
        ordered = group.sort_values("date").reset_index(drop=True)
        history = calculate_symbol_history(ordered)
        last = ordered.iloc[-1]
        measures = history.iloc[-1] if not history.empty else pd.Series(dtype=float)
        valid = all(
            pd.notna(measures.get(name))
            for name in ("spread", "amihud", "adv_volume", "adv_value", "zero_days")
        )
        records.append({
            "symbol": symbol,
            "board": last.get("board", "Chua ro"),
            "sector": last.get("icb_name", "Chua phan nganh"),
            "date": last.get("date"),
            "close": last.get("close"),
            "spread": measures.get("spread"),
            "amihud": measures.get("amihud"),
            "amihud_n": measures.get("amihud_n"),
            "daily_volatility": measures.get("daily_volatility"),
            "adv_volume": measures.get("adv_volume"),
            "adv_value": measures.get("adv_value"),
            "turnover": measures.get("turnover"),
            "floor_low_liq_days": measures.get("floor_low_liq_days"),
            "zero_days": measures.get("zero_days"),
            "status": "Du du lieu" if valid else "Khong du du lieu",
        })

    return score_metrics(pd.DataFrame.from_records(records))


# Trọng số Score. Thanh khoản có ba chiều chính (Kyle, 1985; Sarr & Lybek, 2002): ĐỘ CHẶT (spread – chi phí
# một lệnh nhỏ), ĐỘ SÂU (Amihud – lệnh lớn đẩy giá bao nhiêu) và ĐỘ RỘNG (giá trị giao dịch – thị trường
# hấp thụ được bao nhiêu). Với người đặt lệnh, ba chiều quan trọng ngang nhau nên chia đều 30% mỗi chiều.
# Tỷ lệ ngày không giao dịch (Lesmond, Ogden & Trzcinka, 1999) bằng 0 với đa số mã có giao dịch đều, nên chỉ
# dùng 10% để tách nhóm mã kém thanh khoản. Độ nhạy của xếp hạng theo trọng số: score_weight_sensitivity().
SCORE_WEIGHTS = {"spread": 0.3, "amihud": 0.3, "adv_value": 0.3, "zero_days": 0.1}
WEIGHT_SCENARIOS = {
    "Đang dùng 30/30/30/10": SCORE_WEIGHTS,
    "Bằng nhau 25/25/25/25": {"spread": 0.25, "amihud": 0.25, "adv_value": 0.25, "zero_days": 0.25},
    "Bỏ ngày không GD 33/33/33/0": {"spread": 1 / 3, "amihud": 1 / 3, "adv_value": 1 / 3, "zero_days": 0.0},
    "Nặng chi phí 40/40/20/0": {"spread": 0.4, "amihud": 0.4, "adv_value": 0.2, "zero_days": 0.0},
    "Nặng quy mô 20/20/50/10": {"spread": 0.2, "amihud": 0.2, "adv_value": 0.5, "zero_days": 0.1},
}


def _score(subset: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    ranks = pd.DataFrame({
        "spread": 1 - subset["spread"].rank(pct=True, na_option="keep"),       # spread thấp = tốt
        "amihud": 1 - subset["amihud"].rank(pct=True, na_option="keep"),       # Amihud thấp = tốt
        "adv_value": subset["adv_value"].rank(pct=True, na_option="keep"),     # giá trị GD cao = tốt
        "zero_days": 1 - subset["zero_days"].rank(pct=True, na_option="keep"),
    })
    complete = ranks.notna().all(axis=1)
    total = sum(weights.values())
    score = sum(ranks[name] * weight for name, weight in weights.items()) / total * 100
    return score.where(complete)


def score_metrics(frame: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Chấm điểm thanh khoản tương đối (0–100) cho các mã đủ dữ liệu trong cùng universe."""
    if frame.empty:
        return frame
    frame = frame.copy()
    eligible = frame["status"].eq("Du du lieu")
    score = pd.Series(np.nan, index=frame.index, dtype="float64")
    if eligible.any():
        score.loc[eligible] = _score(frame.loc[eligible], weights or SCORE_WEIGHTS)
    frame["score"] = score
    return frame.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Tương quan hạng Spearman = Pearson trên thứ hạng (không cần cài scipy)."""
    both = pd.concat([a, b], axis=1).dropna()
    if len(both) < 3:
        return float("nan")
    return float(both.iloc[:, 0].rank().corr(both.iloc[:, 1].rank()))


def score_weight_sensitivity(frame: pd.DataFrame, top_share: float = 0.2) -> pd.DataFrame:
    """Xếp hạng thay đổi bao nhiêu khi đổi trọng số: tương quan hạng Spearman với Score đang dùng,
    tỷ lệ trùng nhóm 20% tốt nhất và độ lệch hạng trung vị."""
    eligible = frame[frame["status"].eq("Du du lieu")]
    if len(eligible) < 10:
        return pd.DataFrame()
    base = _score(eligible, SCORE_WEIGHTS)
    base_rank = base.rank(ascending=False)
    top_n = max(1, int(round(len(base) * top_share)))
    base_top = set(base.nlargest(top_n).index)
    rows = []
    for name, weights in WEIGHT_SCENARIOS.items():
        alt = _score(eligible, weights)
        alt_rank = alt.rank(ascending=False)
        rows.append({
            "scenario": name,
            "spearman": spearman(base, alt),
            "top_overlap": len(base_top & set(alt.nlargest(top_n).index)) / top_n,
            "median_shift": float((alt_rank - base_rank).abs().median()),
            "symbols": int(base.notna().sum()),
        })
    return pd.DataFrame(rows)


def score_rank(scores: pd.Series) -> pd.Series:
    """Hạng theo Score đã làm tròn như trên màn hình; bằng điểm thì cùng hạng, hạng sau bỏ qua số chỗ
    đã chia (10đ hạng 1; hai mã 9đ cùng hạng 2; 8đ hạng 4). Mã không có Score trả về NaN."""
    return scores.astype("float64").round(0).rank(method="min", ascending=False, na_option="keep")


def estimate_cost(
    *,
    quantity: int,
    price: float,
    spread: float | None,
    daily_volatility: float | None,
    adv_volume: float | None,
    side: str,
    fee_rate: float,
    tax_rate: float,
) -> dict[str, object]:
    """Ước tính chi phí 3 kịch bản; tỷ lệ phí/thuế nhập dạng thập phân."""
    if quantity <= 0 or price <= 0:
        raise ValueError("Khối lượng và giá phải lớn hơn 0.")
    if side not in {"Mua", "Ban", "Bán"}:
        raise ValueError("Chiều giao dịch chỉ nhận 'Mua' hoặc 'Bán'.")
    if fee_rate < 0 or tax_rate < 0:
        raise ValueError("Phí và thuế không được âm.")

    adv_valid = adv_volume is not None and math.isfinite(adv_volume) and adv_volume > 0
    spread_value = spread if spread is not None and math.isfinite(spread) else None
    volatility = (
        daily_volatility
        if daily_volatility is not None and math.isfinite(daily_volatility)
        else None
    )
    half_spread = spread_value / 2 if spread_value is not None else None
    is_sell = side in {"Ban", "Bán"}
    fixed_cost = fee_rate + (tax_rate if is_sell else 0)
    ratio = quantity / adv_volume if adv_valid else None

    scenarios: list[dict[str, float | str | None]] = []
    for label, impact_multiple in (("Thap", 0.5), ("Co so", 1.0), ("Cao", 1.5)):
        impact = (
            impact_multiple * volatility * math.sqrt(ratio)
            if ratio is not None and volatility is not None
            else None
        )
        total_pct = (
            half_spread + impact + fixed_cost
            if half_spread is not None and impact is not None
            else None
        )
        scenarios.append({
            "scenario": label,
            "half_spread_pct": half_spread,
            "impact_pct": impact,
            "fee_pct": fee_rate,
            "tax_pct": tax_rate if is_sell else 0.0,
            "total_pct": total_pct,
            "cost_vnd": total_pct * price * quantity if total_pct is not None else None,
        })

    warning = (
        "Cao"
        if ratio is None or ratio > 0.20
        else "Trung binh"
        if ratio > 0.05
        else "Thap"
    )
    return {
        "quantity": quantity,
        "price": price,
        "adv_ratio": ratio,
        "warning": warning,
        "scenarios": scenarios,
        "days_to_liquidate": days_to_liquidate(quantity, adv_volume),
    }


def days_to_liquidate(position_volume: float, adv_volume: float | None) -> dict[str, float | None]:
    """Số ngày thanh lý theo 3 mức tham gia ADV; ADV không hợp lệ trả về None."""
    if position_volume < 0:
        raise ValueError("Vị thế không được âm.")
    if adv_volume is None or not math.isfinite(adv_volume) or adv_volume <= 0:
        return {"10%": None, "20%": None, "30%": None}
    return {
        f"{participation:.0%}": position_volume / (participation * adv_volume)
        for participation in (0.10, 0.20, 0.30)
    }


def robust_zscore(
    current: float,
    history: Iterable[float],
    epsilon: float | None = None,
) -> float | None:
    """Robust z-score trên log; epsilon có thể được cố định theo universe/tháng."""
    values = np.asarray(list(history), dtype="float64")
    values = values[np.isfinite(values) & (values >= 0)]
    if not math.isfinite(current) or current < 0 or len(values) < 30:
        return None

    if epsilon is None:
        positive = values[values > 0]
        epsilon = float(np.quantile(positive, 0.01)) if len(positive) else None
    if epsilon is None or epsilon <= 0:
        return None
    logged = np.log(values + epsilon)
    center = float(np.median(logged))
    mad = float(np.median(np.abs(logged - center)))
    if mad == 0:
        return None
    return (math.log(current + epsilon) - center) / (1.4826 * mad)
