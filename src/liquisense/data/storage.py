"""Đọc/ghi Parquet và nhật ký job cập nhật."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv
from loguru import logger

from liquisense.data.clean import clean_daily_bars, clean_with_report, merge_reports

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def data_root() -> Path:
    """Lấy thư mục dữ liệu từ biến môi trường, mặc định là data/."""
    load_dotenv(PROJECT_ROOT / ".env")
    configured = os.getenv("LIQUISENSE_DATA_DIR", "data")
    path = Path(configured)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_daily_bars(root: Path | None = None) -> pd.DataFrame:
    """Đọc các file Parquet; nếu kho rỗng thì dùng dữ liệu demo."""
    root = root or data_root()
    files = sorted(root.glob("daily_bars_*.parquet"))
    if files:
        frames = [frame for frame in (read_partition(path) for path in files) if frame is not None]
        if frames:
            return apply_price_adjustments(clean_daily_bars(pd.concat(frames, ignore_index=True)), root)
    sample_path = PROJECT_ROOT / "data_sample" / "daily_bars.csv"
    if sample_path.exists():
        return clean_daily_bars(pd.read_csv(sample_path))

    from liquisense.data.sample import make_sample_bars

    return clean_daily_bars(make_sample_bars())


ADJUSTMENT_FILE = "dieu_chinh_gia.csv"
ADJUSTMENT_COLUMNS = ("open", "high", "low", "close")


def read_price_adjustments(root: Path) -> pd.DataFrame:
    path = root / ADJUSTMENT_FILE
    if not path.exists():
        return pd.DataFrame(columns=["symbol", "before", "factor", "detected"])
    frame = pd.read_csv(path, dtype={"symbol": str}, encoding="utf-8-sig")
    frame["before"] = pd.to_datetime(frame["before"], errors="coerce").dt.date
    frame["factor"] = pd.to_numeric(frame["factor"], errors="coerce")
    return frame.dropna(subset=["symbol", "before", "factor"])


def append_price_adjustments(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / ADJUSTMENT_FILE
    pd.DataFrame(rows).to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")


def apply_price_adjustments(bars: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Đưa giá các ngày cũ về cùng thang với giá SSI đã điều chỉnh lại (xem update.rescale_factor).

    Mỗi dòng (mã, before, hệ số) nhân giá mở/cao/thấp/đóng cửa của các ngày TRƯỚC ``before``; nhiều sự kiện
    thì nhân dồn. Giá tham chiếu/trần/sàn giữ nguyên (là giá gốc của ngày) — finance.price_scale tự tính lại
    tỷ lệ giữa hai loại giá nên nhận diện trần/sàn vẫn đúng."""
    adjustments = read_price_adjustments(root)
    if adjustments.empty or bars.empty:
        return bars
    bars = bars.copy()
    day = pd.to_datetime(bars["date"]).dt.date
    multiplier = pd.Series(1.0, index=bars.index)
    for record in adjustments.itertuples(index=False):
        hit = bars["symbol"].eq(record.symbol) & (day < record.before)
        multiplier[hit] *= float(record.factor)
    for column in ADJUSTMENT_COLUMNS:
        if column in bars:
            bars[column] = pd.to_numeric(bars[column], errors="coerce") * multiplier
    return bars


def read_partition(path: Path) -> pd.DataFrame | None:
    """Đọc một file ngày; file hỏng (mất điện khi đang ghi, tải về lỗi) được bỏ qua kèm cảnh báo
    thay vì làm sập cả app. Chạy lại scripts/update.py --from-date <ngày đó> để tải lại."""
    try:
        return pd.read_parquet(path)
    except Exception as error:  # pyarrow ném nhiều loại lỗi khác nhau cho file hỏng
        logger.warning("Bỏ qua file hỏng {} ({}).", path.name, type(error).__name__)
        return None


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Ghi ra file tạm rồi đổi tên: nếu bị ngắt giữa chừng, file cũ vẫn nguyên vẹn."""
    temporary = path.with_name(path.name + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def write_daily_bars(frame: pd.DataFrame, root: Path | None = None,
                     report: dict[str, int] | None = None) -> int:
    """Ghi đè idempotent theo ngày, không tạo bản ghi trùng khi chạy lại.

    Nếu truyền `report`, cộng dồn số bản ghi bị loại theo từng lỗi chất lượng và số bản ghi
    đã có trong kho bị thay bằng bản tải mới (khóa "replaced").
    """
    root = root or data_root()
    root.mkdir(parents=True, exist_ok=True)
    cleaned, checked = clean_with_report(frame)
    if report is not None:
        merge_reports(report, checked)
    written = 0
    for date, daily in cleaned.groupby("date", sort=True):
        path = root / f"daily_bars_{date.isoformat()}.parquet"
        # Giữ lại các mã đã có nếu một số mã bị lỗi trong lần cập nhật này.
        previous = read_partition(path) if path.exists() else None
        if path.exists() and previous is None:
            path.replace(path.with_name(path.name + ".hong"))   # giữ lại để kiểm tra, ghi bản mới
        if previous is not None:
            if report is not None:
                report["replaced"] = report.get("replaced", 0) + int(previous["symbol"].isin(daily["symbol"]).sum())
            daily = clean_daily_bars(pd.concat([previous, daily], ignore_index=True))
        _atomic_parquet(daily, path)
        written += len(daily)
    return written


def write_job_log(
    *,
    status: str,
    symbols_ok: int,
    symbols_failed: int,
    message: str,
    root: Path | None = None,
) -> None:
    """Ghi kết quả job, không đưa credential hay token vào log."""
    root = root or data_root()
    root.mkdir(parents=True, exist_ok=True)
    log_path = root / "job_runs.csv"
    record = pd.DataFrame([{
        "finished_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
        "status": status,
        "symbols_ok": symbols_ok,
        "symbols_failed": symbols_failed,
        "message": message,
    }])
    record.to_csv(
        log_path,
        mode="a",
        header=not log_path.exists(),
        index=False,
        encoding="utf-8-sig",
    )


def latest_job(root: Path | None = None) -> dict[str, str] | None:
    """Đọc dòng mới nhất của nhật ký job nếu đã có."""
    path = (root or data_root()) / "job_runs.csv"
    if not path.exists():
        return None
    jobs = pd.read_csv(path, dtype=str)
    return None if jobs.empty else jobs.iloc[-1].fillna("").to_dict()
