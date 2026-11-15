"""Diễn biến thanh khoản theo ngành theo tháng (dùng cho bản đồ nhiệt ngành × tháng và báo cáo PDF).

Hai thước đo cho mỗi ngành – tháng:
- Dòng tiền: giá trị giao dịch BÌNH QUÂN MỖI PHIÊN của cả ngành trong tháng, so với trung bình các tháng
  trong cửa sổ (100% = bình thường của chính ngành đó). Chia theo số phiên nên tháng đang diễn ra hay
  tháng nhiều ngày nghỉ lễ vẫn so được với tháng đủ phiên.
- Spread: trung vị (giữa các mã trong ngành) của spread Corwin–Schultz trung bình tháng của từng mã.

Ngành lấy nguyên tên ICB do SSI trả về; mã thiếu ngành không được tính.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

UNSECTORED = {"", "Chua phan nganh", "Chưa phân ngành"}


def _monthly(table: pd.DataFrame, as_of: date, months: int, boards: list[str] | None) -> pd.DataFrame:
    frame = table[["date", "symbol", "board", "sector", "value", "spread_daily"]]
    frame = frame[(frame["date"] <= as_of) & ~frame["sector"].isin(UNSECTORED)]
    if boards:
        frame = frame[frame["board"].isin(boards)]
    if frame.empty:
        return pd.DataFrame()
    month = pd.to_datetime(frame["date"]).dt.to_period("M")
    last = pd.Period(as_of, "M")
    keep = month > last - months
    frame, month = frame[keep], month[keep]
    return frame.assign(month=month)


def sector_monthly(table: pd.DataFrame, as_of: date, months: int = 12, boards: list[str] | None = None,
                   top: int = 15) -> dict[str, object]:
    """Bảng ngành × tháng: 'flow' (% so với TB của ngành), 'spread' (%), 'value' (đồng/phiên)."""
    frame = _monthly(table, as_of, months, boards)
    if frame.empty or frame["month"].nunique() < 2:
        return {}
    sessions = frame.groupby("month")["date"].nunique()
    value = frame.groupby(["sector", "month"])["value"].sum().unstack("month")
    per_session = value.div(sessions, axis=1)
    ranked = per_session.sum(axis=1).sort_values(ascending=False)
    sectors = ranked.head(top).index
    per_session = per_session.loc[sectors]
    flow = per_session.div(per_session.mean(axis=1), axis=0)

    symbol_month = frame.groupby(["sector", "symbol", "month"])["spread_daily"].mean().reset_index()
    spread = (symbol_month.groupby(["sector", "month"])["spread_daily"].median().unstack("month")
              .reindex(index=sectors, columns=flow.columns))
    counts = frame.groupby("sector")["symbol"].nunique().reindex(sectors)

    last_month = flow.columns[-1]
    last_bday = pd.Timestamp(last_month.end_time.date())
    while last_bday.weekday() >= 5:
        last_bday = last_bday - pd.Timedelta(days=1)
    partial = pd.Timestamp(frame.loc[frame["month"] == last_month, "date"].max()) < last_bday
    return {"flow": flow, "spread": spread, "value": per_session, "counts": counts,
            "sessions": sessions.reindex(flow.columns), "partial": bool(partial)}


def sector_trend(table: pd.DataFrame, sector: str, as_of: date, months: int = 6) -> pd.DataFrame:
    """Diễn biến một ngành: dùng trong báo cáo PDF của một mã."""
    frame = _monthly(table, as_of, 12, None)
    if frame.empty or sector in UNSECTORED:
        return pd.DataFrame()
    sessions = frame.groupby("month")["date"].nunique()
    mine = frame[frame["sector"] == sector]
    if mine.empty:
        return pd.DataFrame()
    per_session = mine.groupby("month")["value"].sum() / sessions
    per_session = per_session.dropna()
    symbol_month = mine.groupby(["symbol", "month"])["spread_daily"].mean().reset_index()
    spread = symbol_month.groupby("month")["spread_daily"].median()
    out = pd.DataFrame({"value": per_session, "flow": per_session / per_session.mean(),
                        "spread": spread.reindex(per_session.index),
                        "symbols": mine.groupby("month")["symbol"].nunique().reindex(per_session.index)})
    return out.tail(months)


def month_label(period: pd.Period) -> str:
    return f"T{period.month}/{str(period.year)[2:]}"
