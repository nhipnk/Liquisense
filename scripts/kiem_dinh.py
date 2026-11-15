"""Kiểm định ngoài mẫu toàn bộ lịch sử đã tải; ghi kết quả ra data/kiem_dinh_*.csv để app hiển thị.

    python scripts/kiem_dinh.py                 # mặc định: mỗi 20 phiên một mốc
    python scripts/kiem_dinh.py --buoc 10       # dày hơn (chậm hơn)

Chạy sau khi đã tải lịch sử (scripts/update.py). Với 5 năm dữ liệu mất vài phút, chủ yếu ở phần cảnh báo.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from liquisense.snapshot import data_root, load_history_table  # noqa: E402
from liquisense.validation import (  # noqa: E402
    alert_follow_up, liquidation_check, score_out_of_sample, summarize_alerts, summarize_liquidation,
)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Kiểm định ngoài mẫu LiquiSense.")
    parser.add_argument("--buoc", type=int, default=20, help="Khoảng cách giữa các mốc t (phiên), mặc định 20")
    parser.add_argument("--bo-canh-bao", action="store_true", help="Bỏ qua phần kiểm định cảnh báo (nhanh hơn)")
    args = parser.parse_args()

    started = time.time()
    print("Đọc bảng chỉ số lịch sử…")
    table = load_history_table()
    sessions = sorted(set(table["date"])) if not table.empty else []
    if len(sessions) < 60:
        print(f"Chỉ có {len(sessions)} phiên — cần ít nhất 60 phiên (nên 1 năm trở lên) để kiểm định có ý nghĩa.")
        return 1
    print(f"{len(sessions)} phiên từ {sessions[0]:%d/%m/%Y} đến {sessions[-1]:%d/%m/%Y}.")
    out = data_root()

    print("\n[1/3] Score tại t so với thanh khoản thực tế 20 phiên sau…")
    score = score_out_of_sample(table, step=args.buoc)
    score.to_csv(out / "kiem_dinh_score.csv", index=False, encoding="utf-8-sig")
    if not score.empty:
        print(f"  {len(score)} mốc · Spearman trung bình: Score {score['rho_score'].mean():.2f}, "
              f"Amihud {score['rho_amihud'].mean():.2f}, ADV {score['rho_adv'].mean():.2f}, "
              f"spread {score['rho_spread'].mean():.2f} · nhóm top 20% giữ được vị trí "
              f"{score['top_stays_top'].mean():.0%}")

    print("\n[2/3] Số phiên bán hết: dự báo so với thực tế…")
    liq = summarize_liquidation(liquidation_check(table, step=max(5, args.buoc // 4)))
    liq.to_csv(out / "kiem_dinh_so_phien.csv", index=False, encoding="utf-8-sig")
    if not liq.empty:
        print(liq.round(3).to_string(index=False))

    if not args.bo_canh_bao:
        print("\n[3/3] Cảnh báo so với diễn biến 20 phiên sau…")
        detail = alert_follow_up(table, step=args.buoc,
                                 progress=lambda n, total, t: print(f"  mốc {n}/{total}: {t:%d/%m/%Y}", end="\r"))
        print()
        alerts = summarize_alerts(detail)
        alerts.to_csv(out / "kiem_dinh_canh_bao.csv", index=False, encoding="utf-8-sig")
        if not alerts.empty:
            print(alerts.round(3).to_string(index=False))
        else:
            print("  Chưa đủ lịch sử (cần hơn 100 phiên).")

    print(f"\nXong sau {time.time() - started:.0f} giây. Kết quả: {out}\\kiem_dinh_*.csv (app đọc tự động).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
