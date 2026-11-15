"""Phần dùng chung của giao diện: định dạng số, dữ liệu, CSS, đầu trang, bộ chọn thời gian, bộ lọc."""

from __future__ import annotations

import html
import importlib.util
import threading
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from liquisense.analytics import ALERT_NAMES
from liquisense.insights import (
    DISCLAIMER,
    Insight,
)
from liquisense.snapshot import (
    alerts_at,
    data_root,
    fetch_prebuilt_cache,
    history_cache_path,
    latest_stale_history,
    load_history_table,
    read_history_file,
    load_or_compute_alerts,
    metrics_at,
    metrics_for_range,
    store_signature,
)



# --------------------------------------------------------------------------
# Bảng màu theo bản thiết kế (sáng / tối)
# --------------------------------------------------------------------------
THEMES: dict[str, dict[str, object]] = {
    "light": {
        "bg": "#F5F6F8", "surf": "#FFFFFF", "surf2": "#F0F2F5", "line": "#E2E5EA",
        "text": "#0F172A", "muted": "#556070", "accent": "#0B6E6E", "onAccent": "#FFFFFF",
        "accentSoft": "#E1F0EF", "accentText": "#0A5C5C",
        "warn": "#8A5100", "warnBg": "#FFF4DF", "bad": "#B42318", "badBg": "#FDECEA",
        "info": "#1D4ED8", "infoBg": "#E8EEFD", "ok": "#0B6B4D", "okBg": "#E2F3EB",
        "c1": "#7DBDB8", "c2": "#0B6E6E", "c3": "#B9C1CC", "selRow": "#F2F8F8",
        "seq": ["#E3F1F0", "#B5DAD7", "#7DBDB8", "#3A9690", "#0B5F5F"],
        "seqFg": ["#0F172A", "#0F172A", "#0F172A", "#FFFFFF", "#FFFFFF"],
    },
    "dark": {
        "bg": "#0B0F14", "surf": "#121821", "surf2": "#19212C", "line": "#263040",
        "text": "#E7ECF3", "muted": "#9AA6B6", "accent": "#5CC2BE", "onAccent": "#06201F",
        "accentSoft": "#14302F", "accentText": "#8FDCD8",
        "warn": "#F2B45A", "warnBg": "#2A2113", "bad": "#F28B82", "badBg": "#3A1A18",
        "info": "#8AB4F8", "infoBg": "#162440", "ok": "#6DD3A8", "okBg": "#10291F",
        "c1": "#2A6A69", "c2": "#6CCBC6", "c3": "#4A5566", "selRow": "#14222A",
        "seq": ["#16272B", "#1E4446", "#2A6A69", "#3E9693", "#6CCBC6"],
        "seqFg": ["#E7ECF3", "#E7ECF3", "#E7ECF3", "#06201F", "#06201F"],
    },
}

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # mọi mốc thời gian hiển thị theo giờ Việt Nam
SELL_TAX_PCT = 0.1  # Thuế TNCN 0,1% trên giá trị bán chứng khoán, không cho người dùng chỉnh.
PAGES = ["Giới thiệu", "Tổng quan", "Thanh khoản", "Chi phí giao dịch", "Mô phỏng danh mục"]
BOARDS = ["HOSE", "HNX", "UPCoM"]
MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Consolas, monospace"


# --------------------------------------------------------------------------
# Định dạng số kiểu Việt Nam (dấu chấm hàng nghìn, dấu phẩy thập phân)
# --------------------------------------------------------------------------
def _valid(value: object) -> bool:
    try:
        return value is not None and not pd.isna(value) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def vn(value: object, digits: int = 0) -> str:
    if not _valid(value):
        return "—"
    text = f"{float(value):,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def vn_sig(value: object, sig: int = 3) -> str:
    """Số rất nhỏ (Amihud): giữ 3 chữ số có nghĩa, ví dụ 0,0000123 -> '1,23e-5'."""
    if not _valid(value):
        return "—"
    number = float(value)
    if number == 0:
        return "0"
    if abs(number) >= 0.001:
        return vn(number, 4)
    return f"{number:.{sig - 1}e}".replace(".", ",").replace("e-0", "e-")


def vn_pct(value: object, digits: int = 2) -> str:
    """Nhận tỷ lệ thập phân (0.0041) và trả về '0,41%'."""
    return "—" if not _valid(value) else vn(float(value) * 100, digits) + "%"


def vn_bil(value: object) -> str:
    """Đồng -> 'x tỷ'."""
    if not _valid(value):
        return "—"
    billions = float(value) / 1e9
    return vn(billions, 0 if billions >= 100 else 1) + " tỷ"


def esc(value: object) -> str:
    return html.escape(str(value))


# --------------------------------------------------------------------------


def vn_thousand(value: object) -> str:
    """Đồng -> 'x nghìn đ'."""
    return "—" if not _valid(value) else vn(float(value) / 1000) + " nghìn đ"


# --------------------------------------------------------------------------
# Dữ liệu: bảng lịch sử chỉ số tính sẵn (cache trên đĩa + giữ trong bộ nhớ)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Period:
    """Khoảng thời gian người dùng chọn."""

    mode: str      # "day" hoặc "range"
    as_of: date    # phiên cuối dùng cho cảnh báo, giá đóng cửa
    start: date    # đầu khoảng (biểu đồ; và chỉ số khi mode = "range")
    end: date

    @property
    def is_range(self) -> bool:
        return self.mode == "range"

    @property
    def label(self) -> str:
        if self.is_range:
            return f"từ {self.start:%d/%m/%Y} đến {self.end:%d/%m/%Y}"
        return f"phiên {self.as_of:%d/%m/%Y}"

    @property
    def basis(self) -> str:
        if self.is_range:
            return f"gộp trong khoảng {self.start:%d/%m/%Y} – {self.end:%d/%m/%Y}"
        return f"cửa sổ 20 phiên đến {self.as_of:%d/%m/%Y}"


@st.cache_resource(show_spinner=False, max_entries=1)
def _history_table(signature: str) -> pd.DataFrame:
    # cache_resource: giữ một bản duy nhất trong bộ nhớ, không sao chép mỗi lần dùng (chỉ đọc).
    return load_history_table()


_BUILD_LOCK = threading.Lock()


def _build_in_background() -> None:
    """Dựng bảng chỉ số mới ở luồng nền; giao diện vẫn dùng bảng cũ nên không phải chờ."""
    if not _BUILD_LOCK.acquire(blocking=False):
        return  # đang có một luồng dựng bảng rồi

    def work() -> None:
        try:
            load_history_table()
        finally:
            _BUILD_LOCK.release()

    threading.Thread(target=work, name="liquisense-history", daemon=True).start()


@st.cache_resource(show_spinner=False, max_entries=1)
def _stale_table(path: str, mtime: float) -> pd.DataFrame:
    return read_history_file(Path(path))


def _cache_url() -> str:
    """Địa chỉ bảng tính sẵn (GitHub Release); đặt trong Secrets của Streamlit hoặc biến môi trường."""
    url = os.environ.get("LIQUISENSE_CACHE_URL", "")
    if not url:
        try:
            url = str(st.secrets.get("LIQUISENSE_CACHE_URL", ""))
        except Exception:  # không có file secrets khi chạy trên máy
            url = ""
    return url


@st.cache_resource(show_spinner=False, max_entries=4)
def _prebuilt(signature: str) -> bool:
    url = _cache_url()
    return bool(url) and fetch_prebuilt_cache(url)


def history_table() -> pd.DataFrame:
    """Bảng chỉ số hiện hành. Nếu dữ liệu vừa cập nhật mà bảng mới chưa dựng xong thì dùng tạm
    bảng của lần trước và dựng bảng mới ở nền — người dùng không phải nhìn màn hình chờ."""
    signature = store_signature()
    if not history_cache_path().exists():
        _prebuilt(signature)   # trên cloud: tải bảng đã tính sẵn (vài giây) thay vì tự tính (1–2 phút)
    if history_cache_path().exists():
        return _history_table(signature)
    stale = latest_stale_history()
    if stale is not None:
        _build_in_background()
        return _stale_table(str(stale), stale.stat().st_mtime)
    return _history_table(signature)  # lần chạy đầu tiên, chưa có bảng nào


