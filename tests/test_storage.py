from datetime import date

import pandas as pd

from liquisense.data.storage import write_daily_bars


def _bar(symbol, date_value, volume=100):
    return {
        "date": date_value, "symbol": symbol, "open": 10, "high": 11,
        "low": 9, "close": 10, "volume": volume, "board": "HOSE",
    }


def test_rerun_merges_rows_without_duplicates(tmp_path):
    first = pd.DataFrame([_bar("AAA", "2026-01-05"), _bar("BBB", "2026-01-05")])
    second = pd.DataFrame([_bar("AAA", "2026-01-05", volume=200)])
    write_daily_bars(first, tmp_path)
    write_daily_bars(second, tmp_path)

    saved = pd.read_parquet(tmp_path / "daily_bars_2026-01-05.parquet")
    assert set(saved["symbol"]) == {"AAA", "BBB"}
    assert saved.loc[saved["symbol"] == "AAA", "volume"].item() == 200
    assert saved["symbol"].duplicated().sum() == 0


def test_write_partitions_by_trading_date(tmp_path):
    bars = pd.DataFrame([
        _bar("AAA", date(2026, 1, 5).isoformat()),
        _bar("AAA", date(2026, 1, 6).isoformat()),
    ])
    assert write_daily_bars(bars, tmp_path) == 2
    assert len(list(tmp_path.glob("daily_bars_*.parquet"))) == 2
