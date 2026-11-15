"""Tính sẵn bảng chỉ số và cảnh báo phiên mới nhất, đóng gói vào thư mục dist/ để GitHub Actions tải lên
GitHub Release "cache". App trên Streamlit Cloud tải về khi khởi động (vài giây) thay vì tự tính (1–2 phút).

    python scripts/dong_goi_cache.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from liquisense.snapshot import (  # noqa: E402
    alerts_cache_path, data_root, history_cache_path, precompute_latest, store_signature,
)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    root = data_root()
    print("Đang tính bảng chỉ số và cảnh báo phiên mới nhất…")
    latest = precompute_latest(root)
    if latest is None:
        print("Kho dữ liệu rỗng, không có gì để đóng gói.")
        return 1
    dist = PROJECT_ROOT / "dist"
    dist.mkdir(exist_ok=True)
    shutil.copyfile(history_cache_path(root), dist / "history.parquet")
    shutil.copyfile(alerts_cache_path(latest, root), dist / "alerts.parquet")
    meta = {"signature": store_signature(root), "as_of": latest.isoformat()}
    (dist / "cache.json").write_text(json.dumps(meta), encoding="utf-8")
    size = (dist / "history.parquet").stat().st_size / 1e6
    print(f"Xong: chữ ký {meta['signature']}, phiên {latest:%d/%m/%Y}, bảng chỉ số {size:.0f} MB → dist/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
