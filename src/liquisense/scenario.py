"""Tình huống thực tế: bán (hoặc mua) Q cổ phiếu của một mã thì mất bao lâu và tốn bao nhiêu.

Đánh đổi cốt lõi khi đặt lệnh lớn:
- Bán dồn trong ít phiên → mỗi phiên chiếm tỷ trọng lớn của ADV → tác động giá cao.
- Chia nhỏ trong nhiều phiên → tác động giá mỗi phiên thấp, nhưng phải chờ lâu hơn → rủi ro giá biến
  động trong thời gian chờ (xấp xỉ ±σ·√n với n phiên).

Mỗi phương án tham gia p% ADV/phiên: số phiên n = ⌈Q / (p·ADV)⌉; mỗi phiên khớp tối đa p·ADV nên
chi phí tác động = Y·σ·√(khối lượng mỗi phiên / ADV). Phương án "dồn 1 phiên" dùng nguyên Q/ADV.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from liquisense.finance import estimate_cost

PARTICIPATIONS = (0.10, 0.20, 0.30)
PLAN_LABELS = {0.10: "Thận trọng · 10% ADV", 0.20: "Cơ sở · 20% ADV", 0.30: "Nhanh · 30% ADV"}


@dataclass(frozen=True)
class Scenario:
    symbol: str
    quantity: int
    side: str
    price: float
    adv_volume: float
    spread: float
    volatility: float
    plans: pd.DataFrame        # mỗi dòng một phương án

    @property
    def value(self) -> float:
        return self.quantity * self.price

    @property
    def adv_ratio(self) -> float:
        return self.quantity / self.adv_volume


def _finite(value: object) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def order_scenario(row: pd.Series, quantity: int, *, side: str = "Bán",
                   fee: float = 0.0015, tax: float = 0.001) -> Scenario:
    """Các phương án khớp lệnh ``quantity`` cổ phiếu dựa trên chỉ số 20 phiên của mã (một dòng metrics)."""
    needed = ("close", "adv_volume", "spread", "daily_volatility")
    missing = [k for k in needed if not _finite(row.get(k)) or float(row.get(k)) < 0]
    if missing or float(row["adv_volume"]) <= 0 or float(row["close"]) <= 0:
        raise ValueError("Mã chưa đủ dữ liệu giá, ADV, spread hoặc biến động để lập tình huống.")
    if quantity <= 0:
        raise ValueError("Khối lượng phải lớn hơn 0.")
    price, adv = float(row["close"]), float(row["adv_volume"])
    spread, sigma = float(row["spread"]), float(row["daily_volatility"])

    plans = []
    options = [("Dồn trong 1 phiên", None)] + [(PLAN_LABELS[p], p) for p in PARTICIPATIONS]
    for label, participation in options:
        if participation is None:
            sessions, per_session = 1, quantity
        else:
            capacity = participation * adv
            sessions = max(1, math.ceil(quantity / capacity - 1e-9))
            per_session = min(quantity, capacity)
        if participation is not None and sessions == 1:
            continue  # trùng với phương án dồn 1 phiên
        # Chi phí tính trên lát lệnh mỗi phiên (tác động giá theo tỷ trọng của lát đó trong ADV).
        result = estimate_cost(quantity=max(1, int(round(per_session))), price=price, spread=spread,
                               daily_volatility=sigma, adv_volume=adv, side=side, fee_rate=fee, tax_rate=tax)
        scen = {s["scenario"]: s for s in result["scenarios"]}
        plans.append({
            "plan": label,
            "participation": participation if participation is not None else quantity / adv,
            "sessions": sessions,
            "last_session": "T" if sessions == 1 else f"T+{sessions - 1}",
            "settled": f"T+{sessions + 1}",           # thanh toán T+2 tính từ phiên khớp cuối
            "low_pct": scen["Thap"]["total_pct"], "base_pct": scen["Co so"]["total_pct"],
            "high_pct": scen["Cao"]["total_pct"],
            "impact_pct": scen["Co so"]["impact_pct"],
            "base_vnd": scen["Co so"]["total_pct"] * price * quantity,
            "price_risk": sigma * math.sqrt(sessions),  # 1 độ lệch chuẩn của giá trong thời gian chờ
        })
    return Scenario(symbol=str(row.get("symbol", "")), quantity=int(quantity), side=side, price=price,
                    adv_volume=adv, spread=spread, volatility=sigma, plans=pd.DataFrame(plans))


def _n(value: float, digits: int = 0) -> str:
    """Số kiểu Việt Nam: 1.234,5."""
    return f"{value:,.{digits}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def scenario_summary(sc: Scenario) -> str:
    """Một đoạn văn trả lời "mất bao lâu, tốn bao nhiêu" cho phương án cơ sở."""
    plans = sc.plans
    base = plans[plans["participation"].eq(0.20)]
    base = base.iloc[0] if not base.empty else plans.iloc[-1]
    rush = plans.iloc[0]
    verb = "Bán" if sc.side in {"Bán", "Ban"} else "Mua"
    head = (f"{verb} {_n(sc.quantity)} cổ phiếu {sc.symbol} (≈ {_n(sc.value / 1e9, 2)} tỷ đồng, bằng "
            f"{_n(sc.adv_ratio * 100)}% khối lượng giao dịch bình quân một phiên).")
    if base["sessions"] <= 1:
        return (f"{head} Lệnh nhỏ hơn 20% ADV nên khớp hết ngay trong phiên T (thanh toán xong ở phiên T+2), chi phí "
                f"ước tính {_n(base['base_pct'] * 100, 2)}% ≈ {_n(base['base_vnd'] / 1e6)} triệu đồng.")
    text = (f"{head} Theo phương án cơ sở 20% ADV mỗi phiên cần {base['sessions']:.0f} phiên (khớp xong ở phiên "
            f"{base['last_session']}, thanh toán xong ở phiên {base['settled']}), chi phí ước tính "
            f"{_n(base['base_pct'] * 100, 2)}% ≈ {_n(base['base_vnd'] / 1e6)} triệu đồng")
    if rush["sessions"] == 1:
        text += (f"; nếu dồn hết trong 1 phiên, chi phí tăng lên {_n(rush['base_pct'] * 100, 2)}% ≈ "
                 f"{_n(rush['base_vnd'] / 1e6)} triệu đồng")
    text += (f". Đổi lại, chờ {base['sessions']:.0f} phiên thì giá có thể dao động khoảng ±"
             f"{_n(base['price_risk'] * 100, 1)}% (1 độ lệch chuẩn).")
    return text
