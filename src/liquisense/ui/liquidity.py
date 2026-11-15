"""Trang Thanh khoản từng mã (kèm phương pháp, độ nhạy trọng số, kiểm định ngoài mẫu)."""

from __future__ import annotations


import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from liquisense.sector_flow import sector_trend
from liquisense.finance import score_rank, score_weight_sensitivity
from liquisense.insights import (
    stock_insights,
)
from liquisense.snapshot import (
    data_root,
)
from liquisense.ui.common import (
    BOARDS,
    LEVEL_VI,
    PDF_READY,
    Period,
    SELL_TAX_PCT,
    STATUS_VI,
    _alpha,
    _valid,
    alert_levels,
    alert_reasons,
    alert_summary,
    board_sector_filters,
    category_axis,
    esc,
    filter_metrics,
    get_snapshot,
    history_table,
    insight_card,
    kpi_cards,
    md,
    page_title,
    section_head,
    segmented,
    show_chart,
    status_badge,
    style_figure,
    symbol_history,
    table_key,
    vn,
    vn_bil,
    vn_pct,
    vn_sig,
    x_labels,
)


# --------------------------------------------------------------------------
# Trang 2 · Thanh khoản từng mã
# --------------------------------------------------------------------------
def ranking_card(metrics: pd.DataFrame, levels: dict[str, str], period: Period, t: dict[str, object]) -> pd.DataFrame:
    with st.container(border=True, key="card_rank"):
        head, search_col, sort_col, size_col = st.columns([2.6, 1.2, 1.4, 0.8], vertical_alignment="bottom")
        with head:
            section_head("Bảng xếp hạng thanh khoản",
                         f"Chỉ số {period.basis} · Score là thứ hạng tương đối, không phải xác suất")
        query = search_col.text_input("Tìm mã", placeholder="Tìm mã…", key="rank_search").strip().upper()
        sorts = {
            "Score cao → thấp": ("score", False),
            "Spread thấp → cao": ("spread", True),
            "Amihud thấp → cao": ("amihud", True),
            "ADV giá trị cao → thấp": ("adv_value", False),
        }
        sort_label = sort_col.selectbox("Sắp xếp", list(sorts), key="rank_sort")
        size = size_col.selectbox("Hiển thị", [25, 50, 100, 500], key="rank_size")

        frame = metrics.copy()
        frame["rank"] = score_rank(frame["score"])  # hạng tính trên cả danh sách đang lọc, trước khi tìm mã
        if query:
            frame = frame[frame["symbol"].astype(str).str.contains(query, regex=False)]
        field, ascending = sorts[sort_label]
        if field == "score":  # cùng điểm thì giữ thứ tự theo mã cho dễ dò
            frame = frame.sort_values(["rank", "symbol"], na_position="last").reset_index(drop=True)
        else:
            frame = frame.sort_values(field, ascending=ascending, na_position="last").reset_index(drop=True)
        shown = frame.head(size)

        rows = []
        for i, r in shown.iterrows():
            if _valid(r["score"]):
                score = (f'<div class="ls-bar"><b>{r["score"]:.0f}</b>'
                         f'<span><i style="width:{max(0, min(100, r["score"])):.0f}%"></i></span></div>')
            else:
                score = f'<span style="color:{t["muted"]}">Không có Score</span>'
            rows.append(
                f'<tr><td class="ls-stt">{int(r["rank"]) if _valid(r["rank"]) else "—"}</td>'
                f'<td class="ls-mono" style="font-weight:600">{esc(r["symbol"])}</td>'
                f'<td style="color:{t["muted"]}">{esc(r["board"])}</td>'
                f'<td>{esc(r["sector"])}</td><td style="width:200px">{score}</td>'
                f'<td class="num">{vn_pct(r["spread"])}</td><td class="num">{vn_sig(r["amihud"])}</td>'
                f'<td class="num">{vn_bil(r["adv_value"])}</td>'
                f'<td>{status_badge(str(r["symbol"]), r["status"], levels, t)}</td></tr>'
            )
        if rows:
            md(
                '<div class="ls-table-wrap"><table class="ls-table"><thead><tr>'
                '<th>Hạng</th><th>Mã</th><th>Sàn</th><th>Ngành</th><th>Score</th>'
                '<th style="text-align:right">Spread ước lượng</th><th style="text-align:right">Amihud</th>'
                '<th style="text-align:right">ADV giá trị</th><th>Trạng thái</th>'
                f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            )
        else:
            st.info("Không có mã nào khớp bộ lọc.")
        caption_col, button_col = st.columns([3, 1], vertical_alignment="center")
        caption_col.caption(f"Hiển thị {len(shown)} / {len(frame)} mã · {period.label}")
        export = frame[["rank", "symbol", "board", "sector", "score", "spread", "amihud", "adv_value", "status"]].copy()
        export["rank"] = export["rank"].astype("Int64")
        export["status"] = export["status"].map(STATUS_VI).fillna("Chưa xác định")
        export["Cảnh báo"] = export["symbol"].map(levels).map(LEVEL_VI).fillna("")
        export = export.rename(columns={
            "rank": "Hạng", "symbol": "Mã", "board": "Sàn", "sector": "Ngành", "score": "Score",
            "spread": "Spread ước lượng", "amihud": "Amihud", "adv_value": "ADV giá trị (đồng)",
            "status": "Tình trạng dữ liệu",
        })
        button_col.download_button(
            "Xuất CSV", export.to_csv(index=False).encode("utf-8-sig"), icon=":material/download:",
            file_name=f"liquisense_xep_hang_{period.as_of.isoformat()}.csv", mime="text/csv", width="stretch",
            on_click="ignore",
        )
    return frame


