"""Giao diện Streamlit LiquiSense: tổng quan, thanh khoản, chi phí giao dịch, danh mục."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st
from loguru import logger

# Thêm src/ vào import path để chạy app trực tiếp sau khi cài requirements.txt.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


from liquisense.data.storage import latest_job  # noqa: E402
from liquisense.ui import common  # noqa: E402
from liquisense.ui.common import (  # noqa: E402
    header, history_cache_path, history_table, inject_css, is_demo_data, latest_stale_history, md,
    notice_band, table_key, theme, time_control,
)
from liquisense.ui.cost import cost_page  # noqa: E402
from liquisense.ui.intro import intro_page  # noqa: E402
from liquisense.ui.liquidity import liquidity_page  # noqa: E402
from liquisense.ui.overview import overview_page  # noqa: E402
from liquisense.ui.portfolio import portfolio_page  # noqa: E402

st.set_page_config(
    page_title="LiquiSense · Radar thanh khoản",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=2)
def _trading_dates(signature: str) -> list[date]:
    return sorted(set(history_table()["date"]))


def main() -> None:
    common._HEADER_SLOT = None   # mô-đun dùng chung không chạy lại mỗi lượt, nên xóa vị trí đầu trang cũ
    t = theme()
    inject_css(t)
    try:
        if not history_cache_path().exists() and latest_stale_history() is None:
            with st.spinner("Đang chuẩn bị dữ liệu lịch sử lần đầu — việc này chỉ diễn ra một lần, vui lòng đợi…"):
                table = history_table()
        else:
            table = history_table()
    except (OSError, ValueError, ImportError) as error:
        st.error(f"Không đọc được kho dữ liệu: {error}")
        st.info("Kiểm tra các tệp Parquet trong data/ hoặc chạy scripts/update.py.")
        st.stop()
    if table.empty:
        st.warning("Kho dữ liệu rỗng. Hãy chạy scripts/update.py để tải dữ liệu từ SSI.")
        st.stop()

    job = latest_job()
    dates = _trading_dates(table_key())
    page = header(dates[-1] if len(dates) else None, job, t)
    notice_band(dates[-1], is_demo_data(), job, t)
    if page == "Giới thiệu":
        intro_page(dates, t)
        return
    common._HEADER_SLOT = st.container()      # đầu trang nằm trên thanh chọn thời gian
    period = time_control(dates)

    pages = {"Tổng quan": overview_page, "Thanh khoản": liquidity_page,
             "Chi phí giao dịch": cost_page, "Mô phỏng danh mục": portfolio_page}
    loading = {"Tổng quan": "Đang tổng hợp thanh khoản toàn thị trường…",
               "Thanh khoản": "Đang tính chỉ số thanh khoản từng mã…",
               "Chi phí giao dịch": "Đang ước tính chi phí giao dịch…",
               "Mô phỏng danh mục": "Đang tính rủi ro thanh khoản của danh mục…"}
    try:
        with st.spinner(f"{loading.get(page, 'Đang tải dữ liệu…')} Vui lòng đợi giây lát."):
            pages.get(page, overview_page)(period, t)
    except Exception as error:  # noqa: BLE001 — không để cả app sập vì một khối lỗi
        logger.exception("Lỗi khi hiển thị trang {}", page)
        st.error(f"Không hiển thị được trang “{page}” do lỗi xử lý dữ liệu ({type(error).__name__}). "
                 "Dữ liệu đã lưu không bị ảnh hưởng — hãy tải lại trang hoặc chọn thời gian khác.")

    md('<div class="ls-foot">LiquiSense là công cụ phân tích học thuật, không phải khuyến nghị đầu tư. '
       'Mọi chỉ số, spread và chi phí đều là ước lượng từ dữ liệu lịch sử SSI FastConnect.</div>')


if __name__ == "__main__":
    main()