def table_key() -> str:
    """Khóa cache theo bảng đang dùng (bảng hiện hành hoặc bảng tạm của lần trước)."""
    if history_cache_path().exists():
        return store_signature()
    stale = latest_stale_history()
    return f"tam-{stale.name}" if stale is not None else store_signature()


def is_demo_data() -> bool:
    return not list(data_root().glob("daily_bars_*.parquet"))


@st.cache_data(show_spinner=False, max_entries=48)
def _metrics(signature: str, period: Period) -> pd.DataFrame:
    table = history_table()
    if period.is_range:
        return metrics_for_range(table, period.start, period.end)
    return metrics_at(table, period.as_of)


@st.cache_data(show_spinner=False, max_entries=48)
def _alerts(signature: str, as_of: date) -> pd.DataFrame:
    if signature.startswith("tam-"):
        return alerts_at(history_table(), as_of)  # bảng tạm: không ghi cache ra đĩa
    return load_or_compute_alerts(as_of, history_table())


def get_metrics(period: Period) -> pd.DataFrame:
    return _metrics(table_key(), period)


def get_alerts(period: Period) -> pd.DataFrame:
    return _alerts(table_key(), period.as_of)


def get_snapshot(period: Period) -> tuple[pd.DataFrame, pd.DataFrame]:
    return get_metrics(period), get_alerts(period)


@st.cache_data(show_spinner=False, max_entries=32)
def _market_value(signature: str, board: str, sector: str) -> pd.DataFrame:
    table = history_table()
    if board != "Tất cả":
        table = table[table["board"].eq(board)]
    if sector != "Tất cả ngành":
        table = table[table["sector"].eq(sector)]
    out = table.groupby(["date", "board"], as_index=False)["value"].sum()
    out["value"] = out["value"].astype("float64")
    return out.sort_values("date")


def market_value(board: str, sector: str) -> pd.DataFrame:
    return _market_value(table_key(), board, sector)


def symbol_history(symbol: str, as_of: date) -> pd.DataFrame:
    table = history_table()
    one = table[(table["symbol"] == symbol) & (table["date"] <= as_of)].sort_values("date")
    one = one.astype({c: "float64" for c in one.select_dtypes("float32").columns})
    one = one.copy()
    one["date"] = pd.to_datetime(one["date"])
    return one.reset_index(drop=True)


def alert_levels(alerts: pd.DataFrame) -> dict[str, str]:
    """Mã -> mức cảnh báo nặng nhất ('Do' > 'Vang' > 'Thong bao')."""
    rank = {"Do": 0, "Vang": 1, "Thong bao": 2}
    levels: dict[str, str] = {}
    if alerts.empty:
        return levels
    for symbol, severity in zip(alerts["symbol"], alerts["severity"]):
        if symbol not in levels or rank.get(severity, 9) < rank.get(levels[symbol], 9):
            levels[symbol] = severity
    return levels


def theme() -> dict[str, object]:
    return THEMES["dark" if st.session_state.get("dark", False) else "light"]


