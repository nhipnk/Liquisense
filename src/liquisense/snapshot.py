"""Bộ nhớ đệm trên đĩa cho dữ liệu đã làm sạch và chỉ số thanh khoản.

Ý tưởng tăng tốc: chỉ số theo ngày (spread, Amihud, ADV… cửa sổ 20 phiên) của mỗi mã chỉ
phụ thuộc vào các phiên trước đó, nên tính MỘT LẦN cho toàn bộ lịch sử rồi lưu thành
"bảng lịch sử chỉ số" (data/cache/history_*.parquet). Sau đó:

- Chọn một ngày bất kỳ  -> chỉ cần lấy dòng cuối của mỗi mã tính đến ngày đó và xếp hạng.
- Chọn một khoảng ngày  -> gộp các giá trị ngày trong đúng khoảng đó (trung vị, trung bình…).
- Cảnh báo               -> dùng lại bảng này, không phải tính lại từ nến.

Bảng được tính lại tự động khi kho Parquet thay đổi (job cập nhật ghi dữ liệu mới).
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from liquisense.analytics import alerts_from_history
from liquisense.data.storage import data_root, load_daily_bars
from liquisense.finance import LIMIT_LOCK_SHARE, calculate_symbol_history, score_metrics

STOCK_PATTERN = r"[A-Z0-9]{3}"
ALERT_WINDOW_SESSIONS = 130  # cảnh báo cần 60 phiên lịch sử + 20 phiên cửa sổ + tháng trước
MIN_RANGE_SESSIONS = 10      # khoảng ngắn hơn 10 phiên thì không đủ để chấm điểm
METRIC_FIELDS = ("spread", "amihud", "adv_volume", "adv_value", "zero_days")
HISTORY_VERSION = "h6"   # h4: lợi suất giá điều chỉnh; h5: chèn phiên không có nến; h6: đếm phiên trần/sàn       # đổi khi cấu trúc bảng lịch sử thay đổi


def board_label(value: object) -> str:
    text = str(value or "").strip()
    mapped = {"UPCOM": "UPCoM", "HSX": "HOSE", "CHUA RO": "Chưa rõ"}.get(text.upper(), text)
    return mapped or "Chưa rõ"


def sector_label(value: object) -> str:
    text = str(value or "").strip()
    return {"Chua phan nganh": "Chưa phân ngành", "": "Chưa phân ngành"}.get(text, text)


def store_signature(root: Path | None = None) -> str:
    """Chữ ký của kho dữ liệu: đổi khi có file Parquet được thêm hoặc ghi lại."""
    root = root or data_root()
    parts = [HISTORY_VERSION]
    # Chỉ dùng tên và kích thước file (không dùng giờ sửa file): sau khi git clone, giờ sửa file thay đổi
    # nhưng nội dung thì không — nhờ vậy bảng tính sẵn trên GitHub Actions dùng lại được trên Streamlit Cloud.
    files = sorted(root.glob("daily_bars_*.parquet"))
    adjustments = root / "dieu_chinh_gia.csv"
    if adjustments.exists():
        files.append(adjustments)
    for path in files:
        parts.append(f"{path.name}:{path.stat().st_size}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _cache_dir(root: Path) -> Path:
    path = root / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prune(cache: Path, keep: str) -> None:
    """Xóa cache của các phiên bản kho cũ để thư mục không phình ra."""
    for path in cache.glob("*.parquet"):
        if keep not in path.name:
            try:
                path.unlink()
            except OSError:
                pass


def _read_cached(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError):
        return None
    if "date" in frame:
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def _write_cached(frame: pd.DataFrame, path: Path) -> None:
    try:
        frame.to_parquet(path, index=False)
    except (OSError, ValueError):
        pass


# --------------------------------------------------------------------------
# Dữ liệu nến đã làm sạch
# --------------------------------------------------------------------------
def prepare_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Chỉ giữ cổ phiếu (mã 3 ký tự) và chuẩn hóa nhãn sàn, ngành có dấu."""
    if bars.empty:
        return bars
    bars = bars[bars["symbol"].astype(str).str.fullmatch(STOCK_PATTERN)].copy()
    bars["board"] = bars["board"].map(board_label)
    bars["icb_name"] = bars["icb_name"].map(sector_label)
    return bars.reset_index(drop=True)


