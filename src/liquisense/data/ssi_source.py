"""Kết nối chỉ đọc đến SSI FastConnect qua client Data của ssi-sdk."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, TypeVar

from dotenv import load_dotenv
from loguru import logger

from liquisense.data.storage import PROJECT_ROOT

T = TypeVar("T")

# Mã cổ phiếu niêm yết có đúng 3 ký tự; chứng quyền (CACB2501…), hợp đồng tương lai
# (41I1G…) và trái phiếu dài hơn nên bị bỏ để không tốn lượt gọi API.
STOCK_SYMBOL_LENGTH = 3

# Gia hạn token sớm trước khi hết hạn thật để không bị 401 giữa chừng.
TOKEN_REFRESH_MARGIN_SECONDS = 120


def _plain_record(value: Any) -> dict[str, Any]:
    """Chuyển model SDK thành dict mà không in/log thông tin xác thực."""
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return {key: item for key, item in attributes.items() if not key.startswith("_")}
    slots = getattr(type(value), "__slots__", ())
    return {key: getattr(value, key) for key in slots if hasattr(value, key)}


def _value(record: dict[str, Any], *names: str, default: Any = None) -> Any:
    """Đọc alias tên trường để tương thích các model SDK."""
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return default


def _date_text(value: date | datetime) -> str:
    return value.strftime("%Y/%m/%d")


def _date_value(value: Any) -> str | None:
    """Chuẩn ngày từ các model SSI về YYYY-MM-DD để ghép bảng."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    text = str(value).strip().replace("/", "-")
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def is_stock_symbol(symbol: str) -> bool:
    return len(symbol) == STOCK_SYMBOL_LENGTH and symbol.isalnum()


