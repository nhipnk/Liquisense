"""Tình huống thực tế: bán/mua Q cổ phiếu một mã mất bao nhiêu phiên, tốn bao nhiêu.

Ví dụ:
    python scripts/tinh_huong.py ANV 500000
    python scripts/tinh_huong.py FPT HPG ANV --so-luong 500000 --mua --ngay 2026-11-06 --csv data/tinh_huong.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from liquisense.scenario import order_scenario, scenario_summary  # noqa: E402
from liquisense.snapshot import load_history_table, metrics_at  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Tình huống đặt lệnh lớn cho một hoặc nhiều mã.")
    parser.add_argument("ma", nargs="+", help="Mã cổ phiếu; có thể kèm số lượng ở cuối, ví dụ: ANV 500000")
    parser.add_argument("--so-luong", type=int, default=None, help="Số cổ phiếu (mặc định 500.000)")
    parser.add_argument("--mua", action="store_true", help="Tình huống MUA (mặc định là BÁN)")
    parser.add_argument("--ngay", type=date.fromisoformat, default=None, help="Ngày dữ liệu YYYY-MM-DD (mặc định phiên mới nhất)")
    parser.add_argument("--phi", type=float, default=0.0015, help="Phí giao dịch dạng thập phân (mặc định 0.0015)")
    parser.add_argument("--thue", type=float, default=0.001, help="Thuế bán dạng thập phân (mặc định 0.001)")
    parser.add_argument("--csv", type=Path, default=None, help="Ghi bảng kết quả ra file CSV")
    args = parser.parse_args()

    symbols = [s.upper() for s in args.ma if not s.isdigit()]
    numbers = [int(s) for s in args.ma if s.isdigit()]
    quantity = args.so_luong or (numbers[0] if numbers else 500_000)

    table = load_history_table()
    if table.empty:
        print("Chưa có dữ liệu. Hãy chạy scripts/update.py trước.")
        return 1
    as_of = args.ngay or max(table["date"])
    metrics = metrics_at(table, as_of).set_index("symbol")
    side = "Mua" if args.mua else "Bán"

    frames = []
    for symbol in symbols:
        if symbol not in metrics.index:
            print(f"\n{symbol}: không có trong dữ liệu đến {as_of:%d/%m/%Y}.")
            continue
        row = metrics.loc[symbol].copy()
        row["symbol"] = symbol
        try:
            sc = order_scenario(row, quantity, side=side, fee=args.phi, tax=args.thue)
        except ValueError as exc:
            print(f"\n{symbol}: {exc}")
            continue
        print(f"\n=== {symbol} · dữ liệu 20 phiên đến {pd.Timestamp(row['date']):%d/%m/%Y} ===")
        print(scenario_summary(sc))
        view = sc.plans.assign(
            **{"Chi phí thấp": sc.plans["low_pct"].map("{:.2%}".format),
               "Chi phí cơ sở": sc.plans["base_pct"].map("{:.2%}".format),
               "Chi phí cao": sc.plans["high_pct"].map("{:.2%}".format),
               "Cơ sở (triệu đ)": (sc.plans["base_vnd"] / 1e6).round(0),
               "Dao động giá khi chờ": sc.plans["price_risk"].map("±{:.1%}".format)},
        ).rename(columns={"plan": "Phương án", "sessions": "Số phiên", "last_session": "Khớp xong",
                          "settled": "Thanh toán xong"})
        print(view[["Phương án", "Số phiên", "Khớp xong", "Thanh toán xong", "Chi phí thấp", "Chi phí cơ sở",
                    "Chi phí cao", "Cơ sở (triệu đ)", "Dao động giá khi chờ"]].to_string(index=False))
        frames.append(sc.plans.assign(symbol=symbol, side=side, quantity=quantity, price=sc.price,
                                      adv_volume=sc.adv_volume, as_of=as_of))
    if args.csv and frames:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(frames).to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"\nĐã ghi {args.csv}")
    return 0 if frames else 1


if __name__ == "__main__":
    raise SystemExit(main())
