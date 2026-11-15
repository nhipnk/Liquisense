"""Tính sẵn chỉ số thanh khoản cho phiên mới nhất để mở app không phải chờ."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from liquisense.snapshot import precompute_latest


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    print("Đang tính sẵn chỉ số thanh khoản (khoảng 1 phút)…")
    latest = precompute_latest()
    print(f"Xong. Đã lưu chỉ số cho phiên {latest}; mở app sẽ có ngay.")
