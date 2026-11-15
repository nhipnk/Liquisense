"""Job cập nhật dữ liệu SSI sau phiên giao dịch.

Cách chạy:
    python scripts/update.py                 # cập nhật toàn bộ cổ phiếu
    python scripts/update.py --chi-ma-loi    # chỉ tải lại các mã bị lỗi ở lần chạy trước
    python scripts/update.py --tat-ca-ma     # tải cả chứng quyền, phái sinh, trái phiếu
    python scripts/update.py --so-nam 3      # kéo dài lịch sử lên 3 năm (tải bù phần còn thiếu)
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from loguru import logger

from liquisense.data.ssi_source import SsiMarketData, default_history_start, history_years
from liquisense.data.clean import QUALITY_FILE, VN_TZ, append_quality_log
from liquisense.data.storage import (
    ADJUSTMENT_FILE, append_price_adjustments, data_root, read_partition, read_price_adjustments,
    write_daily_bars, write_job_log,
)

FAILED_FILE = "ma_loi.txt"
BATCH_SIZE = 200  # ghi xuống đĩa sau mỗi 200 mã để lỡ dừng giữa chừng không mất dữ liệu


def _stored_date_ranges(root: Path) -> dict[str, tuple[date, date]]:
    """Ngày sớm nhất và mới nhất đã lưu của từng mã trong các file Parquet hiện có."""
    ranges: dict[str, tuple[date, date]] = {}
    for path in root.glob("daily_bars_*.parquet"):
        frame = pd.read_parquet(path, columns=["symbol", "date"])
        if frame.empty:
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
        grouped = frame.dropna(subset=["date"]).groupby("symbol")["date"].agg(["min", "max"])
        for symbol, row in grouped.iterrows():
            symbol = str(symbol)
            if symbol in ranges:
                first, last = ranges[symbol]
                ranges[symbol] = (min(first, row["min"]), max(last, row["max"]))
            else:
                ranges[symbol] = (row["min"], row["max"])
    return ranges


def _start_date(symbol: str, stored: dict[str, tuple[date, date]], target: date,
                backfill: bool, from_date: date | None) -> date:
    """Ngày bắt đầu tải của một mã.

    - Có --from-date: dùng đúng ngày đó.
    - Mã chưa có trong kho: tải đủ số năm lịch sử.
    - Mã đã có: chỉ tải bù 7 ngày gần nhất; riêng khi chạy --so-nam mà kho còn thiếu
      phần lịch sử cũ hơn thì tải lại từ mốc mới.
    """
    if from_date:
        return from_date
    if symbol not in stored:
        return target
    first, last = stored[symbol]
    if backfill and first > target + timedelta(days=10):
        return target
    return max(last - timedelta(days=7), target)


RESCALE_TOLERANCE = 0.005   # giá đóng cửa tải lại lệch > 0,5% so với giá đã lưu = SSI đã điều chỉnh lại lịch sử


def _stored_closes(root: Path, since: date) -> dict[tuple[str, date], float]:
    """Giá đóng cửa đã lưu của các ngày từ ``since`` (chỉ đọc vài file ngày gần nhất)."""
    closes: dict[tuple[str, date], float] = {}
    known: dict[str, list[tuple[date, float]]] = {}   # so với giá đã quy về thang mới, tránh ghi trùng sự kiện
    for record in read_price_adjustments(root).itertuples(index=False):
        known.setdefault(str(record.symbol), []).append((record.before, float(record.factor)))
    for path in root.glob("daily_bars_*.parquet"):
        try:
            day = date.fromisoformat(path.stem.removeprefix("daily_bars_"))
        except ValueError:
            continue
        if day < since:
            continue
        frame = read_partition(path)
        if frame is None or frame.empty:
            continue
        for symbol, close in zip(frame["symbol"].astype(str), pd.to_numeric(frame["close"], errors="coerce")):
            if close == close and close > 0:
                factor = 1.0
                for before, value in known.get(symbol, ()):
                    if before > day:
                        factor *= value
                closes[(symbol, day)] = float(close) * factor
    return closes


def rescale_factor(symbol: str, bars: list[dict[str, object]],
                   stored_closes: dict[tuple[str, date], float]) -> tuple[float, date] | None:
    """So giá vừa tải với giá đã lưu ở các ngày trùng nhau. Nếu lệch quá 0,5% thì SSI đã điều chỉnh lại toàn bộ
    lịch sử giá của mã (sự kiện quyền): trả về (hệ số = giá mới / giá cũ, ngày tải lại sớm nhất).
    Dùng trung vị các ngày trùng để loại sai số làm tròn bước giá."""
    ratios, first_day = [], None
    for bar in bars:
        day = bar["date"] if isinstance(bar["date"], date) else date.fromisoformat(str(bar["date"])[:10])
        first_day = day if first_day is None else min(first_day, day)
        old = stored_closes.get((symbol, day))
        new = pd.to_numeric(bar.get("close"), errors="coerce")
        if old is not None and new == new and new > 0:
            ratios.append(float(new) / old)
    if not ratios or first_day is None:
        return None
    factor = float(pd.Series(ratios).median())
    return (factor, first_day) if abs(factor - 1) > RESCALE_TOLERANCE else None


def read_failed_symbols(root: Path) -> list[str]:
    path = root / FAILED_FILE
    if not path.exists():
        return []
    return [line.strip().upper() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_failed_symbols(root: Path, symbols: list[str]) -> None:
    path = root / FAILED_FILE
    if symbols:
        root.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(symbols) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()


def _flush(records: list[dict[str, object]], root: Path, quality: dict[str, int] | None = None) -> int:
    if not records:
        return 0
    written = write_daily_bars(pd.DataFrame.from_records(records), root, quality)
    records.clear()
    return written


def _log_quality(root: Path, quality: dict[str, int], run: str) -> None:
    """Ghi kết quả kiểm tra chất lượng của lần tải này vào data/chat_luong_du_lieu.csv."""
    if not quality:
        return
    try:
        append_quality_log(root, quality, run=run, replaced=quality.get("replaced", 0))
        dropped = quality.get("raw_rows", 0) - quality.get("kept_rows", 0)
        logger.info("Kiểm tra chất lượng: tải {} bản ghi, loại {} bản ghi lỗi/trùng (chi tiết: {}).",
                    quality.get("raw_rows", 0), dropped, QUALITY_FILE)
    except OSError as error:
        logger.warning("Không ghi được nhật ký chất lượng dữ liệu ({}).", type(error).__name__)


def run_update(
    from_date: date | None = None,
    to_date: date | None = None,
    *,
    only_failed: bool = False,
    include_all_securities: bool = False,
    precompute: bool = True,
    years: int | None = None,
) -> int:
    """Cập nhật universe; lỗi từng mã được log, lưu vào ma_loi.txt để thử lại lần sau."""
    root = data_root()
    today = to_date or datetime.now(VN_TZ).date()  # ngày theo giờ Việt Nam, không phụ thuộc múi giờ máy
    if from_date and from_date > today:
        raise ValueError("--from-date phải nhỏ hơn hoặc bằng --to-date.")
    stored = _stored_date_ranges(root) if root.exists() else {}
    n_years = history_years(years)
    target_start = default_history_start(today, n_years)
    backfill = years is not None
    retry_list = set(read_failed_symbols(root)) if only_failed else set()
    if only_failed and not retry_list:
        logger.info("Không có mã lỗi nào cần tải lại ({} trống).", FAILED_FILE)
        return 0

    symbols_ok = symbols_failed = symbols_empty = written = 0
    records: list[dict[str, object]] = []
    quality: dict[str, int] = {}
    failures: list[str] = []
    run_label = "chi_ma_loi" if only_failed else ("tai_bu" if years is not None or from_date else "hang_ngay")
    started = time.monotonic()

    try:
        with SsiMarketData(include_all_securities=include_all_securities) as client:
            universe = client.get_security_universe()
            if not universe:
                raise RuntimeError("SSI không trả về danh sách mã; dừng job để tránh ghi dữ liệu rỗng.")
            if only_failed:
                universe = [s for s in universe if s["symbol"] in retry_list]
                logger.info("Chỉ tải lại {} mã bị lỗi ở lần chạy trước.", len(universe))

            starts = {
                security["symbol"]: _start_date(security["symbol"], stored, target_start, backfill, from_date)
                for security in universe
            }
            if backfill:
                need = sum(1 for sym, start in starts.items() if start == target_start and sym in stored)
                logger.info("Kéo dài lịch sử lên {} năm (từ {}); {} mã cần tải bù phần cũ.",
                            n_years, target_start, need)
            logger.info("Bắt đầu tải {} mã, từ {} đến {}.", len(universe), min(starts.values()), today)
            reference_data = client.get_reference_data(min(starts.values()), today)
            daily_run = not from_date and not backfill
            stored_closes = _stored_closes(root, min(starts.values())) if daily_run and stored else {}
            adjustments: list[dict[str, object]] = []

            total = len(universe)
            for index, security in enumerate(universe, start=1):
                symbol = security["symbol"]
                try:
                    bars = client.get_bars(
                        symbol=symbol,
                        board=security["board"],
                        icb_name=security.get("icb_name"),
                        listed_shares=security.get("listed_shares"),
                        from_date=starts[symbol],
                        to_date=today,
                    )
                    rescale = rescale_factor(symbol, bars, stored_closes) if bars and stored_closes else None
                    if rescale:
                        # SSI đã điều chỉnh lại lịch sử giá. Không tải lại cả lịch sử (sẽ ghi lại hàng nghìn file
                        # và làm repo phình to), mà lưu hệ số để nhân vào giá các ngày cũ khi đọc kho.
                        adjustments.append({"symbol": symbol, "before": rescale[1].isoformat(),
                                            "factor": rescale[0], "detected": today.isoformat()})
                    if bars:
                        for bar in bars:
                            bar.update(reference_data.get((symbol, bar["date"]), {}))
                        records.extend(bars)
                    else:
                        symbols_empty += 1
                    symbols_ok += 1
                except Exception as error:
                    # Không log nội dung exception của SDK để tránh vô tình in token/headers.
                    symbols_failed += 1
                    failures.append(symbol)
                    logger.warning("[{}/{}] Tải mã {} thất bại ({}).", index, total, symbol, type(error).__name__)

                if index % 50 == 0 or index == total:
                    elapsed = time.monotonic() - started
                    remaining = elapsed / index * (total - index)
                    logger.info(
                        "[{}/{}] {} mã thành công · {} lỗi · còn khoảng {:.0f} phút",
                        index, total, symbols_ok, symbols_failed, remaining / 60,
                    )
                if index % BATCH_SIZE == 0:
                    written += _flush(records, root, quality)
            if adjustments:
                append_price_adjustments(root, adjustments)
                logger.info("Phát hiện {} mã được SSI điều chỉnh lại giá lịch sử (sự kiện quyền): {}. Đã lưu hệ số "
                            "vào {}.", len(adjustments), ", ".join(a["symbol"] for a in adjustments),
                            ADJUSTMENT_FILE)
            if getattr(client, "reauth_count", 0):
                logger.info("Đã tự lấy lại token SSI {} lần trong lúc chạy.", client.reauth_count)
    except Exception as error:
        written += _flush(records, root, quality)  # vẫn lưu phần đã tải được
        write_failed_symbols(root, failures)
        _log_quality(root, quality, run_label)
        write_job_log(
            status="error",
            symbols_ok=symbols_ok,
            symbols_failed=symbols_failed,
            message=f"Job lỗi ({type(error).__name__}).",
            root=root,
        )
        raise

    try:
        written += _flush(records, root, quality)
    except Exception as error:
        write_job_log(
            status="error",
            symbols_ok=symbols_ok,
            symbols_failed=symbols_failed,
            message=f"Lỗi ghi kho dữ liệu ({type(error).__name__}).",
            root=root,
        )
        raise

    _log_quality(root, quality, run_label)

    # Lần chạy đầy đủ thay thế danh sách lỗi; lần chạy --chi-ma-loi chỉ bỏ các mã đã tải được.
    if only_failed:
        remaining_failed = sorted((retry_list - {s["symbol"] for s in universe}) | set(failures))
    else:
        remaining_failed = sorted(failures)
    write_failed_symbols(root, remaining_failed)

    # Mã không có nến (tạm ngừng, hủy niêm yết, chưa giao dịch trong khoảng ngày) KHÔNG phải lỗi tải:
    # chỉ ghi chú trong thông điệp. "partial" chỉ khi thực sự có mã lỗi.
    status = "success" if symbols_failed == 0 else "partial"
    if universe and symbols_failed == len(universe):
        status = "error"
    message = (
        f"Ghi {written} bản ghi; {symbols_ok} mã thành công, "
        f"{symbols_failed} mã lỗi."
        + (f" Ghi chú: {symbols_empty} mã không có nến trong khoảng ngày (tạm ngừng, hủy niêm yết hoặc "
           "không giao dịch) — không phải lỗi." if symbols_empty else "")
    )
    if status == "error":
        message = "Tất cả mã đều lỗi; xem log báo lỗi theo mã và thử lại sau."
    write_job_log(
        status=status,
        symbols_ok=symbols_ok,
        symbols_failed=symbols_failed,
        message=message,
        root=root,
    )
    logger.info(message)
    if universe and symbols_failed == len(universe):
        raise RuntimeError(message)
    if remaining_failed:
        logger.warning(
            "Còn {} mã lỗi, đã lưu vào {}/{}. Chạy lại với --chi-ma-loi để chỉ tải các mã này.",
            len(remaining_failed), root.name, FAILED_FILE,
        )

    if precompute and written:
        try:
            from liquisense.snapshot import precompute_latest

            logger.info("Đang tính sẵn chỉ số thanh khoản cho phiên mới nhất (khoảng 1 phút)…")
            latest = precompute_latest(root)
            logger.info("Đã tính sẵn chỉ số cho phiên {}; mở app sẽ có ngay.", latest)
        except Exception as error:  # không để lỗi tính sẵn làm hỏng job cập nhật
            logger.warning("Không tính sẵn được chỉ số ({}); app sẽ tự tính khi mở.", type(error).__name__)
    return written


def main() -> None:
    # Cửa sổ dòng lệnh Windows / Task Scheduler có thể không dùng UTF-8; tránh lỗi in chữ có dấu.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Cập nhật dữ liệu thị trường SSI cho LiquiSense.")
    parser.add_argument("--from-date", type=date.fromisoformat, help="YYYY-MM-DD; dùng để bù dữ liệu cũ.")
    parser.add_argument("--to-date", type=date.fromisoformat, help="YYYY-MM-DD; mặc định hôm nay.")
    parser.add_argument("--chi-ma-loi", action="store_true",
                        help=f"Chỉ tải lại các mã bị lỗi ở lần chạy trước (đọc từ data/{FAILED_FILE}).")
    parser.add_argument("--tat-ca-ma", action="store_true",
                        help="Tải cả chứng quyền, phái sinh, trái phiếu (mặc định chỉ cổ phiếu).")
    parser.add_argument("--so-nam", type=int, metavar="N",
                        help="Số năm lịch sử muốn có (vd 3). Tải bù phần cũ còn thiếu cho các mã đã có.")
    parser.add_argument("--khong-tinh-san", action="store_true",
                        help="Không tính sẵn chỉ số cho app sau khi tải xong.")
    args = parser.parse_args()
    run_update(
        args.from_date,
        args.to_date,
        only_failed=args.chi_ma_loi,
        include_all_securities=args.tat_ca_ma,
        precompute=not args.khong_tinh_san,
        years=args.so_nam,
    )


if __name__ == "__main__":
    main()