def load_prepared_bars(root: Path | None = None) -> pd.DataFrame:
    """Đọc toàn bộ kho; dùng bản gộp sẵn trong cache nếu kho chưa thay đổi."""
    root = root or data_root()
    if not list(root.glob("daily_bars_*.parquet")):
        return prepare_bars(load_daily_bars(root))  # dữ liệu mẫu, không cần cache
    signature = store_signature(root)
    cache = _cache_dir(root)
    path = cache / f"bars_{signature}.parquet"
    cached = _read_cached(path)
    if cached is not None:
        return cached
    bars = prepare_bars(load_daily_bars(root))
    _write_cached(bars, path)
    return bars


# --------------------------------------------------------------------------
# Bảng lịch sử chỉ số (tính một lần cho mọi mã, mọi ngày)
# --------------------------------------------------------------------------
def fill_missing_sessions(ordered: pd.DataFrame, calendar: pd.Index) -> pd.DataFrame:
    """Chèn các phiên thị trường có mở cửa mà mã không có nến (từ phiên đầu đến phiên cuối của mã):
    khối lượng = giá trị = 0, giá để trống, đánh dấu no_bar=True."""
    ordered = ordered.assign(no_bar=False)
    if ordered.empty:
        return ordered
    sessions = calendar[(calendar >= ordered["date"].iloc[0]) & (calendar <= ordered["date"].iloc[-1])]
    if len(sessions) == len(ordered):
        return ordered
    full = ordered.set_index("date").reindex(sessions)
    missing = full["no_bar"].isna()
    for column in ("symbol", "board", "icb_name", "listed_shares"):
        if column in full:
            full[column] = full[column].ffill().bfill()
    full.loc[missing, ["volume", "value"]] = 0.0
    full.loc[missing, "no_bar"] = True
    if "event_flag" in full:
        full["event_flag"] = full["event_flag"].map(lambda v: bool(v) if pd.notna(v) else False).astype(bool)
    full["no_bar"] = full["no_bar"].map(lambda v: bool(v) if pd.notna(v) else True).astype(bool)
    return full.rename_axis("date").reset_index()


def build_history_table(bars: pd.DataFrame) -> pd.DataFrame:
    """Chỉ số theo ngày của mọi mã: một dòng cho mỗi mã-phiên."""
    frames: list[pd.DataFrame] = []
    # Lịch phiên của thị trường = mọi ngày có ít nhất một mã giao dịch. SSI KHÔNG trả nến cho phiên mà một mã
    # không có giao dịch, nên phải chèn các phiên đó (khối lượng = 0) thì ADV và tỷ lệ ngày không giao dịch
    # mới đúng — nếu không, mã ít giao dịch trông như giao dịch mỗi ngày và ADV bị thổi phồng.
    calendar = pd.Index(sorted(bars["date"].unique()))
    for symbol, group in bars.groupby("symbol", sort=True):
        ordered = fill_missing_sessions(group.sort_values("date").reset_index(drop=True), calendar)
        history = calculate_symbol_history(ordered)
        if history.empty:
            continue
        history = history.reset_index(drop=True)
        history["date"] = ordered["date"].values
        history["symbol"] = symbol
        history["board"] = ordered["board"].values
        history["sector"] = ordered["icb_name"].values
        # Phiên không có nến: giữ giá đóng cửa gần nhất (để hiển thị và tính chi phí), lợi suất vẫn để trống.
        history["close"] = pd.to_numeric(ordered["close"], errors="coerce").ffill().values
        history["volume"] = pd.to_numeric(ordered["volume"], errors="coerce").values
        history["value"] = pd.to_numeric(ordered["value"], errors="coerce").values
        history["no_bar"] = ordered["no_bar"].values
        frames.append(history)
    if not frames:
        return pd.DataFrame()
    table = pd.concat(frames, ignore_index=True)
    float_cols = table.select_dtypes("float64").columns
    table[float_cols] = table[float_cols].astype("float32")  # giảm một nửa bộ nhớ
    return table


