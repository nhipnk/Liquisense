"""Chuẩn hóa dữ liệu SSI, kiểm tra chất lượng và tách thiếu dữ liệu khỏi ngày không giao dịch.

Mỗi bản ghi nến ngày đi qua các bước theo đúng thứ tự trong QUALITY_RULES. Bản ghi vi phạm bước nào
được đếm vào bước đó (đếm một lần, ở lỗi đầu tiên) rồi bị loại; số đếm được ghi vào
data/chat_luong_du_lieu.csv sau mỗi lần cập nhật để người chấm kiểm chứng.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
REQUIRED_COLUMNS = {"date", "symbol", "open", "high", "low", "close", "volume"}
NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume", "value", "listed_shares", "ref_px", "ceil_px", "floor_px")
QUALITY_FILE = "chat_luong_du_lieu.csv"

# (khóa, mô tả) — thứ tự là thứ tự kiểm tra.
QUALITY_RULES: list[tuple[str, str]] = [
    ("missing_key", "Thiếu hoặc sai ngày / mã"),
    ("bad_type", "Giá hoặc khối lượng không phải số (lỗi kiểu dữ liệu)"),
    ("missing_price", "Thiếu giá mở/cao/thấp/đóng cửa hoặc khối lượng"),
    ("non_positive_price", "Giá ≤ 0"),
    ("negative_volume", "Khối lượng âm"),
    ("high_below_low", "Giá cao nhất < giá thấp nhất"),
    ("open_close_outside", "Giá mở/đóng cửa nằm ngoài biên độ cao–thấp của phiên"),
    ("outside_band", "Giá đã điều chỉnh theo sự kiện quyền (nằm ngoài trần–sàn gốc của ngày)"),
    ("duplicate", "Trùng cặp mã–ngày (giữ bản mới nhất)"),
]
RULE_LABELS = dict(QUALITY_RULES)


def _empty_report(rows: int) -> dict[str, int]:
    return {"raw_rows": rows, **{key: 0 for key, _ in QUALITY_RULES}, "kept_rows": 0}


def clean_with_report(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Làm sạch OHLCV và trả kèm số bản ghi bị loại theo từng lỗi. Bản ghi volume=0 được giữ."""
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Thiếu cột bắt buộc: {', '.join(sorted(missing))}")

    report = _empty_report(len(frame))
    cleaned = frame.copy()
    cleaned["date"] = pd.to_datetime(cleaned["date"], errors="coerce").dt.date
    cleaned["symbol"] = cleaned["symbol"].astype("string").str.strip().str.upper()
    price_cols = ["open", "high", "low", "close", "volume"]
    type_error = pd.Series(False, index=cleaned.index)
    for column in NUMERIC_COLUMNS:
        if column in cleaned:
            raw = cleaned[column]
            cleaned[column] = pd.to_numeric(raw, errors="coerce")
            if column in price_cols:  # có giá trị nhưng không đọc được thành số
                type_error |= raw.notna() & cleaned[column].isna()

    checks: list[tuple[str, pd.Series]] = [
        ("missing_key", cleaned["date"].isna() | cleaned["symbol"].isna() | cleaned["symbol"].eq("")),
        ("bad_type", type_error),
        ("missing_price", cleaned[price_cols].isna().any(axis=1)),
        ("non_positive_price", cleaned[["open", "high", "low", "close"]].le(0).any(axis=1)),
        ("negative_volume", cleaned["volume"].lt(0)),
        ("high_below_low", cleaned["high"].lt(cleaned["low"])),
        ("open_close_outside", cleaned["open"].lt(cleaned["low"]) | cleaned["open"].gt(cleaned["high"])
         | cleaned["close"].lt(cleaned["low"]) | cleaned["close"].gt(cleaned["high"])),
    ]

    bad = pd.Series(False, index=cleaned.index)
    for key, failed in checks:
        failed = failed.fillna(False).astype(bool) & ~bad   # mỗi bản ghi chỉ đếm ở lỗi đầu tiên
        report[key] = int(failed.sum())
        bad |= failed

    cleaned = cleaned.loc[~bad].copy()
    # Giá đóng cửa ngoài trần–sàn của ngày: gần như luôn do nến SSI là GIÁ ĐÃ ĐIỀU CHỈNH theo sự kiện quyền
    # trong khi trần/sàn là giá gốc. Bản ghi vẫn đúng, giữ nguyên cả trần/sàn: ngày chạm trần/sàn được xác
    # định bằng TỶ LỆ biên độ (finance.limit_flags) nên không bị ảnh hưởng. Chỉ đếm để báo cáo.
    if "ceil_px" in cleaned and "floor_px" in cleaned:
        has_bounds = cleaned["ceil_px"].notna() & cleaned["floor_px"].notna()
        report["outside_band"] = int((has_bounds & ~cleaned["close"].between(cleaned["floor_px"], cleaned["ceil_px"])).sum())
    before = len(cleaned)
    cleaned = cleaned.drop_duplicates(subset=["symbol", "date"], keep="last")
    report["duplicate"] = before - len(cleaned)

    if "value" not in cleaned:
        cleaned["value"] = cleaned["close"] * cleaned["volume"]
    else:
        cleaned["value"] = cleaned["value"].fillna(cleaned["close"] * cleaned["volume"])
    if "board" not in cleaned:
        cleaned["board"] = "Chua ro"
    if "icb_name" not in cleaned:
        cleaned["icb_name"] = "Chua phan nganh"
    if "event_flag" not in cleaned:
        cleaned["event_flag"] = False

    report["kept_rows"] = len(cleaned)
    return cleaned.sort_values(["symbol", "date"]).reset_index(drop=True), report


