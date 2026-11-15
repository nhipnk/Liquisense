"""Trang Giới thiệu."""

from __future__ import annotations

from datetime import date

import streamlit as st

from liquisense.ui.common import (
    PAGES,
    Period,
    esc,
    get_alerts,
    history_table,
    md,
    table_key,
    vn,
)


def _go_to(page: str) -> None:
    st.session_state["nav"] = page


INTRO_STEPS = [
    ("Tổng quan", "Thị trường hôm nay", "Thanh khoản toàn thị trường, theo sàn, theo ngành và các mã đang bị cảnh báo.",
     '<path d="M4 19V10M10 19V5M16 19v-7M22 19H2" />'),
    ("Thanh khoản", "Soi từng mã", "Xếp hạng Score, hồ sơ chi tiết, lịch sử chỉ số và báo cáo PDF của một mã.",
     '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>'),
    ("Chi phí giao dịch", "Tính trước chi phí", "Nhập mã và khối lượng để biết lệnh tốn bao nhiêu và mất mấy phiên.",
     '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 12h1M14 12h1M9 16h1M14 16h1"/>'),
    ("Mô phỏng danh mục", "Thử bán cả danh mục", "Nhập danh mục của bạn để xem bán ra mất bao lâu và tốn bao nhiêu.",
     '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>'),
]


@st.cache_data(show_spinner=False, max_entries=2)
def _intro_stats(signature: str) -> dict[str, object]:
    table = history_table()
    return {"symbols": int(table["symbol"].nunique()), "sessions": int(table["date"].nunique()),
            "first": min(table["date"]), "sectors": int(table["sector"].nunique())}


def intro_page(dates: list[date], t: dict[str, object]) -> None:
    """Tab Giới thiệu: tên sản phẩm, mục tiêu sử dụng, đối tượng người dùng, dữ liệu và phương pháp."""
    stats = _intro_stats(table_key())
    latest = dates[-1]
    try:
        alerts = get_alerts(Period("day", latest, latest, latest))
        red = int(alerts["severity"].eq("Do").sum()) if not alerts.empty else 0
    except Exception:  # noqa: BLE001 — trang giới thiệu không được hỏng vì cảnh báo
        red = None
    years = max(1, round((latest - stats["first"]).days / 365))
    md(f"""<div class="ls-hero">
  <div class="ls-hero-text">
    <span class="ls-hero-kicker">LiquiSense · Radar thanh khoản cổ phiếu Việt Nam</span>
    <h1>Biết trước lệnh của bạn<br>khớp dễ không và tốn bao nhiêu.</h1>
    <p>Giá đi về đâu là câu hỏi của mọi nhà đầu tư. Nhưng một lệnh mua bán còn phải trả thêm chi phí
    ẩn — chênh lệch giá mua bán và tác động giá — mà bảng giá không hiển thị. LiquiSense đo thanh khoản
    và ước tính chi phí đó cho từng mã, mỗi ngày.</p>
  </div>
  <svg class="ls-hero-art" viewBox="0 0 220 160" aria-hidden="true">
    <circle cx="110" cy="80" r="70" fill="none" stroke="currentColor" stroke-opacity=".25"/>
    <circle cx="110" cy="80" r="46" fill="none" stroke="currentColor" stroke-opacity=".35"/>
    <circle cx="110" cy="80" r="22" fill="none" stroke="currentColor" stroke-opacity=".5"/>
    <path d="M110 80 L168 38" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
    <path d="M30 120 C 60 60, 80 140, 110 90 S 160 40, 195 60" fill="none" stroke="currentColor"
      stroke-width="4" stroke-linecap="round"/>
    <circle cx="150" cy="58" r="5" fill="currentColor"/><circle cx="72" cy="104" r="4" fill="currentColor" opacity=".7"/>
  </svg>
</div>
<div class="ls-hero-stats">
  <div><b>{vn(stats['symbols'])}</b><span>cổ phiếu HOSE · HNX · UPCoM</span></div>
  <div><b>{vn(stats['sessions'])}</b><span>phiên lịch sử (khoảng {years} năm)</span></div>
  <div><b>{vn(stats['sectors'])}</b><span>ngành theo phân ngành ICB</span></div>
  <div><b>{'—' if red is None else vn(red)}</b><span>mã đang cảnh báo đỏ · phiên {latest:%d/%m/%Y}</span></div>
</div>
<div class="ls-intro">
  <section><span class="ico">◎</span><div><b>Mục tiêu sử dụng</b>
    <p>Đo thanh khoản của toàn bộ cổ phiếu niêm yết và đăng ký giao dịch, ước tính chi phí giao dịch ẩn
    theo quy mô lệnh, và cảnh báo sớm khi thanh khoản của một mã suy yếu bất thường so với chính nó —
    để quyết định khối lượng và cách chia lệnh trước khi đặt, thay vì phát hiện ra sau khi đã khớp.</p></div></section>
  <section><span class="ico">◉</span><div><b>Đối tượng người dùng</b>
    <p><strong>Nhà đầu tư cá nhân</strong> — muốn biết trước một lệnh mua hay bán sẽ tốn bao nhiêu và mất
    mấy phiên để thoát hàng, nhất là với cổ phiếu vừa và nhỏ, nơi một lệnh lớn có thể tự đẩy giá đi xa.</p>
    <p><strong>Môi giới chứng khoán</strong> — cần một thước đo khách quan, cập nhật mỗi ngày để tư vấn
    khách hàng về quy mô lệnh hợp lý và rủi ro thanh khoản của từng mã.</p></div></section>
  <section><span class="ico">◈</span><div><b>Dữ liệu &amp; phương pháp</b>
    <p>Toàn bộ dữ liệu lấy từ SSI FastConnect Data API: danh mục chứng khoán, nến ngày, giá tham chiếu –
    trần – sàn và sự kiện quyền, tự cập nhật sau mỗi phiên. Thanh khoản được đo bằng spread Corwin–Schultz,
    Amihud, giá trị giao dịch bình quân và tỷ lệ ngày không giao dịch; chi tiết ở tab <i>Thanh khoản</i> →
    <i>Phương pháp &amp; giới hạn</i>.</p>
    <p class="ls-note">Mọi chỉ số và chi phí là ước lượng phục vụ học thuật, không phải khuyến nghị đầu tư.</p>
  </div></section>
</div>
<div class="ls-qs-head"><span class="ls-qs-kicker">Bắt đầu nhanh</span>
<h2>Bốn bước để khai thác LiquiSense</h2>
<p>Bấm vào một thẻ để mở tab tương ứng</p></div>""")
    grid = st.columns(2, gap="medium") + st.columns(2, gap="medium")
    for number, (column, (page, title, text, icon)) in enumerate(zip(grid, INTRO_STEPS), start=1):
        with column, st.container(key=f"qs_card_{PAGES.index(page)}"):
            md(f'<div class="ls-qs-card"><div class="ls-qs-top"><span class="ls-qs-icon">'
               f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
               f'stroke-linecap="round" stroke-linejoin="round">{icon}</svg></span>'
               f'<span class="ls-qs-no">0{number}</span></div>'
               f'<b>{esc(title)}</b><p>{esc(text)}</p>'
               f'<span class="ls-qs-go">Mở tab {esc(page)} <i>→</i></span></div>')
            st.button(f"Mở {page}", key=f"qsbtn_{PAGES.index(page)}", on_click=_go_to, args=(page,), width="stretch")
