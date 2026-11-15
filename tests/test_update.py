from datetime import date, timedelta

import pandas as pd

from liquisense.data import update
from liquisense.data.storage import latest_job, write_daily_bars


def _bar(symbol, day):
    return {
        "date": day.isoformat(),
        "symbol": symbol,
        "board": "HOSE",
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10,
        "volume": 100,
    }


def test_update_retries_recent_gap_and_logs_empty_security(monkeypatch, tmp_path):
    latest = date(2026, 1, 20)
    write_daily_bars(pd.DataFrame([_bar("AAA", latest)]), tmp_path)
    today = date(2026, 1, 30)
    requests = []

    class FakeSsiClient:
        reauth_count = 0

        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get_security_universe(self):
            return [
                {"symbol": "AAA", "board": "HOSE"},
                {"symbol": "BBB", "board": "HNX"},
            ]

        def get_reference_data(self, _from, _to):
            return {}

        def get_bars(self, **kwargs):
            requests.append(kwargs)
            if kwargs["symbol"] == "BBB":
                return []
            return [_bar("AAA", today)]

    monkeypatch.setattr(update, "data_root", lambda: tmp_path)
    monkeypatch.setattr(update, "SsiMarketData", FakeSsiClient)

    update.run_update(to_date=today)

    starts = {request["symbol"]: request["from_date"] for request in requests}
    assert starts["AAA"] == latest - timedelta(days=7)
    assert starts["BBB"] == today - timedelta(days=365)
    job = latest_job(tmp_path)
    assert job["status"] == "success"                # mã không có nến không phải lỗi
    assert "1 mã không có nến" in job["message"]


def test_failed_symbols_are_saved_and_retried(monkeypatch, tmp_path):
    today = date(2026, 1, 30)
    calls = []
    failures_left = {"CCC": 1}

    class FlakyClient:
        reauth_count = 0

        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get_security_universe(self):
            return [{"symbol": "AAA", "board": "HOSE"}, {"symbol": "CCC", "board": "HNX"}]

        def get_reference_data(self, _from, _to):
            return {}

        def get_bars(self, **kwargs):
            calls.append(kwargs["symbol"])
            if failures_left.get(kwargs["symbol"], 0) > 0:
                failures_left[kwargs["symbol"]] -= 1
                raise RuntimeError("tam thoi")
            return [_bar(kwargs["symbol"], today)]

    monkeypatch.setattr(update, "data_root", lambda: tmp_path)
    monkeypatch.setattr(update, "SsiMarketData", FlakyClient)

    update.run_update(to_date=today, precompute=False)
    assert update.read_failed_symbols(tmp_path) == ["CCC"]

    calls.clear()
    update.run_update(to_date=today, only_failed=True, precompute=False)
    assert calls == ["CCC"]
    assert update.read_failed_symbols(tmp_path) == []


def test_start_date_backfills_only_when_more_years_requested():
    today = date(2026, 11, 12)
    target = today - timedelta(days=365 * 3)
    stored = {"AAA": (today - timedelta(days=365), today - timedelta(days=1))}
    # Chạy hằng ngày: chỉ tải bù 7 ngày gần nhất.
    assert update._start_date("AAA", stored, target, False, None) == today - timedelta(days=8)
    # Chạy --so-nam 3: kho mới có 1 năm nên tải lại từ mốc 3 năm.
    assert update._start_date("AAA", stored, target, True, None) == target
    # Mã chưa có trong kho: tải đủ số năm.
    assert update._start_date("BBB", stored, target, False, None) == target