class SsiMarketData:
    """Vòng đời một phiên SDK chỉ đọc; không khởi tạo client giao dịch/stream.

    Token truy cập của SSI chỉ sống khoảng 15 phút, còn client Data của SDK không tự
    gia hạn. Vì vậy mọi lời gọi API đi qua ``_call``: gia hạn token trước khi hết hạn,
    đăng nhập lại khi gặp lỗi xác thực (401/403), và thử lại khi gặp lỗi mạng tạm thời.
    """

    def __init__(self, include_all_securities: bool = False) -> None:
        load_dotenv(PROJECT_ROOT / ".env")
        api_key = os.getenv("SSI_API_KEY", "").strip()
        api_secret = os.getenv("SSI_API_SECRET", "").strip()
        self.client_id = os.getenv("SSI_CLIENT_ID", "").strip()
        self.include_all_securities = include_all_securities
        if not api_key or not api_secret:
            raise RuntimeError(
                "Thiếu SSI_API_KEY hoặc SSI_API_SECRET. Hãy tạo .env từ .env.example."
            )

        try:
            from ssi_sdk import Auth, Config
        except ImportError as error:
            raise RuntimeError(
                "Chưa cài ssi-sdk. Hãy cài dependencies trong requirements.txt."
            ) from error

        # Mặc định SDK cho 10 request/giây; giảm xuống để tránh bị SSI chặn tạm thời.
        rate = int(os.getenv("LIQUISENSE_RATE_LIMIT", "5") or 5)
        self._auth = Auth(Config(
            api_key=api_key,
            api_secret=api_secret,
            client_id=self.client_id,
            rate_limit_per_second=max(1, rate),
        ))
        self._data_client = None
        self.reauth_count = 0

    def __enter__(self) -> "SsiMarketData":
        self._auth.__enter__()
        try:
            self._login()
            from ssi_sdk import Data

            self._data_client = Data(self._auth)
            self._data_client.__enter__()
        except Exception:
            self._auth.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._data_client is not None:
            self._data_client.__exit__(exc_type, exc, traceback)
        self._auth.__exit__(exc_type, exc, traceback)

    # -- xác thực và thử lại ------------------------------------------------------
    def _login(self) -> None:
        """Đăng nhập lại bằng API key/secret (API dữ liệu không cần OTP)."""
        self._auth.authenticate()

    def _token_expiring(self) -> bool:
        token = getattr(self._auth, "token", None)
        expires_at = getattr(token, "expires_at", 0) or 0
        if expires_at <= 0:
            return bool(getattr(self._auth, "is_token_expired", False))
        return time.time() >= expires_at - TOKEN_REFRESH_MARGIN_SECONDS

    def _renew(self, reason: str) -> None:
        self.reauth_count += 1
        logger.info("Lấy token SSI mới ({}).", reason)
        self._login()

    def _call(self, fn: Callable[[], T], attempts: int = 3) -> T:
        """Gọi API với token còn hạn; tự đăng nhập lại và thử lại khi lỗi tạm thời."""
        from ssi_sdk.exceptions import AuthenticationError, RateLimitError

        if self._token_expiring():
            self._renew("token sắp hết hạn")
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except AuthenticationError as error:
                last_error = error
                self._renew("SSI báo lỗi xác thực")
            except RateLimitError as error:
                last_error = error
                time.sleep(3 * attempt)
            except Exception as error:  # lỗi mạng, timeout, 5xx
                last_error = error
                if attempt < attempts:
                    time.sleep(2 * attempt)
        assert last_error is not None
        raise last_error

    @property
    def market_data(self) -> Any:
        if self._data_client is None:
            raise RuntimeError("Client SSI chưa được mở trong context.")
        return self._data_client.market_data

    # -- dữ liệu ---------------------------------------------------------------------
    def get_security_universe(self) -> list[dict[str, Any]]:
        """Lấy mã trên 3 sàn; mặc định chỉ giữ cổ phiếu (mã 3 ký tự)."""
        from ssi_sdk.enums import Board

        securities: list[dict[str, Any]] = []
        skipped = 0
        for board_name in ("HOSE", "HNX", "UPCOM"):
            board = getattr(Board, board_name)
            items = self._call(lambda b=board: self.market_data.get_securities_info_by_board(b)) or []
            for item in items:
                record = _plain_record(item)
                symbol = _value(record, "symbol", "ticker", "stock_code")
                if not symbol:
                    continue
                symbol = str(symbol).strip().upper()
                if not self.include_all_securities and not is_stock_symbol(symbol):
                    skipped += 1
                    continue
                securities.append({
                    "symbol": symbol,
                    "board": board_name,
                    "icb_name": _value(record, "icb_name", "industry_name", "icb_name_en"),
                    "listed_shares": _value(
                        record, "listed_shares", "listed_share", "listing_volume"
                    ),
                })
        if skipped:
            logger.info("Bỏ qua {} mã không phải cổ phiếu (chứng quyền, phái sinh, trái phiếu…).", skipped)
        return securities

    def get_bars(
        self,
        *,
        symbol: str,
        board: str,
        icb_name: str | None,
        listed_shares: object,
        from_date: date,
        to_date: date,
    ) -> list[dict[str, Any]]:
        """Tải nến ngày theo SSI; SDK tự phân trang đến khi hết kết quả."""
        from ssi_sdk.enums import Timeframe

        candles = self._call(lambda: list(self.market_data.get_ohlc_all(
            symbol,
            Timeframe.DAY_1,
            from_date=_date_text(from_date),
            to_date=_date_text(to_date),
            ascending=True,
        ) or []))
        result: list[dict[str, Any]] = []
        for item in candles:
            record = _plain_record(item)
            candle_date = _date_value(_value(record, "trading_date", "date"))
            if not candle_date:
                continue
            result.append({
                "date": candle_date,
                "symbol": symbol,
                "board": board,
                "icb_name": icb_name or "Chua phan nganh",
                "open": _value(record, "open_price", "open"),
                "high": _value(record, "high_price", "high"),
                "low": _value(record, "low_price", "low"),
                "close": _value(record, "close_price", "close"),
                "volume": _value(record, "volume", "total_volume"),
                "value": _value(record, "value", "total_value"),
                "listed_shares": listed_shares,
                "ref_px": _value(record, "ref_price", "reference_price"),
                "ceil_px": _value(record, "ceiling", "ceiling_price"),
                "floor_px": _value(record, "floor", "floor_price"),
                "event_flag": False,
                "data_origin": "SSI FastConnect",
            })
        return result

    def get_reference_data(
        self, from_date: date, to_date: date
    ) -> dict[tuple[str, str], dict[str, object]]:
        """Lấy giá tham chiếu và ngày quyền từ endpoint SSI, không tự suy diễn."""
        reference: dict[tuple[str, str], dict[str, object]] = {}
        # Chia thành từng tháng để một lần gọi không quá lớn khi tải nhiều năm.
        long_range = (to_date - from_date).days > 60
        if long_range:
            logger.info("Bước chuẩn bị 1/2: lấy giá tham chiếu – trần – sàn từ {:%m/%Y} đến {:%m/%Y}…",
                        from_date, to_date)
        last_logged = from_date
        cursor = from_date
        while cursor <= to_date:
            window_end = min(cursor + timedelta(days=30), to_date)
            try:
                master_rows = self._call(lambda c=cursor, w=window_end: self.market_data.get_master_data_historical(
                    _date_text(c), _date_text(w)
                ))
            except Exception as error:
                logger.warning("Không lấy được giá tham chiếu {} – {} ({}); dùng giá trong nến.",
                               cursor, window_end, type(error).__name__)
                master_rows = []
            for item in master_rows or []:
                record = _plain_record(item)
                symbol = _value(record, "symbol")
                trading_date = _date_value(_value(record, "trading_date", "date"))
                if not symbol or not trading_date:
                    continue
                reference[(str(symbol).strip().upper(), trading_date)] = {
                    "ref_px": _value(record, "ref_price", "reference_price"),
                    "ceil_px": _value(record, "ceiling", "ceiling_price"),
                    "floor_px": _value(record, "floor", "floor_price"),
                    "event_flag": False,
                }
            if long_range and ((window_end - last_logged).days >= 180 or window_end >= to_date):
                logger.info("  … giá tham chiếu đã lấy đến {:%m/%Y}", window_end)
                last_logged = window_end
            cursor = window_end + timedelta(days=1)

        # SSI giới hạn khoảng ngày của endpoint sự kiện quyền tối đa 5 ngày.
        if long_range:
            logger.info("Bước chuẩn bị 2/2: lấy sự kiện quyền (mỗi lần tối đa 5 ngày theo giới hạn SSI)…")
        last_logged = from_date
        cursor = from_date
        while cursor <= to_date:
            window_end = min(cursor + timedelta(days=4), to_date)
            try:
                events = self._call(lambda c=cursor, w=window_end: self.market_data.get_corporate_actions_historical(
                    from_date=_date_text(c),
                    to_date=_date_text(w),
                    symbol=None,
                    language="vn",
                ))
            except Exception as error:
                logger.warning("Không lấy được sự kiện quyền {} – {} ({}).", cursor, window_end, type(error).__name__)
                events = []
            for item in events or []:
                record = _plain_record(item)
                symbol = _value(record, "symbol")
                event_date = _date_value(
                    _value(record, "exright_date", "ex_right_date")
                )
                if not symbol or not event_date:
                    continue
                key = (str(symbol).strip().upper(), event_date)
                reference.setdefault(key, {})["event_flag"] = True
            if long_range and ((window_end - last_logged).days >= 180 or window_end >= to_date):
                logger.info("  … sự kiện quyền đã lấy đến {:%m/%Y}", window_end)
                last_logged = window_end
            cursor = window_end + timedelta(days=1)
        if long_range:
            logger.info("Xong bước chuẩn bị; bắt đầu tải nến ngày từng mã.")
        return reference


def history_years(value: int | None = None) -> int:
    """Số năm lịch sử: ưu tiên tham số dòng lệnh, sau đó LIQUISENSE_HISTORY_YEARS, mặc định 1."""
    if value:
        return max(1, int(value))
    load_dotenv(PROJECT_ROOT / ".env")
    try:
        return max(1, int(os.getenv("LIQUISENSE_HISTORY_YEARS", "1") or 1))
    except ValueError:
        return 1


def default_history_start(today: date | None = None, years: int = 1) -> date:
    """Mốc tải lần đầu: mặc định một năm lịch sử (mức tối thiểu của đồ án)."""
    return (today or datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()) - timedelta(days=365 * years)