def inject_css(t: dict[str, object]) -> None:
    st.markdown(
        f"""<style>
:root {{
  --bg:{t['bg']}; --surf:{t['surf']}; --surf2:{t['surf2']}; --line:{t['line']};
  --text:{t['text']}; --muted:{t['muted']}; --accent:{t['accent']}; --on-accent:{t['onAccent']};
  --accent-soft:{t['accentSoft']}; --accent-text:{t['accentText']};
  --warn:{t['warn']}; --warn-bg:{t['warnBg']}; --bad:{t['bad']}; --bad-bg:{t['badBg']};
  --info:{t['info']}; --info-bg:{t['infoBg']}; --ok:{t['ok']}; --ok-bg:{t['okBg']};
}}
html, body, .stApp, [data-testid="stAppViewContainer"] {{
  background: var(--bg) !important; color: var(--text);
  font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
}}
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {{ display: none; }}
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {{ display: none; }}
.block-container {{ max-width: 1360px; padding: 0 1.5rem 3rem; }}
.stApp p, .stApp span, .stApp label, .stApp li {{ color: inherit; }}
[data-testid="stWidgetLabel"] p {{ color: var(--muted) !important; font-size: 12px !important; font-weight: 500; }}

/* Thẻ (card) = st.container(border=True, key="card_...") */
div[class*="st-key-card"] {{
  background: var(--surf); border: 1px solid var(--line) !important; border-radius: 16px;
  padding: 20px !important; box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 4px 14px rgba(15,23,42,.03);
}}
/* Ô nhập liệu, select, textarea (hỗ trợ cả widget baseweb cũ và react-aria mới) */
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"],
.stSelectbox [role="group"], .stSelectbox input, .stTextInput input, .stTextInput [data-testid="stTextInputRootElement"],
[data-testid="stNumberInputContainer"], [data-testid="stNumberInputField"], .stTextArea textarea {{
  background: var(--surf) !important; color: var(--text) !important;
  border-color: var(--line) !important; -webkit-text-fill-color: var(--text);
}}
.stSelectbox [role="group"], [data-baseweb="select"] > div, [data-testid="stNumberInputContainer"],
.stTextInput [data-testid="stTextInputRootElement"], .stTextArea textarea {{ border-radius: 10px !important; }}
.stSelectbox button, [data-baseweb="select"] svg {{ color: var(--muted) !important; fill: var(--muted); background: transparent !important; }}
input::placeholder, textarea::placeholder {{ color: var(--muted) !important; -webkit-text-fill-color: var(--muted); }}
input:disabled {{ opacity: .55; }}
[data-testid="stDateInputField"], [data-testid="stDateInputField"] *, [data-baseweb="datepicker"] input {{
  background: var(--surf) !important; color: var(--text) !important; -webkit-text-fill-color: var(--text);
}}
[data-testid="stDateInputField"] {{ border:1px solid var(--line) !important; border-radius:10px !important; }}
[data-testid="stDateInput"] button {{ background: var(--surf) !important; color: var(--muted) !important; }}
[data-testid="stDateInputField"] [role="spinbutton"]:focus {{ background: var(--accent-soft) !important; }}
[data-testid="stDateInputCalendar"], [data-baseweb="calendar"], [data-baseweb="calendar"] > div {{
  background: var(--surf) !important; color: var(--text) !important; border:1px solid var(--line);
}}
[data-testid="stDateInputCalendar"] *, [data-baseweb="calendar"] * {{ color: var(--text); background-color: transparent; }}
[data-testid="stDateInputCalendar"] [data-selected="true"], [data-testid="stDateInputCalendar"] [aria-selected="true"],
[data-baseweb="calendar"] [aria-selected="true"] div {{
  background: var(--accent) !important; color: var(--on-accent) !important; border-radius: 8px;
}}
[data-testid="stDateInputCalendar"] [data-disabled="true"], [data-testid="stDateInputCalendar"] [aria-disabled="true"],
[data-testid="stDateInputCalendar"] [data-outside-month="true"] {{ opacity: .35; }}
[data-testid="stDateInputCalendar"] [data-hovered="true"] {{ background: var(--surf2) !important; }}
[data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"], .stNumberInput button {{
  background: var(--surf2) !important; color: var(--text) !important;
}}
[role="listbox"], [role="option"], [data-baseweb="popover"] ul, [data-baseweb="popover"] li, [data-baseweb="menu"] {{
  background: var(--surf) !important; color: var(--text) !important;
}}
[role="option"]:hover, [role="option"][data-focused="true"], [role="option"][aria-selected="true"],
[data-baseweb="popover"] li:hover {{ background: var(--surf2) !important; }}

/* Nút bấm */
button[data-testid^="stBaseButton"] {{
  background: var(--surf2); color: var(--text); border: 1px solid var(--line);
  border-radius: 10px; font-weight: 600; min-height: 38px;
}}
button[data-testid^="stBaseButton"]:hover {{ border-color: var(--accent); color: var(--accent-text); }}
button[data-testid^="stBaseButton"] p {{ color: inherit !important; }}
button[data-testid^="stBaseButton-primary"] {{ background: var(--accent); color: var(--on-accent); border-color: var(--accent); }}

/* Segmented control kiểu "pill" như bản thiết kế */
[data-testid="stButtonGroup"] > div:not([data-testid="stWidgetLabel"]) {{
  background: var(--surf2); border: 1px solid var(--line); border-radius: 10px; padding: 3px;
  width: fit-content; max-width: 100%; gap: 2px; flex-wrap: wrap;
}}
[data-testid="stButtonGroup"] button {{
  border: 0 !important; background: transparent !important; color: var(--muted) !important;
  border-radius: 8px !important; min-height: 32px; font-weight: 600; box-shadow: none !important;
}}
[data-testid="stButtonGroup"] button[aria-checked="true"],
[data-testid="stButtonGroup"] button[data-testid$="Active"] {{
  background: var(--surf) !important; color: var(--text) !important;
  box-shadow: 0 1px 2px rgba(0,0,0,.18) !important;
}}
[data-testid="stButtonGroup"] button p {{ color: inherit !important; font-weight: 600; }}
/* Thanh điều hướng trên cùng kiểu website: tràn ngang, dính trên đầu khi cuộn */
[data-testid="stMain"], section.main {{ overflow-x: clip; }}
[data-testid="stLayoutWrapper"]:has(> div.st-key-card_header),
[data-testid="stElementContainer"]:has(> div.st-key-card_header) {{
  position: sticky; top: 0; z-index: 990; margin-top: -1rem;
}}
div.st-key-card_header {{
  width: 100vw !important; max-width: 100vw;
  margin-left: calc(50% - 50vw); margin-top: 0; margin-bottom: 6px;
  border: 0 !important; border-bottom: 1px solid var(--line) !important; border-radius: 0 !important;
  padding: 4px max(24px, calc(50vw - 660px)) 8px !important; background: var(--surf);
  box-shadow: 0 2px 10px rgba(15, 23, 42, .05);
}}
div.st-key-card_header [data-testid="stButtonGroup"] > div:not([data-testid="stWidgetLabel"]) {{
  background: transparent !important; border: 0 !important; padding: 0 !important; gap: 4px;
}}
div.st-key-card_header [data-testid="stButtonGroup"] button {{
  border-radius: 0 !important; min-height: 68px; padding: 0 18px !important;
  border-bottom: 2px solid transparent !important; background: transparent !important;
  color: var(--muted) !important; box-shadow: none !important;
}}
div.st-key-card_header [data-testid="stButtonGroup"] button:hover {{ color: var(--text) !important; }}
div.st-key-card_header [data-testid="stButtonGroup"] button p {{ font-size: 15.5px !important; }}
div.st-key-card_header .ls-brand b {{ font-size: 19px; }}
div.st-key-card_header .ls-brand small {{ font-size: 12px; }}
div.st-key-card_header .ls-pill {{ font-size: 13px; padding: 5px 12px; }}
div.st-key-card_header [data-testid="stButtonGroup"] button[aria-checked="true"],
div.st-key-card_header [data-testid="stButtonGroup"] button[data-testid$="Active"] {{
  color: var(--accent-text) !important; border-bottom-color: var(--accent) !important;
  background: transparent !important; box-shadow: none !important;
}}
.st-key-card_time [data-testid="stButtonGroup"] > div:not([data-testid="stWidgetLabel"]) {{ flex-wrap: nowrap; }}
.st-key-card_time [data-testid="stButtonGroup"] button {{ padding: 0 10px !important; white-space: nowrap; }}
/* Nút "Tải về" (popover) và khung lựa chọn bên trong — theo màu giao diện sáng/tối */
button[data-testid="stPopoverButton"] {{
  background: var(--surf2) !important; color: var(--text) !important; border: 1px solid var(--line) !important;
  border-radius: 10px; font-weight: 600;
}}
button[data-testid="stPopoverButton"]:hover {{ border-color: var(--accent) !important; color: var(--accent-text) !important; }}
button[data-testid="stPopoverButton"] p, button[data-testid="stPopoverButton"] span {{ color: inherit !important; }}
[data-testid="stPopoverBody"] {{
  background: var(--surf) !important; color: var(--text) !important; border: 1px solid var(--line) !important;
  box-shadow: 0 10px 30px rgba(0,0,0,.25);
}}
[data-testid="stPopoverBody"] p, [data-testid="stPopoverBody"] span {{ color: inherit; }}
/* Expander = "Phương pháp & giới hạn" */
[data-testid="stExpander"] details {{
  background: var(--surf); border: 1px solid var(--line); border-radius: 14px;
}}
[data-testid="stExpander"] summary {{ color: var(--text); font-weight: 600; }}
[data-testid="stExpander"] summary:hover {{ color: var(--accent-text); }}
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p,
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] li {{ color: var(--muted); font-size: 13px; }}
[data-testid="stSlider"] [data-testid="stThumbValue"],
[data-testid="stSlider"] [data-testid="stTickBarMin"],
[data-testid="stSlider"] [data-testid="stTickBarMax"] {{ color: var(--muted); }}
[data-testid="stAlert"] {{ border-radius: 12px; }}

/* Khối HTML tự dựng */
.ls-brand {{ display:flex; align-items:center; gap:10px; }}
.ls-brand b {{ display:block; font-size:16px; letter-spacing:-.01em; color:var(--text); }}
.ls-brand small {{ display:block; font-size:11px; color:var(--muted); line-height:1.2; }}
.ls-status {{ display:flex; flex-direction:column; align-items:flex-end; gap:3px; }}
.ls-status small {{ font-size:11px; color:var(--muted); text-align:right; line-height:1.3; }}
.ls-hero {{ position:relative; overflow:hidden; display:flex; align-items:center; gap:28px;
  border-radius:20px; padding:34px 40px; margin:4px 0 0; color:#fff;
  background:radial-gradient(120% 140% at 100% 0%, #18908E 0%, #0B6E6E 45%, #08484A 100%); }}
.ls-hero-text {{ flex:1; min-width:0; }}
.ls-hero-kicker {{ display:inline-block; font-size:12px; letter-spacing:.06em; text-transform:uppercase;
  background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.25); border-radius:999px;
  padding:4px 12px; margin-bottom:14px; }}
.ls-hero h1 {{ color:#fff !important; font-size:34px !important; line-height:1.18 !important;
  margin:0 0 12px !important; font-weight:800 !important; letter-spacing:-.01em; }}
.ls-hero p {{ color:rgba(255,255,255,.88) !important; font-size:15px; line-height:1.65; max-width:720px; margin:0; }}
.ls-hero-art {{ width:220px; flex:none; color:#fff; opacity:.9; }}
.ls-hero-stats {{ display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; margin:14px 0 18px; }}
.ls-hero-stats div {{ background:var(--surf); border:1px solid var(--line); border-radius:14px; padding:14px 18px; }}
.ls-hero-stats b {{ display:block; font-family:var(--mono, monospace); font-size:26px; color:var(--accent-text); }}
.ls-hero-stats span {{ font-size:12.5px; color:var(--muted); }}
.ls-intro {{ display:flex; flex-direction:column; gap:12px; }}
.ls-intro section {{ display:flex; gap:18px; background:var(--surf); border:1px solid var(--line);
  border-radius:14px; padding:18px 22px; }}
.ls-intro .ico {{ flex:none; width:40px; height:40px; border-radius:12px; display:flex; align-items:center;
  justify-content:center; font-size:20px; color:var(--accent-text); background:var(--accent-soft, rgba(11,110,110,.12)); }}
.ls-intro b {{ display:block; font-size:16px; color:var(--text); margin-bottom:6px; }}
.ls-intro p {{ font-size:14.5px; color:var(--text); line-height:1.65; margin:0 0 8px; max-width:960px; }}
@media (max-width: 900px) {{ .ls-hero {{ flex-direction:column; padding:26px; }} .ls-hero-art {{ width:160px; }}
  .ls-hero-stats {{ grid-template-columns:repeat(2, minmax(0,1fr)); }} }}
.ls-qs-head {{ text-align:center; margin:40px auto 18px; max-width:720px; }}
.ls-qs-kicker {{ display:inline-block; font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase;
  color:var(--accent-text); background:var(--accent-soft, rgba(11,110,110,.10)); border-radius:999px; padding:5px 14px; }}
.ls-qs-head h2 {{ margin:12px 0 6px !important; padding:0 !important; font-size:30px !important; font-weight:800 !important;
  letter-spacing:-.02em; color:var(--text) !important; }}
.ls-qs-head h2 a {{ display:none !important; }}
.ls-qs-head p {{ margin:0 !important; font-size:14px !important; color:var(--muted) !important; }}
[class*="st-key-qs_card_"] {{ position:relative; gap:0 !important; }}
.ls-qs-card {{ height:100%; min-height:170px; margin-bottom:6px; display:flex; flex-direction:column; gap:6px; padding:20px 20px 18px;
  border-radius:16px; background:var(--surf); border:1px solid var(--line);
  transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease; }}
.ls-qs-top {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px; }}
.ls-qs-icon {{ width:44px; height:44px; border-radius:12px; display:flex; align-items:center; justify-content:center;
  color:#fff; background:linear-gradient(135deg, #18908E, #0B6E6E); box-shadow:0 6px 14px rgba(11,110,110,.25); }}
.ls-qs-icon svg {{ width:22px; height:22px; }}
.ls-qs-no {{ font-family:var(--mono, monospace); font-size:30px; font-weight:700; color:var(--muted); opacity:.28; line-height:1; }}
.ls-qs-card b {{ font-size:16px; color:var(--text); }}
.ls-qs-card p {{ font-size:13.5px !important; color:var(--muted) !important; line-height:1.55; margin:0; flex:1; }}
.ls-qs-go {{ font-size:13px; font-weight:600; color:var(--accent-text); margin-top:10px; }}
.ls-qs-go i {{ font-style:normal; display:inline-block; transition:transform .18s ease; }}
[class*="st-key-qs_card_"]:hover .ls-qs-card {{ transform:translateY(-3px); border-color:var(--accent);
  box-shadow:0 10px 24px rgba(15,23,42,.10); }}
[class*="st-key-qs_card_"]:hover .ls-qs-go i {{ transform:translateX(4px); }}
/* Nút thật phủ kín thẻ: bấm vào đâu trên thẻ cũng mở tab */
[class*="st-key-qsbtn_"] {{ position:absolute !important; inset:0; z-index:3; margin:0 !important; }}
[class*="st-key-qsbtn_"] > div, [class*="st-key-qsbtn_"] [data-testid="stButton"] {{ height:100%; }}
[class*="st-key-qsbtn_"] button {{ width:100%; height:100% !important; opacity:0; cursor:pointer; }}
/* Thông báo chờ: thẻ nhỏ giữa màn hình thay cho vòng quay mặc định */
[data-testid="stSpinner"] {{ position:fixed !important; inset:0; z-index:9999; display:flex !important;
  align-items:center; justify-content:center; pointer-events:none;
  background:rgba(15,23,42,.10); backdrop-filter:blur(1.5px); }}
[data-testid="stSpinner"] > div {{ pointer-events:auto; display:flex; align-items:center; gap:14px;
  max-width:420px; padding:18px 24px; border-radius:16px; background:var(--surf);
  border:1px solid var(--line); box-shadow:0 20px 50px rgba(15,23,42,.22); }}
[data-testid="stSpinner"] p, [data-testid="stSpinner"] div {{ color:var(--text) !important; font-size:14.5px !important;
  font-weight:500; line-height:1.45; }}
[data-testid="stSpinner"] i, [data-testid="stSpinnerIcon"] {{ border-top-color:var(--accent) !important; }}
.ls-why-list {{ margin:0 0 6px 18px; padding:0; font-size:14px; line-height:1.6; color:var(--text); }}
.ls-why {{ margin-top:2px; font-size:12.5px; color:var(--muted); }}
.ls-why summary {{ cursor:pointer; color:var(--accent-text); font-weight:600; list-style:none; width:max-content; }}
.ls-why summary::-webkit-details-marker {{ display:none; }}
.ls-why summary::after {{ content:" ▾"; }}
.ls-why[open] summary::after {{ content:" ▴"; }}
.ls-why span {{ display:block; margin-top:4px; line-height:1.5; }}
.ls-pill {{ display:inline-flex; align-items:center; gap:8px; padding:6px 12px; border-radius:999px;
  font-size:12px; font-weight:600; white-space:nowrap; }}
.ls-band {{ border-radius:12px; padding:9px 16px; font-size:12.5px; display:flex; flex-wrap:wrap;
  gap:4px 16px; margin: 2px 0 6px; }}
.ls-band strong {{ font-weight:600; }}
.ls-callout {{ display:flex; gap:14px; align-items:flex-start; margin:14px 0 6px; padding:16px 20px;
  border-radius:14px; background:{t["warnBg"]}; border:1px solid {_alpha(str(t["warn"]), 0.35)};
  border-left:5px solid {t["warn"]}; color:{t["text"]}; }}
.ls-callout .ico {{ flex:0 0 auto; width:38px; height:38px; border-radius:50%; display:flex;
  align-items:center; justify-content:center; background:{t["warn"]}; color:{t["surf"]}; font-size:20px; font-weight:700; }}
.ls-callout h4 {{ margin:0 0 6px !important; padding:0 !important; font-size:16.5px !important; font-weight:700 !important;
  color:{t["warn"]} !important; letter-spacing:-.01em; }}
.ls-callout p {{ margin:0 0 6px !important; font-size:14.5px; line-height:1.6; }}
.ls-callout p:last-child {{ margin-bottom:0 !important; }}
.ls-callout b {{ font-weight:700; }}
.ls-empty {{ text-align:center; padding:38px 20px 34px; border:1.5px dashed var(--line, {t["line"]});
  border-radius:16px; margin:14px 0 4px; background:{t["surf2"]}; }}
.ls-empty .ico {{ font-size:34px; line-height:1; margin-bottom:10px; }}
.ls-empty h4 {{ margin:0 0 6px !important; padding:0 !important; font-size:18px !important; font-weight:700 !important;
  color:{t["text"]} !important; }}
.ls-empty p {{ margin:0 auto !important; max-width:560px; font-size:14px; color:{t["muted"]}; line-height:1.6; }}
.ls-empty ul {{ display:inline-flex; flex-wrap:wrap; justify-content:center; gap:8px; list-style:none;
  padding:0; margin:14px 0 0; }}
.ls-empty li {{ font-size:12.5px; padding:5px 12px; border-radius:999px; background:{t["surf"]};
  border:1px solid {t["line"]}; color:{t["text"]}; }}
.stApp h1.ls-h1 {{ margin:6px 0 0 !important; padding:0 !important; font-size:26px !important; font-weight:700;
  letter-spacing:-.02em; color:var(--text); line-height:1.25; }}
.stApp p.ls-sub {{ margin:4px 0 6px; color:var(--muted); font-size:14px !important; }}
/* Đầu trang dạng dải màu (cùng phong cách tab Giới thiệu) */
.ls-ph {{ position:relative; overflow:hidden; display:flex; align-items:center; gap:18px; margin:6px 0 10px;
  padding:20px 26px; border-radius:18px; color:#fff;
  background:radial-gradient(120% 160% at 100% 0%, #18908E 0%, #0B6E6E 50%, #08484A 100%); }}
.ls-ph-icon {{ flex:none; width:50px; height:50px; border-radius:14px; display:flex; align-items:center;
  justify-content:center; background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.25); }}
.ls-ph-icon svg {{ width:26px; height:26px; }}
.ls-ph-text {{ flex:1; min-width:0; position:relative; z-index:1; }}
.ls-ph .stApp h1.ls-h1, .stApp .ls-ph h1.ls-h1 {{ color:#fff !important; margin:0 !important; font-size:24px !important; }}
.stApp .ls-ph p.ls-sub {{ color:rgba(255,255,255,.82) !important; margin:4px 0 0 !important; font-size:13.5px !important; }}
.ls-ph-art {{ position:absolute; right:10px; top:0; height:100%; width:240px; color:#fff; pointer-events:none; }}
@media (max-width: 900px) {{ .ls-ph-art {{ display:none; }} }}
.ls-kpis {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); gap:16px; margin:4px 0 8px; }}
.ls-kpi {{ position:relative; overflow:hidden; background:var(--surf); border:1px solid var(--line);
  border-radius:16px; padding:18px 20px 18px 22px; display:flex; flex-direction:column; gap:8px;
  box-shadow:0 1px 2px rgba(15,23,42,.04); transition:transform .18s ease, box-shadow .18s ease; }}
.ls-kpi::before {{ content:""; position:absolute; left:0; top:14px; bottom:14px; width:4px; border-radius:0 4px 4px 0;
  background:linear-gradient(180deg, #18908E, #0B6E6E); }}
.ls-kpi:hover {{ transform:translateY(-2px); box-shadow:0 8px 20px rgba(15,23,42,.08); }}
.ls-kpi .l {{ font-size:12.5px; color:var(--muted); font-weight:500; }}
.ls-kpi .v {{ font-family:{MONO}; font-size:28px; font-weight:600; letter-spacing:-.02em;
  font-variant-numeric:tabular-nums; color:var(--text); line-height:1.2; }}
.ls-kpi .s {{ font-size:12.5px; }}
.stApp h2.ls-h2 {{ margin:0 !important; padding:0 !important; font-size:16px !important; font-weight:650;
  color:var(--text); line-height:1.35; letter-spacing:0; display:flex; align-items:center; gap:8px; }}
.stApp h2.ls-h2::before {{ content:""; flex:none; width:8px; height:8px; border-radius:3px;
  background:linear-gradient(135deg, #18908E, #0B6E6E); }}
.stApp .ls-h1 a, .stApp .ls-h2 a, [data-testid="stHeaderActionElements"] {{ display:none !important; }}
.stApp p.ls-note {{ margin:2px 0 12px; font-size:12.5px !important; color:var(--muted); line-height:1.45; }}
.ls-heat {{ display:grid; gap:6px; min-width:360px; }}
.ls-heat .h {{ font-size:12px; color:var(--muted); font-weight:600; padding:4px 0; text-align:center; }}
.ls-heat .h:first-child {{ text-align:left; }}
.ls-heat .r {{ display:flex; align-items:center; font-weight:500; font-size:13px; color:var(--text);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.ls-heat .c small {{ font-size:10.5px; font-weight:500; opacity:.8; margin-left:6px; }}
.ls-heat .c {{ height:40px; border-radius:8px; display:flex; align-items:center; justify-content:center;
  font-family:{MONO}; font-weight:600; font-size:14px; font-variant-numeric:tabular-nums; }}
.ls-legend {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; font-size:12px; color:var(--muted); }}
.ls-legend i {{ width:22px; height:12px; border-radius:3px; display:inline-block; }}
.ls-alerts {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:10px; }}
.ls-alerts li {{ display:flex; gap:12px; padding:12px; border-radius:10px; background:var(--surf2);
  border:1px solid var(--line); margin:0; }}
.ls-chip {{ flex:0 0 auto; display:inline-flex; align-items:center; height:24px; padding:0 8px;
  border-radius:6px; font-size:11.5px; font-weight:700; white-space:nowrap; }}
.ls-mono {{ font-family:{MONO}; font-variant-numeric:tabular-nums; }}
.ls-table-wrap {{ overflow-x:auto; }}
.ls-table {{ width:100%; min-width:820px; border-collapse:collapse; font-size:13.5px; color:var(--text); }}
.stApp table.ls-table, .stApp .ls-table th, .stApp .ls-table td {{ border-left:0 !important; border-right:0 !important; border-top:0 !important; }}
.ls-table th {{ text-align:left; color:var(--muted); font-size:12px; font-weight:600; padding:10px 12px;
  border-bottom:1px solid var(--line); white-space:nowrap; }}
.ls-table td {{ padding:11px 12px; border-bottom:1px solid var(--line); }}
.ls-table .num {{ text-align:right; font-family:{MONO}; font-variant-numeric:tabular-nums; white-space:nowrap; }}
.ls-badge {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:12px; font-weight:600; white-space:nowrap; }}
.ls-bar {{ display:flex; align-items:center; gap:10px; }}
.ls-bar b {{ font-family:{MONO}; width:28px; text-align:right; }}
.ls-bar span {{ flex:1; height:8px; border-radius:99px; background:var(--surf2); overflow:hidden; min-width:80px; }}
.ls-bar span i {{ display:block; height:100%; background:var(--accent); border-radius:99px; }}
.ls-scen {{ display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:12px; }}
.ls-scen article {{ border-radius:14px; padding:16px; display:flex; flex-direction:column; gap:6px; }}
.ls-scen .n {{ font-size:13px; font-weight:600; color:var(--text); }}
.ls-scen .n small {{ color:var(--muted); font-weight:500; font-size:12px; }}
.ls-scen .p {{ font-family:{MONO}; font-size:26px; font-weight:600; letter-spacing:-.02em; color:var(--text); }}
.ls-scen .d {{ font-size:12.5px; color:var(--muted); }}
.ls-stack {{ display:flex; height:8px; border-radius:99px; overflow:hidden; background:var(--surf2); margin-top:4px; }}
.ls-dl {{ display:grid; grid-template-columns:1fr auto; gap:8px 12px; margin:6px 0 0; padding-top:14px;
  border-top:1px solid var(--line); font-size:13px; }}
.ls-dl dt {{ color:var(--muted); font-size:13px; }}
.ls-dl dd {{ font-size:13px; margin:0; text-align:right; font-family:{MONO}; font-weight:600; color:var(--text); }}
.ls-dtl {{ display:flex; justify-content:space-between; align-items:baseline; padding:10px 0;
  border-bottom:1px solid var(--line); font-size:13.5px; color:var(--text); }}
.ls-dtl:last-child {{ border-bottom:0; }}
.ls-explain b {{ white-space:nowrap; color:var(--text); }}
.ls-explain {{ display:flex; gap:10px; padding:14px 16px; border-radius:12px; background:var(--surf2);
  border:1px solid var(--line); color:var(--muted); font-size:13px; margin-top:4px; }}
div[class*="st-key-pfrow"] {{ border-bottom:1px solid var(--line); padding:4px 0 6px; gap:0 !important; }}
div[class*="st-key-pfrow"] [data-testid="stHorizontalBlock"] {{ align-items:center; }}
.ls-cell {{ font-size:13.5px; color:var(--text); }}
.ls-cell.num {{ text-align:right; font-family:{MONO}; font-variant-numeric:tabular-nums; }}
.ls-cell.head {{ font-size:12px; color:var(--muted); font-weight:600; font-family:inherit; }}
.ls-fixed {{ display:flex; flex-direction:column; gap:2px; padding-top:2px; }}
.ls-fixed span {{ font-size:12px; color:var(--muted); font-weight:500; }}
.ls-fixed b {{ font-family:{MONO}; font-size:15px; color:var(--text); background:var(--surf2);
  border:1px solid var(--line); border-radius:10px; padding:7px 12px; }}
.ls-fixed small {{ font-size:11.5px; color:var(--muted); }}
.ls-more {{ max-height: 420px; overflow-y: auto; padding-right: 4px; }}
.ls-more table {{ min-width: 0 !important; }}
.ls-stt {{ color: var(--muted); font-family:{MONO}; width: 44px; }}
.ls-insight {{ background:var(--surf); border:1px solid var(--line); border-left:4px solid var(--accent);
  border-radius:12px; padding:14px 18px; margin:4px 0 12px; }}
.ls-insight .hd {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:baseline; gap:4px 12px; }}
.ls-insight .hd b {{ font-size:14.5px; color:var(--text); }}
.ls-insight .hd small {{ font-size:11.5px; color:var(--muted); }}
.ls-insight ul {{ list-style:none; margin:10px 0 0; padding:0; display:flex; flex-direction:column; gap:7px; }}
.ls-insight li {{ display:flex; gap:10px; align-items:flex-start; margin:0; font-size:13.5px; color:var(--text);
  line-height:1.5; }}
.ls-insight li i {{ width:8px; height:8px; border-radius:50%; margin-top:7px; flex:0 0 auto; }}
.ls-insight li b {{ font-weight:650; }}
.ls-chips {{ display:flex; flex-wrap:wrap; gap:8px; margin:4px 0 2px; }}
.ls-chips div {{ background:var(--surf2); border:1px solid var(--line); border-radius:10px; padding:7px 12px;
  display:flex; flex-direction:column; gap:1px; min-width:120px; }}
.ls-chips span {{ font-size:11.5px; color:var(--muted); }}
.ls-chips b {{ font-family:{MONO}; font-size:14px; color:var(--text); font-weight:600; }}
.ls-foot {{ color:var(--muted); font-size:12px; margin-top:18px; padding-top:12px; border-top:1px solid var(--line); }}
@media (max-width: 760px) {{ .ls-scen {{ grid-template-columns:1fr; }} .block-container {{ padding: .6rem .8rem 2rem; }} }}
</style>""",
        unsafe_allow_html=True,
    )


