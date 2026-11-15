"""Báo cáo PDF tổng hợp thanh khoản cho một mã cổ phiếu.

Dựng bằng reportlab (bố cục) và matplotlib (biểu đồ) — đều thuần Python, không cần trình duyệt.
Font tiếng Việt dùng DejaVu Sans đi kèm sẵn trong matplotlib nên không phải cài thêm font.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import numpy as np
import pandas as pd

from liquisense.scenario import order_scenario, scenario_summary
from liquisense.finance import days_to_liquidate, estimate_cost, score_rank
from liquisense.insights import (
    DISCLAIMER,
    THRESHOLDS,
    Insight,
    sector_context_insights,
    peer_insights,
    size_insights,
    stock_insights,
)

ACCENT = "#0B6E6E"
ACCENT_SOFT = "#E1F0EF"
TEXT = "#0F172A"
MUTED = "#556070"
LINE = "#E2E5EA"
SURF2 = "#F0F2F5"
TONE = {"good": "#0B6B4D", "warn": "#8A5100", "bad": "#B42318", "neutral": ACCENT}
LEVEL_TEXT = {"Do": ("Cảnh báo đỏ", "#B42318"), "Vang": ("Cảnh báo vàng", "#8A5100"),
              "Thong bao": ("Hoạt động bất thường", "#1D4ED8")}


@dataclass(frozen=True)
class ReportContext:
    symbol: str
    period_label: str      # ví dụ "cửa sổ 20 phiên đến 06/11/2026"
    chart_start: date
    as_of: date
    data_end: date
    sell_tax: float = 0.001
    fee: float = 0.0015
    rank: int | None = None        # hạng như trên bảng xếp hạng của app (None: tính trên toàn thị trường)
    rank_total: int | None = None
    rank_scope: str = "toàn thị trường"
    sector_trend: pd.DataFrame | None = None   # diễn biến ngành theo tháng (sector_flow.sector_trend)
    alert_reason: str | None = None            # lý do cảnh báo cụ thể (nếu mã đang bị cảnh báo)
    scenario_qty: int = 500_000                # tình huống "bán Q cổ phiếu" ở mục 5


# --------------------------------------------------------------------------
# Tiện ích định dạng
# --------------------------------------------------------------------------
def _ok(value: object) -> bool:
    try:
        return value is not None and not pd.isna(value) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _vn(value: object, digits: int = 0) -> str:
    if not _ok(value):
        return "—"
    text = f"{float(value):,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def _pct(value: object, digits: int = 2) -> str:
    return "—" if not _ok(value) else _vn(float(value) * 100, digits) + "%"


def _sig(value: object) -> str:
    if not _ok(value):
        return "—"
    number = float(value)
    if number == 0:
        return "0"
    return _vn(number, 4) if abs(number) >= 0.001 else f"{number:.2e}".replace(".", ",").replace("e-0", "e-")


def _bil(value: object) -> str:
    return "—" if not _ok(value) else _vn(float(value) / 1e9, 1) + " tỷ"


def _markup(text: str) -> str:
    """**đậm** -> <b>đậm</b> cho Paragraph của reportlab (đã escape ký tự đặc biệt)."""
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    parts = safe.split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(parts))


# --------------------------------------------------------------------------
# Font và biểu đồ
# --------------------------------------------------------------------------
def _font_paths() -> tuple[Path, Path]:
    import matplotlib

    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    return base / "DejaVuSans.ttf", base / "DejaVuSans-Bold.ttf"


def _register_fonts() -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.fonts import addMapping

    if "LS" in pdfmetrics.getRegisteredFontNames():
        return
    regular, bold = _font_paths()
    pdfmetrics.registerFont(TTFont("LS", str(regular)))
    pdfmetrics.registerFont(TTFont("LS-Bold", str(bold)))
    addMapping("LS", 0, 0, "LS")
    addMapping("LS", 1, 0, "LS-Bold")
    addMapping("LS", 0, 1, "LS")
    addMapping("LS", 1, 1, "LS-Bold")


def _chart_png(history: pd.DataFrame, daily_col: str, smooth: pd.Series, title: str,
               scale: float, unit: str, bars: bool) -> bytes:
    """Biểu đồ một chỉ số: giá trị từng phiên (chấm hoặc cột mờ) + trung bình 20 phiên (đường tô nền)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    daily = history[daily_col].astype("float64") * scale
    line = smooth.astype("float64") * scale
    x = np.arange(len(history))
    fig, ax = plt.subplots(figsize=(7.2, 2.15), dpi=200)
    if bars:
        ax.bar(x, daily, color="#B9C1CC", width=0.75, label="Giá trị từng phiên")
    else:
        cap = max(np.nanmax(line) if line.notna().any() else 0, daily.quantile(0.95) if daily.notna().any() else 0)
        cap = cap * 1.35 if cap > 0 else None
        shown = daily if cap is None else daily.where(daily <= cap)
        ax.scatter(x, shown, s=6, color="#8B95A3", alpha=0.7, label="Giá trị từng phiên", zorder=2)
        if cap is not None and (daily > cap).any():
            over = np.flatnonzero((daily > cap).values)
            ax.scatter(over, [cap * 0.985] * len(over), marker="^", s=18, color="#C27803", zorder=3,
                       label="Đột biến (vượt khung)")
            ax.set_ylim(0, cap * 1.04)
    ax.plot(x, line.interpolate(limit_area="inside"), color=ACCENT, linewidth=1.8, label="Trung bình 20 phiên",
            zorder=4)
    ax.fill_between(x, 0, line.interpolate(limit_area="inside").fillna(0), color=ACCENT, alpha=0.08, zorder=1)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(LINE)
    ax.grid(axis="y", color=LINE, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=6.5, length=0)
    ax.set_ylim(bottom=0)

    def fmt(value: float, _pos: object) -> str:
        if unit == "%":
            return _vn(value, 1) + "%"
        if unit == " tỷ":
            return _vn(value, 0) + " tỷ"
        return f"{value:.1e}".replace(".", ",") if 0 < abs(value) < 0.01 else _vn(value, 2)

    ax.yaxis.set_major_formatter(FuncFormatter(fmt))
    step = max(1, len(x) // 7)
    ticks = list(range(0, len(x), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([pd.Timestamp(history["date"].iloc[i]).strftime("%d/%m/%y") for i in ticks])
    ax.set_xlim((-0.6, len(x) - 0.4) if bars else (-0.15, len(x) - 0.85))
    ax.set_title(title, loc="left", fontsize=8.5, color=TEXT, fontweight="bold", pad=6)
    ax.legend(loc="upper left", fontsize=6.3, frameon=False, ncol=3, bbox_to_anchor=(0, 1.0))
    fig.tight_layout(pad=0.4)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor="white")
    plt.close(fig)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Số liệu cho báo cáo
# --------------------------------------------------------------------------
def _percentile_better(series: pd.Series, value: float, lower_is_better: bool) -> float | None:
    values = series.dropna()
    if not _ok(value) or values.empty:
        return None
    worse = (values > value) if lower_is_better else (values < value)
    return float(worse.mean())


def cost_table(row: pd.Series, ctx: ReportContext) -> pd.DataFrame:
    """Chi phí lệnh MUA theo các quy mô % ADV (dùng spread, σ, ADV 20 phiên của mã)."""
    rows = []
    adv, price = float(row["adv_volume"]), float(row["close"])
    for pct in (0.01, 0.05, 0.10, 0.20, 0.50):
        quantity = max(1, int(round(adv * pct / 100.0)) * 100)
        result = estimate_cost(quantity=quantity, price=price, spread=float(row["spread"]),
                               daily_volatility=float(row["daily_volatility"]), adv_volume=adv,
                               side="Mua", fee_rate=ctx.fee, tax_rate=ctx.sell_tax)
        scen = {s["scenario"]: s for s in result["scenarios"]}
        rows.append({
            "pct_adv": pct, "quantity": quantity, "value": quantity * price,
            "low": scen["Thap"]["total_pct"], "base": scen["Co so"]["total_pct"], "high": scen["Cao"]["total_pct"],
            "days20": days_to_liquidate(quantity, adv)["20%"],
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Dựng PDF
# --------------------------------------------------------------------------
def build_stock_report(row: pd.Series, metrics: pd.DataFrame, history: pd.DataFrame,
                       level: str | None, ctx: ReportContext) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as canvas_module
    from reportlab.platypus import (
        Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    _register_fonts()
    symbol = ctx.symbol
    created = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))  # giờ Việt Nam
    width, height = A4
    margin = 16 * mm

    # ---- Kiểu chữ
    base = ParagraphStyle("base", fontName="LS", fontSize=9, leading=13, textColor=colors.HexColor(TEXT))
    small = ParagraphStyle("small", parent=base, fontSize=7.5, leading=10, textColor=colors.HexColor(MUTED))
    h1 = ParagraphStyle("h1", parent=base, fontName="LS-Bold", fontSize=16, leading=20)
    cell = ParagraphStyle("cell", parent=base, fontSize=8.3, leading=11)
    cell_r = ParagraphStyle("cellr", parent=cell, alignment=2)
    cell_h = ParagraphStyle("cellh", parent=cell, fontName="LS-Bold", textColor=colors.HexColor(MUTED), fontSize=7.8)
    cell_hr = ParagraphStyle("cellhr", parent=cell_h, alignment=2)
    bullet = ParagraphStyle("bullet", parent=base, bulletFontName="LS", leftIndent=11, bulletIndent=0, spaceAfter=3, alignment=TA_LEFT)
    usable = width - 2 * margin
    sec_num = ParagraphStyle("secn", parent=base, fontName="LS-Bold", fontSize=11, leading=13,
                             textColor=colors.white, alignment=1)
    sec_title = ParagraphStyle("sect", parent=base, fontName="LS-Bold", fontSize=12.5, leading=16,
                               textColor=colors.HexColor(TEXT))

    def section(number: str, title: str) -> Table:
        """Tiêu đề mục: ô số màu chủ đạo + tên mục, gạch chân mảnh."""
        head = Table([[Paragraph(number, sec_num), Paragraph(title, sec_title)]],
                     colWidths=[8 * mm, usable - 8 * mm])
        head.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(ACCENT)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (1, 0), (1, 0), 0.8, colors.HexColor(LINE)),
        ]))
        head.spaceBefore, head.spaceAfter = 12, 7
        return head

    # ---- Khung trang: logo, tên dự án, ngày tải, số trang
    class NumberedCanvas(canvas_module.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):  # noqa: N802 (tên theo reportlab)
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._decorate(total)
                super().showPage()
            super().save()

        def _decorate(self, total: int) -> None:
            c = self
            if self._pageNumber == 1:
                draw_cover(c)
                return
            c.setFillColor(colors.HexColor(ACCENT))
            c.rect(0, height - 3 * mm, width, 3 * mm, stroke=0, fill=1)   # dải màu đầu trang
            top = height - 12 * mm
            # Logo
            c.setFillColor(colors.HexColor(ACCENT))
            c.roundRect(margin, top - 7.5 * mm, 9 * mm, 9 * mm, 2.2 * mm, stroke=0, fill=1)
            c.setStrokeColor(colors.white)
            c.setLineWidth(1.6)
            c.setLineCap(1)
            path = c.beginPath()
            x0, y0 = margin + 2.2 * mm, top - 4.6 * mm
            path.moveTo(x0, y0)
            path.curveTo(x0 + 1.6 * mm, y0 + 2.6 * mm, x0 + 2.4 * mm, y0 + 2.6 * mm, x0 + 3.2 * mm, y0 + 0.6 * mm)
            path.curveTo(x0 + 3.9 * mm, y0 - 1.2 * mm, x0 + 4.6 * mm, y0 - 0.6 * mm, x0 + 4.8 * mm, y0 + 2.4 * mm)
            c.drawPath(path, stroke=1, fill=0)
            # Tên dự án
            c.setFillColor(colors.HexColor(TEXT))
            c.setFont("LS-Bold", 12)
            c.drawString(margin + 11.5 * mm, top - 2.6 * mm, "LiquiSense")
            c.setFont("LS", 7.5)
            c.setFillColor(colors.HexColor(MUTED))
            c.drawString(margin + 11.5 * mm, top - 6.4 * mm, "Radar thanh khoản cổ phiếu Việt Nam")
            c.setFont("LS-Bold", 9)
            c.setFillColor(colors.HexColor(TEXT))
            c.drawRightString(width - margin, top - 2.6 * mm, f"Báo cáo thanh khoản · {symbol}")
            c.setFont("LS", 7.5)
            c.setFillColor(colors.HexColor(MUTED))
            c.drawRightString(width - margin, top - 6.4 * mm, f"Ngày tải: {created:%d/%m/%Y %H:%M}")
            c.setStrokeColor(colors.HexColor(LINE))
            c.setLineWidth(0.7)
            c.line(margin, top - 10 * mm, width - margin, top - 10 * mm)
            # Chân trang
            c.line(margin, 14 * mm, width - margin, 14 * mm)
            c.setFont("LS", 7)
            c.drawString(margin, 10 * mm, f"Dữ liệu SSI FastConnect đến phiên {ctx.data_end:%d/%m/%Y} · "
                                          "LiquiSense — đồ án FinTech")
            c.drawString(margin, 6.5 * mm, DISCLAIMER + " Mọi chỉ số và chi phí đều là ước lượng.")
            c.drawRightString(width - margin, 10 * mm, f"Trang {self._pageNumber} / {total}")

    story: list[object] = []
    sector, board = str(row.get("sector", "")), str(row.get("board", ""))

    # ---- Trang bìa (vẽ trực tiếp trên canvas ở trang 1) rồi sang trang nội dung
    story += [Spacer(1, 1), PageBreak()]
    story += [
        Paragraph(f"Tổng quan chỉ số · {symbol}", h1),
        Spacer(1, 2),
        Paragraph(f"{board} · {sector} · Giá đóng cửa {_vn(row.get('close'))} đ (phiên {ctx.as_of:%d/%m/%Y}) · "
                  f"Kỳ phân tích: {ctx.period_label} · Biểu đồ từ {ctx.chart_start:%d/%m/%Y}", small),
        Spacer(1, 8),
    ]

    # ---- Thẻ chỉ số chính
    if ctx.rank is not None:
        rank, total = ctx.rank, ctx.rank_total
    else:
        ranks = score_rank(metrics["score"])
        mine = ranks[metrics["symbol"].eq(symbol)]
        rank = int(mine.iloc[0]) if len(mine) and _ok(mine.iloc[0]) else None
        total = int(ranks.notna().sum())
    level_text, level_color = LEVEL_TEXT.get(level, ("Không có cảnh báo", "#0B6B4D"))
    kpis = [
        ("Score thanh khoản", _vn(row.get("score")) if _ok(row.get("score")) else "—",
         f"Hạng {rank}/{total} {ctx.rank_scope}" if rank else
         ("Kẹt trần/sàn liên tục" if row.get("status") == "Tran san lien tuc" else "Chưa đủ dữ liệu")),
        ("Spread ước lượng", _pct(row.get("spread")), "Trung bình · Corwin–Schultz"),
        ("Amihud", _sig(row.get("amihud")), "Biến động giá / tỷ đồng giao dịch"),
        ("ADV giá trị", _bil(row.get("adv_value")), f"ADV khối lượng {_vn(row.get('adv_volume'))} cổ"),
        ("Biến động ngày σ", _pct(row.get("daily_volatility")), "Độ lệch chuẩn lợi suất ngày"),
        ("Ngày không giao dịch", _pct(row.get("zero_days"), 1), "Tỷ lệ phiên trong kỳ"),
        ("Tỷ lệ luân chuyển", _pct(row.get("turnover"), 3), "ADV khối lượng / cổ phiếu niêm yết"),
        ("Cảnh báo thanh khoản", level_text, f"Phiên {ctx.as_of:%d/%m/%Y}"),
    ]
    value_style = ParagraphStyle("kv", parent=base, fontName="LS-Bold", fontSize=14, leading=17)
    grid, line_cells = [], []
    for i, (label, value, sub) in enumerate(kpis):
        color = level_color if label == "Cảnh báo thanh khoản" else TEXT
        size = 10.5 if label == "Cảnh báo thanh khoản" else 14
        line_cells.append([Paragraph(label, small),
                           Paragraph(f'<font color="{color}" size="{size}">{value}</font>', value_style),
                           Paragraph(sub, small)])
        if len(line_cells) == 4:
            grid.append(line_cells)
            line_cells = []
    card_w = (width - 2 * margin) / 4
    kpi_table = Table(grid, colWidths=[card_w] * 4)
    kpi_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(LINE)),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.HexColor(LINE)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAFBFC")),
        ("LINEABOVE", (0, 0), (-1, 0), 2.2, colors.HexColor(ACCENT)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [kpi_table, Spacer(1, 6)]

    # ---- 1. Nhận xét tổng hợp
    costs = cost_table(row, ctx) if all(_ok(row.get(k)) for k in ("spread", "daily_volatility", "adv_volume", "close")) \
        and float(row["adv_volume"]) > 0 else pd.DataFrame()
    insights: list[Insight] = []
    insights += stock_insights(symbol, row, metrics, history, level, ctx.alert_reason)
    insights += peer_insights(symbol, row, metrics)
    insights += sector_context_insights(symbol, sector, ctx.sector_trend)
    insights += size_insights(costs)
    story.append(section("1", "Nhận xét tổng hợp"))
    for item in insights:
        tone_style = ParagraphStyle(f"b_{item.tone}", parent=bullet,
                                    bulletColor=colors.HexColor(TONE.get(item.tone, ACCENT)), bulletFontSize=8)
        story.append(Paragraph(_markup(item.text), tone_style, bulletText="●"))
    story.append(Paragraph(DISCLAIMER, small))

    # ---- 2. So sánh với ngành, sàn, thị trường
    eligible = metrics[metrics["status"].eq("Du du lieu")]
    peers = eligible[eligible["sector"].eq(sector)]
    board_peers = eligible[eligible["board"].eq(board)]
    spec = [
        ("Score thanh khoản", "score", False, lambda v: _vn(v)),
        ("Spread ước lượng", "spread", True, lambda v: _pct(v)),
        ("Amihud", "amihud", True, _sig),
        ("ADV giá trị", "adv_value", False, _bil),
        ("Biến động ngày σ", "daily_volatility", True, lambda v: _pct(v)),
        ("Ngày không giao dịch", "zero_days", True, lambda v: _pct(v, 1)),
    ]
    rows = [[Paragraph("Chỉ số", cell_h), Paragraph(symbol, cell_hr),
             Paragraph(f"Trung vị ngành ({len(peers)} mã)", cell_hr),
             Paragraph(f"Trung vị {board} ({len(board_peers)} mã)", cell_hr),
             Paragraph("Tốt hơn … số mã toàn thị trường", cell_hr)]]
    for label, column, lower_better, fmt in spec:
        better = _percentile_better(eligible[column], row.get(column), lower_better)
        rows.append([
            Paragraph(label, cell), Paragraph(f"<b>{fmt(row.get(column))}</b>", cell_r),
            Paragraph(fmt(peers[column].median()) if len(peers) else "—", cell_r),
            Paragraph(fmt(board_peers[column].median()) if len(board_peers) else "—", cell_r),
            Paragraph(_pct(better, 0) if better is not None else "—", cell_r),
        ])
    compare = Table(rows, colWidths=[usable * 0.27, usable * 0.16, usable * 0.19, usable * 0.19, usable * 0.19])
    compare.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(LINE)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(LINE)),
        ("BACKGROUND", (1, 1), (1, -1), colors.HexColor(ACCENT_SOFT)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [KeepTogether([section("2", "So sánh với ngành, sàn và toàn thị trường"), compare,
                            Spacer(1, 3),
                            Paragraph("Với spread, Amihud, biến động và tỷ lệ ngày không giao dịch: càng thấp càng tốt. "
                                      "Cột cuối là tỷ lệ số mã đủ dữ liệu mà mã này tốt hơn.", small)])]
    trend = ctx.sector_trend
    if trend is not None and not trend.empty:
        rows = [[Paragraph(h, cell_hr if i else cell_h) for i, h in enumerate(
            ["Tháng", "GTGD bình quân phiên", "So với TB 12 tháng", "Spread trung vị", "Số mã"])]]
        for month, r in trend.iterrows():
            rows.append([Paragraph(f"{month.month:02d}/{month.year}", cell), Paragraph(_bil(r["value"]), cell_r),
                         Paragraph(f"<b>{_pct(r['flow'], 0)}</b>", cell_r), Paragraph(_pct(r["spread"]), cell_r),
                         Paragraph(_vn(r["symbols"]), cell_r)])
        table = Table(rows, colWidths=[usable * w for w in (0.16, 0.24, 0.22, 0.22, 0.16)])
        table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(LINE)),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(LINE)),
            ("BACKGROUND", (2, 1), (2, -1), colors.HexColor(ACCENT_SOFT)),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(KeepTogether([
            Spacer(1, 8), Paragraph(f"<b>Thanh khoản của ngành {sector} theo tháng</b>", base), Spacer(1, 4), table,
            Spacer(1, 3), Paragraph("GTGD bình quân phiên = tổng giá trị giao dịch của cả ngành trong tháng chia số "
                                    "phiên; 100% = mức trung bình 12 tháng của chính ngành. Tháng cuối có thể chưa "
                                    "đủ phiên.", small)]))

    # ---- 3. Diễn biến thanh khoản
    # Đường trung bình 20 phiên tính trên TOÀN BỘ lịch sử rồi mới cắt theo kỳ, để đường bắt đầu ngay
    # từ phiên đầu của biểu đồ (tính trên phần đã cắt thì 10 phiên đầu bị hở).
    full_ok = history["volume"].notna() & (history["volume"] >= 0)
    history = history.assign(_value_ma=history["value"].where(full_ok).rolling(20, min_periods=10).mean())
    view = history[(history["date"].dt.date >= ctx.chart_start) & (history["date"].dt.date <= ctx.as_of)]
    view = view.reset_index(drop=True)
    section3 = section("3", "Diễn biến thanh khoản")
    if view.empty:
        story += [section3, Paragraph("Không có dữ liệu trong khoảng thời gian đã chọn.", base)]
    else:
        charts = [
            ("Spread ước lượng (%)", "spread_daily", view["spread"], 100, "%", False),
            ("Amihud (biến động giá / tỷ đồng)", "amihud_daily", view["amihud"], 1, "", False),
            ("Giá trị giao dịch (tỷ đồng)", "value",
             view["_value_ma"], 1e-9, " tỷ", True),
        ]
        for title, daily_col, smooth, scale, unit, bars in charts:
            png = _chart_png(view, daily_col, smooth, title, scale, unit, bars)
            image = Image(io.BytesIO(png), width=usable, height=usable * 2.15 / 7.2)
            daily = view[daily_col].astype("float64") * scale
            stats = (f"Trung bình cả kỳ: <b>{_vn(daily.mean(), 2 if unit == '%' else 1) + unit if unit else _sig(daily.mean())}</b> · "
                     f"TB 20 phiên cuối kỳ: <b>{_vn(smooth.dropna().iloc[-1] * scale, 2 if unit == '%' else 1) + unit if unit and smooth.notna().any() else _sig(smooth.dropna().iloc[-1]) if smooth.notna().any() else '—'}</b> · "
                     f"{len(view)} phiên")
            head = [section3] if title.startswith("Spread") else []
            story.append(KeepTogether(head + [image, Paragraph(stats, small), Spacer(1, 6)]))
        story.append(Paragraph("Trục ngang gồm các phiên giao dịch (đã loại bỏ cuối tuần, nghỉ lễ). Chấm/cột xám là giá "
                               "trị từng phiên; đường xanh là trung bình 20 phiên; tam giác cam là phiên đột biến vượt khung.",
                               small))

    # ---- 4. Chi phí giao dịch theo quy mô lệnh
    block: list[object] = [section("4", "Chi phí giao dịch ước tính theo quy mô lệnh (lệnh mua)")]
    if costs.empty:
        block.append(Paragraph(
            "Mã kẹt trần/sàn liên tục: spread không ước lượng được nên không tính chi phí theo mô hình; lệnh lớn "
            "có thể không khớp ở bất kỳ mức giá nào trong biên độ." if row.get("status") == "Tran san lien tuc"
            else "Chưa đủ dữ liệu spread, biến động hoặc ADV để ước tính chi phí.", base))
    else:
        rows = [[Paragraph(h, cell_hr if i else cell_h) for i, h in enumerate(
            ["Quy mô", "Khối lượng (cổ)", "Giá trị lệnh", "Thấp (Y=0,5)", "Cơ sở (Y=1)", "Cao (Y=1,5)",
             "Số phiên khớp hết (20% ADV)"])]]
        for _, r in costs.iterrows():
            rows.append([
                Paragraph(f"{_vn(r['pct_adv'] * 100)}% ADV", cell), Paragraph(_vn(r["quantity"]), cell_r),
                Paragraph(_vn(r["value"] / 1e6) + " tr đ", cell_r), Paragraph(_pct(r["low"]), cell_r),
                Paragraph(f"<b>{_pct(r['base'])}</b>", cell_r), Paragraph(_pct(r["high"]), cell_r),
                Paragraph(f'{max(1, math.ceil(r["days20"] - 1e-9))} phiên (hàng về T+{max(1, math.ceil(r["days20"] - 1e-9)) + 1})'
                          if _ok(r["days20"]) else "—", cell_r),
            ])
        table = Table(rows, colWidths=[usable * w for w in (0.11, 0.13, 0.14, 0.12, 0.12, 0.12, 0.26)])
        table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(LINE)),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(LINE)),
            ("BACKGROUND", (4, 1), (4, -1), colors.HexColor(ACCENT_SOFT)),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        block += [table, Spacer(1, 3), Paragraph(
            f"Chi phí = nửa spread + tác động giá Y·σ·√(Q/ADV) + phí {_pct(ctx.fee)}. Lệnh bán cộng thêm thuế "
            f"{_pct(ctx.sell_tax, 1)}. Thanh toán T+2 tính từ phiên khớp cuối. Giả định toàn bộ lệnh khớp trong một phiên; hệ số tác động giá chưa được "
            "hiệu chỉnh cho cổ phiếu Việt Nam.", small)]
    story.append(KeepTogether(block))

    # ---- 5. Tình huống thực tế
    block = [section("5", f"Tình huống: bán {_vn(ctx.scenario_qty)} cổ phiếu {symbol} mất bao lâu, tốn bao nhiêu")]
    try:
        sc = order_scenario(pd.concat([row, pd.Series({"symbol": symbol})]), ctx.scenario_qty, side="Bán", fee=ctx.fee, tax=ctx.sell_tax)
    except ValueError as exc:
        if row.get("status") == "Tran san lien tuc":
            block.append(Paragraph(
                f"{symbol} đang kẹt trần/sàn liên tục nên không ước lượng được chi phí. Thực tế, ở các phiên đóng cửa "
                "giá sàn, lệnh bán thường chỉ khớp một phần rất nhỏ hoặc không khớp; số phiên cần để bán hết "
                f"{_vn(ctx.scenario_qty)} cổ phiếu phụ thuộc vào thời điểm mã thoát khỏi trạng thái này.", base))
        else:
            block.append(Paragraph(str(exc), base))
    else:
        block.append(Paragraph(scenario_summary(sc), base))
        rows = [[Paragraph(h, cell_hr if i else cell_h) for i, h in enumerate(
            ["Phương án", "Số phiên", "Khớp xong", "Thanh toán xong", "Chi phí cơ sở", "Thấp – cao",
             "Chi phí cơ sở (đồng)", "Dao động giá khi chờ"])]]
        for _, r in sc.plans.iterrows():
            rows.append([
                Paragraph(r["plan"], cell), Paragraph(_vn(r["sessions"]), cell_r),
                Paragraph(r["last_session"], cell_r), Paragraph(r["settled"], cell_r),
                Paragraph(f"<b>{_pct(r['base_pct'])}</b>", cell_r),
                Paragraph(f"{_pct(r['low_pct'])} – {_pct(r['high_pct'])}", cell_r),
                Paragraph(_vn(r["base_vnd"] / 1e6) + " tr", cell_r), Paragraph("±" + _pct(r["price_risk"], 1), cell_r),
            ])
        table = Table(rows, colWidths=[usable * w for w in (0.21, 0.07, 0.09, 0.11, 0.11, 0.17, 0.11, 0.13)])
        table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(LINE)),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(LINE)),
            ("BACKGROUND", (4, 1), (4, -1), colors.HexColor(ACCENT_SOFT)),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        block += [Spacer(1, 4), table, Spacer(1, 3), Paragraph(
            "Mỗi phiên khớp tối đa p% ADV khối lượng; chi phí tác động giá tính trên lát lệnh mỗi phiên. Chia nhỏ "
            "lệnh giảm chi phí nhưng kéo dài thời gian chờ, khi đó giá có thể dao động khoảng ±σ·√(số phiên). "
            "Số phiên tính theo ADV trung bình nên thường lạc quan — kiểm định ngoài mẫu cho thấy thực tế hay lâu "
            "hơn khoảng 1 phiên. "
            f"Đã gồm phí {_pct(ctx.fee)} và thuế bán {_pct(ctx.sell_tax, 1)}.", small)]
    story.append(KeepTogether(block))

    # ---- 6. Phương pháp & giới hạn
    method: list[object] = [section("6", "Phương pháp và giới hạn")]
    for text in (
        "Dữ liệu: nến ngày từ SSI FastConnect (chỉ đọc); radar chỉ xét cổ phiếu mã 3 ký tự trên HOSE, HNX, UPCoM.",
        "Spread Corwin–Schultz: ước lượng từng ngày từ biên độ cao/thấp hai ngày liên tiếp, giá trị âm đặt về 0, "
        "lấy trung bình 20 phiên theo khuyến nghị của bài báo gốc (Corwin & Schultz, 2012).",
        "Amihud: |lợi suất| / giá trị giao dịch (tỷ đồng), bỏ ngày chạm trần/sàn và ngày có sự kiện quyền.",
        "Score = 30% spread + 30% Amihud + 30% ADV giá trị + 10% tỷ lệ ngày không giao dịch, theo thứ hạng phần "
        "trăm trong các mã đủ dữ liệu. Score và cảnh báo luôn dùng cửa sổ 20 phiên. Ba chiều spread (độ chặt), "
        "Amihud (độ sâu) và giá trị giao dịch (độ rộng) theo Kyle (1985) và Sarr & Lybek (2002) được chia đều; tỷ lệ "
        "ngày không giao dịch (Lesmond và cộng sự, 1999) giữ 10% để tách nhóm mã ít giao dịch. Đổi sang trọng số "
        "bằng nhau hoặc nặng chi phí/quy mô, tương quan hạng Spearman với Score vẫn trên 0,97.",
        "Cảnh báo: robust z-score so với 60 phiên trước của chính mã; đỏ khi ít nhất hai chỉ số cùng xấu đi với |z| > 2.",
        "Ngành theo tháng: giá trị giao dịch của cả ngành chia số phiên, so với trung bình 12 tháng của chính ngành; "
        "phân ngành ICB lấy nguyên từ SSI.",
        f"Nhận xét sinh tự động theo ngưỡng cố định (ví dụ nhóm tốt nhất = top {_pct(THRESHOLDS['top_group'], 0)}, "
        f"xu hướng khi thay đổi từ {_pct(THRESHOLDS['trend_change'], 0)}); chỉ mô tả, không khuyến nghị mua/bán.",
    ):
        method.append(Paragraph(text, bullet, bulletText="•"))
    story.append(KeepTogether(method))

    # ---- Trang bìa
    cover_points = [i for i in insights if i.tone in ("bad", "warn", "good")][:3] or insights[:3]
    spark_src = history.loc[history["date"].dt.date <= ctx.as_of, "_value_ma"].dropna().tail(160)
    toc = ["Tổng quan chỉ số & nhận xét", "So sánh với ngành, sàn, thị trường", "Diễn biến thanh khoản",
           "Chi phí giao dịch theo quy mô lệnh", f"Tình huống bán {_vn(ctx.scenario_qty)} cổ phiếu",
           "Phương pháp và giới hạn"]

    def draw_cover(c) -> None:
        teal, deep = colors.HexColor(ACCENT), colors.HexColor("#08504F")
        split = height * 0.47
        # Nền màu chủ đạo (nửa trên), chuyển sắc nhẹ bằng các dải
        steps = 40
        for i in range(steps):
            mix = i / (steps - 1)
            r1, g1, b1 = deep.red, deep.green, deep.blue
            r2, g2, b2 = teal.red, teal.green, teal.blue
            c.setFillColorRGB(r1 + (r2 - r1) * mix, g1 + (g2 - g1) * mix, b1 + (b2 - b1) * mix)
            band = (height - split) / steps
            c.rect(0, split + i * band, width, band + 0.5, stroke=0, fill=1)
        # Hình trang trí: vòng tròn mờ
        c.saveState()
        c.setFillColor(colors.white)
        for cx, cy, rad, alpha in ((width * 0.92, height * 0.93, 70 * mm, 0.06),
                                   (width * 0.80, height * 0.62, 38 * mm, 0.05),
                                   (width * 0.08, split + 8 * mm, 26 * mm, 0.04)):
            c.setFillAlpha(alpha)
            c.circle(cx, cy, rad, stroke=0, fill=1)
        c.restoreState()
        # Đường giá trị giao dịch (TB 20 phiên) thật của mã, làm hoạ tiết nền
        if len(spark_src) >= 10:
            vals = spark_src.to_numpy(dtype="float64")
            lo, hi = float(np.nanmin(vals)), float(np.nanmax(vals))
            span = hi - lo if hi > lo else 1.0
            x0, x1 = margin, width - margin
            y0, y1 = split + 19 * mm, split + 35 * mm
            c.saveState()
            c.setStrokeColor(colors.white)
            c.setStrokeAlpha(0.32)
            c.setLineWidth(1.6)
            c.setLineJoin(1)
            path = c.beginPath()
            for k, v in enumerate(vals):
                px = x0 + (x1 - x0) * k / (len(vals) - 1)
                py = y0 + (y1 - y0) * (v - lo) / span
                path.moveTo(px, py) if k == 0 else path.lineTo(px, py)
            c.drawPath(path, stroke=1, fill=0)
            c.setFont("LS", 6.5)
            c.setFillColor(colors.white)
            c.setFillAlpha(0.55)
            c.drawRightString(x1, y1 + 3 * mm, f"Giá trị giao dịch TB 20 phiên · {len(vals)} phiên gần nhất")
            c.restoreState()
        # Logo + tên
        top = height - 18 * mm
        c.setFillColor(colors.white)
        c.roundRect(margin, top - 6 * mm, 11 * mm, 11 * mm, 2.8 * mm, stroke=0, fill=1)
        c.setStrokeColor(teal)
        c.setLineWidth(1.9)
        c.setLineCap(1)
        path = c.beginPath()
        xs, ys = margin + 2.6 * mm, top - 1.8 * mm
        path.moveTo(xs, ys)
        path.curveTo(xs + 2.0 * mm, ys + 3.2 * mm, xs + 3.0 * mm, ys + 3.2 * mm, xs + 4.0 * mm, ys + 0.7 * mm)
        path.curveTo(xs + 4.8 * mm, ys - 1.5 * mm, xs + 5.7 * mm, ys - 0.7 * mm, xs + 5.9 * mm, ys + 3.0 * mm)
        c.drawPath(path, stroke=1, fill=0)
        c.setFillColor(colors.white)
        c.setFont("LS-Bold", 15)
        c.drawString(margin + 14 * mm, top + 0.4 * mm, "LiquiSense")
        c.setFont("LS", 8)
        c.setFillColor(colors.HexColor("#CDE7E5"))
        c.drawString(margin + 14 * mm, top - 4.2 * mm, "Radar thanh khoản cổ phiếu Việt Nam")
        c.drawRightString(width - margin, top + 0.4 * mm, "Đồ án FinTech · Python")
        c.drawRightString(width - margin, top - 4.2 * mm, "Dữ liệu SSI FastConnect")
        # Tiêu đề chính
        y = height * 0.80
        c.setFillColor(colors.HexColor("#CDE7E5"))
        c.setFont("LS-Bold", 9.5)
        c.drawString(margin, y, "BÁO CÁO THANH KHOẢN CỔ PHIẾU", charSpace=2.2)
        c.setFillColor(colors.white)
        c.setFont("LS-Bold", 76)
        c.drawString(margin - 1.5 * mm, y - 30 * mm, symbol)
        c.setFont("LS-Bold", 14)
        c.drawString(margin, y - 40 * mm, f"{board}  ·  {sector}")
        c.setFont("LS", 10.5)
        c.setFillColor(colors.HexColor("#CDE7E5"))
        c.drawString(margin, y - 47 * mm,
                     f"Giá đóng cửa {_vn(row.get('close'))} đ  ·  phiên {ctx.as_of:%d/%m/%Y}  ·  {ctx.period_label}")
        # Nhãn cảnh báo
        pill_w = c.stringWidth(level_text, "LS-Bold", 9) + 12 * mm
        px, py = margin, y - 58 * mm
        c.setFillColor(colors.white)
        c.roundRect(px, py, pill_w, 7.5 * mm, 3.75 * mm, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(level_color))
        c.circle(px + 4.5 * mm, py + 3.75 * mm, 1.5 * mm, stroke=0, fill=1)
        c.setFont("LS-Bold", 9)
        c.drawString(px + 8 * mm, py + 2.55 * mm, level_text)

        # Thẻ chỉ số nằm vắt qua mép nền màu
        tiles = [
            ("Score thanh khoản", _vn(row.get("score")) if _ok(row.get("score")) else "—",
             f"Hạng {rank}/{total}" if rank else
             ("Kẹt trần/sàn liên tục" if row.get("status") == "Tran san lien tuc" else "Chưa đủ dữ liệu")),
            ("Spread ước lượng", _pct(row.get("spread")), "Corwin–Schultz · 20 phiên"),
            ("ADV giá trị", _bil(row.get("adv_value")), f"{_vn(row.get('adv_volume'))} cổ / phiên"),
            ("Biến động ngày σ", _pct(row.get("daily_volatility")), "Độ lệch chuẩn lợi suất"),
        ]
        gap = 4 * mm
        tw = (usable - 3 * gap) / 4
        th = 27 * mm
        ty = split - th / 2
        for k, (label, value, sub) in enumerate(tiles):
            tx = margin + k * (tw + gap)
            c.setFillColor(colors.HexColor("#000000"))
            c.setFillAlpha(0.06)
            c.roundRect(tx + 0.6 * mm, ty - 0.9 * mm, tw, th, 2.5 * mm, stroke=0, fill=1)   # bóng nhẹ
            c.setFillAlpha(1)
            c.setFillColor(colors.white)
            c.setStrokeColor(colors.HexColor(LINE))
            c.setLineWidth(0.6)
            c.roundRect(tx, ty, tw, th, 2.5 * mm, stroke=1, fill=1)
            c.setFillColor(teal)
            c.rect(tx + 5 * mm, ty + th - 1.3 * mm, 9 * mm, 1.3 * mm, stroke=0, fill=1)
            c.setFillColor(colors.HexColor(MUTED))
            c.setFont("LS", 7.5)
            c.drawString(tx + 5 * mm, ty + th - 7 * mm, label)
            c.setFillColor(colors.HexColor(TEXT))
            c.setFont("LS-Bold", 17 if len(value) <= 9 else 14)
            c.drawString(tx + 5 * mm, ty + th - 15.5 * mm, value)
            c.setFillColor(colors.HexColor(MUTED))
            c.setFont("LS", 6.8)
            c.drawString(tx + 5 * mm, ty + 4.5 * mm, sub)

        # Điểm chính
        y = ty - 11 * mm
        c.setFillColor(colors.HexColor(ACCENT))
        c.setFont("LS-Bold", 11)
        c.drawString(margin, y, "Điểm chính")
        c.setStrokeColor(colors.HexColor(LINE))
        c.line(margin + c.stringWidth("Điểm chính", "LS-Bold", 11) + 4 * mm, y + 1.2 * mm, width - margin, y + 1.2 * mm)
        y -= 4 * mm
        point_style = ParagraphStyle("cp", parent=base, fontSize=9.6, leading=14)
        floor_y = 72 * mm
        for item in cover_points:
            para = Paragraph(_markup(item.text), point_style)
            _, ph = para.wrap(usable - 7 * mm, 200 * mm)
            if y - ph < floor_y:
                break
            c.setFillColor(colors.HexColor(TONE.get(item.tone, ACCENT)))
            c.circle(margin + 1.6 * mm, y - 3.3 * mm, 1.3 * mm, stroke=0, fill=1)
            para.drawOn(c, margin + 7 * mm, y - ph)
            y -= ph + 3 * mm

        # Nội dung báo cáo
        y = 62 * mm
        c.setFillColor(colors.HexColor(ACCENT))
        c.setFont("LS-Bold", 11)
        c.drawString(margin, y, "Nội dung báo cáo")
        c.setStrokeColor(colors.HexColor(LINE))
        c.line(margin + c.stringWidth("Nội dung báo cáo", "LS-Bold", 11) + 4 * mm, y + 1.2 * mm, width - margin,
               y + 1.2 * mm)
        col_w = usable / 2
        for k, name in enumerate(toc):
            cx = margin + (k // 3) * col_w
            cy = y - 7.5 * mm - (k % 3) * 6.5 * mm
            c.setFillColor(colors.HexColor(ACCENT))
            c.roundRect(cx, cy - 1.4 * mm, 5.2 * mm, 5.2 * mm, 1.2 * mm, stroke=0, fill=1)
            c.setFillColor(colors.white)
            c.setFont("LS-Bold", 8)
            c.drawCentredString(cx + 2.6 * mm, cy + 0.2 * mm, str(k + 1))
            c.setFillColor(colors.HexColor(TEXT))
            c.setFont("LS", 9)
            c.drawString(cx + 8 * mm, cy, name)

        # Thông tin báo cáo
        y = 26 * mm
        c.setStrokeColor(colors.HexColor(LINE))
        c.line(margin, y + 7 * mm, width - margin, y + 7 * mm)
        meta = [("Kỳ phân tích", ctx.period_label), ("Dữ liệu đến phiên", f"{ctx.data_end:%d/%m/%Y}"),
                ("Ngày tạo báo cáo", f"{created:%d/%m/%Y %H:%M}"), ("Nguồn dữ liệu", "SSI FastConnect Data")]
        offsets = np.cumsum([0, 0.36, 0.20, 0.23]) * usable
        for k, (label, value) in enumerate(meta):
            mx = margin + offsets[k]
            c.setFillColor(colors.HexColor(MUTED))
            c.setFont("LS", 7)
            c.drawString(mx, y + 2 * mm, label)
            c.setFillColor(colors.HexColor(TEXT))
            c.setFont("LS-Bold", 8.5 if len(value) < 26 else 7.5)
            c.drawString(mx, y - 2.5 * mm, value)
        c.setFillColor(colors.HexColor(MUTED))
        c.setFont("LS", 6.8)
        c.drawString(margin, 11 * mm, DISCLAIMER + " Mọi chỉ số và chi phí đều là ước lượng từ dữ liệu lịch sử.")
        c.setFillColor(teal)
        c.rect(0, 0, width, 3 * mm, stroke=0, fill=1)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=26 * mm, bottomMargin=20 * mm,
                            title=f"LiquiSense — Báo cáo thanh khoản {symbol}", author="LiquiSense",
                            subject=f"Báo cáo thanh khoản {symbol}")
    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()