def load_history_table(root: Path | None = None, bars: pd.DataFrame | None = None) -> pd.DataFrame:
    root = root or data_root()
    signature = store_signature(root)
    path = _cache_dir(root) / f"history_{signature}.parquet"
    cached = _read_cached(path)
    if cached is not None:
        return cached
    if bars is None:
        bars = load_prepared_bars(root)
    table = build_history_table(bars)
    if list(root.glob("daily_bars_*.parquet")):
        _write_cached(table, path)
        _prune(_cache_dir(root), signature)  # chỉ xóa bản cũ khi bản mới đã ghi xong
    return table


def history_cache_path(root: Path | None = None) -> Path:
    root = root or data_root()
    return _cache_dir(root) / f"history_{store_signature(root)}.parquet"


def latest_stale_history(root: Path | None = None) -> Path | None:
    """Bảng lịch sử của lần cập nhật trước (nếu còn), dùng tạm trong lúc dựng bảng mới."""
    root = root or data_root()
    files = sorted(_cache_dir(root).glob("history_*.parquet"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def read_history_file(path: Path) -> pd.DataFrame:
    frame = _read_cached(path)
    return frame if frame is not None else pd.DataFrame()


# --------------------------------------------------------------------------
# Chỉ số tại một ngày và trong một khoảng ngày
# --------------------------------------------------------------------------
LIMIT_STATUS = "Tran san lien tuc"


def limit_share(frame: pd.DataFrame) -> pd.Series:
    """Tỷ lệ phiên đóng cửa ở trần hoặc sàn trong cửa sổ."""
    days = frame.get("ceil_days", 0) + frame.get("floor_days", 0)
    sessions = frame["sessions"] if "sessions" in frame else 20.0
    return (pd.Series(days, index=frame.index) / sessions).fillna(0.0)


def _status(frame: pd.DataFrame) -> pd.Series:
    """Đủ dữ liệu / Kẹt trần-sàn liên tục / Không đủ dữ liệu.

    Mã kẹt trần/sàn thường thiếu spread (phiên chạm trần/sàn không dùng được cho Corwin–Schultz) nhưng
    không phải "thiếu dữ liệu": đó là trạng thái thanh khoản xấu nhất, nên được tách thành nhóm riêng."""
    valid = frame[list(METRIC_FIELDS)].notna().all(axis=1)
    status = valid.map({True: "Du du lieu", False: "Khong du du lieu"})
    locked = ~valid & limit_share(frame).ge(LIMIT_LOCK_SHARE)
    return status.mask(locked, LIMIT_STATUS)


def metrics_at(table: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Chỉ số cửa sổ 20 phiên của mỗi mã tại phiên gần nhất <= as_of (giống latest_metrics)."""
    visible = table[table["date"] <= as_of]
    if visible.empty:
        return pd.DataFrame()
    last = visible.sort_values(["symbol", "date"]).groupby("symbol", sort=True).tail(1)
    columns = ["symbol", "board", "sector", "date", "close", "spread", "amihud", "amihud_n",
               "daily_volatility", "adv_volume", "adv_value", "turnover", "floor_low_liq_days",
               "zero_days", "spread_adj", "ceil_days", "floor_days"]
    frame = last.reindex(columns=columns).reset_index(drop=True).astype({c: "float64" for c in columns[4:]})
    frame["status"] = _status(frame)
    return score_metrics(frame)


def metrics_for_range(table: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Chỉ số gộp đúng trong khoảng [start, end] người dùng chọn.

    - Spread: trung bình spread ngày trong khoảng. - Amihud: trung bình Amihud ngày.
    - ADV khối lượng/giá trị: bình quân các phiên có giao dịch hợp lệ trong khoảng.
    - Biến động: độ lệch chuẩn lợi suất ngày.     - Tỷ lệ ngày không giao dịch trong khoảng.
    Mã có ít hơn 10 quan sát hợp lệ trong khoảng thì không đủ dữ liệu để chấm điểm.
    """
    window = table[(table["date"] >= start) & (table["date"] <= end)]
    if window.empty:
        return pd.DataFrame()
    window = window.sort_values(["symbol", "date"])
    valid_day = window["volume"].notna() & (window["volume"] >= 0)
    work = window.assign(
        vol_ok=window["volume"].where(valid_day),
        val_ok=window["value"].where(valid_day),
        zero=((window["volume"] == 0) & valid_day).astype("float64"),
        observed=valid_day.astype("float64"),
        session=1.0,
        ceil_flag=window["ceil_flag"].astype("float64") if "ceil_flag" in window else 0.0,
        floor_flag=window["floor_flag"].astype("float64") if "floor_flag" in window else 0.0,
    )
    grouped = work.groupby("symbol", sort=True)
    last = grouped.tail(1).set_index("symbol")
    counts = grouped.agg(
        spread_n=("spread_daily", "count"), amihud_n=("amihud_daily", "count"),
        ret_n=("daily_return", "count"), vol_n=("vol_ok", "count"), observed=("observed", "sum"),
    )
    frame = pd.DataFrame({
        "board": last["board"], "sector": last["sector"], "date": last["date"],
        "close": last["close"].astype("float64"),
        "spread": grouped["spread_daily"].mean(),
        "spread_adj": grouped["spread_daily_adj"].mean(),
        "amihud": grouped["amihud_daily"].mean(),
        "amihud_n": counts["amihud_n"],
        "daily_volatility": grouped["daily_return"].std(),
        "adv_volume": grouped["vol_ok"].mean(),
        "adv_value": grouped["val_ok"].mean(),
        "floor_low_liq_days": np.nan,
        "zero_days": grouped["zero"].sum() / counts["observed"].where(counts["observed"] > 0),
        "ceil_days": grouped["ceil_flag"].sum(),
        "floor_days": grouped["floor_flag"].sum(),
        "sessions": grouped["session"].sum(),
    })
    # turnover = ADV khối lượng / số cổ phiếu niêm yết; suy ra số cổ phiếu từ phiên cuối.
    with np.errstate(divide="ignore", invalid="ignore"):
        shares = (last["adv_volume"] / last["turnover"]).astype("float64")
    frame["turnover"] = (frame["adv_volume"] / shares.where(shares > 0)).astype("float64")
    minimum = MIN_RANGE_SESSIONS
    frame.loc[counts["spread_n"] < minimum, ["spread", "spread_adj"]] = np.nan
    frame.loc[counts["amihud_n"] < minimum, "amihud"] = np.nan
    frame.loc[counts["ret_n"] < minimum, "daily_volatility"] = np.nan
    frame.loc[counts["vol_n"] < minimum, ["adv_volume", "adv_value", "zero_days"]] = np.nan
    frame = frame.reset_index().rename(columns={"index": "symbol"})
    frame = frame.astype({c: "float64" for c in ("spread", "spread_adj", "amihud", "daily_volatility", "adv_volume",
                                                  "adv_value", "zero_days", "amihud_n", "ceil_days", "floor_days",
                                                  "sessions")})
    frame["status"] = _status(frame)
    return score_metrics(frame)


def alerts_at(table: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Cảnh báo của các mã có giao dịch đúng phiên as_of."""
    visible = table[table["date"] <= as_of]
    sessions = sorted(set(visible["date"]))
    if len(sessions) > ALERT_WINDOW_SESSIONS:
        visible = visible[visible["date"] >= sessions[-ALERT_WINDOW_SESSIONS]]
    alerts = alerts_from_history(visible[["date", "symbol", "spread", "amihud", "adv_value"]]
                                 .astype({"spread": "float64", "amihud": "float64", "adv_value": "float64"}))
    if not alerts.empty:
        alerts = alerts[pd.to_datetime(alerts["date"]).dt.date == as_of].reset_index(drop=True)
    locked = limit_lock_alerts(visible, as_of)
    if not locked.empty:
        alerts = locked if alerts.empty else pd.concat([alerts, locked], ignore_index=True)
        alerts["date"] = pd.to_datetime(alerts["date"])     # cùng kiểu ngày để ghi parquet
    return alerts


def limit_lock_alerts(visible: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Cảnh báo đỏ cho mã đóng cửa ở trần/sàn từ 8/20 phiên gần nhất trở lên."""
    if "ceil_days" not in visible:
        return pd.DataFrame()
    last = visible[visible["date"].eq(as_of)]
    rows = []
    for _, r in last.iterrows():
        ceil, floor = float(r["ceil_days"]), float(r["floor_days"])
        if (ceil + floor) / 20 < LIMIT_LOCK_SHARE:
            continue
        total = ceil + floor
        if floor >= 2 * ceil:
            what = (f"Đóng cửa ở giá sàn {floor:.0f}/20 phiên gần nhất — dư bán giá sàn, người cần bán "
                    "rất khó khớp lệnh")
        elif ceil >= 2 * floor:
            what = (f"Đóng cửa ở giá trần {ceil:.0f}/20 phiên gần nhất — dư mua giá trần, người cần mua "
                    "rất khó khớp lệnh và giá dễ đảo chiều")
        else:
            what = (f"Đóng cửa ở giá trần hoặc sàn {total:.0f}/20 phiên gần nhất (trần {ceil:.0f}, sàn {floor:.0f}) — "
                    "giá chạy hết biên độ cả hai chiều, lệnh lớn khó khớp ở mức giá mong muốn")
        rows.append({"date": r["date"], "symbol": r["symbol"], "severity": "Do",
                     "type": "Ket tran san", "reason": what + "; không ước lượng được spread trong các phiên này"})
    return pd.DataFrame(rows)


def alerts_cache_path(as_of: date, root: Path | None = None) -> Path:
    root = root or data_root()
    return _cache_dir(root) / f"alerts_v3_{as_of.isoformat()}_{store_signature(root)}.parquet"   # v3: kẹt trần/sàn


def fetch_prebuilt_cache(base_url: str, root: Path | None = None, timeout: float = 90.0) -> bool:
    """Tải bảng chỉ số đã tính sẵn trên GitHub Actions (file đính kèm của GitHub Release) thay vì tự tính lại
    khi app vừa khởi động trên cloud. Chỉ dùng khi chữ ký kho dữ liệu khớp đúng với bản tính sẵn."""
    import json
    import urllib.request

    root = root or data_root()
    base = base_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/cache.json", timeout=timeout) as response:
            meta = json.loads(response.read().decode("utf-8"))
        if meta.get("signature") != store_signature(root):
            return False
        targets = {"history.parquet": history_cache_path(root)}
        if meta.get("as_of"):
            targets["alerts.parquet"] = alerts_cache_path(date.fromisoformat(meta["as_of"]), root)
        for name, target in targets.items():
            temporary = target.with_name(target.name + ".tai")
            with urllib.request.urlopen(f"{base}/{name}", timeout=timeout) as response, open(temporary, "wb") as out:
                while chunk := response.read(1 << 20):
                    out.write(chunk)
            pd.read_parquet(temporary, columns=["symbol"] if name == "history.parquet" else None)  # file hợp lệ
            temporary.replace(target)
        return True
    except Exception as error:  # mạng lỗi, chưa có release, file hỏng: tự tính như bình thường
        from loguru import logger
        logger.warning("Không dùng được bảng tính sẵn ({}); app sẽ tự tính.", type(error).__name__)
        return False


def load_or_compute_alerts(as_of: date, table: pd.DataFrame | None = None,
                           root: Path | None = None) -> pd.DataFrame:
    root = root or data_root()
    path = alerts_cache_path(as_of, root)
    if path.exists():
        try:
            return pd.read_parquet(path)
        except (OSError, ValueError):
            pass
    if table is None:
        table = load_history_table(root)
    alerts = alerts_at(table, as_of)
    if list(root.glob("daily_bars_*.parquet")):
        _write_cached(alerts, path)
    return alerts


def compute_snapshot(bars: pd.DataFrame, as_of: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Giữ cho tương thích: chỉ số + cảnh báo tại ngày as_of, tính trực tiếp từ nến."""
    table = build_history_table(bars[bars["date"] <= as_of])
    return metrics_at(table, as_of), alerts_at(table, as_of)


def precompute_latest(root: Path | None = None) -> date | None:
    """Gọi sau mỗi lần cập nhật: dựng sẵn bảng lịch sử chỉ số và cảnh báo phiên mới nhất."""
    root = root or data_root()
    bars = load_prepared_bars(root)
    if bars.empty:
        return None
    table = load_history_table(root, bars)
    latest = max(table["date"])
    load_or_compute_alerts(latest, table, root)
    return latest
