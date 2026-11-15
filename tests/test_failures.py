"""Các tình huống lỗi: thiếu/sai khóa, mất mạng, giới hạn tần suất, dữ liệu rỗng, file hỏng.

Không gọi SSI thật: mọi client đều là giả lập. Xem docs/kiem_thu_tinh_huong_loi.md.
"""
from datetime import date

import pandas as pd
import pytest

from liquisense.data import ssi_source, storage, update
from liquisense.data.storage import latest_job, load_daily_bars, write_daily_bars

ssi_sdk = pytest.importorskip("ssi_sdk")
from ssi_sdk.exceptions import AuthenticationError, RateLimitError  # noqa: E402

TODAY = date(2026, 1, 30)
SECRET = "SECRET-TOKEN-123"


def _bar(symbol, day=TODAY):
    return {"date": day.isoformat(), "symbol": symbol, "board": "HOSE", "open": 10, "high": 11, "low": 9,
            "close": 10, "volume": 100}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(ssi_source.time, "sleep", lambda _s: None)


# ---- 1. Thiếu khóa API -------------------------------------------------------------------------
@pytest.mark.parametrize("missing", ["SSI_API_KEY", "SSI_API_SECRET"])
def test_missing_key_gives_clear_message(monkeypatch, missing):
    monkeypatch.setattr(ssi_source, "load_dotenv", lambda *_a, **_k: None)   # không đọc .env thật của máy
    monkeypatch.setenv("SSI_API_KEY", "abc")
    monkeypatch.setenv("SSI_API_SECRET", "xyz")
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match="Thiếu SSI_API_KEY hoặc SSI_API_SECRET"):
        ssi_source.SsiMarketData()


class _Auth:
    def __init__(self):
        self.logins = 0
        self.token = None

    def authenticate(self):
        self.logins += 1


def _client():
    client = object.__new__(ssi_source.SsiMarketData)
    client._auth = _Auth()
    client.reauth_count = 0
    return client


# ---- 2. Sai khóa / token bị từ chối ------------------------------------------------------------
def test_wrong_key_stops_after_three_attempts():
    client = _client()

    def rejected():
        raise AuthenticationError("401 Unauthorized")

    with pytest.raises(AuthenticationError):
        client._call(rejected)
    assert client._auth.logins == 3          # thử đăng nhập lại đúng 3 lần rồi dừng, không lặp vô hạn


# ---- 3. Mất mạng tạm thời / kéo dài ------------------------------------------------------------
def test_transient_network_error_is_retried():
    client, state = _client(), {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise ConnectionError("mất mạng")
        return "ok"

    assert client._call(flaky) == "ok" and state["n"] == 3


def test_network_down_raises_after_retries():
    client, state = _client(), {"n": 0}

    def down():
        state["n"] += 1
        raise TimeoutError("timeout")

    with pytest.raises(TimeoutError):
        client._call(down)
    assert state["n"] == 3


# ---- 4. Bị giới hạn tần suất -------------------------------------------------------------------
def test_rate_limit_waits_and_retries(monkeypatch):
    waits = []
    monkeypatch.setattr(ssi_source.time, "sleep", waits.append)
    client, state = _client(), {"n": 0}

    def limited():
        state["n"] += 1
        if state["n"] == 1:
            raise RateLimitError("429")
        return "ok"

    assert client._call(limited) == "ok" and waits == [3]


# ---- 5. Mất kết nối ngay khi đăng nhập: job ghi lỗi, không ghi dữ liệu rỗng --------------------
def _fake_client(universe=None, bars=None, enter_error=None):
    class Fake:
        reauth_count = 0

        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            if enter_error:
                raise enter_error
            return self

        def __exit__(self, *_args):
            return None

        def get_security_universe(self):
            return universe if universe is not None else [{"symbol": "AAA", "board": "HOSE"}]

        def get_reference_data(self, _from, _to):
            return {}

        def get_bars(self, **kwargs):
            return bars(kwargs["symbol"]) if callable(bars) else (bars or [])

    return Fake


def test_login_network_failure_logs_error_without_details(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "data_root", lambda: tmp_path)
    monkeypatch.setattr(update, "SsiMarketData", _fake_client(enter_error=ConnectionError(f"token={SECRET}")))
    with pytest.raises(ConnectionError):
        update.run_update(to_date=TODAY, precompute=False)
    job = latest_job(tmp_path)
    assert job["status"] == "error" and "ConnectionError" in job["message"]
    assert SECRET not in (tmp_path / "job_runs.csv").read_text(encoding="utf-8-sig")
    assert not list(tmp_path.glob("daily_bars_*.parquet"))


def test_empty_universe_stops_job(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "data_root", lambda: tmp_path)
    monkeypatch.setattr(update, "SsiMarketData", _fake_client(universe=[]))
    with pytest.raises(RuntimeError, match="không trả về danh sách mã"):
        update.run_update(to_date=TODAY, precompute=False)
    assert latest_job(tmp_path)["status"] == "error"


def test_every_symbol_failing_is_error_and_secret_not_logged(monkeypatch, tmp_path):
    def boom(_symbol):
        raise RuntimeError(f"Authorization: Bearer {SECRET}")

    monkeypatch.setattr(update, "data_root", lambda: tmp_path)
    monkeypatch.setattr(update, "SsiMarketData", _fake_client(
        universe=[{"symbol": "AAA", "board": "HOSE"}, {"symbol": "BBB", "board": "HNX"}], bars=boom))
    with pytest.raises(Exception):
        update.run_update(to_date=TODAY, precompute=False)
    assert latest_job(tmp_path)["status"] == "error"
    assert SECRET not in (tmp_path / "job_runs.csv").read_text(encoding="utf-8-sig")
    assert update.read_failed_symbols(tmp_path) == ["AAA", "BBB"]


# ---- 6. File dữ liệu hỏng ----------------------------------------------------------------------
def test_corrupt_partition_is_skipped_and_rewritten(tmp_path):
    write_daily_bars(pd.DataFrame([_bar("AAA", date(2026, 1, 29))]), tmp_path)
    broken = tmp_path / "daily_bars_2026-01-30.parquet"
    broken.write_bytes(b"not a parquet file")
    bars = load_daily_bars(tmp_path)                    # không sập, bỏ qua file hỏng
    assert set(pd.to_datetime(bars["date"]).dt.date) == {date(2026, 1, 29)}
    write_daily_bars(pd.DataFrame([_bar("AAA")]), tmp_path)   # tải lại ngày hỏng
    assert (tmp_path / "daily_bars_2026-01-30.parquet.hong").exists()
    assert len(storage.read_partition(broken)) == 1


def test_write_is_atomic(tmp_path, monkeypatch):
    write_daily_bars(pd.DataFrame([_bar("AAA")]), tmp_path)
    path = tmp_path / "daily_bars_2026-01-30.parquet"
    before = path.read_bytes()

    def crash(self, *_a, **_k):
        raise OSError("mất điện")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", crash)
    with pytest.raises(OSError):
        write_daily_bars(pd.DataFrame([_bar("BBB")]), tmp_path)
    assert path.read_bytes() == before                 # file cũ còn nguyên


def test_empty_store_falls_back_to_sample(tmp_path):
    bars = load_daily_bars(tmp_path)                    # thư mục trống: không sập, dùng dữ liệu mẫu tổng hợp
    assert not bars.empty and set(bars["symbol"]) <= {"AAA", "BBB", "CCC", "DDD", "EEE", "FFF"}