def md(markup: str) -> None:
    """Chèn HTML; bỏ thụt dòng để Markdown không biến thành code block."""
    st.markdown(" ".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


def insight_card(items: list[Insight], t: dict[str, object]) -> None:
    """Khung "Nhận xét": vài gạch đầu dòng tự sinh theo quy tắc, chấm màu theo mức độ."""
    if not items:
        return
    colors = {"good": t["ok"], "warn": t["warn"], "bad": t["bad"], "neutral": t["accent"]}
    rows = []
    for item in items:
        text = esc(item.text)
        parts = text.split("**")
        text = "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(parts))
        rows.append(f'<li><i style="background:{colors.get(item.tone, t["accent"])}"></i><span>{text}</span></li>')
    md(f'<div class="ls-insight"><div class="hd"><b>Nhận xét</b><small>{esc(DISCLAIMER)}</small></div>'
       f'<ul>{"".join(rows)}</ul></div>')


def kpi_cards(items: list[tuple[str, str, str, str]]) -> None:
    cards = "".join(
        f'<article class="ls-kpi"><span class="l">{esc(label)}</span>'
        f'<span class="v">{esc(value)}</span>'
        f'<span class="s" style="color:{color}">{esc(sub)}</span></article>'
        for label, value, sub, color in items
    )
    md(f'<section class="ls-kpis">{cards}</section>')


PAGE_ICONS = {
    "overview": '<path d="M4 19V10M10 19V5M16 19v-7M22 19H2" />',
    "liquidity": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    "cost": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 12h1M14 12h1M9 16h1M14 16h1"/>',
    "portfolio": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>',
}


_HEADER_SLOT = None


def page_title(title: str, subtitle: str, icon: str = "") -> None:
    """Đầu trang: dải màu cùng phong cách tab Giới thiệu, có biểu tượng của tab."""
    art = (f'<span class="ls-ph-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
           f'stroke-linecap="round" stroke-linejoin="round">{PAGE_ICONS[icon]}</svg></span>' if icon in PAGE_ICONS else "")
    slot = _HEADER_SLOT if _HEADER_SLOT is not None else st.container()
    with slot:
        _page_band(art, title, subtitle)


def _page_band(art: str, title: str, subtitle: str) -> None:
    md(f'<div class="ls-ph">{art}<div class="ls-ph-text"><h1 class="ls-h1">{esc(title)}</h1>'
       f'<p class="ls-sub">{esc(subtitle)}</p></div>'
       '<svg class="ls-ph-art" viewBox="0 0 220 90" aria-hidden="true"><circle cx="170" cy="45" r="60" fill="none" '
       'stroke="currentColor" stroke-opacity=".18"/><circle cx="170" cy="45" r="36" fill="none" stroke="currentColor" '
       'stroke-opacity=".25"/><path d="M10 70 C 50 20, 80 90, 120 45 S 180 10, 215 30" fill="none" '
       'stroke="currentColor" stroke-opacity=".5" stroke-width="3" stroke-linecap="round"/></svg></div>')


def section_head(title: str, note: str = "") -> None:
    note_html = f'<p class="ls-note">{esc(note)}</p>' if note else '<div style="height:10px"></div>'
    md(f'<h2 class="ls-h2">{esc(title)}</h2>{note_html}')


def style_figure(fig: go.Figure, t: dict[str, object], height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=8, t=8, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color=str(t["muted"]), size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, bgcolor="rgba(0,0,0,0)",
                    font=dict(color=str(t["text"]))),
        hoverlabel=dict(bgcolor=str(t["surf"]), font_color=str(t["text"]), bordercolor=str(t["line"])),
        separators=",.",  # dấu phẩy thập phân, dấu chấm hàng nghìn
    )
    fig.update_xaxes(showgrid=False, linecolor=str(t["line"]), zeroline=False)
    fig.update_yaxes(gridcolor=str(t["line"]), zeroline=False)
    return fig