def clean_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Làm sạch OHLCV; bản ghi volume=0 được giữ, bản ghi lỗi bị loại."""
    return clean_with_report(frame)[0]


def merge_reports(total: dict[str, int], part: dict[str, int]) -> dict[str, int]:
    for key, value in part.items():
        total[key] = total.get(key, 0) + int(value)
    return total


def append_quality_log(root: Path, report: dict[str, int], *, run: str, replaced: int = 0) -> None:
    """Ghi một dòng kết quả kiểm tra chất lượng của lần tải (giờ Việt Nam)."""
    root.mkdir(parents=True, exist_ok=True)
    row = {"thoi_diem": datetime.now(VN_TZ).isoformat(timespec="seconds"), "lan_chay": run,
           "ban_ghi_tai_ve": report.get("raw_rows", 0)}
    row.update({key: report.get(key, 0) for key, _ in QUALITY_RULES})
    row["ghi_de_ban_cu"] = replaced
    row["ban_ghi_hop_le"] = report.get("kept_rows", 0)
    path = root / QUALITY_FILE
    pd.DataFrame([row]).to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8")


def read_quality_log(root: Path) -> pd.DataFrame:
    path = root / QUALITY_FILE
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, ValueError):
        return pd.DataFrame()


def store_quality(bars: pd.DataFrame) -> dict[str, object]:
    """Tình trạng kho dữ liệu hiện tại (sau làm sạch): đủ, thiếu, lặp, đến muộn."""
    if bars.empty:
        return {}
    dates = pd.to_datetime(bars["date"])
    sessions = sorted(dates.dt.date.unique())
    latest = sessions[-1]
    if "no_bar" in bars:   # bảng lịch sử đã chèn phiên không có nến
        no_bar = bars["no_bar"].fillna(False).astype(bool)
        gaps = no_bar.groupby(bars["symbol"]).sum()
        traded = bars[~no_bar]
        per_symbol = traded.assign(_d=pd.to_datetime(traded["date"]).dt.date).groupby("symbol")["_d"].agg(["min", "max", "count"])
        bars = traded
    else:
        per_symbol = bars.assign(_d=dates.dt.date).groupby("symbol")["_d"].agg(["min", "max", "count"])
        position = {d: i for i, d in enumerate(sessions)}
        # Số phiên lẽ ra phải có kể từ phiên đầu tiên của mã = số phiên chung của thị trường trong khoảng đó.
        expected = per_symbol.apply(lambda r: position[r["max"]] - position[r["min"]] + 1, axis=1)
        gaps = (expected - per_symbol["count"]).clip(lower=0)
    optional = {c: int(bars[c].isna().sum()) for c in ("listed_shares", "ref_px", "ceil_px", "floor_px") if c in bars}
    return {
        "rows": len(bars),
        "symbols": int(bars["symbol"].nunique()),
        "sessions": len(sessions),
        "first": sessions[0],
        "latest": latest,
        "duplicates": int(bars.duplicated(["symbol", "date"]).sum()),
        "zero_volume_rows": int(bars["volume"].eq(0).sum()),
        "event_rows": int(bars.get("event_flag", pd.Series(False)).fillna(False).astype(bool).sum()),
        "symbols_with_gaps": int(gaps.gt(0).sum()),
        "missing_sessions": int(gaps.sum()),
        "late_symbols": int(per_symbol["max"].lt(latest).sum()),
        "late_list": sorted(per_symbol.index[per_symbol["max"].lt(latest)].tolist()),
        "optional_missing": optional,
    }