WINDOW_OPTIONS = ["10 phiên", "20 phiên", "60 phiên"]
WINDOW_NOTE = "Score và cảnh báo luôn dùng 20 phiên — mức đã được kiểm định."


def window_selector(key: str, label: str = "Cửa sổ trung bình") -> int:
    """Chọn số phiên làm mượt (10/20/60, mặc định 20) — chỉ dùng cho khám phá dữ liệu và kịch bản."""
    choice = segmented(label, WINDOW_OPTIONS, key, "20 phiên")
    return int(choice.split()[0])


def rolling_series(history: pd.DataFrame, metric: str, window: int) -> pd.Series:
    """Đường làm mượt theo cửa sổ người dùng chọn, tính lại từ giá trị ngày."""
    minimum = max(3, window // 2)
    if metric == "Spread":
        return history["spread_daily"].rolling(window, min_periods=minimum).mean()
    if metric == "Amihud":
        return history["amihud_daily"].rolling(window, min_periods=minimum).mean()
    volume_ok = history["volume"].notna() & (history["volume"] >= 0)
    return history["value"].where(volume_ok).rolling(window, min_periods=minimum).mean()


def history_chart(symbol: str, period: Period, levels: dict[str, str], t: dict[str, object], key: str) -> None:
    c1, c2, c3 = st.columns([1.2, 1.2, 2.2], vertical_alignment="bottom")
    with c1:
        metric = segmented("Chỉ số", ["Spread", "Amihud", "ADV"], key, "Amihud")
    with c2:
        window = window_selector(f"{key}_window")
    with c3:
        md(f'<p class="ls-note" style="margin:0 0 10px">{WINDOW_NOTE}</p>')
    defs = {
        "Spread": ("spread ước lượng", "spread_daily", 100, "%"),
        "Amihud": ("Amihud", "amihud_daily", 1, ""),
        "ADV": ("giá trị giao dịch (tỷ đồng)", "value", 1e-9, " tỷ"),
    }
    name, daily_col, scale, suffix = defs[metric]
    history = symbol_history(symbol, period.as_of)
    md(f'<p class="ls-note" style="margin:6px 0 4px">Lịch sử {esc(name)} · {esc(symbol)} · '
       f'{period.start:%d/%m/%Y} – {period.as_of:%d/%m/%Y}</p>')
    if history.empty:
        st.info("Chưa có lịch sử cho mã này.")
        return
    history = history.assign(_smooth=rolling_series(history, metric, window))
    view = history[(history["date"].dt.date >= period.start) & (history["date"].dt.date <= period.as_of)]
    if view.empty:
        st.info("Mã này không có phiên nào trong khoảng thời gian đã chọn.")
        return
    labels = x_labels(view["date"])
    daily = (view[daily_col] * scale).astype("float64")
    smooth = (view["_smooth"] * scale).astype("float64")
    fmt = {"Spread": lambda v: f"{vn(v, 2)}%", "Amihud": lambda v: vn_sig(v),
           "ADV": lambda v: f"{vn(v, 1)} tỷ"}[metric]
    hover_fmt = {"Spread": ":.2f", "Amihud": ":.3g", "ADV": ":,.1f"}[metric]

    # Hàng số liệu tóm tắt phía trên biểu đồ
    latest = smooth.dropna().iloc[-1] if smooth.notna().any() else np.nan
    period_mean = daily.mean()
    peak_idx = daily.idxmax() if daily.notna().any() else None
    peak_text = (f"{fmt(daily.loc[peak_idx])} · {view.loc[peak_idx, 'date']:%d/%m}" if peak_idx is not None else "—")
    zero_share = (daily == 0).mean() if metric == "Spread" else np.nan
    observed = int(daily.notna().sum()) if metric != "ADV" else int(view["volume"].gt(0).sum())
    traded = int(view["volume"].gt(0).sum())
    chips = [
        (f"TB {window} phiên hiện tại", fmt(latest) if _valid(latest) else "—"),
        ("Trung bình cả khoảng", fmt(period_mean) if _valid(period_mean) else "—"),
        ("Cao nhất trong ngày", peak_text),
        ("Phiên có số liệu", f"{vn(observed)}/{vn(len(view))}"),
    ]
    if _valid(zero_share):
        chips.append(("Ngày ước lượng = 0", vn_pct(zero_share, 0)))
    md('<div class="ls-chips">' + "".join(
        f'<div><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in chips) + '</div>')
    # Mã ít giao dịch: giải thích vì sao biểu đồ thưa và thiếu đường trung bình.
    notes = []
    if smooth.notna().sum() < len(view) * 0.5:
        need = {"Spread": "cả phiên đó và phiên liền trước cùng có khớp lệnh, không chạm trần/sàn",
                "Amihud": "cả phiên đó và phiên liền trước cùng có khớp lệnh, không chạm trần/sàn",
                "ADV": "phiên có khớp lệnh"}[metric]
        notes.append(f"{esc(symbol)} chỉ có <b>{vn(traded)}/{vn(len(view))} phiên có giao dịch</b> và "
                     f"<b>{vn(observed)} phiên tính được {esc(name)}</b> (cần {need}). Đường trung bình {window} phiên "
                     f"cần ít nhất {vn(max(3, window // 2))} phiên có số liệu trong mỗi cửa sổ nên "
                     + ("không vẽ được" if smooth.isna().all() else "chỉ vẽ được ở một vài đoạn")
                     + " — dấu hiệu thanh khoản rất kém.")
    last_trade = view.loc[view["volume"].gt(0), "date"].max()
    if pd.notna(last_trade) and (view["date"] > last_trade).sum() >= 5:
        notes.append(f"Không có giao dịch nào từ sau phiên {last_trade:%d/%m/%Y} "
                     f"({vn(int((view['date'] > last_trade).sum()))} phiên gần nhất) nên cuối biểu đồ để trống.")
    elif pd.isna(last_trade):
        notes.append("Mã không có giao dịch nào trong khoảng thời gian đã chọn.")
    if notes:
        title = ("Vì sao không vẽ được đường trung bình?" if smooth.isna().all() and observed
                 else "Vì sao biểu đồ thưa?" if observed else "Không có dữ liệu để vẽ")
        md(f'<div class="ls-callout"><div class="ico">!</div><div><h4>{title}</h4>'
           + "".join(f"<p>{n}</p>" for n in notes) + "</div></div>")

    accent, muted = str(t["accent"]), str(t["muted"])
    fig = go.Figure()
    if metric == "ADV":
        # Giá trị giao dịch: cột mờ cho từng phiên, đường làm mượt nổi bật phía trên.
        fig.add_trace(go.Bar(
            x=labels, y=daily, name="Giá trị từng phiên", marker_color=_alpha(muted, 0.28),
            marker_line_width=0, hovertemplate="%{y" + hover_fmt + "}" + suffix + "<extra>Phiên</extra>",
        ))
        y_cap = None
    else:
        # Spread/Amihud ngày rất nhiễu: vẽ dạng chấm nhỏ; giá trị đột biến bị cắt ở mép trên
        # (đánh dấu tam giác, rê chuột vẫn thấy số thật) để không đè bẹp đường xu hướng.
        top = max(float(np.nanmax(smooth)) if smooth.notna().any() else 0.0,
                  float(daily.quantile(0.95)) if daily.notna().any() else 0.0)
        y_cap = top * 1.35 if top > 0 else None
        inside = daily if y_cap is None else daily.where(daily <= y_cap)
        fig.add_trace(go.Scatter(
            x=labels, y=inside, mode="markers", name="Giá trị từng phiên",
            marker=dict(size=5, color=_alpha(muted, 0.55)),
            hovertemplate="%{y" + hover_fmt + "}" + suffix + "<extra>Phiên</extra>",
        ))
        if y_cap is not None and (daily > y_cap).any():
            over = daily > y_cap
            fig.add_trace(go.Scatter(
                x=[lab for lab, o in zip(labels, over) if o], y=[y_cap * 0.985] * int(over.sum()),
                customdata=daily[over].values, mode="markers", name="Vượt khung",
                marker=dict(symbol="triangle-up", size=9, color=str(t["warn"])),
                hovertemplate="%{customdata" + hover_fmt + "}" + suffix + "<extra>Đột biến</extra>",
            ))
    fig.add_trace(go.Scatter(
        x=labels, y=smooth, mode="lines", name=f"Trung bình {window} phiên", connectgaps=True,
        line=dict(color=accent, width=2.6, shape="spline", smoothing=0.6),
        fill="tozeroy", fillcolor=_alpha(accent, 0.10),
        hovertemplate="%{y" + hover_fmt + "}" + suffix + f"<extra>TB {window} phiên</extra>",
    ))
    if _valid(period_mean):
        fig.add_hline(y=period_mean, line_dash="dot", line_width=1, line_color=muted,
                      annotation_text=f"TB cả khoảng {fmt(period_mean)}", annotation_position="top left",
                      annotation_font=dict(size=11, color=muted))
    if _valid(latest):
        last_label = labels[int(np.flatnonzero(smooth.notna().values)[-1])]
        alert = levels.get(symbol)
        dot = str(t["bad"]) if alert == "Do" else str(t["warn"]) if alert == "Vang" else accent
        fig.add_trace(go.Scatter(
            x=[last_label], y=[latest], mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(size=10, color=dot, line=dict(width=2.5, color=str(t["surf"]))),
        ))
        fig.add_annotation(x=last_label, y=latest, text=f"<b>{fmt(latest)}</b>", showarrow=False,
                           xanchor="right", yanchor="bottom", xshift=-6, yshift=6,
                           font=dict(size=12, color=dot), bgcolor=_alpha(str(t["surf"]), 0.85))
    style_figure(fig, t, 340)
    fig.update_layout(
        hovermode="x unified", bargap=0.25, margin=dict(l=4, r=12, t=36, b=4),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(size=12, color=str(t["text"]))),
    )
    fig.update_yaxes(ticksuffix=suffix, rangemode="tozero", nticks=6,
                     gridcolor=_alpha(str(t["line"]), 0.7),
                     range=[0, y_cap * 1.04] if y_cap else None)
    fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1, spikedash="dot",
                     spikecolor=muted)
    category_axis(fig, labels)
    export = pd.DataFrame({"Ngày": view["date"].dt.date, f"{name} · ngày": daily.values,
                           f"{name} · TB {window} phiên": smooth.values})
    show_chart(fig, export, f"liquisense_{symbol}_{metric.lower()}_{window}phien", t, f"hist_{key}")
    st.caption("Trục ngang gồm các phiên giao dịch (đã loại bỏ cuối tuần, nghỉ lễ).")


def symbol_picker(metrics: pd.DataFrame, prefix: str, require_choice: bool = False) -> str | None:
    """Chọn mã giống bộ lọc bảng xếp hạng: sàn, ngành, ô tìm mã, rồi chọn trong danh sách."""
    cols = st.columns([1.7, 1.5, 1.1, 1.4], vertical_alignment="bottom")
    with cols[0]:
        board = segmented("Sàn", ["Tất cả"] + BOARDS, f"{prefix}_board", "Tất cả")
    sectors = sorted(metrics["sector"].dropna().astype(str).unique().tolist())
    sector = cols[1].selectbox("Ngành", ["Tất cả ngành"] + sectors, key=f"{prefix}_sector")
    query = cols[2].text_input("Tìm mã", placeholder="Tìm mã…", key=f"{prefix}_search").strip().upper()
    pool = filter_metrics(metrics, board, sector)
    symbols = sorted(pool["symbol"].astype(str).tolist())
    if query:
        exact = [s for s in symbols if s == query]
        symbols = exact + [s for s in symbols if query in s and s != query]
        if not symbols and query in set(metrics["symbol"].astype(str)):
            symbols = [query]  # gõ đúng mã nhưng khác sàn/ngành đang lọc vẫn cho xem
    if not symbols:
        cols[3].selectbox("Mã cổ phiếu", ["—"], disabled=True, key=f"{prefix}_none")
        st.warning(f"Không tìm thấy mã {query} trong bộ lọc hiện tại hoặc trong kho dữ liệu." if query
                   else "Không có mã nào trong bộ lọc này.")
        return None
    sector_of = dict(zip(metrics["symbol"].astype(str), metrics["sector"].astype(str)))
    # require_choice: chưa chọn sẵn mã nào; gõ đúng một mã vào ô tìm thì chọn luôn mã đó.
    index = 0 if not require_choice or (query and symbols[0] == query) else None
    return cols[3].selectbox(f"Mã cổ phiếu ({len(symbols)} mã)", symbols, index=index,
                             placeholder="Chọn mã…",
                             format_func=lambda s: f"{s} · {sector_of.get(s, '')}",
                             key=f"{prefix}_symbol_{board}_{sector}_{query}")


def rank_of(symbol: str, listed: pd.DataFrame, metrics: pd.DataFrame) -> tuple[int | None, int, str]:
    """Hạng của mã đúng như cột Hạng trên bảng xếp hạng (cùng bộ lọc). Nếu mã không nằm trong danh sách
    đang lọc thì xếp trên toàn thị trường."""
    if listed["symbol"].eq(symbol).any():
        frame = listed
        scope = "toàn thị trường" if len(listed) == len(metrics) else "trong danh sách đang lọc"
    else:
        frame, scope = metrics, "toàn thị trường"
    ranks = score_rank(frame["score"])
    mine = ranks[frame["symbol"].eq(symbol)].iloc[0]
    return (int(mine) if _valid(mine) else None), int(ranks.notna().sum()), scope


def missing_data_reasons(symbol: str, row: pd.Series, period: Period) -> list[str]:
    """Lý do cụ thể khiến mã "Không đủ dữ liệu" (đếm trên đúng cửa sổ/khoảng đang xem)."""
    history = symbol_history(symbol, period.as_of)
    if period.mode == "day":
        window = history.tail(20)
        scope = "20 phiên gần nhất"
    else:
        window = history[history["date"].dt.date >= period.start]
        scope = "khoảng đã chọn"
    n = len(window)
    traded = int(window["volume"].gt(0).sum()) if n else 0
    need = 10
    out = []
    if len(history) < 20:
        out.append(f"Mã mới có <b>{vn(len(history))} phiên</b> lịch sử trong kho dữ liệu (mới niêm yết hoặc mới "
                   "chuyển sàn).")
    if not _valid(row.get("adv_value")) or not _valid(row.get("zero_days")):
        out.append(f"ADV và tỷ lệ ngày không giao dịch: chỉ <b>{vn(n)} phiên</b> có dữ liệu trong {scope} "
                   f"(cần {need}).")
    if traded < n:
        out.append(f"Chỉ <b>{vn(traded)}/{vn(n)} phiên có giao dịch</b> trong {scope} — mã giao dịch thưa thớt.")
    if not _valid(row.get("spread")):
        k = int(window["spread_daily"].notna().sum()) if n else 0
        out.append(f"Spread: chỉ <b>{vn(k)} phiên ước lượng được</b> (cần {need}). Mỗi ước lượng cần hai phiên liền "
                   "nhau cùng có khớp lệnh và không chạm trần/sàn.")
    if not _valid(row.get("amihud")):
        k = int(window["amihud_daily"].notna().sum()) if n else 0
        out.append(f"Amihud: chỉ <b>{vn(k)} phiên tính được</b> (cần {need}), vì cần giá của phiên liền trước để "
                   "tính lợi suất.")
    if not out:
        out.append("Một hoặc nhiều chỉ số (spread, Amihud, ADV, tỷ lệ ngày không giao dịch) chưa tính được.")
    return out


def pdf_button(symbol: str, row: pd.Series, metrics: pd.DataFrame, level: str | None, period: Period,
               ranking: tuple[int | None, int, str], reason: str | None = None) -> None:
    """Nút xuất báo cáo PDF của một mã: tổng hợp chỉ số, nhận xét, biểu đồ, so sánh ngành và chi phí."""
    if not PDF_READY:
        st.button("Xuất báo cáo PDF", icon=":material/picture_as_pdf:", disabled=True, key="pdf_off",
                  help="Cần cài thêm: python -m pip install reportlab matplotlib")
        return

    if row.get("status") == "Khong du du lieu":
        reasons = missing_data_reasons(symbol, row, period)
        md('<div class="ls-callout"><div class="ico">!</div><div>'
           f'<h4>Chưa xuất được báo cáo PDF cho {esc(symbol)}</h4>'
           '<p>Mã chưa đủ dữ liệu để tính đủ các chỉ số thanh khoản trong kỳ đã chọn, nên báo cáo sẽ gần như '
           'toàn dấu “—” và các nhận xét, so sánh, chi phí đều không có cơ sở. Cụ thể:</p>'
           + "".join(f"<p>• {r}</p>" for r in reasons)
           + '<p>Thử chọn <b>khoảng thời gian dài hơn</b> ở thanh thời gian phía trên, hoặc chọn mã khác.</p>'
           '</div></div>')
        st.button("Xuất báo cáo PDF", icon=":material/picture_as_pdf:", disabled=True, key=f"pdf_off_{symbol}",
                  help="Mã chưa đủ dữ liệu trong kỳ đã chọn")
        return

    def build() -> bytes:
        from liquisense.report import ReportContext, build_stock_report

        history = symbol_history(symbol, period.as_of)
        data_end = pd.Timestamp(history_table()["date"].max()).date()
        context = ReportContext(symbol=symbol, period_label=period.basis, chart_start=period.start,
                                as_of=period.as_of, data_end=data_end, sell_tax=SELL_TAX_PCT / 100,
                                rank=ranking[0], rank_total=ranking[1], rank_scope=ranking[2], alert_reason=reason,
                                sector_trend=sector_trend(history_table(), str(row.get("sector", "")), period.as_of))
        return build_stock_report(row, metrics, history, level, context)

    st.download_button("Xuất báo cáo PDF", data=build, file_name=f"LiquiSense_{symbol}_{period.as_of:%Y%m%d}.pdf",
                       mime="application/pdf", icon=":material/picture_as_pdf:", on_click="ignore",
                       key=f"pdf_{symbol}", help="Báo cáo đầy đủ: chỉ số, nhận xét chi tiết, so sánh ngành, "
                                                 "biểu đồ và chi phí theo quy mô lệnh")


def liquidity_page(period: Period, t: dict[str, object]) -> None:
    metrics, alerts = get_snapshot(period)
    if metrics.empty:
        st.warning("Không có dữ liệu cho thời gian đã chọn.")
        return
    eligible = int(metrics["status"].eq("Du du lieu").sum())
    page_title("Thanh khoản cổ phiếu",
               f"Xếp hạng và hồ sơ thanh khoản từng mã · {period.label} · "
               f"{vn(eligible)} / {vn(len(metrics))} mã đủ dữ liệu để chấm điểm", "liquidity")
    levels = alert_levels(alerts)
    reasons = alert_reasons(alerts)
    board, sector, tier, alert = board_sector_filters(metrics, "lq", with_tier=True, with_alert=True)
    listed = filter_metrics(metrics, board, sector, tier, alert, levels)
    ranking_card(listed, levels, period, t)

    with st.container(border=True, key="card_profile"):
        section_head("Hồ sơ thanh khoản một mã",
                     "Lọc theo sàn, ngành hoặc gõ mã vào ô tìm kiếm, rồi chọn mã trong danh sách")
        symbol = symbol_picker(metrics, "pf", require_choice=True)
        if not symbol:
            md('<div class="ls-empty"><div class="ico">🔎</div><h4>Chọn một mã để xem hồ sơ thanh khoản</h4>'
               '<p>Gõ mã vào ô <b>Tìm mã</b> hoặc chọn trong danh sách <b>Mã cổ phiếu</b> phía trên '
               '(có thể lọc trước theo sàn, ngành).</p>'
               '<ul><li>Score và hạng</li><li>Spread · Amihud · ADV</li><li>Nhận xét tự động</li>'
               '<li>Lý do cảnh báo</li><li>Biểu đồ lịch sử</li><li>Báo cáo PDF</li></ul></div>')
        else:
            row = metrics.loc[metrics["symbol"].eq(symbol)].iloc[0]
            md(f'<p class="ls-note" style="margin:6px 0 10px"><b class="ls-mono" style="font-size:15px;'
               f'color:{t["text"]}">{esc(symbol)}</b> · {esc(row["board"])} · {esc(row["sector"])} · '
               f'giá đóng cửa {vn(row["close"])} đ · {status_badge(symbol, row["status"], levels, t)}</p>')
            rank, total, scope = rank_of(symbol, listed, metrics)
            kpi_cards([
                ("Score thanh khoản", f'{row["score"]:.0f}' if _valid(row["score"]) else "—",
                 f"Hạng {rank}/{total} {scope}" if rank else "Chưa đủ dữ liệu để xếp hạng", str(t["muted"])),
                ("Spread ước lượng", vn_pct(row["spread"]), "Trung bình · Corwin–Schultz", str(t["muted"])),
                ("Amihud", vn_sig(row["amihud"]), "Biến động giá trên mỗi tỷ đồng giao dịch", str(t["muted"])),
                ("ADV giá trị", vn_bil(row["adv_value"]), f"ADV khối lượng {vn(row['adv_volume'])} cổ",
                 str(t["muted"])),
            ])
            insight_card(stock_insights(symbol, row, metrics, symbol_history(symbol, period.as_of),
                                        levels.get(symbol),
                                        alert_summary(reasons[symbol]) if symbol in reasons else None), t)
            if symbol in reasons and levels.get(symbol):
                with st.expander("Vì sao mã này bị cảnh báo? Xem số liệu chi tiết"):
                    md("<ul class='ls-why-list'>" + "".join(f"<li>{esc(part)}</li>" for part in reasons[symbol].split("; "))
                       + "</ul><p class='ls-note'>Mức thường = trung vị 60 phiên trước của chính mã; σ = độ lệch chuẩn "
                       "ước lượng bền vững. Cảnh báo đỏ khi ít nhất hai chỉ số cùng xấu đi với |z| &gt; 2.</p>")
            pdf_button(symbol, row, metrics, levels.get(symbol), period, (rank, total, scope), reasons.get(symbol))
            history_chart(symbol, period, levels, t, "profile_metric")

    with st.expander("Phương pháp & giới hạn"):
        st.markdown(
            "- **Một ngày:** chỉ số tính trên cửa sổ 20 phiên kết thúc ở ngày đó. **Khoảng:** spread, Amihud "
            "và ADV lấy trung bình, biến động lấy độ lệch chuẩn, tất cả trong đúng khoảng đã chọn "
            "(cần ít nhất 10 phiên hợp lệ).\n"
            "- **Spread Corwin–Schultz:** ước lượng từng ngày từ biên độ cao/thấp hai ngày liên tiếp; ước lượng âm "
            "đặt về 0, rồi lấy **trung bình** theo khuyến nghị của bài báo gốc (Corwin & Schultz, 2012). "
            "Lấy trung vị sẽ cho ra 0 với rất nhiều mã vì hơn nửa số ngày bị cắt về 0.\n"
            "- **Score** = 30% spread ước lượng + 30% Amihud + 30% ADV giá trị "
            "+ 10% tỷ lệ ngày không giao dịch, theo thứ hạng phần trăm trong universe. **Vì sao 30/30/30/10:** "
            "thanh khoản có ba chiều chính (Kyle, 1985; Sarr & Lybek, 2002) — *độ chặt* (spread: chi phí một lệnh "
            "nhỏ), *độ sâu* (Amihud: lệnh lớn đẩy giá bao nhiêu) và *độ rộng* (giá trị giao dịch: thị trường hấp thụ "
            "được bao nhiêu). Không có căn cứ để ưu tiên chiều nào nên chia đều. Tỷ lệ ngày không giao dịch "
            "(Lesmond và cộng sự, 1999) bằng 0 với đa số mã nên chỉ giữ 10% để tách nhóm mã ít giao dịch. "
            "Bảng độ nhạy bên dưới cho thấy xếp hạng gần như không đổi khi đổi trọng số.\n"
            "- Mã thiếu dữ liệu không có Score và không bị gán 0. Radar chỉ xét cổ phiếu (mã 3 ký tự).\n"
            "- Cảnh báo dựa trên robust z-score so với 60 phiên trước của chính mã, xét ở phiên cuối; không phải dự báo.\n"
            "- **Ngành theo tháng:** dòng tiền = giá trị giao dịch của cả ngành chia số phiên trong tháng, so với "
            "trung bình 12 tháng của chính ngành; spread ngành = trung vị spread tháng của các mã. Ngành theo ICB "
            "do SSI cung cấp."
        )
        robustness_table(period, metrics, t)
        weight_table(metrics)
        validation_panel()


def _read_validation(name: str) -> pd.DataFrame:
    path = data_root() / f"kiem_dinh_{name}.csv"
    try:
        return pd.read_csv(path, encoding="utf-8-sig") if path.exists() else pd.DataFrame()
    except (OSError, ValueError):
        return pd.DataFrame()


def _table(head: list[str], body: list[list[str]], min_width: int = 560) -> str:
    right = ' style="text-align:right"'
    th = "".join(f"<th{right if i else ''}>{esc(h)}</th>" for i, h in enumerate(head))
    num = ' class="num"'
    rows = "".join("<tr>" + "".join(f"<td{num if i else ''}>{c}</td>" for i, c in enumerate(r)) + "</tr>"
                   for r in body)
    return (f'<div class="ls-table-wrap"><table class="ls-table" style="min-width:{min_width}px"><thead><tr>{th}'
            f'</tr></thead><tbody>{rows}</tbody></table></div>')


def _liq_overall(liq: pd.DataFrame, size: float) -> pd.Series | None:
    if liq.empty or "group" not in liq:
        return None
    hit = liq[(liq["size_adv"].round(3) == size) & liq["group"].eq("Tất cả")]
    return hit.iloc[0] if not hit.empty else None


def dtl_bias_note() -> str:
    """Một câu nhắc thời gian thực tế dài hơn dự báo, lấy số từ kết quả kiểm định nếu có."""
    row = _liq_overall(_read_validation("so_phien"), 1.0)
    if row is not None and _valid(row.get("on_time")):
        return (f"Số phiên tính theo ADV trung bình nên thường lạc quan: kiểm định trên lịch sử, lệnh bằng 1 lần ADV "
                f"dự báo {vn(row['predicted'])} phiên nhưng thực tế trung vị {vn(row['median_realized'])} phiên, chỉ "
                f"{vn_pct(row['on_time'], 0)} trường hợp xong đúng hạn. Nên dự phòng thêm khoảng 1 phiên.")
    return ("Số phiên tính theo ADV trung bình nên thường lạc quan (khối lượng phân phối lệch phải: vài phiên đột "
            "biến kéo trung bình lên). Nên dự phòng thêm khoảng 1 phiên.")


def validation_findings(score: pd.DataFrame, liq: pd.DataFrame, alerts: pd.DataFrame) -> list[str]:
    """Diễn giải trung thực kết quả kiểm định: nói rõ cái làm được và cái chưa."""
    out = []
    if not score.empty:
        amihud, adv, spread = (score[c].mean() for c in ("rho_amihud", "rho_adv", "rho_spread"))
        out.append(f"<b>Score dự báo tốt thứ hạng Amihud và giá trị giao dịch</b> của 20 phiên sau (Spearman "
                   f"{vn(amihud, 2)} và {vn(adv, 2)}), nhưng <b>gần như không dự báo được spread tương lai</b> "
                   f"({vn(spread, 2)}). Spread Corwin–Schultz trên dữ liệu ngày ở Việt Nam rất nhiễu vì biên độ trần/sàn "
                   "và bước giá lớn so với giá cổ phiếu — đây là giới hạn của chỉ số spread, không nên đọc spread "
                   "từng mã như một con số chính xác.")
    row = _liq_overall(liq, 1.0)
    if row is not None:
        out.append(f"<b>Số phiên bán hết bị lạc quan có hệ thống.</b> Lệnh bằng 1 lần ADV: dự báo {vn(row['predicted'])} "
                   f"phiên, thực tế trung vị {vn(row['median_realized'])} phiên; chỉ {vn_pct(row['on_time'], 0)} xong "
                   f"đúng hạn, {vn_pct(row['within_one'], 0)} xong trong vòng trễ 1 phiên. Nguyên nhân: ADV là trung bình "
                   "còn khối lượng phân phối lệch phải. Trang Chi phí giao dịch đã ghi chú dự phòng thêm khoảng 1 phiên.")
    if not alerts.empty and {"Đỏ", "Không cảnh báo"} <= set(alerts["level"]):
        a = alerts.set_index("level")
        red, none = a.loc["Đỏ"], a.loc["Không cảnh báo"]
        ratio = red["value_worse"] / none["value_worse"] if none["value_worse"] else float("nan")
        if _valid(ratio) and ratio >= 1.1:
            out.append(f"<b>Cảnh báo đỏ báo trước thanh khoản giảm tiếp:</b> {vn_pct(red['value_worse'], 0)} mã đỏ "
                       f"có giá trị giao dịch 20 phiên sau thấp hơn mức tại thời điểm cảnh báo, so với "
                       f"{vn_pct(none['value_worse'], 0)} ở nhóm không cảnh báo (gấp {vn(ratio, 2)} lần).")
        else:
            out.append(f"<b>Cảnh báo mô tả sự suy giảm đã xảy ra, không dự báo suy giảm tiếp theo.</b> Sau cảnh báo "
                       f"đỏ, {vn_pct(red['value_worse'], 0)} mã có giá trị giao dịch 20 phiên sau thấp hơn mức tại thời "
                       f"điểm cảnh báo — không cao hơn nhóm không cảnh báo ({vn_pct(none['value_worse'], 0)}); trung vị "
                       f"giá trị giao dịch 20 phiên sau bằng {vn_pct(red['median_value_ratio'], 0)} mức lúc cảnh báo "
                       "(thanh khoản thường hồi lại một phần). Vì vậy cảnh báo nên được hiểu là “thanh khoản của mã "
                       "vừa xấu đi bất thường so với chính nó” để người dùng xem kỹ trước khi đặt lệnh, không phải "
                       "tín hiệu dự báo.")
    return out


def validation_panel() -> None:
    """Kết quả kiểm định ngoài mẫu (scripts/kiem_dinh.py ghi ra data/kiem_dinh_*.csv)."""
    score, liq, alerts = (_read_validation(n) for n in ("score", "so_phien", "canh_bao"))
    md('<h2 class="ls-h2" style="margin-top:10px !important">Kiểm định ngoài mẫu</h2>')
    if score.empty and liq.empty and alerts.empty:
        md('<p class="ls-note">Chưa có kết quả. Chạy <code>python scripts/kiem_dinh.py</code> sau khi đã tải lịch sử.</p>')
        return
    md('<p class="ls-note">Dự báo chỉ dùng dữ liệu đến phiên t, rồi so với 20 phiên thực tế sau t (không tham gia '
       'tính dự báo). Lặp lại trên nhiều mốc t trong lịch sử.</p>')
    findings = validation_findings(score, liq, alerts)
    if findings:
        md('<div class="ls-callout" style="background:var(--surf2,#F0F2F5);border-left-color:#0B6E6E">'
           '<div class="ico" style="background:#0B6E6E">✓</div><div><h4 style="color:inherit !important">'
           'Kết luận từ kiểm định — điểm mạnh và giới hạn</h4>'
           + "".join(f"<p>• {f}</p>" for f in findings) + "</div></div>")
    if not score.empty:
        md(f'<p class="ls-note"><b>1. Score có xếp đúng thanh khoản tương lai không</b> — {vn(len(score))} mốc, '
           f'từ {pd.to_datetime(score["origin"]).min():%d/%m/%Y} đến {pd.to_datetime(score["origin"]).max():%d/%m/%Y}. '
           'Spearman giữa Score tại t và chỉ số thực tế 20 phiên sau (1 = xếp đúng hoàn toàn).</p>')
        md(_table(["Đại lượng thực tế 20 phiên sau", "Spearman trung bình", "Thấp nhất", "Cao nhất"], [
            [label, vn(score[c].mean(), 2), vn(score[c].min(), 2), vn(score[c].max(), 2)]
            for label, c in (("Score", "rho_score"), ("Amihud (đảo dấu)", "rho_amihud"),
                             ("Giá trị giao dịch", "rho_adv"), ("Spread (đảo dấu)", "rho_spread"))
        ] + [["Mã top 20% vẫn ở top 20%", vn_pct(score["top_stays_top"].mean(), 0), "", ""],
             ["Spread thực tế: top 20% / kém nhất 20%",
              f'{vn_pct(score["spread_top"].median())} / {vn_pct(score["spread_bottom"].median())}', "", ""]]))
    if not liq.empty:
        md('<p class="ls-note"><b>2. Số phiên bán hết</b> — lệnh bằng k lần ADV, mỗi phiên bán 20% khối lượng thực tế '
           'của phiên đó. “Đúng hạn” = xong trong số phiên dự báo.</p>')
        md(_table(["Quy mô · nhóm Score", "Dự báo", "Thực tế (trung vị)", "Đúng hạn", "Trễ ≤ 1 phiên",
                   "Chưa xong sau 20 phiên"], [
            [f'{vn(r["size_adv"] * 100)}% ADV · {esc(r["group"])}', f'{vn(r["predicted"])} phiên',
             f'{vn(r["median_realized"])} phiên', vn_pct(r["on_time"], 0), vn_pct(r["within_one"], 0),
             vn_pct(r["unfinished"], 0)] for _, r in liq.iterrows()
        ], 700))
    if not alerts.empty:
        md('<p class="ls-note"><b>3. Cảnh báo</b> — trong 20 phiên sau, thanh khoản có kém hơn mức của chính mã '
           'trong 20 phiên tại thời điểm t không. “Độ nâng” = tỷ lệ xấu đi của nhóm cảnh báo chia nhóm không '
           'cảnh báo (cột “Ít nhất một”).</p>')
        md(_table(["Nhóm", "Số trường hợp", "GTGD thấp hơn thường", "Spread cao hơn thường", "Ít nhất một",
                   "Độ nâng"], [
            [esc(r["level"]), vn(r["cases"]), vn_pct(r["value_worse"], 0), vn_pct(r["spread_worse"], 0),
             vn_pct(r["either"], 0), f'{vn(r["lift"], 2)}×'] for _, r in alerts.iterrows()
        ]))


def weight_table(metrics: pd.DataFrame) -> None:
    result = score_weight_sensitivity(metrics)
    if result.empty:
        return
    rows = "".join(
        f'<tr><td>{esc(r["scenario"])}</td><td class="num">{vn(r["spearman"], 3)}</td>'
        f'<td class="num">{vn_pct(r["top_overlap"], 0)}</td><td class="num">{vn(r["median_shift"])} bậc</td></tr>'
        for _, r in result.iterrows()
    )
    md('<h2 class="ls-h2" style="margin-top:10px !important">Độ nhạy của Score theo trọng số</h2>'
       f'<p class="ls-note">Chấm lại {vn(result["symbols"].iloc[0])} mã đủ dữ liệu với từng bộ trọng số rồi so với '
       'Score đang dùng. Tương quan hạng Spearman gần 1 và nhóm 20% tốt nhất trùng phần lớn nghĩa là kết luận '
       'không phụ thuộc vào việc chọn trọng số cụ thể.</p>'
       '<div class="ls-table-wrap"><table class="ls-table" style="min-width:560px"><thead><tr>'
       '<th>Bộ trọng số (spread/Amihud/ADV/ngày không GD)</th><th style="text-align:right">Spearman với Score</th>'
       '<th style="text-align:right">Trùng nhóm top 20%</th><th style="text-align:right">Lệch hạng trung vị</th>'
       f'</tr></thead><tbody>{rows}</tbody></table></div>')


@st.cache_data(show_spinner=False, max_entries=16)
def _robustness(signature: str, period: Period) -> pd.DataFrame:
    """So số mã có spread = 0 giữa các cách tính, trên cùng tập mã và cùng cửa sổ."""
    table = history_table()
    if period.is_range:
        rows = table[(table["date"] >= period.start) & (table["date"] <= period.end)]
    else:
        rows = table[table["date"] <= period.as_of].sort_values(["symbol", "date"]).groupby("symbol").tail(20)
    grouped = rows.groupby("symbol")
    counts = grouped["spread_daily"].count()
    keep = counts[counts >= 10].index
    frame = pd.DataFrame({
        "median": grouped["spread_daily"].median(),
        "mean": grouped["spread_daily"].mean(),
        "mean_adj": grouped["spread_daily_adj"].mean(),
    }).loc[keep].astype("float64")
    zero_days = rows["spread_daily"].eq(0).sum() / max(1, rows["spread_daily"].notna().sum())
    zero_days_adj = rows["spread_daily_adj"].eq(0).sum() / max(1, rows["spread_daily_adj"].notna().sum())
    return pd.DataFrame([
        {"Cách tính": "Trung vị, không điều chỉnh (cách cũ)", "col": "median", "zero_days": zero_days},
        {"Cách tính": "Trung bình, không điều chỉnh (đang dùng)", "col": "mean", "zero_days": zero_days},
        {"Cách tính": "Trung bình + điều chỉnh nhảy giá qua đêm", "col": "mean_adj", "zero_days": zero_days_adj},
    ]).assign(
        zeros=lambda d: [int((frame[c] == 0).sum()) for c in d["col"]],
        total=len(frame),
        median_spread=lambda d: [float(frame[c].median()) for c in d["col"]],
        mean_spread=lambda d: [float(frame[c].mean()) for c in d["col"]],
    )


def robustness_table(period: Period, metrics: pd.DataFrame, t: dict[str, object]) -> None:
    result = _robustness(table_key(), period)
    if result.empty or not result["total"].iloc[0]:
        return
    rows = "".join(
        f'<tr><td>{esc(r["Cách tính"])}</td><td class="num">{vn_pct(r["zero_days"], 1)}</td>'
        f'<td class="num">{vn(r["zeros"])} / {vn(r["total"])} ({vn_pct(r["zeros"] / r["total"], 1)})</td>'
        f'<td class="num">{vn_pct(r["mean_spread"])}</td></tr>'
        for _, r in result.iterrows()
    )
    md('<h2 class="ls-h2" style="margin-top:10px !important">Kiểm tra độ bền của spread Corwin–Schultz</h2>'
       f'<p class="ls-note">Cùng tập mã, cùng cửa sổ ({esc(period.basis)}). Điều chỉnh qua đêm: nếu giá ngày sau '
       'nhảy ra ngoài giá đóng cửa ngày trước, dịch high/low của ngày sau về sát giá đóng cửa đó trước khi tính '
       '(Corwin & Schultz, 2012). Score và cảnh báo dùng cách “đang dùng”.</p>'
       '<div class="ls-table-wrap"><table class="ls-table" style="min-width:560px"><thead><tr>'
       '<th>Cách tính</th><th style="text-align:right">Tỷ lệ ngày bị cắt về 0</th>'
       '<th style="text-align:right">Số mã có spread = 0</th>'
       '<th style="text-align:right">Spread trung bình các mã</th>'
       f'</tr></thead><tbody>{rows}</tbody></table></div>')