def segmented(label: str, options: list[str], key: str, default: str, show_label: bool = True) -> str:
    """Segmented control; nếu người dùng bấm bỏ chọn thì giữ lựa chọn cũ."""
    remember = f"_{key}_last"
    current = st.session_state.get(remember, default)
    if current not in options:
        current = default
    value = st.segmented_control(
        label, options, default=current, key=key, selection_mode="single",
        label_visibility="visible" if show_label else "collapsed",
    )
    value = value or current
    st.session_state[remember] = value
    return value


def _alpha(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# --------------------------------------------------------------------------
# Xuất biểu đồ: CSV dữ liệu hoặc ảnh PNG
# --------------------------------------------------------------------------
PNG_READY = importlib.util.find_spec("kaleido") is not None
PDF_READY = all(importlib.util.find_spec(name) is not None for name in ("reportlab", "matplotlib"))


def chart_config(name: str) -> dict[str, object]:
    """Thanh công cụ Plotly chỉ giữ nút tải ảnh (chạy ngay trên trình duyệt, không cần cài thêm)."""
    return {
        "displaylogo": False,
        "modeBarButtons": [["toImage"]],
        "toImageButtonOptions": {"format": "png", "filename": name, "scale": 2},
    }


def show_chart(fig: go.Figure, data: pd.DataFrame, name: str, t: dict[str, object], key: str) -> None:
    """Vẽ biểu đồ kèm hàng nút xuất: dữ liệu CSV hoặc ảnh PNG, người dùng tự chọn."""
    st.plotly_chart(fig, width="stretch", config=chart_config(name), key=f"chart_{key}")
    export = fig.to_dict()
    background = str(t["surf"])

    def make_png() -> bytes:
        image = go.Figure(export)
        image.update_layout(paper_bgcolor=background, plot_bgcolor=background,
                            margin=dict(l=40, r=30, t=30, b=40))
        return image.to_image(format="png", width=1400, height=int((image.layout.height or 320) * 1.6),
                              scale=2)

    with st.popover("Tải về", icon=":material/download:"):
        st.caption("Chọn định dạng muốn tải")
        st.download_button(
            "Dữ liệu (CSV)", data.to_csv(index=False).encode("utf-8-sig"), file_name=f"{name}.csv",
            mime="text/csv", icon=":material/table_view:", key=f"csv_{key}", width="stretch",
            on_click="ignore",
        )
        if PNG_READY:
            st.download_button(
                "Ảnh biểu đồ (PNG)", make_png, file_name=f"{name}.png", mime="image/png",
                icon=":material/image:", key=f"png_{key}", width="stretch", on_click="ignore",
            )
        else:
            st.button("Ảnh biểu đồ (PNG)", icon=":material/image:", key=f"png_{key}", width="stretch",
                      disabled=True)
            st.caption("Cần cài thư viện kaleido (pip install kaleido). Tạm thời có thể rê chuột lên biểu đồ "
                       "và bấm biểu tượng máy ảnh ở góc phải để tải ảnh.")


# --------------------------------------------------------------------------
# Thanh điều hướng, dải thông báo, bộ chọn thời gian
# --------------------------------------------------------------------------
def _job_time(job: dict[str, str] | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str((job or {}).get("finished_at", ""))).astimezone(VN_TZ)
    except ValueError:
        return None


def data_pill(latest: date | None, job: dict[str, str] | None, t: dict[str, object]) -> str:
    """Thanh trạng thái: dữ liệu đến phiên nào, lần cập nhật SSI gần nhất."""
    if latest is None:
        text, fg, bg, icon = "Chưa có dữ liệu", t["muted"], t["surf2"], "•"
    else:
        text, fg, bg, icon = f"Dữ liệu đến phiên {latest:%d/%m/%Y}", t["ok"], t["okBg"], "✓"
    finished = _job_time(job)
    if job and job.get("status") == "error":
        ssi, ssi_color = (f"SSI: lỗi kết nối lúc {finished:%H:%M %d/%m}" if finished else "SSI: lỗi kết nối"), t["bad"]
    elif finished:
        ssi, ssi_color = f"SSI: cập nhật {finished:%H:%M %d/%m}", t["muted"]
    else:
        ssi, ssi_color = "SSI: chưa có nhật ký cập nhật", t["muted"]
    tooltip = f"{text}. {ssi} (SSI FastConnect, cập nhật sau mỗi phiên, giờ Việt Nam)."
    return (
        f'<div class="ls-status" title="{esc(tooltip)}">'
        f'<span class="ls-pill" role="status" style="background:{bg};color:{fg}"><b>{icon}</b>'
        f'<span>{esc(text)}</span></span>'
        f'<small><span style="color:{ssi_color}">{esc(ssi)}</span></small></div>'
    )


def header(latest: date | None, job: dict[str, str] | None, t: dict[str, object]) -> str:
    with st.container(key="card_header"):
        brand, nav, status, toggle = st.columns([1.9, 5.2, 2.2, 0.8], vertical_alignment="center", gap="small")
        with brand:
            md(
                f'<div class="ls-brand"><svg width="36" height="36" viewBox="0 0 28 28" aria-hidden="true">'
                f'<rect width="28" height="28" rx="7" fill="{t["accent"]}"></rect>'
                f'<path d="M7 18c3-6 5-6 7-2s4 4 7-4" stroke="{t["onAccent"]}" stroke-width="2.2" '
                f'fill="none" stroke-linecap="round"></path></svg>'
                f'<div><b>LiquiSense</b><small>Radar thanh khoản cổ phiếu Việt Nam</small></div></div>'
            )
        with nav:
            page = segmented("Điều hướng", PAGES, "nav", PAGES[0], show_label=False)
        with status:
            md(data_pill(latest, job, t))
        with toggle:
            dark = st.session_state.get("dark", False)
            if st.button("Sáng" if dark else "Tối", key="theme_toggle",
                         icon=":material/light_mode:" if dark else ":material/dark_mode:",
                         help="Chuyển giao diện sáng / tối", width="stretch"):
                st.session_state["dark"] = not dark
                st.rerun()
    return page


def notice_band(latest: date, demo: bool, job: dict[str, str] | None, t: dict[str, object]) -> None:
    business_days = len(pd.bdate_range(latest + timedelta(days=1), datetime.now(VN_TZ).date()))
    disclaimer = "Công cụ phân tích học thuật, không phải khuyến nghị đầu tư. Mọi spread và chi phí đều là ước lượng."
    if demo:
        head, fg, bg = "Số liệu minh họa — chưa phải dữ liệu SSI.", t["warn"], t["warnBg"]
    elif business_days > 1:
        head, fg, bg = f"Dữ liệu có thể đã cũ — phiên mới nhất {latest:%d/%m/%Y}.", t["warn"], t["warnBg"]
    elif job and job.get("status") == "error":
        head, fg, bg = "Lần cập nhật gần nhất gặp lỗi — đang hiển thị dữ liệu đã lưu.", t["bad"], t["badBg"]
    else:
        head, fg, bg = f"Dữ liệu SSI FastConnect · sau phiên {latest:%d/%m/%Y}.", t["accentText"], t["accentSoft"]
    md(f'<div class="ls-band" style="background:{bg};color:{fg}"><strong>{esc(head)}</strong>'
       f'<span>{esc(disclaimer)}</span></div>')


PRESETS = {"1 tháng": 31, "3 tháng": 92, "6 tháng": 183, "1 năm": 366, "3 năm": 1096,
           "5 năm": 1827, "Tất cả": -1, "Tùy chọn": 0}


def time_control(dates: list[date]) -> Period:
    """Chọn một ngày (lịch hoặc gõ tay) hoặc một khoảng thời gian.

    - Một ngày: chỉ số = cửa sổ 20 phiên kết thúc ở phiên đó.
    - Khoảng: chỉ số được gộp đúng trong khoảng đã chọn; cảnh báo lấy ở phiên cuối khoảng.
    """
    first, last = dates[0], dates[-1]

    def snap(day: date) -> date:
        earlier = [d for d in dates if d <= day]
        return earlier[-1] if earlier else first

    with st.container(border=True, key="card_time"):
        c1, c2, c3, c4 = st.columns([1.25, 5.4, 1.7, 1.2], vertical_alignment="bottom")
        with c1:
            mode = segmented("Thời gian", ["Một ngày", "Khoảng"], "time_mode", "Một ngày")
        if mode == "Một ngày":
            with c2:
                chosen = st.date_input(
                    "Chọn hoặc gõ ngày (dd/mm/yyyy)", value=st.session_state.get("_day_last", last),
                    min_value=first, max_value=last, format="DD/MM/YYYY", key="time_day",
                )
            chosen = chosen if isinstance(chosen, date) else last
            st.session_state["_day_last"] = chosen
            as_of = snap(chosen)
            period = Period("day", as_of, max(first, as_of - timedelta(days=183)), as_of)
            with c3:
                note = (f"Ngày {chosen:%d/%m/%Y} không có phiên → dùng phiên {as_of:%d/%m/%Y}"
                        if as_of != chosen else "Chỉ số = cửa sổ 20 phiên kết thúc ở ngày này")
                md(f'<p class="ls-note" style="margin:0 0 10px">{esc(note)}</p>')
        else:
            with c2:
                preset = segmented("Khoảng nhanh", list(PRESETS), "time_preset", "3 tháng")
            if preset == "Tùy chọn":
                with c3:
                    default_range = st.session_state.get("_range_last", (max(first, last - timedelta(days=92)), last))
                    picked = st.date_input(
                        "Từ ngày – đến ngày", value=default_range, min_value=first, max_value=last,
                        format="DD/MM/YYYY", key="time_range",
                    )
                picked = tuple(picked) if isinstance(picked, (tuple, list)) else (picked,)
                start = picked[0] if picked else first
                end = picked[1] if len(picked) > 1 else last
                if start > end:
                    start, end = end, start
                st.session_state["_range_last"] = (start, end)
            else:
                end = last
                days = PRESETS[preset]
                start = first if days < 0 else max(first, end - timedelta(days=days))
                with c3:
                    md(f'<p class="ls-note" style="margin:0 0 10px">Chỉ số tính trong khoảng '
                       f'{start:%d/%m/%Y} – {end:%d/%m/%Y}</p>')
            as_of = snap(end)
            sessions = sum(1 for d in dates if start <= d <= end)
            if sessions < MIN_SESSIONS_RANGE:
                st.warning(f"Khoảng đã chọn chỉ có {sessions} phiên giao dịch; cần ít nhất "
                           f"{MIN_SESSIONS_RANGE} phiên để tính chỉ số. Hãy chọn khoảng dài hơn.")
            period = Period("range", as_of, start, end)
        with c4:
            md(f'<p class="ls-note" style="margin:0 0 10px;text-align:right">Kho dữ liệu: '
               f'{first:%d/%m/%Y} – {last:%d/%m/%Y} · {vn(len(dates))} phiên</p>')
    return period


MIN_SESSIONS_RANGE = 10


# --------------------------------------------------------------------------
# Thành phần dùng chung giữa các trang
# --------------------------------------------------------------------------
def alert_summary(reason: str) -> str:
    """Bản rút gọn của lý do cảnh báo: chỉ tên chỉ số và mức thay đổi (chi tiết để người dùng bấm xem)."""
    parts = []
    for part in reason.split("; "):
        if part.startswith("Đóng cửa ở giá"):          # kẹt trần/sàn: chỉ giữ vế đầu
            parts.append(part.split(" — ")[0])
            continue
        if part.startswith("không ước lượng được spread"):
            continue
        head, _, rest = part.partition(", ")
        change = rest.split(" so với")[0] if rest else ""
        known = next((n for n in ALERT_NAMES.values() if head.startswith(n)), None)
        if not change or known is None:
            parts.append(part)       # lý do kiểu cũ (cache trước bản cập nhật): giữ nguyên
            continue
        name = known.replace(" (độ nhạy giá)", "").replace(" TB 20 phiên", "")
        parts.append(f"{name} {change}")
    return " · ".join(parts)


def alert_reasons(alerts: pd.DataFrame) -> dict[str, str]:
    """Lý do cảnh báo cụ thể theo mã (ưu tiên mức nặng nhất nếu một mã có nhiều dòng)."""
    if alerts is None or alerts.empty or "reason" not in alerts:
        return {}
    order = {"Do": 0, "Vang": 1, "Thong bao": 2}
    ordered = alerts.assign(_o=alerts["severity"].map(order)).sort_values("_o")
    return {str(r["symbol"]): reason_vi(r["reason"]) for _, r in ordered.drop_duplicates("symbol").iterrows()}


def reason_vi(text: str) -> str:
    """Dịch lý do cảnh báo (module analytics ghi không dấu) sang tiếng Việt có dấu."""
    out = str(text)
    for src, dst in (
        ("Spread uoc tinh tang", "Spread ước lượng tăng"),
        ("Amihud tang", "Amihud tăng"),
        ("ADV gia tri giam", "ADV giá trị giảm"),
        ("ADV gia tri tang", "Giá trị giao dịch tăng"),
        (" so voi lich su", " so với 60 phiên"),
    ):
        out = out.replace(src, dst)
    parts = [tok.replace(".", ",") if tok.replace(".", "").isdigit() else tok for tok in out.split(" ")]
    return " ".join(parts).replace(" sigma", "σ")


STATUS_VI = {"Du du lieu": "Đủ dữ liệu", "Khong du du lieu": "Không đủ dữ liệu",
             "Tran san lien tuc": "Kẹt trần/sàn liên tục"}
LEVEL_VI = {"Do": "Cảnh báo đỏ", "Vang": "Cảnh báo vàng", "Thong bao": "Hoạt động bất thường"}
ALERT_FILTERS = ["Tất cả", "Đỏ", "Vàng", "Bất thường", "Đỏ hoặc vàng", "Không cảnh báo"]


def status_badge(symbol: str, status: str, levels: dict[str, str], t: dict[str, object]) -> str:
    level = levels.get(symbol)
    if status == "Tran san lien tuc":
        text, bg, fg = "Kẹt trần/sàn liên tục", t["badBg"], t["bad"]
    elif level == "Do":
        text, bg, fg = "Cảnh báo đỏ", t["badBg"], t["bad"]
    elif level == "Vang":
        text, bg, fg = "Cảnh báo vàng", t["warnBg"], t["warn"]
    elif level == "Thong bao":
        text, bg, fg = "Bất thường", t["infoBg"], t["info"]
    elif status == "Du du lieu":
        text, bg, fg = "Đủ dữ liệu", t["okBg"], t["ok"]
    else:
        text, bg, fg = "Không đủ dữ liệu", t["surf2"], t["muted"]
    return f'<span class="ls-badge" style="background:{bg};color:{fg}">{text}</span>'


def filter_metrics(metrics: pd.DataFrame, board: str, sector: str, tier: str = "",
                   alert: str = "Tất cả", levels: dict[str, str] | None = None) -> pd.DataFrame:
    out = metrics
    if board != "Tất cả":
        out = out[out["board"].eq(board)]
    if sector != "Tất cả ngành":
        out = out[out["sector"].eq(sector)]
    if tier.startswith("Tầng 2"):
        out = out[out["status"].eq("Du du lieu")]
    elif tier.startswith("Tầng 3"):
        out = out[out["score"].ge(70)]
    if alert != "Tất cả" and levels is not None:
        level = out["symbol"].map(levels)
        wanted = {
            "Đỏ": level.eq("Do"),
            "Vàng": level.eq("Vang"),
            "Bất thường": level.eq("Thong bao"),
            "Đỏ hoặc vàng": level.isin(["Do", "Vang"]),
            "Không cảnh báo": level.isna(),
        }[alert]
        out = out[wanted]
    return out


def board_sector_filters(metrics: pd.DataFrame, prefix: str, with_tier: bool = False,
                         with_alert: bool = False) -> tuple[str, str, str, str]:
    widths = [1.7, 1.5] + ([1.3] if with_tier else []) + ([1.3] if with_alert else [])
    cols = st.columns(widths, vertical_alignment="bottom")
    with cols[0]:
        board = segmented("Sàn", ["Tất cả"] + BOARDS, f"{prefix}_board", "Tất cả")
    sectors = sorted(metrics["sector"].dropna().astype(str).unique().tolist())
    sector = cols[1].selectbox("Ngành", ["Tất cả ngành"] + sectors, key=f"{prefix}_sector")
    tier, alert, index = "", "Tất cả", 2
    if with_tier:
        tier = cols[index].selectbox(
            "Tầng", ["Tầng 1 · toàn bộ", "Tầng 2 · đủ dữ liệu", "Tầng 3 · Score ≥ 70"], key=f"{prefix}_tier"
        )
        index += 1
    if with_alert:
        alert = cols[index].selectbox("Màu cảnh báo", ALERT_FILTERS, key=f"{prefix}_alert",
                                      help="Lọc theo cảnh báo ở phiên cuối của khoảng đã chọn")
    return board, sector, tier, alert


def x_labels(dates: pd.Series) -> list[str]:
    return [f"{d:%d/%m/%y}" for d in pd.to_datetime(dates)]


def category_axis(fig: go.Figure, labels: list[str]) -> None:
    """Trục ngang chỉ gồm các phiên giao dịch: không chừa chỗ trống cho cuối tuần, lễ, Tết.

    Đặt khoảng hiển thị cố định để phiên đầu tiên nằm sát trục dọc (Plotly mặc định chừa lề);
    biểu đồ cột chừa nửa cột hai đầu để cột đầu/cuối không bị cắt.
    """
    has_bars = any(getattr(trace, "type", "") == "bar" for trace in fig.data)
    left, right = (-0.5, len(labels) - 0.5) if has_bars else (-0.15, len(labels) - 0.85)
    fig.update_xaxes(type="category", nticks=10, categoryorder="array", categoryarray=labels,
                     range=[left, right], autorange=False)
