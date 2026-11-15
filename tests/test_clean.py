import pandas as pd
import pytest

from liquisense.data.clean import clean_daily_bars


def test_clean_keeps_zero_volume_but_drops_invalid_rows_and_duplicates():
    source = pd.DataFrame([
        {
            "date": "2026-01-05", "symbol": "aaa", "open": 10, "high": 11,
            "low": 9, "close": 10, "volume": 0,
        },
        {
            "date": "2026-01-05", "symbol": "AAA", "open": 10, "high": 9,
            "low": 10, "close": 10, "volume": 100,
        },
        {
            "date": "2026-01-06", "symbol": "BBB", "open": 10, "high": 11,
            "low": 9, "close": 10, "volume": -1,
        },
    ])
    cleaned = clean_daily_bars(source)
    assert len(cleaned) == 1
    assert cleaned.iloc[0]["symbol"] == "AAA"
    assert cleaned.iloc[0]["volume"] == 0


def test_clean_requires_core_columns():
    with pytest.raises(ValueError, match="Thiếu cột"):
        clean_daily_bars(pd.DataFrame({"symbol": ["AAA"]}))


def test_missing_value_is_computed_from_price_and_volume():
    bars = clean_daily_bars(pd.DataFrame([{
        "date": "2026-02-01", "symbol": "AAA", "open": 10,
        "high": 11, "low": 9, "close": 10, "volume": 100,
    }]))
    assert bars.iloc[0]["value"] == 1_000
