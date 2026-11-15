"""Các cảnh báo thanh khoản có thể truy vết theo lịch sử từng mã."""

from __future__ import annotations

import pandas as pd

from liquisense.finance import calculate_symbol_history, robust_zscore


def latest_alerts(bars: pd.DataFrame) -> pd.DataFrame:
    """Sinh cảnh báo từ cửa sổ quá khứ, không dùng dữ liệu tương lai."""
    prepared: list[pd.DataFrame] = []
    for symbol, group in bars.groupby("symbol", sort=True):
        ordered = group.sort_values("date").reset_index(drop=True)
        history = calculate_symbol_history(ordered)
        if not history.empty:
            history = history.copy()
            history["date"] = pd.to_datetime(ordered["date"])
            history["symbol"] = symbol
            prepared.append(history)
    if not prepared:
        return pd.DataFrame(columns=["date", "symbol", "severity", "type", "reason"])
    return alerts_from_history(pd.concat(prepared, ignore_index=True))


def _vn_number(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _alert_value(field: str, value: float) -> str:
    if field == "spread":
        return _vn_number(value * 100, 2) + "%"
    if field == "adv_value":
        if abs(value) >= 1e9:
            return _vn_number(value / 1e9, 1) + " tỷ/phiên"
        return _vn_number(value / 1e6, 0) + " triệu/phiên"
    return f"{value:.2e}".replace(".", ",")


ALERT_NAMES = {"spread": "Spread ước lượng", "amihud": "Amihud (độ nhạy giá)", "adv_value": "Giá trị giao dịch TB 20 phiên"}


def alert_detail(field: str, current: float, baseline: float, z_score: float) -> str:
    """Lý do cảnh báo cụ thể: giá trị hiện tại, mức thường thấy (trung vị 60 phiên trước) và mức lệch."""
    name = ALERT_NAMES[field]
    now, usual = _alert_value(field, current), _alert_value(field, baseline)
    z_text = _vn_number(abs(z_score), 1)
    if baseline > 0:
        ratio = current / baseline
        if ratio >= 1.5:
            change = f"gấp {_vn_number(ratio, 1)} lần"
        elif ratio >= 1:
            change = f"tăng {_vn_number((ratio - 1) * 100, 0)}%"
        else:
            change = f"giảm {_vn_number((1 - ratio) * 100, 0)}%"
    else:
        change = "tăng từ mức gần 0"
    return f"{name} {now}, {change} so với mức thường {usual} của 60 phiên trước (lệch {z_text}σ)"


def alerts_from_history(all_history: pd.DataFrame) -> pd.DataFrame:
    """Cảnh báo cho phiên cuối của từng mã, từ bảng chỉ số theo ngày đã tính sẵn.

    ``all_history`` cần các cột date, symbol, spread, amihud, adv_value (mỗi dòng một mã-ngày).
    """
    if all_history.empty:
        return pd.DataFrame(columns=["date", "symbol", "severity", "type", "reason"])
    all_history = all_history.copy()
    all_history["date"] = pd.to_datetime(all_history["date"])
    prepared = [
        (symbol, group.sort_values("date").reset_index(drop=True))
        for symbol, group in all_history.groupby("symbol", sort=True)
    ]
    latest_cross_section = all_history.sort_values("date").groupby("symbol").tail(1)
    rank_correlation = latest_cross_section["spread"].rank().corr(
        latest_cross_section["amihud"].rank()
    )
    correlated_core_signals = pd.notna(rank_correlation) and rank_correlation > 0.7
    alerts: list[dict[str, object]] = []
    epsilon_cache: dict[tuple[pd.Timestamp, str], float | None] = {}

    def monthly_epsilon(reference_date: pd.Timestamp, field: str) -> float | None:
        month_start = reference_date.to_period("M").start_time
        key = (month_start, field)
        if key not in epsilon_cache:
            previous_month_start = month_start - pd.DateOffset(months=1)
            universe_values = pd.to_numeric(
                all_history.loc[
                    all_history["date"].ge(previous_month_start)
                    & all_history["date"].lt(month_start),
                    field,
                ],
                errors="coerce",
            )
            positive_universe = universe_values[universe_values > 0].dropna()
            epsilon_cache[key] = (
                float(positive_universe.quantile(0.01))
                if not positive_universe.empty
                else None
            )
        return epsilon_cache[key]

    for symbol, history in prepared:
        ordered_history = history.sort_values("date").reset_index(drop=True)
        adverse_z: list[tuple[str, str, float]] = []
        details: list[str] = []
        latest_date = ordered_history.iloc[-1]["date"]

        for field, label, direction in (
            ("spread", "Spread uoc tinh tang", 1),
            ("amihud", "Amihud tang", 1),
            ("adv_value", "ADV gia tri giam", -1),
        ):
            series = pd.to_numeric(ordered_history[field], errors="coerce")
            valid_history = series.iloc[-61:-1].dropna().tail(60)
            current = series.iloc[-1]
            epsilon = monthly_epsilon(latest_date, field)
            z_score = (
                robust_zscore(float(current), valid_history, epsilon=epsilon)
                if pd.notna(current)
                else None
            )
            if z_score is not None and direction * z_score > 2:
                adverse_z.append((field, label, direction * z_score))
                details.append(alert_detail(field, float(current), float(valid_history.median()),
                                            direction * z_score))

        if adverse_z:
            signal_count = len(adverse_z)
            core_signals = {item[0] for item in adverse_z} & {"spread", "amihud"}
            if correlated_core_signals and len(core_signals) == 2:
                signal_count -= 1
            severity = "Do" if signal_count >= 2 else "Vang"
            reason = "; ".join(details)
            alerts.append({
                "date": latest_date,
                "symbol": symbol,
                "severity": severity,
                "type": "Suy giam thanh khoan",
                "reason": reason,
            })

        adv_value = pd.to_numeric(ordered_history["adv_value"], errors="coerce")
        previous = adv_value.iloc[-61:-1].dropna().tail(60)
        current_adv = adv_value.iloc[-1]
        epsilon = monthly_epsilon(latest_date, "adv_value")
        activity_z = (
            robust_zscore(float(current_adv), previous, epsilon=epsilon)
            if pd.notna(current_adv)
            else None
        )
        if activity_z is not None and activity_z > 3:
            alerts.append({
                "date": latest_date,
                "symbol": symbol,
                "severity": "Thong bao",
                "type": "Giao dich bat thuong",
                "reason": alert_detail("adv_value", float(current_adv), float(previous.median()), activity_z),
            })

    return pd.DataFrame(alerts)
