"""Tạo bộ dữ liệu giả lập cố định để trình diễn khi chưa có dữ liệu SSI."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_sample_bars(days: int = 180, seed: int = 17) -> pd.DataFrame:
    """Dữ liệu này là tổng hợp, không phải giá lịch sử hay dữ liệu SSI."""
    symbols = [
        ("AAA", "HOSE", "Công nghiệp", 18_500, 48_000_000, 850_000),
        ("BBB", "HOSE", "Tài chính", 42_000, 120_000_000, 2_500_000),
        ("CCC", "HNX", "Vật liệu", 12_300, 65_000_000, 430_000),
        ("DDD", "UPCOM", "Công nghệ", 27_800, 22_000_000, 95_000),
        ("EEE", "HOSE", "Hàng tiêu dùng", 76_000, 85_000_000, 680_000),
        ("FFF", "HNX", "Bất động sản", 9_600, 31_000_000, 140_000),
    ]
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    rows: list[dict[str, object]] = []

    for index, (symbol, board, sector, initial, shares, typical_volume) in enumerate(symbols):
        previous = float(initial)
        for date in dates:
            daily_return = float(rng.normal(0.0002, 0.018 + index * 0.0015))
            close = max(1_000.0, previous * (1 + daily_return))
            spread_noise = float(rng.uniform(0.003, 0.025))
            high = max(previous, close) * (1 + spread_noise / 2)
            low = min(previous, close) * (1 - spread_noise / 2)
            volume = max(0, int(rng.lognormal(np.log(typical_volume), 0.55)))
            if rng.random() < 0.07 + index * 0.01:
                volume = 0
            ceiling = round(previous * 1.07 / 100) * 100
            floor = round(previous * 0.93 / 100) * 100
            if volume == 0:
                low = high = close = previous
            rows.append({
                "date": date.date().isoformat(),
                "symbol": symbol,
                "board": board,
                "icb_name": sector,
                "open": round(previous * (1 + daily_return / 3), 2),
                "high": round(high, 2),
                "low": round(max(1, low), 2),
                "close": round(close, 2),
                "volume": volume,
                "value": round(close * volume),
                "listed_shares": shares,
                "ref_px": round(previous, 2),
                "ceil_px": ceiling,
                "floor_px": floor,
                "event_flag": False,
                "data_origin": "Du lieu gia lap",
            })
            previous = close

    return pd.DataFrame(rows)
