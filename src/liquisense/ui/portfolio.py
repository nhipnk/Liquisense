"""Trang Mô phỏng danh mục."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from liquisense.finance import days_to_liquidate
from liquisense.insights import (
    portfolio_insights,
)
from liquisense.snapshot import (
    data_root,
)
from liquisense.ui.common import (
    Period,
    running_on_cloud,
    _valid,
    alert_levels,
    esc,
    get_snapshot,
    insight_card,
    kpi_cards,
    md,
    page_title,
    section_head,
    vn,
    vn_bil,
    vn_pct,
)
from liquisense.ui.liquidity import (
    history_chart,
)
from liquisense.ui.cost import (
    _t_label,
    settlement_sessions,
)


# --------------------------------------------------------------------------
# Trang 4 · Danh mục do người dùng tự nhập
# --------------------------------------------------------------------------
def _portfolio_path() -> Path:
    return data_root() / "danh_muc_mo_phong.json"


def load_portfolio() -> list[dict[str, object]]:
    """Danh mục của người đang xem.

    - Trên máy cá nhân: đọc/ghi file data/danh_muc_mo_phong.json để giữ lại giữa các lần mở app.
    - Trên cloud (nhiều người dùng chung một máy chủ): CHỈ giữ trong phiên trình duyệt (st.session_state), không
      đọc/ghi file — mỗi người xem có một danh mục riêng, người khác không thấy và không sửa được."""
    if "portfolio" not in st.session_state:
        positions: list[dict[str, object]] = []
        if not running_on_cloud():
            try:
                path = _portfolio_path()
                if path.exists():
                    positions = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                positions = []
        st.session_state["portfolio"] = positions
    return st.session_state["portfolio"]


def save_portfolio(positions: list[dict[str, object]]) -> None:
    st.session_state["portfolio"] = positions
    if running_on_cloud():
        return
    try:
        path = _portfolio_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(positions, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # Không ghi được file thì vẫn giữ trong phiên làm việc.


def storage_note() -> str:
    if running_on_cloud():
        return ("chỉ được giữ trong trình duyệt của bạn trong lần mở này — người khác không xem được, và sẽ mất "
                "khi bạn đóng hoặc tải lại trang")
    return "được lưu trong file data/danh_muc_mo_phong.json trên máy của bạn"


def add_position(symbol: str, qty: int, cost: float) -> None:
    positions = [dict(p) for p in load_portfolio()]
    for pos in positions:
        if pos["symbol"] == symbol:
            total = int(pos["qty"]) + qty
            pos["cost"] = (float(pos["cost"]) * int(pos["qty"]) + cost * qty) / total
            pos["qty"] = total
            break
    else:
        positions.append({"symbol": symbol, "qty": qty, "cost": cost})
    save_portfolio(positions)


def remove_position(symbol: str) -> None:
    save_portfolio([p for p in load_portfolio() if p["symbol"] != symbol])


def portfolio_page(period: Period, t: dict[str, object]) -> None:
    page_title("Danh mục mô phỏng & rủi ro thanh khoản",
               f"Bao lâu để thoát toàn bộ vị thế nếu mỗi phiên chỉ giao dịch một phần ADV · chỉ số {period.basis}",
               "portfolio")
    md(f'<div class="ls-band" style="background:{t["infoBg"]};color:{t["info"]};margin:0 0 12px">'
       '<strong>Danh mục do bạn tự nhập để mô phỏng.</strong>'
       '<span>LiquiSense không kết nối tài khoản chứng khoán, không đọc số dư và không gửi lệnh. '
       f'Mã, khối lượng và giá vốn chỉ là số liệu giả định của bạn, {storage_note()}.</span></div>')
    metrics, alerts = get_snapshot(period)
    if metrics.empty:
        st.warning("Không có dữ liệu cho thời gian đã chọn.")
        return
    levels = alert_levels(alerts)
    lookup = metrics.set_index("symbol")

    with st.container(border=True, key="card_add"):
        section_head("Thêm mã vào danh mục",
                     "Nhập được cả lô lẻ (dưới 100 cổ) · thêm trùng mã sẽ cộng dồn và tính lại giá vốn bình quân")
        labels = {s: f"{s} · {b}" for s, b in zip(metrics["symbol"], metrics["board"])}
        with st.form("add_position", clear_on_submit=True, border=False):
            c1, c2, c3, c4 = st.columns([1.3, 1.2, 1.4, 1.1], vertical_alignment="bottom")
            symbol = c1.selectbox("Mã cổ phiếu", sorted(labels), format_func=labels.get, index=None,
                                  placeholder="Chọn hoặc gõ mã…")
            qty = c2.number_input("Khối lượng (cổ)", min_value=1, value=None, step=100, format="%d",
                                  placeholder="Nhập số cổ phiếu")
            cost = c3.number_input("Giá vốn (đ/cổ)", min_value=0, value=None, step=100, format="%d",
                                   placeholder="Để trống = giá đóng cửa")
            submitted = c4.form_submit_button("Thêm vào danh mục", type="primary", width="stretch",
                                              icon=":material/add:")
        if submitted:
            if not symbol:
                st.warning("Hãy chọn mã cổ phiếu.")
            elif not qty or int(qty) < 1:
                st.warning("Hãy nhập khối lượng, tối thiểu 1 cổ.")
            else:
                close = float(lookup.at[symbol, "close"]) if symbol in lookup.index else 0.0
                add_position(symbol, int(qty), float(cost) if cost else close)
                st.rerun()

    positions = load_portfolio()
    if not positions:
        with st.container(border=True, key="card_empty"):
            md('<h2 class="ls-h2">Danh mục hiện tại đang trống</h2>'
               '<p class="ls-note">Thêm mã ở ô phía trên, hoặc dùng danh mục mẫu để xem thử.</p>')
            if st.button("Dùng danh mục mẫu", key="sample_portfolio"):
                liquid = metrics.dropna(subset=["score"]).sort_values("adv_value", ascending=False)
                ranked = liquid["symbol"].tolist()
                picks = [ranked[i] for i in (0, 1, 5, 40, 120) if i < len(ranked)]
                save_portfolio([
                    {"symbol": s, "qty": q, "cost": float(lookup.at[s, "close"])}
                    for s, q in zip(picks, (200_000, 150_000, 500_000, 300_000, 200_050))
                ])
                st.rerun()
        return

    rows: list[dict[str, object]] = []
    for pos in positions:
        symbol, qty, cost = str(pos["symbol"]), int(pos["qty"]), float(pos["cost"])
        known = symbol in lookup.index
        close = float(lookup.at[symbol, "close"]) if known else np.nan
        adv = float(lookup.at[symbol, "adv_volume"]) if known and _valid(lookup.at[symbol, "adv_volume"]) else None
        d = days_to_liquidate(qty, adv)
        rows.append({
            "symbol": symbol, "board": lookup.at[symbol, "board"] if known else "Không rõ",
            "qty": qty, "cost": cost, "close": close, "market": qty * close if known else np.nan,
            "pnl": (close - cost) * qty if known else np.nan,
            "pnl_pct": (close / cost - 1) if known and cost > 0 else np.nan,
            "adv": adv, "d10": d["10%"], "d20": d["20%"], "d30": d["30%"],
            "s10": settlement_sessions(d["10%"]), "s20": settlement_sessions(d["20%"]),
            "s30": settlement_sessions(d["30%"]),
            "status": lookup.at[symbol, "status"] if known else "",
        })
    book = pd.DataFrame(rows)

    valid_d20 = book["d20"].dropna()
    stuck = int((book["s20"].dropna() > 3).sum())
    worst = book.loc[valid_d20.idxmax()] if not valid_d20.empty else None
    in_alert = [(s, levels[s]) for s in book["symbol"] if levels.get(s) in ("Do", "Vang")]
    total_market, total_cost = book["market"].sum(), (book["qty"] * book["cost"]).sum()
    pnl = total_market - total_cost
    kpi_cards([
        ("Giá trị thị trường", vn_bil(total_market),
         f"{len(book)} mã · lãi/lỗ tạm tính {'+' if pnl >= 0 else ''}{vn_bil(pnl)}"
         + (f" ({'+' if pnl >= 0 else ''}{vn_pct(pnl / total_cost, 1)})" if total_cost > 0 else ""),
         str(t["ok"] if pnl >= 0 else t["bad"])),
        ("Số phiên bán hết lâu nhất (cơ sở)", f"{int(worst['s20'])} phiên" if worst is not None else "—",
         f"{worst['symbol']} · bán xong {_t_label(int(worst['s20']))} · {vn(worst['qty'])} cổ so với ADV "
         f"{vn(worst['adv'])}" if worst is not None else "—",
         str(t["bad"] if worst is not None and worst["s20"] > 3 else t["muted"])),
        ("Mã khó thoát (> 3 phiên)", str(stuck), "theo kịch bản cơ sở 20% ADV", str(t["bad"] if stuck else t["muted"])),
        ("Mã đang cảnh báo", str(len(in_alert)),
         " · ".join(f"{s} {'đỏ' if lv == 'Do' else 'vàng'}" for s, lv in in_alert) or "Không có",
         str(t["warn"] if in_alert else t["muted"])),
    ])

    insight_card(portfolio_insights(book, levels), t)

    with st.container(border=True, key="card_book"):
        head_col, clear_col, export_col = st.columns([3.6, 1, 1], vertical_alignment="center")
        with head_col:
            section_head("Danh mục hiện tại",
                         f"Giá đóng cửa {period.as_of:%d/%m/%Y} · bấm Xóa ở cuối dòng để bỏ một mã")
        if clear_col.button("Xóa tất cả", key="clear_all", width="stretch", icon=":material/delete_sweep:"):
            save_portfolio([])
            st.rerun()
        export = book.rename(columns={
            "symbol": "Mã", "board": "Sàn", "qty": "Khối lượng", "cost": "Giá vốn", "close": "Giá đóng cửa",
            "market": "Giá trị thị trường", "pnl": "Lãi/lỗ tạm tính", "pnl_pct": "Lãi/lỗ (%)",
            "adv": "ADV khối lượng", "s10": "Số phiên bán hết 10%", "s20": "Số phiên bán hết 20%",
            "s30": "Số phiên bán hết 30%",
        })
        export_col.download_button("Xuất CSV", export.to_csv(index=False).encode("utf-8-sig"),
                                   icon=":material/download:", file_name="liquisense_danh_muc.csv",
                                   mime="text/csv", width="stretch", on_click="ignore")

        widths = [1.0, 1.05, 1.0, 1.05, 1.0, 1.45, 1.1, 1.3, 0.95]
        heads = ["Mã", "Khối lượng", "Giá vốn", "Giá đóng cửa", "Giá trị", "Lãi/lỗ tạm tính",
                 "Bán hết (cơ sở)", "Đánh giá", ""]
        with st.container(key="pfrow_head"):
            for col, text in zip(st.columns(widths, vertical_alignment="center"), heads):
                with col:
                    align = "" if text in ("Mã", "Đánh giá", "") else " num"
                    md(f'<div class="ls-cell head{align}">{text}</div>')
        for i, r in book.iterrows():
            if r["status"] == "Tran san lien tuc":
                badge = ("Kẹt trần/sàn", t["badBg"], t["bad"])
            elif not _valid(r["s20"]):
                badge = ("Không đủ dữ liệu", t["surf2"], t["muted"])
            elif r["s20"] > 3:
                badge = ("Khó thoát", t["badBg"], t["bad"])
            elif r["s20"] > 1:
                badge = ("Cần chia lệnh", t["warnBg"], t["warn"])
            else:
                badge = ("Thoát trong 1 phiên", t["okBg"], t["ok"])
            pnl_color = t["ok"] if _valid(r["pnl"]) and r["pnl"] >= 0 else t["bad"]
            pnl_text = (f"{'+' if r['pnl'] >= 0 else ''}{vn(r['pnl'])} đ"
                        + (f" ({'+' if r['pnl'] >= 0 else ''}{vn_pct(r['pnl_pct'], 1)})" if _valid(r["pnl_pct"]) else "")
                        if _valid(r["pnl"]) else "—")
            d20_color = t["bad"] if _valid(r["s20"]) and r["s20"] > 3 else t["text"]
            odd = f' <span style="color:{t["muted"]};font-size:11px">lô lẻ {int(r["qty"]) % 100}</span>' \
                if int(r["qty"]) % 100 else ""
            cells = [
                f'<div class="ls-cell"><b class="ls-mono">{esc(r["symbol"])}</b> '
                f'<span style="color:{t["muted"]};font-size:12px">{esc(r["board"])}</span></div>',
                f'<div class="ls-cell num">{vn(r["qty"])}{odd}</div>',
                f'<div class="ls-cell num">{vn(r["cost"])}</div>',
                f'<div class="ls-cell num">{vn(r["close"])}</div>',
                f'<div class="ls-cell num">{vn_bil(r["market"])}</div>',
                f'<div class="ls-cell num" style="color:{pnl_color}">{pnl_text}</div>',
                f'<div class="ls-cell num" style="color:{d20_color}">'
                + (f'{int(r["s20"])} phiên<br><small class="ls-sub2">bán xong {_t_label(int(r["s20"]))}'
                 '</small>' if _valid(r["s20"]) else "Không thể ước tính") + '</div>',
                f'<div class="ls-cell"><span class="ls-badge" style="background:{badge[1]};color:{badge[2]}">'
                f'{badge[0]}</span></div>',
            ]
            with st.container(key=f"pfrow_{i}"):
                cols = st.columns(widths, vertical_alignment="center")
                for col, html_cell in zip(cols[:-1], cells):
                    with col:
                        md(html_cell)
                cols[-1].button("Xóa", key=f"del_{r['symbol']}", icon=":material/delete:", width="stretch",
                                help=f"Xóa {r['symbol']} khỏi danh mục",
                                on_click=remove_position, args=(r["symbol"],))

    with st.container(border=True, key="card_dtl_table"):
        section_head("Số phiên bán hết theo kịch bản tỷ lệ tham gia",
                     "Thận trọng 10% · cơ sở 20% · cao 30% ADV khối lượng · tô đỏ khi cần hơn 3 phiên")
        body = []
        for _, r in book.iterrows():
            def cell(v: object) -> str:
                if not _valid(v):
                    return f'<td class="num" style="color:{t["muted"]}">Không thể ước tính</td>'
                n = int(v)
                return (f'<td class="num" style="color:{t["bad"] if n > 3 else t["text"]}">{n} phiên'
                        f'<br><small class="ls-sub2">bán xong {_t_label(n)}</small></td>')
            body.append(
                f'<tr><td><span class="ls-mono" style="font-weight:600">{esc(r["symbol"])}</span></td>'
                f'<td class="num">{vn(r["qty"])}</td><td class="num">{vn(r["adv"])}</td>'
                f'{cell(r["s10"])}{cell(r["s20"])}{cell(r["s30"])}</tr>'
            )
        md('<div class="ls-table-wrap"><table class="ls-table"><thead><tr>'
           '<th>Mã</th><th style="text-align:right">Khối lượng nắm giữ</th>'
           '<th style="text-align:right">ADV khối lượng</th><th style="text-align:right">Thận trọng</th>'
           '<th style="text-align:right">Cơ sở</th><th style="text-align:right">Cao</th>'
           f'</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
           '<p class="ls-note" style="margin:12px 0 0">Số phiên làm tròn lên, tối thiểu 1 phiên; phiên T là phiên '
           'bắt đầu bán, cổ phiếu trong danh mục được giả định đã về tài khoản (T+2). Mã có ADV = 0 hoặc thiếu dữ '
           'liệu ghi “không thể ước tính”.</p>')

    with st.container(border=True, key="card_pf_history"):
        section_head("Diễn biến thanh khoản của mã trong danh mục")
        symbols = [s for s in book["symbol"] if s in lookup.index]
        if symbols:
            symbol = st.selectbox("Mã", symbols, key="pf_hist_symbol")
            history_chart(symbol, period, levels, t, "pf_hist_metric")

    with st.expander("Phương pháp & giới hạn"):
        st.markdown(
            "- **Sức chứa một phiên** = p × ADV khối lượng, với p = 10%, 20%, 30%; số phiên bán hết = khối lượng "
            "nắm giữ / sức chứa. "
            "Đây là tham số phân tích độ nhạy, không phải tỷ lệ thực hiện được bảo đảm.\n"
            "- **Số phiên bán hết** làm tròn lên (tối thiểu 1 phiên): 0,3 lần sức chứa vẫn là 1 phiên.\n"
            "- **Thanh toán T+2:** giả định cổ phiếu trong danh mục đã về tài khoản (mua từ phiên T−2 trở về "
            "trước) nên bán được ngay từ phiên T.\n"
            "- **Lãi/lỗ tạm tính** = (giá đóng cửa − giá vốn) × khối lượng, chưa trừ phí và thuế.\n"
            "- Danh mục cho phép lô lẻ; khi bán thực tế, phần lô lẻ thường khớp chậm hơn và giá kém hơn.\n"
            + ("- Bản trực tuyến: danh mục chỉ nằm trong phiên trình duyệt của bạn, không lưu lên máy chủ, người "
               "khác không xem được; tải lại trang là mất.\n" if running_on_cloud() else
               "- Danh mục lưu ở file `data/danh_muc_mo_phong.json` trên máy bạn; xóa file này là xóa danh mục.\n")
        )
