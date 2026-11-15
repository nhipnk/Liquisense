"""SSI điều chỉnh lại lịch sử giá sau sự kiện quyền: phát hiện khi cập nhật hằng ngày và quy giá cũ về
cùng thang (dữ liệu tổng hợp)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from liquisense.data import update
from liquisense.data.storage import load_daily_bars, read_price_adjustments, write_daily_bars

DAYS = [date(2026, 3, 2) + timedelta(days=i) for i in range(12) if (date(2026, 3, 2) + timedelta(days=i)).weekday() < 5]


def _bar(day, close, symbol="AAA"):
    return {"date": day.isoformat(), "symbol": symbol, "board": "HOSE", "open": close, "high": close * 1.01,
            "low": close * 0.99, "close": close, "volume": 1000, "value": close * 1000}


def test_rescale_factor_detects_adjusted_history():
    stored = {("AAA", d): 20_000.0 for d in DAYS[:4]}
    bars = [_bar(d, 20_000 * 0.8) for d in DAYS[:4]]            # SSI hạ cả lịch sử 20% (chia cổ tức cổ phiếu)
    factor, before = update.rescale_factor("AAA", bars, stored)
    assert factor == pytest.approx(0.8) and before == DAYS[0]
    small = [_bar(d, 20_000 * 1.002) for d in DAYS[:4]]           # lệch 0,2%: làm tròn bước giá, bỏ qua
    assert update.rescale_factor("AAA", small, stored) is None


def test_adjustments_put_old_prices_on_new_scale(tmp_path):
    write_daily_bars(pd.DataFrame([_bar(d, 20_000.0) for d in DAYS[:5]] + [_bar(d, 30_000.0, "BBB") for d in DAYS[:5]]),
                     tmp_path)
    write_daily_bars(pd.DataFrame([_bar(d, 16_000.0) for d in DAYS[3:8]]), tmp_path)   # 2 ngày trùng đã thang mới
    update.append_price_adjustments(tmp_path, [{"symbol": "AAA", "before": DAYS[3].isoformat(), "factor": 0.8,
                                                "detected": DAYS[7].isoformat()}])
    bars = load_daily_bars(tmp_path)
    aaa = bars[bars["symbol"].eq("AAA")].sort_values("date")
    assert aaa["close"].round(6).eq(16_000.0).all()               # không còn bước nhảy giữa hai thang
    assert bars.loc[bars["symbol"].eq("BBB"), "close"].eq(30_000.0).all()
    # Lần cập nhật hôm sau so với giá đã quy đổi nên không ghi trùng sự kiện
    closes = update._stored_closes(tmp_path, DAYS[0])
    assert closes[("AAA", DAYS[1])] == pytest.approx(16_000.0)
    assert update.rescale_factor("AAA", [_bar(d, 16_000.0) for d in DAYS[1:6]], closes) is None
    assert len(read_price_adjustments(tmp_path)) == 1


def test_signature_ignores_mtime_and_prebuilt_cache_is_used(tmp_path):
    import json
    import os
    import shutil

    from liquisense.snapshot import fetch_prebuilt_cache, history_cache_path, store_signature

    store = tmp_path / "data"
    store.mkdir()
    write_daily_bars(pd.DataFrame([_bar(d, 20_000.0) for d in DAYS]), store)
    signature = store_signature(store)
    for path in store.glob("daily_bars_*.parquet"):
        os.utime(path, (1, 1))                       # git clone đổi giờ sửa file, nội dung giữ nguyên
    assert store_signature(store) == signature

    dist = tmp_path / "dist"
    dist.mkdir()
    pd.DataFrame({"symbol": ["AAA"], "x": [1.0]}).to_parquet(dist / "history.parquet")
    (dist / "cache.json").write_text(json.dumps({"signature": "khac"}), encoding="utf-8")
    assert not fetch_prebuilt_cache(dist.as_uri(), store)            # chữ ký không khớp: tự tính
    (dist / "cache.json").write_text(json.dumps({"signature": signature}), encoding="utf-8")
    assert fetch_prebuilt_cache(dist.as_uri(), store)
    assert history_cache_path(store).exists()
    shutil.rmtree(dist)
    assert not fetch_prebuilt_cache((tmp_path / "khong_co").as_uri(), store)   # mất mạng / chưa có release
