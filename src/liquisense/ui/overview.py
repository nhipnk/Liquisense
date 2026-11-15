"""Trang Tổng quan thị trường."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from liquisense.sector_flow import month_label, sector_monthly
from liquisense.data.clean import QUALITY_RULES, read_quality_log, store_quality
from liquisense.insights import (
    sector_flow_insights,
    market_insights,
)
from liquisense.snapshot import (
    data_root,
)
from liquisense.ui.common import (
    BOARDS,
    Period,
    VN_TZ,
    _valid,
    alert_summary,
    board_sector_filters,
    category_axis,
    esc,
    filter_metrics,
    get_snapshot,
    history_table,
    insight_card,
    kpi_cards,
    market_value,
    md,
    page_title,
    reason_vi,
    section_head,
    segmented,
    show_chart,
    style_figure,
    table_key,
    vn,
    vn_bil,
    vn_pct,
    x_labels,
)


# --------------------------------------------------------------------------
# Trang 1 · Tổng quan thị trường
# --------------------------------------------------------------------------
def heat_card(metrics: pd.DataFrame, boards: list[str], t: dict[str, object]) -> None:
    seq, seq_fg = t["seq"], t["seqFg"]
    scored = metrics.dropna(subset=["score"])
    with st.container(border=True, key="card_heat"):
        legend = "".join(f'<i style="background:{c}"></i>' for c in seq)
        md(
            '<div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:10px;align-items:flex-start">'
            '<div><h2 class="ls-h2">Điểm thanh khoản theo ngành × sàn</h2>'
            '<p class="ls-note">Score trung bình của các mã trong ô · 12 ngành nhiều mã nhất</p></div>'
            f'<div class="ls-legend"><span>Thấp</span>{legend}<span>Cao</span>'
            f'<i style="border:1px dashed {t["muted"]};margin-left:8px"></i><span>Không đủ dữ liệu</span></div></div>'
        )
        if scored.empty:
            st.info("Chưa có mã nào đủ dữ liệu để chấm điểm trong bộ lọc này.")
            return
        top = scored["sector"].value_counts().head(12).index
        subset = scored[scored["sector"].isin(top)]
        pivot = subset.pivot_table(index="sector", columns="board", values="score", aggfunc="mean"
                                   ).reindex(columns=boards)
        counts = subset.pivot_table(index="sector", columns="board", values="score", aggfunc="count"
                                    ).reindex(index=pivot.index, columns=boards)
        pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index]
        cells = ['<div class="h" style="text-align:left">Ngành</div>'] + [f'<div class="h">{b}</div>' for b in boards]
        for sector, row in pivot.iterrows():
            cells.append(f'<div class="r" title="{esc(sector)}">{esc(sector)}</div>')
            for board in boards:
                value = row.get(board)
                if not _valid(value):
                    cells.append(f'<div class="c" style="border:1px dashed {t["line"]};color:{t["muted"]}" '
                                 f'aria-label="Không đủ dữ liệu">—</div>')
                    continue
                idx = min(4, int(float(value) // 20))
                n = counts.at[sector, board]
                label = f"Score trung bình {value:.0f} · {n:.0f} mã"
                cells.append(f'<div class="c" style="background:{seq[idx]};color:{seq_fg[idx]}" '
                             f'title="{label}" aria-label="{label}"><b>{value:.0f}</b></div>')
        grid = f"grid-template-columns:minmax(150px,1.4fr) repeat({len(boards)}, minmax(0,1fr))"
        md(f'<div class="ls-table-wrap"><div class="ls-heat" style="{grid}" role="table">{"".join(cells)}</div></div>')


@st.cache_data(show_spinner=False, max_entries=16)
def _sector_monthly(signature: str, as_of: date, board: str) -> dict:
    return sector_monthly(history_table(), as_of, 12, None if board == "Tất cả" else [board])


def sector_month_card(period: Period, board: str, t: dict[str, object]) -> None:
    """Bản đồ nhiệt ngành × tháng: dòng tiền (so với bình thường của ngành) hoặc spread trung vị."""
    with st.container(border=True, key="card_sector_month"):
        head, pick = st.columns([3, 1.4], vertical_alignment="bottom")
        with pick:
            measure = segmented("Thước đo", ["Dòng tiền", "Spread"], "sector_month_measure", "Dòng tiền")
        result = _sector_monthly(table_key(), period.as_of, board)
        scope = "toàn thị trường" if board == "Tất cả" else f"sàn {board}"
        with head:
            note = ("Giá trị giao dịch bình quân mỗi phiên của ngành so với trung bình 12 tháng của chính ngành "
                    "(100% = bình thường)" if measure == "Dòng tiền" else
                    "Spread Corwin–Schultz trung vị của các mã trong ngành, trung bình theo tháng")
            section_head(f"Thanh khoản theo ngành qua từng tháng · {scope}",
                         f"{note} · 15 ngành giao dịch nhiều nhất")
        if not result:
            st.info("Cần dữ liệu ít nhất 2 tháng đến ngày đã chọn để vẽ bản đồ nhiệt theo tháng.")
            return
        flow, spread, counts = result["flow"], result["spread"], result["counts"]
        labels = [month_label(m) + ("*" if result["partial"] and i == len(flow.columns) - 1 else "")
                  for i, m in enumerate(flow.columns)]
        rows = [f"{s} ({int(counts[s])} mã)" for s in flow.index]
        if measure == "Dòng tiền":
            z = (flow * 100).round(0)
            text = z.map(lambda v: "" if pd.isna(v) else f"{v:.0f}%")
            scale = [[0, str(t["warn"])], [0.5, str(t["surf2"])], [1, str(t["accent"])]]
            fig = go.Figure(go.Heatmap(
                z=z.values, x=labels, y=rows, text=text.values, texttemplate="%{text}", colorscale=scale,
                zmid=100, zmin=40, zmax=160, xgap=2, ygap=2,
                colorbar=dict(title=dict(text="% bình thường", side="right"), ticksuffix="%", thickness=10),
                hovertemplate="%{y}<br>%{x}: %{z:.0f}% mức trung bình của ngành<extra></extra>"))
            export = z.copy()
        else:
            z = (spread * 100).round(2)
            text = z.map(lambda v: "" if pd.isna(v) else f"{v:.2f}".replace(".", ","))
            scale = [[0, str(t["surf2"])], [0.5, str(t["warn"])], [1, str(t["bad"])]]
            fig = go.Figure(go.Heatmap(
                z=z.values, x=labels, y=rows, text=text.values, texttemplate="%{text}", colorscale=scale,
                xgap=2, ygap=2, colorbar=dict(title=dict(text="Spread %", side="right"), thickness=10),
                hovertemplate="%{y}<br>%{x}: spread trung vị %{z:.2f}%<extra></extra>"))
            export = z.copy()
        style_figure(fig, t, 36 + 30 * len(rows))
        fig.update_yaxes(autorange="reversed", showgrid=False, ticks="")
        fig.update_xaxes(side="top", type="category")
        export.columns = labels
        export.index.name = "Ngành"
        show_chart(fig, export.reset_index(), f"liquisense_nganh_theo_thang_{measure.lower()}", t, "sector_month")
        if result["partial"]:
            md('<p class="ls-note">* Tháng đang diễn ra: tính bình quân trên các phiên đã có nên vẫn so sánh được '
               'với tháng đủ phiên.</p>')
        insight_card(sector_flow_insights(result), t)


ALERT_STYLE_KEYS = {"Do": ("Đỏ", "badBg", "bad", "▲"), "Vang": ("Vàng", "warnBg", "warn", "●"),
                    "Thong bao": ("Bất thường", "infoBg", "info", "◆")}


def _alert_chip(severity: str, t: dict[str, object]) -> str:
    label, bg, fg, icon = ALERT_STYLE_KEYS.get(severity, ("Khác", "surf2", "muted", "•"))
    return f'<span class="ls-chip" style="background:{t[bg]};color:{t[fg]}">{icon}&nbsp;{label}</span>'


def alert_card(alerts: pd.DataFrame, metrics: pd.DataFrame, as_of: date, t: dict[str, object]) -> None:
    board_of = dict(zip(metrics["symbol"].astype(str), metrics["board"].astype(str)))
    with st.container(border=True, key="card_alerts"):
        md('<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">'
           '<h2 class="ls-h2">Cảnh báo mới nhất</h2>'
           f'<span style="font-size:12px;color:{t["muted"]}">phiên {as_of:%d/%m/%Y} · so với 60 phiên của chính mã</span></div>'
           '<div style="height:12px"></div>')
        if alerts.empty:
            md('<p class="ls-note">Chưa có mã nào vượt ngưỡng cảnh báo trong phiên này.</p>')
            return
        order = {"Do": 0, "Vang": 1, "Thong bao": 2}
        ordered = alerts.assign(_o=alerts["severity"].map(order)).sort_values(["_o", "symbol"])
        top, rest = ordered.head(6), ordered.iloc[6:]
        items = []
        for _, row in top.iterrows():
            reason = reason_vi(row["reason"])
            if row["severity"] == "Thong bao":
                reason += " — thông báo, không phải rủi ro"
            items.append(
                f'<li>{_alert_chip(row["severity"], t)}'
                f'<div style="display:flex;flex-direction:column;gap:2px;min-width:0">'
                f'<span style="font-weight:600"><span class="ls-mono">{esc(row["symbol"])}</span> · '
                f'<span style="color:{t["muted"]};font-weight:500">{esc(board_of.get(row["symbol"], ""))}</span></span>'
                f'<span style="font-size:13px;color:{t["text"]};line-height:1.45">{esc(alert_summary(reason))}</span>'
                f'<details class="ls-why"><summary>Xem chi tiết</summary>'
                f'<span>{"<br>".join(esc(part) for part in reason.split("; "))}</span></details></div></li>'
            )
        md(f'<ul class="ls-alerts">{"".join(items)}</ul>')
        rest = rest[rest["severity"].eq("Do")]
        if not rest.empty:
            with st.expander(f"Xem thêm {len(rest)} mã cảnh báo đỏ"):
                rows = "".join(
                    f'<tr><td>{_alert_chip(r["severity"], t)}</td>'
                    f'<td class="ls-mono" style="font-weight:600">{esc(r["symbol"])}</td>'
                    f'<td style="color:{t["muted"]}">{esc(board_of.get(r["symbol"], ""))}</td>'
                    f'<td style="font-size:13px">{"<br>".join(esc(p) for p in reason_vi(r["reason"]).split("; "))}</td></tr>'
                    for _, r in rest.iterrows()
                )
                md('<div class="ls-more"><table class="ls-table"><thead><tr><th>Mức</th><th>Mã</th><th>Sàn</th>'
                   f'<th>Lý do</th></tr></thead><tbody>{rows}</tbody></table></div>')
        md('<p class="ls-note" style="margin:12px 0 0">Đỏ: ít nhất 2 chỉ số cùng xấu đi với |z| &gt; 2, hoặc mã '
           'đóng cửa ở trần/sàn từ 8/20 phiên trở lên (kẹt trần/sàn — chưa chấm Score vì không ước lượng được spread). '
           'Mã vàng và hoạt động bất thường: xem ở tab Thanh khoản, lọc theo Màu cảnh báo.</p>')


def market_chart(series: pd.DataFrame, period: Period, scope: str, t: dict[str, object]) -> None:
    with st.container(border=True, key="card_market"):
        section_head(f"Giá trị giao dịch theo phiên · {scope}",
                     f"Tỷ đồng · {period.start:%d/%m/%Y} – {period.as_of:%d/%m/%Y} · đường = trung bình 20 phiên")
        total = series.groupby("date", as_index=False)["value"].sum().sort_values("date")
        total["ma20"] = total["value"].rolling(20, min_periods=5).mean()
        view = total[(total["date"] >= period.start) & (total["date"] <= period.as_of)]
        part = series[(series["date"] >= period.start) & (series["date"] <= period.as_of)]
        if view.empty:
            st.info("Không có phiên nào trong khoảng thời gian đã chọn.")
            return
        labels = x_labels(view["date"])
        colors = {"HOSE": t["c2"], "HNX": t["c1"], "UPCoM": t["c3"]}
        fig = go.Figure()
        for board in [b for b in BOARDS if b in set(part["board"])]:
            sub = part[part["board"].eq(board)]
            fig.add_trace(go.Bar(
                x=x_labels(sub["date"]), y=sub["value"] / 1e9, name=board,
                marker_color=str(colors.get(board, t["c3"])),
                hovertemplate="%{x}<br>" + board + ": %{y:,.0f} tỷ<extra></extra>",
            ))
        fig.add_trace(go.Scatter(
            x=labels, y=view["ma20"] / 1e9, name="TB 20 phiên", mode="lines", connectgaps=True,
            line=dict(color=str(t["text"]), width=2),
            hovertemplate="%{x}<br>TB 20 phiên: %{y:,.0f} tỷ<extra></extra>",
        ))
        style_figure(fig, t, 300)
        fig.update_layout(barmode="stack", bargap=0.15)
        fig.update_yaxes(ticksuffix=" tỷ")
        category_axis(fig, labels)
        export = part.pivot_table(index="date", columns="board", values="value", aggfunc="sum").reset_index()
        export["Tổng"] = export.drop(columns="date").sum(axis=1)
        export = export.rename(columns={"date": "Ngày"})
        show_chart(fig, export, f"liquisense_gtgd_{period.as_of.isoformat()}", t, "market")


def score_chart(metrics: pd.DataFrame, t: dict[str, object]) -> None:
    with st.container(border=True, key="card_dist"):
        section_head("Phân bố Score thanh khoản", "Số mã theo từng khoảng điểm · màu theo sàn")
        scored = metrics.dropna(subset=["score"])
        if scored.empty:
            st.info("Chưa có mã đủ dữ liệu.")
            return
        bins = list(range(0, 101, 10))
        labels = [f"{b}–{b + 10}" for b in bins[:-1]]
        colors = {"HOSE": t["c2"], "HNX": t["c1"], "UPCoM": t["c3"]}
        fig = go.Figure()
        table: dict[str, object] = {"Khoảng Score": labels}
        for board in [b for b in BOARDS if b in set(scored["board"])]:
            sub = scored[scored["board"].eq(board)]
            counts = pd.cut(sub["score"], bins=bins, labels=labels, include_lowest=True).value_counts().reindex(labels)
            table[board] = counts.values
            fig.add_trace(go.Bar(x=labels, y=counts.values, name=board, marker_color=str(colors[board]),
                                 hovertemplate="Score %{x}<br>" + board + ": %{y} mã<extra></extra>"))
        style_figure(fig, t, 300)
        fig.update_layout(barmode="stack", bargap=0.15)
        fig.update_yaxes(title_text="Số mã")
        show_chart(fig, pd.DataFrame(table), "liquisense_phan_bo_score", t, "score")




def overview_page(period: Period, t: dict[str, object]) -> None:
    metrics, alerts = get_snapshot(period)
    if metrics.empty:
        st.warning("Không có dữ liệu cho thời gian đã chọn.")
        return
    page_title("Tổng quan thị trường", f"Bức tranh thanh khoản {period.label} · chỉ số {period.basis}", "overview")
    board, sector, _, _ = board_sector_filters(metrics, "ov")
    scope = "toàn thị trường" if board == "Tất cả" else f"sàn {board}"
    if sector != "Tất cả ngành":
        scope += f" · {sector}"

    fm = filter_metrics(metrics, board, sector)
    fa = alerts[alerts["symbol"].isin(fm["symbol"])] if not alerts.empty else alerts
    eligible = int(fm["status"].eq("Du du lieu").sum())
    series = market_value(board, sector)
    per_day = series.groupby("date")["value"].sum()
    ratio = change = np.nan
    if period.is_range:
        inside = per_day[(per_day.index >= period.start) & (per_day.index <= period.end)]
        before = per_day[per_day.index < period.start].tail(len(inside))
        value_label = "GTGD bình quân phiên"
        value_text = vn_bil(inside.mean()) if not inside.empty else "—"
        change = inside.mean() / before.mean() - 1 if len(before) and before.mean() > 0 else np.nan
        value_sub = (f"Tổng {vn_bil(inside.sum())} · {len(inside)} phiên"
                     + (f" · {'+' if change >= 0 else ''}{vn(change * 100)}% so với khoảng trước" if _valid(change) else ""))
    else:
        upto = per_day[per_day.index <= period.as_of]
        last_value = upto.iloc[-1] if not upto.empty and upto.index[-1] == period.as_of else np.nan
        mean20 = upto.tail(20).mean() if not upto.empty else np.nan
        ratio = last_value / mean20 if _valid(last_value) and _valid(mean20) and mean20 > 0 else np.nan
        value_label = "Giá trị giao dịch phiên"
        value_text = vn_bil(last_value)
        value_sub = f"Bằng {vn(ratio * 100)}% trung bình 20 phiên" if _valid(ratio) else "Chưa đủ dữ liệu so sánh"
    spreads = fm.loc[fm["status"].eq("Du du lieu"), "spread"].dropna()
    counts = fa["severity"].value_counts() if not fa.empty else pd.Series(dtype=int)
    red, yellow, info = (int(counts.get(k, 0)) for k in ("Do", "Vang", "Thong bao"))
    kpi_cards([
        ("Spread ước lượng · trung bình các mã", vn_pct(spreads.mean()) if not spreads.empty else "—",
         f"{scope} · {vn(len(spreads))} mã đủ dữ liệu", str(t["muted"])),
        (f"{value_label} · {board if board != 'Tất cả' else 'toàn thị trường'}", value_text, value_sub,
         str(t["muted"])),
        (f"Mã cảnh báo · phiên {period.as_of:%d/%m}", f"{red} · {yellow}",
         f"{red} đỏ · {yellow} vàng · {info} hoạt động bất thường", str(t["bad"] if red else t["muted"])),
        ("Độ phủ dữ liệu", vn_pct(eligible / len(fm), 1) if len(fm) else "—",
         f"{vn(eligible)} đủ · {vn(len(fm) - eligible)} thiếu · trên {vn(len(fm))} mã", str(t["muted"])),
    ])

    insight_card(market_insights(
        fm, fa, scope=scope,
        day_ratio=None if period.is_range else ratio,
        range_change=change if period.is_range else None,
        compare_boards=board == "Tất cả",
    ), t)

    left, right = st.columns([1.55, 1], gap="medium")
    with left:
        market_chart(series, period, scope, t)
    with right:
        alert_card(fa, metrics, period.as_of, t)
    left, right = st.columns([1.55, 1], gap="medium")
    with left:
        heat_card(fm, BOARDS if board == "Tất cả" else [board], t)
    with right:
        score_chart(fm, t)
    sector_month_card(period, board, t)
    quality_card(t)


@st.cache_data(show_spinner=False, max_entries=2)
def _store_quality(signature: str) -> dict[str, object]:
    table = history_table()
    return store_quality(table[[c for c in ("date", "symbol", "volume", "no_bar") if c in table]])


QUALITY_ACTION = {
    "missing_key": "Loại bỏ", "bad_type": "Loại bỏ", "missing_price": "Loại bỏ", "non_positive_price": "Loại bỏ",
    "negative_volume": "Loại bỏ", "high_below_low": "Loại bỏ", "open_close_outside": "Loại bỏ",
    "outside_band": "Giữ nguyên; trần/sàn xét theo tỷ lệ biên độ", "duplicate": "Giữ bản tải mới nhất",
}


def quality_card(t: dict[str, object]) -> None:
    """Bằng chứng chất lượng dữ liệu: kiểm tra lúc tải về (theo nhật ký) và tình trạng kho hiện tại."""
    root = data_root()
    log = read_quality_log(root)
    store = _store_quality(table_key())
    failed_path = root / "ma_loi.txt"
    failed = [x for x in failed_path.read_text(encoding="utf-8").split() if x] if failed_path.exists() else []
    with st.expander("Chất lượng dữ liệu · kiểm tra và xử lý"):
        if store:
            kpi_cards([
                ("Bản ghi nến ngày trong kho", vn(store["rows"]), f"{vn(store['symbols'])} mã cổ phiếu",
                 str(t["muted"])),
                ("Số phiên đã lưu", vn(store["sessions"]),
                 f"{store['first']:%d/%m/%Y} – {store['latest']:%d/%m/%Y}", str(t["muted"])),
                ("Trùng mã–ngày còn lại", vn(store["duplicates"]), "Đã khử trùng khi ghi kho",
                 str(t["ok"] if store["duplicates"] == 0 else t["bad"])),
                ("Mã đang lỗi tải", vn(len(failed)), "Chạy lại với --chi-ma-loi" if failed else "Không có mã lỗi",
                 str(t["warn"] if failed else t["muted"])),
            ])

        # 1) Kiểm tra từng bản ghi lúc tải về
        if log.empty:
            md('<p class="ls-note">Chưa có nhật ký kiểm tra — sẽ được ghi từ lần chạy scripts/update.py tiếp theo '
               '(tệp data/chat_luong_du_lieu.csv).</p>')
        else:
            total = {key: int(log[key].sum()) for key, _ in QUALITY_RULES if key in log}
            last = log.iloc[-1]
            raw_total = int(log["ban_ghi_tai_ve"].sum())
            rows = "".join(
                f'<tr><td>{esc(label)}</td><td class="num">{vn(int(last.get(key, 0)))}</td>'
                f'<td class="num">{vn(total.get(key, 0))}</td><td>{QUALITY_ACTION[key]}</td></tr>'
                for key, label in QUALITY_RULES
            )
            rows += (f'<tr><td>Bản ghi đã có trong kho được thay bằng bản tải mới</td>'
                     f'<td class="num">{vn(int(last.get("ghi_de_ban_cu", 0)))}</td>'
                     f'<td class="num">{vn(int(log.get("ghi_de_ban_cu", pd.Series([0])).sum()))}</td>'
                     f'<td>Ghi đè theo mã–ngày (chạy lại không tạo bản trùng)</td></tr>')
            try:
                stamp = datetime.fromisoformat(str(last["thoi_diem"])).astimezone(VN_TZ).strftime("%H:%M %d/%m/%Y")
            except ValueError:
                stamp = str(last["thoi_diem"])
            md('<h2 class="ls-h2" style="margin-top:6px !important">Kiểm tra từng bản ghi khi tải từ SSI</h2>'
               f'<p class="ls-note">{vn(len(log))} lần cập nhật · lần gần nhất {esc(stamp)} (giờ Việt Nam): tải '
               f'{vn(int(last["ban_ghi_tai_ve"]))} bản ghi, giữ {vn(int(last["ban_ghi_hop_le"]))}. Tổng cộng đã tải '
               f'{vn(raw_total)} bản ghi. Mỗi bản ghi lỗi chỉ đếm ở lỗi đầu tiên.</p>'
               '<div class="ls-table-wrap"><table class="ls-table" style="min-width:620px"><thead><tr>'
               '<th>Kiểm tra</th><th style="text-align:right">Lần gần nhất</th>'
               '<th style="text-align:right">Tất cả các lần</th><th>Xử lý</th>'
               f'</tr></thead><tbody>{rows}</tbody></table></div>')

        # 2) Tình trạng kho và cách xử lý khi tính chỉ số
        if store:
            late = store["late_list"]
            late_text = ", ".join(late[:12]) + (f" và {len(late) - 12} mã khác" if len(late) > 12 else "")
            items = [
                ("Phiên khối lượng = 0", vn(store["zero_volume_rows"]),
                 "Giữ lại; tính là ngày không giao dịch, không tính spread/Amihud ngày đó"),
                ("Phiên mã không có nến (SSI không trả)", f'{vn(store["symbols_with_gaps"])} mã · {vn(store["missing_sessions"])} phiên',
                 "Chèn vào với khối lượng = 0: tính là ngày không giao dịch và kéo ADV xuống; không nội suy giá"),
                ("Mã chưa có phiên mới nhất", vn(store["late_symbols"]),
                 "Dữ liệu đến muộn, tạm ngừng hoặc hủy niêm yết; không có Score ở phiên mới nhất"
                 + (f" ({esc(late_text)})" if late else "")),
                ("Mất kết nối / token hết hạn", "Tự xử lý",
                 "Tự lấy lại token trước khi hết hạn; thử lại khi lỗi; ghi kho sau mỗi 200 mã; mã lỗi lưu vào ma_loi.txt"),
                ("Giới hạn tần suất", "≤ 5 yêu cầu/giây", "Bộ giới hạn tốc độ ở client; dashboard không gọi API"),
            ]
            rows = "".join(f'<tr><td>{esc(a)}</td><td class="num">{b}</td><td>{c}</td></tr>' for a, b, c in items)
            md('<h2 class="ls-h2" style="margin-top:10px !important">Tình trạng kho dữ liệu</h2>'
               '<div class="ls-table-wrap"><table class="ls-table" style="min-width:620px"><thead><tr>'
               '<th>Tình huống</th><th style="text-align:right">Số lượng</th><th>Xử lý</th>'
               f'</tr></thead><tbody>{rows}</tbody></table></div>')
        if not log.empty:
            st.download_button("Tải nhật ký chất lượng (CSV)", data=log.to_csv(index=False).encode("utf-8-sig"),
                               file_name="chat_luong_du_lieu.csv", mime="text/csv", icon=":material/download:",
                               on_click="ignore", key="dl_quality")
