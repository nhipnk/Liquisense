"""Kiểm định ngoài mẫu: đầu ra của LiquiSense tại phiên t có khớp với những gì xảy ra SAU phiên t không.

Mọi phép kiểm tra chỉ dùng dữ liệu đến phiên t để tạo dự báo, rồi so với dữ liệu thực tế của
``horizon`` phiên kế tiếp (t+1 … t+horizon) — các phiên này không tham gia tính dự báo.

1. score_out_of_sample  – Score tại t có xếp đúng thứ tự thanh khoản THỰC TẾ của 20 phiên sau không
                           (tương quan hạng Spearman; so nhóm 20% tốt nhất với 20% kém nhất).
2. liquidation_check    – "Số phiên bán hết" dự báo bằng ADV quá khứ so với số phiên thực sự cần nếu
                           mỗi phiên chỉ bán 20% khối lượng THỰC TẾ của phiên đó.
3. alert_follow_up      – Mã bị cảnh báo tại t có thật sự kém thanh khoản hơn mức thường của chính nó
                           trong 20 phiên sau không, so với nhóm không bị cảnh báo.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from liquisense.finance import spearman
from liquisense.snapshot import alerts_at, metrics_at, metrics_for_range

HORIZON = 20


def _sessions(table: pd.DataFrame) -> list[date]:
    return sorted(set(table["date"]))


def _origins(sessions: list[date], horizon: int, step: int, warmup: int) -> list[int]:
    """Chỉ số các phiên gốc t: đủ ``warmup`` phiên trước và đủ ``horizon`` phiên sau."""
    return list(range(warmup, len(sessions) - horizon, step))


def _spearman(a: pd.Series, b: pd.Series) -> float:
    both = pd.concat([a, b], axis=1).dropna()
    return spearman(both.iloc[:, 0], both.iloc[:, 1]) if len(both) >= 10 else np.nan


# --------------------------------------------------------------------------
# 1. Score có dự báo được thanh khoản thực tế của 20 phiên sau không
# --------------------------------------------------------------------------
def score_out_of_sample(table: pd.DataFrame, horizon: int = HORIZON, step: int = HORIZON) -> pd.DataFrame:
    sessions = _sessions(table)
    rows = []
    for i in _origins(sessions, horizon, step, warmup=HORIZON):
        t, start, end = sessions[i], sessions[i + 1], sessions[i + horizon]
        now = metrics_at(table, t)
        now = now[now["status"].eq("Du du lieu") & now["score"].notna()].set_index("symbol")
        future = metrics_for_range(table, start, end).set_index("symbol")
        if len(now) < 30 or future.empty:
            continue
        joined = now[["score", "spread", "amihud", "adv_value"]].join(
            future[["score", "spread", "amihud", "adv_value"]], rsuffix="_future", how="inner")
        top = joined["score"] >= joined["score"].quantile(0.8)
        bottom = joined["score"] <= joined["score"].quantile(0.2)
        rows.append({
            "origin": t, "future_start": start, "future_end": end, "symbols": len(joined),
            "rho_score": _spearman(joined["score"], joined["score_future"]),
            "rho_spread": _spearman(joined["score"], -joined["spread_future"]),
            "rho_amihud": _spearman(joined["score"], -joined["amihud_future"]),
            "rho_adv": _spearman(joined["score"], joined["adv_value_future"]),
            "spread_top": joined.loc[top, "spread_future"].median(),
            "spread_bottom": joined.loc[bottom, "spread_future"].median(),
            "top_stays_top": float((joined.loc[top, "score_future"]
                                    >= joined["score_future"].quantile(0.8)).mean()),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 2. Ước tính "số phiên bán hết" so với thực tế
# --------------------------------------------------------------------------
def liquidation_check(table: pd.DataFrame, horizon: int = HORIZON, step: int = 5,
                      sizes: tuple[float, ...] = (0.1, 0.5, 1.0, 2.0), participation: float = 0.2) -> pd.DataFrame:
    """Với lệnh Q = k × ADV(t): dự báo ⌈k / p⌉ phiên; thực tế = số phiên đầu tiên mà tổng p × khối lượng
    thực tế các phiên t+1, t+2, … đạt Q. Nếu sau ``horizon`` phiên vẫn chưa đủ thì ghi nhận là chưa xong."""
    sessions = _sessions(table)
    volume = table.pivot_table(index="date", columns="symbol", values="volume", aggfunc="last").reindex(sessions)
    rows = []
    for i in _origins(sessions, horizon, step, warmup=HORIZON):
        t = sessions[i]
        now = metrics_at(table, t)
        now = now[now["status"].eq("Du du lieu") & now["adv_volume"].gt(0)].set_index("symbol")
        if now.empty:
            continue
        future = volume.iloc[i + 1:i + 1 + horizon][now.index].fillna(0.0).to_numpy(dtype="float64")
        capacity = np.cumsum(participation * future, axis=0)          # phiên × mã
        adv = now["adv_volume"].to_numpy(dtype="float64")
        score = now["score"].to_numpy(dtype="float64")
        for k in sizes:
            target = k * adv
            done = capacity >= target[None, :]
            realized = np.where(done.any(axis=0), done.argmax(axis=0) + 1, np.nan)
            predicted = max(1, math.ceil(k / participation - 1e-9))
            rows.append(pd.DataFrame({"origin": t, "size_adv": k, "predicted": predicted, "realized": realized,
                                      "score": score}))
    if not rows:
        return pd.DataFrame()
    detail = pd.concat(rows, ignore_index=True)
    detail["group"] = pd.cut(detail.groupby("origin")["score"].rank(pct=True), [0, 0.2, 0.8, 1.0],
                             labels=["20% kém nhất", "Giữa", "20% tốt nhất"], include_lowest=True).astype(str)
    return detail


def summarize_liquidation(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return detail
    detail = pd.concat([detail, detail.assign(group="Tất cả")], ignore_index=True)
    work = detail.assign(
        finished=detail["realized"].notna(),
        on_time=detail["realized"].le(detail["predicted"]),
        within_one=detail["realized"].le(detail["predicted"] + 1),
        ratio=detail["realized"] / detail["predicted"],
    )
    out = work.groupby(["size_adv", "group"], observed=True).agg(
        cases=("predicted", "size"), predicted=("predicted", "first"),
        median_realized=("realized", "median"), on_time=("on_time", "mean"), within_one=("within_one", "mean"),
        unfinished=("finished", lambda s: 1 - s.mean()),
    ).reset_index()
    return out


# --------------------------------------------------------------------------
# 3. Cảnh báo có báo trước thanh khoản kém hơn mức thường không
# --------------------------------------------------------------------------
def alert_follow_up(table: pd.DataFrame, horizon: int = HORIZON, step: int = HORIZON, baseline: int = HORIZON,
                    progress=None) -> pd.DataFrame:
    """Mỗi mã tại phiên t: tỷ số (giá trị GD trung bình t+1…t+horizon) / (trung bình ``baseline`` phiên kết thúc
    ở t) và tỷ số spread tương tự; so giữa nhóm cảnh báo và không cảnh báo.

    Mốc so sánh là CHÍNH cửa sổ 20 phiên tại t (cửa sổ cảnh báo đang nhìn), không phải 60 phiên trước đó: nếu so
    với 60 phiên trước thì một phần "xấu đi" chỉ là quán tính — mã đã kém sẵn ở t thì 20 phiên sau vẫn kém."""
    sessions = _sessions(table)
    value = table.pivot_table(index="date", columns="symbol", values="value", aggfunc="last").reindex(sessions)
    spread = table.pivot_table(index="date", columns="symbol", values="spread_daily", aggfunc="last").reindex(sessions)
    origins = _origins(sessions, horizon, step, warmup=max(baseline, 60) + HORIZON)
    rows = []
    for n, i in enumerate(origins, 1):
        t = sessions[i]
        if progress:
            progress(n, len(origins), t)
        alerts = alerts_at(table, t)
        # Một mã có thể có nhiều dòng cảnh báo (mỗi chỉ số một dòng): giữ mức nặng nhất.
        if alerts.empty:
            level = pd.Series(dtype=object)
        else:
            rank = alerts["severity"].map({"Do": 0, "Vang": 1}).fillna(2)
            level = (alerts.assign(_r=rank).sort_values("_r").drop_duplicates("symbol")
                     .set_index("symbol")["severity"])
        traded = table.loc[table["date"].eq(t) & table["volume"].gt(0), "symbol"]
        past_v = value.iloc[i - baseline + 1:i + 1].fillna(0).mean()
        next_v = value.iloc[i + 1:i + 1 + horizon].fillna(0).mean()
        past_s = spread.iloc[i - baseline + 1:i + 1].mean()
        next_s = spread.iloc[i + 1:i + 1 + horizon].mean()
        frame = pd.DataFrame({"value_ratio": next_v / past_v.where(past_v > 0),
                              "spread_ratio": next_s / past_s.where(past_s > 0)}).loc[lambda d: d.index.isin(traded)]
        frame["level"] = level.reindex(frame.index).map({"Do": "Đỏ", "Vang": "Vàng", "Thong bao": "Bất thường"}).fillna("Không cảnh báo")
        frame["origin"] = t
        rows.append(frame.rename_axis("symbol").reset_index())
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def summarize_alerts(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return detail
    work = detail.assign(value_worse=detail["value_ratio"].lt(1.0), spread_worse=detail["spread_ratio"].gt(1.0),
                         either=detail["value_ratio"].lt(1.0) | detail["spread_ratio"].gt(1.0))
    out = work.groupby("level").agg(
        cases=("symbol", "size"), value_worse=("value_worse", "mean"), spread_worse=("spread_worse", "mean"),
        either=("either", "mean"), median_value_ratio=("value_ratio", "median"),
        median_spread_ratio=("spread_ratio", "median"),
    )
    base = out.loc["Không cảnh báo", "either"] if "Không cảnh báo" in out.index else np.nan
    out["lift"] = out["either"] / base
    order = [x for x in ("Đỏ", "Vàng", "Bất thường", "Không cảnh báo") if x in out.index]
    return out.loc[order].reset_index()
