"""Trang Chi phí giao dịch theo kịch bản."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from liquisense.finance import estimate_cost
from liquisense.insights import (
    cost_insights,
    window_cost,
)
from liquisense.ui.common import (
    Period,
    SELL_TAX_PCT,
    _alpha,
    _valid,
    esc,
    get_metrics,
    insight_card,
    md,
    page_title,
    section_head,
    segmented,
    show_chart,
    style_figure,
    symbol_history,
    vn,
    vn_pct,
    vn_thousand,
)
from liquisense.ui.liquidity import (
    WINDOW_NOTE,
    dtl_bias_note,
    window_selector,
)


# --------------------------------------------------------------------------
# Trang 3 · Chi phí giao dịch theo kịch bản
# --------------------------------------------------------------------------
def _t_label(sessions: int) -> str:
    """Phiên khớp cuối cùng khi chia lệnh trong ``sessions`` phiên, tính từ phiên T."""
    return "ngay phiên T" if sessions <= 1 else f"T+{sessions - 1}"


def settlement_sessions(days: float | None) -> int | None:
    """Số phiên cần để khớp hết lệnh (làm tròn lên; tối thiểu 1 phiên)."""
    return max(1, math.ceil(days - 1e-9)) if _valid(days) else None


def _round_lot(value: float) -> int:
    return max(100, int(value // 100 * 100))


def quantity_input(symbol: str, adv: float) -> int | None:
    """Ô nhập số + thanh kéo, đồng bộ hai chiều; tối thiểu 1 cổ (cho phép lô lẻ), ban đầu để trống."""
    max_slider = max(_round_lot(adv * 0.5), 10_000)
    num_key, slide_key = f"qty_num_{symbol}", f"qty_slide_{symbol}"
    if num_key not in st.session_state:
        st.session_state[num_key] = None
        st.session_state[slide_key] = 1

    def from_number() -> None:
        value = st.session_state[num_key]
        if value is not None:
            st.session_state[slide_key] = min(max(1, int(value)), max_slider)

    def from_slider() -> None:
        st.session_state[num_key] = int(st.session_state[slide_key])

    st.number_input("Khối lượng (cổ phiếu) — gõ số hoặc kéo thanh bên dưới", min_value=1,
                    max_value=10_000_000_000, step=100, format="%d", key=num_key, on_change=from_number,
                    placeholder="Nhập số cổ phiếu, ví dụ 10000")
    st.slider("Kéo để chọn nhanh", 1, max_slider, step=1, key=slide_key, format="%d",
              on_change=from_slider, label_visibility="collapsed")
    value = st.session_state[num_key]
    return int(value) if value else None


def cost_inputs(symbol: str, as_of: date, window: int) -> tuple[float, float]:
    """ADV khối lượng và σ lợi suất ngày trên N phiên gần nhất tính đến as_of."""
    history = symbol_history(symbol, as_of).tail(window)
    minimum = max(3, window // 2)
    volume = history["volume"].where(history["volume"].notna() & (history["volume"] >= 0))
    adv = float(volume.mean()) if volume.count() >= minimum else np.nan
    returns = history["daily_return"].dropna()
    sigma = float(returns.std()) if len(returns) >= minimum else np.nan
    return adv, sigma


def cost_page(period: Period, t: dict[str, object]) -> None:
    page_title(
        "Ước tính chi phí giao dịch theo kịch bản",
        "Nửa spread ước lượng + tác động giá (mô hình căn bậc hai) + phí và thuế · "
        f"giả định toàn bộ lệnh khớp trong một phiên · chỉ số {period.basis}",
        "cost",
    )
    metrics = get_metrics(period)
    available = metrics[
        metrics["status"].eq("Du du lieu") & metrics["daily_volatility"].notna() & metrics["close"].gt(0)
    ].sort_values("adv_value", ascending=False) if not metrics.empty else metrics
    if available.empty:
        st.warning("Không có mã đủ dữ liệu để ước tính. Hãy cập nhật thêm dữ liệu hoặc chọn khoảng dài hơn.")
        return

    form_col, result_col = st.columns([1, 1.9], gap="medium")
    with form_col, st.container(border=True, key="card_form"):
        section_head("Thông số lệnh giả định")
        labels = {s: f"{s} · {b} · {sec}"
                  for s, b, sec in zip(available["symbol"], available["board"], available["sector"])}
        symbol = st.selectbox("Mã cổ phiếu (gõ để tìm)", list(labels), format_func=labels.get, key="cost_symbol")
        row = available.loc[available["symbol"].eq(symbol)].iloc[0]
        side = segmented("Chiều lệnh", ["Mua", "Bán"], "cost_side", "Mua")
        window = window_selector("cost_window", "Số phiên tính ADV và σ")
        md(f'<p class="ls-note" style="margin:-6px 0 10px">ADV và biến động σ tính trên {window} phiên gần nhất '
           f'đến {period.as_of:%d/%m/%Y} để xem chi phí nhạy với giả định thế nào. {WINDOW_NOTE}</p>')
        adv, sigma = cost_inputs(symbol, period.as_of, window)
        if not _valid(adv) or adv <= 0:
            adv = float(row["adv_volume"])
        if not _valid(sigma):
            sigma = float(row["daily_volatility"])
        quantity = quantity_input(symbol, adv)
        fee_col, tax_col = st.columns(2)
        fee_pct = fee_col.number_input("Phí giao dịch (%)", min_value=0.0, value=0.15, step=0.01, format="%.2f")
        tax_pct = SELL_TAX_PCT if side == "Bán" else 0.0
        with tax_col:
            md(f'<div class="ls-fixed"><span>Thuế bán (%) · cố định</span>'
               f'<b>{vn(SELL_TAX_PCT, 1)}</b>'
               f'<small>{"áp dụng cho lệnh bán" if side == "Bán" else "lệnh mua không chịu thuế"}</small></div>')
        md(
            '<dl class="ls-dl">'
            f'<dt>Giá đóng cửa</dt><dd>{vn(row["close"])} đ</dd>'
            f'<dt>Giá trị lệnh</dt><dd>{vn_thousand(quantity * float(row["close"])) if quantity else "—"}</dd>'
            f'<dt>ADV khối lượng ({window} phiên)</dt><dd>{vn(adv)}</dd>'
            f'<dt>Spread ước lượng (S)</dt><dd>{vn_pct(row["spread"])}</dd>'
            f'<dt>Biến động ngày σ ({window} phiên)</dt><dd>{vn_pct(sigma)}</dd>'
            '</dl>'
        )

    if not quantity:
        with result_col:
            md('<div class="ls-explain"><b>Bắt đầu</b><span>Nhập khối lượng cổ phiếu ở ô bên trái '
               '(hoặc kéo thanh) để xem chi phí theo 3 kịch bản.</span></div>')
        return
    spread, price = float(row["spread"]), float(row["close"])
    fee, tax = fee_pct / 100, tax_pct / 100
    result = estimate_cost(quantity=int(quantity), price=price, spread=spread, daily_volatility=sigma,
                           adv_volume=adv, side=side, fee_rate=fee, tax_rate=tax)
    ratio = float(result["adv_ratio"])
    fixed = fee + (tax if side == "Bán" else 0.0)
    half = spread / 2

    with result_col:
        lvl = {
            "Thap": ("Thấp", "lệnh nhỏ so với thanh khoản, giả định mô hình phù hợp hơn", t["okBg"], t["ok"]),
            "Trung binh": ("Trung bình", "nên đọc kết quả như một khoảng, không phải một con số",
                           t["warnBg"], t["warn"]),
            "Cao": ("Cao", "lệnh lớn so với thanh khoản, giả định mô hình kém phù hợp; cân nhắc chia lệnh",
                    t["badBg"], t["bad"]),
        }[result["warning"]]
        md(f'<div class="ls-band" style="background:{lvl[2]};color:{lvl[3]};padding:12px 16px;margin:0 0 12px">'
           f'<strong>Mức cảnh báo quy mô lệnh: {lvl[0]}</strong>'
           f'<span>Q/ADV = {vn_pct(ratio, 1)} · {esc(lvl[1])}</span></div>')

        names = {"Thap": ("Tác động thấp", "0,5"), "Co so": ("Cơ sở", "1,0"), "Cao": ("Tác động cao", "1,5")}
        cards = []
        for scen in result["scenarios"]:
            name, y = names[scen["scenario"]]
            total, impact = scen["total_pct"], scen["impact_pct"]
            base = scen["scenario"] == "Co so"
            stack = (
                f'<div class="ls-stack"><span style="width:{half / total * 100:.1f}%;background:{t["c1"]}"></span>'
                f'<span style="width:{impact / total * 100:.1f}%;background:{t["c2"]}"></span>'
                f'<span style="width:{fixed / total * 100:.1f}%;background:{t["c3"]}"></span></div>'
            )
            cards.append(
                f'<article style="background:{t["accentSoft"] if base else t["surf"]};'
                f'border:1px solid {t["accent"] if base else t["line"]}">'
                f'<span class="n">{name} <small>· Y = {y}</small></span>'
                f'<span class="p">{vn_pct(total)}</span>'
                f'<span class="d">≈ {vn_thousand(scen["cost_vnd"])}</span>{stack}</article>'
            )
        md(f'<div class="ls-scen">{"".join(cards)}</div>'
           f'<div class="ls-legend" style="margin:10px 0 14px;gap:14px">'
           f'<span><i style="background:{t["c1"]}"></i> Nửa spread {vn_pct(half)}</span>'
           f'<span><i style="background:{t["c2"]}"></i> Tác động giá (theo Y)</span>'
           f'<span><i style="background:{t["c3"]}"></i> Phí và thuế {vn_pct(fixed)}</span></div>')

        window_costs = {}
        for w in (10, 20, 60):
            adv_w, sigma_w = cost_inputs(symbol, period.as_of, w)
            ratio_w = quantity / adv_w if _valid(adv_w) and adv_w > 0 else None
            window_costs[w] = window_cost(half, sigma_w, fixed, ratio_w)
        base = next(s_ for s_ in result["scenarios"] if s_["scenario"] == "Co so")
        insight_card(cost_insights(
            symbol=symbol, ratio=ratio, half=half, sigma=sigma, fixed=fixed,
            base_total=base["total_pct"], impact=base["impact_pct"], window=window,
            window_costs=window_costs,
        ), t)

        chart_col, dtl_col = st.columns([1.65, 1], gap="medium")
        with chart_col, st.container(border=True, key="card_curve"):
            section_head("Chi phí theo quy mô lệnh",
                         "Dải màu = khoảng giữa kịch bản thấp và cao · chấm = lệnh của bạn")
            grid = np.linspace(0, max(0.4, ratio * 1.15), 81)

            def cost_at(y: float, r: np.ndarray | float) -> np.ndarray | float:
                return (half + y * sigma * np.sqrt(r) + fixed) * 100

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=grid * 100, y=cost_at(1.5, grid), mode="lines",
                                     line=dict(width=0), hoverinfo="skip", showlegend=False))
            fig.add_trace(go.Scatter(x=grid * 100, y=cost_at(0.5, grid), mode="lines", fill="tonexty",
                                     fillcolor=_alpha(str(t["accent"]), 0.18), line=dict(width=0),
                                     hoverinfo="skip", showlegend=False))
            fig.add_trace(go.Scatter(x=grid * 100, y=cost_at(1.0, grid), mode="lines", name="Cơ sở",
                                     line=dict(color=str(t["accent"]), width=2.5),
                                     hovertemplate="Q/ADV %{x:.1f}%<br>Chi phí %{y:.2f}%<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=[ratio * 100], y=[cost_at(1.0, ratio)], mode="markers", name="Lệnh của bạn",
                marker=dict(size=11, color=str(t["accent"]), line=dict(width=3, color=str(t["surf"]))),
                hovertemplate="Lệnh của bạn<br>Q/ADV %{x:.1f}%<br>Chi phí %{y:.2f}%<extra></extra>",
            ))
            style_figure(fig, t, 260)
            fig.update_layout(showlegend=False)
            fig.update_xaxes(title_text="Khối lượng lệnh / ADV (%)", ticksuffix="%")
            fig.update_yaxes(title_text="Tổng chi phí", ticksuffix="%", rangemode="tozero")
            curve = pd.DataFrame({"Q/ADV (%)": grid * 100, "Chi phí thấp (%)": cost_at(0.5, grid),
                                  "Chi phí cơ sở (%)": cost_at(1.0, grid), "Chi phí cao (%)": cost_at(1.5, grid)})
            show_chart(fig, curve, f"liquisense_duong_chi_phi_{symbol}", t, "curve")
        with dtl_col, st.container(border=True, key="card_dtl"):
            buying = side == "Mua"
            section_head("Thời gian khớp và thanh toán T+2",
                         ("Chia lệnh theo tỷ lệ tham gia mỗi phiên · cổ phiếu về tài khoản ở phiên T+2"
                          if buying else "Chia lệnh theo tỷ lệ tham gia mỗi phiên"))
            dtl_rows = []
            for name, key in (("Thận trọng", "10%"), ("Cơ sở", "20%"), ("Cao", "30%")):
                days = result["days_to_liquidate"][key]
                sessions = settlement_sessions(days)
                color = t["bad"] if sessions and sessions > 3 else t["text"]
                detail = "—" if not sessions else (
                    f"khớp xong {_t_label(sessions)} · hàng về đủ T+{sessions + 1}" if buying
                    else f"bán xong {_t_label(sessions)}")
                dtl_rows.append(
                    f'<div class="ls-dtl"><span><b>{name}</b> <span style="color:{t["muted"]}">· {key} ADV</span>'
                    f'<br><small style="color:{t["muted"]}">{detail}</small></span>'
                    f'<span class="ls-mono" style="font-weight:600;color:{color}">'
                    f'{str(sessions) + " phiên" if sessions else "—"}</span></div>'
                )
            md("".join(dtl_rows))
            md('<p class="ls-note" style="margin-top:8px">'
               + ("Mua ngày T: cổ phiếu về tài khoản và bán được từ phiên T+2. Lô mua ở phiên cuối "
                  "cùng bán được từ phiên T+2 tính từ phiên đó." if buying else
                  "Cổ phiếu đem bán phải đã về tài khoản, tức đã mua từ phiên T−2 trở về trước.")
               + '</p>')
            md(f'<p class="ls-note" style="margin-top:4px;color:{t["warn"]}">⚠ {dtl_bias_note()}</p>')

        scen = {s["scenario"]: s for s in result["scenarios"]}
        impact_share = scen["Co so"]["impact_pct"] / scen["Co so"]["total_pct"] * 100
        md(f'<div class="ls-explain"><b>Lưu ý</b><span>Lệnh {side.lower()} {vn(quantity)} cổ {esc(symbol)} '
           f'bằng {vn_pct(ratio, 1)} ADV. Chi phí ước tính {vn_pct(scen["Thap"]["total_pct"])}–'
           f'{vn_pct(scen["Cao"]["total_pct"])}, khoảng {vn(impact_share)}% ở kịch bản cơ sở đến từ tác động giá. '
           'Phần tác động giá chưa được kiểm chứng bằng dữ liệu khớp lệnh thực tế; '
           'đây là phân tích kịch bản, không gửi lệnh.</span></div>')

        report = pd.DataFrame([{
            "Mã": symbol, "Chiều lệnh": side, "Khối lượng": int(quantity),
            "Kịch bản": names[s["scenario"]][0], "Nửa spread (%)": s["half_spread_pct"] * 100,
            "Tác động giá (%)": s["impact_pct"] * 100, "Phí (%)": s["fee_pct"] * 100,
            "Thuế (%)": s["tax_pct"] * 100, "Tổng chi phí (%)": s["total_pct"] * 100,
            "Chi phí (nghìn đồng)": s["cost_vnd"] / 1000,
        } for s in result["scenarios"]])
        st.download_button("Tải báo cáo chi phí (CSV)", report.to_csv(index=False).encode("utf-8-sig"),
                           icon=":material/download:", file_name=f"liquisense_chi_phi_{symbol}.csv",
                           mime="text/csv", on_click="ignore")
