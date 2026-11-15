"""Nhận xét tự động theo quy tắc cố định cho dashboard LiquiSense.

Mọi câu nhận xét đều sinh ra từ số liệu bằng các ngưỡng khai báo trong THRESHOLDS, nên có thể
truy vết và kiểm chứng. Nhận xét chỉ MÔ TẢ và SO SÁNH (cao hơn, thuộc nhóm, chiếm…), không bao giờ
đưa ra khuyến nghị mua/bán.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Ngưỡng dùng cho toàn bộ nhận xét — chỉnh ở đây, trích nguyên bảng này vào báo cáo.
THRESHOLDS = {
    "market_high": 1.20,        # GTGD phiên / TB 20 phiên > 120%  -> "cao hơn bình thường"
    "market_low": 0.80,         # < 80%                             -> "thấp hơn bình thường"
    "range_change": 0.15,       # khoảng so với khoảng trước ±15%   -> "tăng/giảm"
    "board_gap": 10,            # chênh Score trung vị giữa hai sàn >= 10 điểm -> nêu ra
    "red_cluster_min": 3,       # >= 3 mã đỏ mới phân tích theo ngành
    "red_cluster_share": 0.25,  # một ngành chiếm >= 25% số mã đỏ -> "tập trung"
    "big_multiple": 3.0,        # thay đổi >= 3 lần -> diễn đạt "gấp N lần" thay vì %
    "wide_spread": 0.01,        # spread > 1% coi là rộng
    "coverage_low": 0.80,       # < 80% mã đủ dữ liệu -> nhắc kết quả mang tính tham khảo
    "top_group": 0.20,          # nhóm 20% tốt nhất / kém nhất theo Score
    "trend_change": 0.25,       # TB 20 phiên so với 60 phiên trước đó ±25% -> "tăng/giảm"
    "zero_spread_share": 0.50,  # >= 50% số ngày spread = 0 -> ước lượng kém tin cậy
    "no_trade_share": 0.10,     # >= 10% phiên không giao dịch
    "split_participation": 0.10,  # gợi ý kịch bản chia lệnh để mỗi phiên <= 10% ADV
    "stuck_days": 3,            # > 3 phiên để thoát -> "khó thoát"
    "weight_high": 0.40,        # một mã chiếm > 40% giá trị danh mục -> tập trung
}

DISCLAIMER = "Nhận xét tự động theo quy tắc, không phải khuyến nghị đầu tư."


@dataclass(frozen=True)
class Insight:
    text: str
    tone: str = "neutral"  # neutral | good | warn | bad


def _vn(value: float, digits: int = 0) -> str:
    text = f"{float(value):,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def _pct(value: float, digits: int = 0) -> str:
    return _vn(value * 100, digits) + "%"


def _ok(value: object) -> bool:
    try:
        return value is not None and not pd.isna(value) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------
# 1. Tổng quan thị trường
# --------------------------------------------------------------------------
def market_insights(
    metrics: pd.DataFrame,
    alerts: pd.DataFrame,
    *,
    scope: str,
    day_ratio: float | None = None,
    range_change: float | None = None,
    compare_boards: bool = True,
) -> list[Insight]:
    out: list[Insight] = []
    th = THRESHOLDS

    # Mức hoạt động giao dịch
    if _ok(day_ratio):
        if day_ratio > th["market_high"]:
            out.append(Insight(f"Thanh khoản {scope} **cao hơn bình thường**: giá trị giao dịch phiên bằng "
                               f"{_pct(day_ratio)} trung bình 20 phiên.", "good"))
        elif day_ratio < th["market_low"]:
            out.append(Insight(f"Thanh khoản {scope} **thấp hơn bình thường**: giá trị giao dịch phiên chỉ bằng "
                               f"{_pct(day_ratio)} trung bình 20 phiên.", "warn"))
        else:
            out.append(Insight(f"Giá trị giao dịch {scope} ở **quanh mức bình thường** "
                               f"({_pct(day_ratio)} trung bình 20 phiên)."))
    elif _ok(range_change):
        if range_change > th["range_change"]:
            out.append(Insight(f"Giá trị giao dịch bình quân {scope} **tăng {_pct(range_change)}** so với "
                               "khoảng thời gian dài bằng nhau liền trước.", "good"))
        elif range_change < -th["range_change"]:
            out.append(Insight(f"Giá trị giao dịch bình quân {scope} **giảm {_pct(-range_change)}** so với "
                               "khoảng thời gian dài bằng nhau liền trước.", "warn"))
        else:
            out.append(Insight(f"Giá trị giao dịch bình quân {scope} **ổn định** so với khoảng trước "
                               f"({'+' if range_change >= 0 else '−'}{_pct(abs(range_change))})."))

    scored = metrics.dropna(subset=["score"])
    # So sánh giữa các sàn
    if compare_boards and not scored.empty:
        by_board = scored.groupby("board")["score"].median()
        by_board = by_board[scored.groupby("board").size() >= 10]
        if len(by_board) >= 2:
            best, worst = by_board.idxmax(), by_board.idxmin()
            gap = by_board[best] - by_board[worst]
            if gap >= th["board_gap"]:
                out.append(Insight(f"{worst} kém thanh khoản hơn {best} rõ rệt: Score trung vị "
                                   f"{_vn(by_board[worst])} so với {_vn(by_board[best])}."))

    # Mức spread
    eligible = metrics[metrics["status"].eq("Du du lieu")]
    if not eligible.empty:
        wide = float((eligible["spread"] > th["wide_spread"]).mean())
        if wide > 0:
            out.append(Insight(f"{_pct(wide)} số mã có spread ước lượng trên {_pct(th['wide_spread'])} — "
                               "giao dịch các mã này tốn chi phí ngầm đáng kể.", "warn" if wide > 0.2 else "neutral"))

    # Cảnh báo đỏ tập trung ở đâu
    if alerts is not None and not alerts.empty:
        red = alerts[alerts["severity"].eq("Do")]
        if len(red) >= th["red_cluster_min"]:
            sector_of = dict(zip(metrics["symbol"], metrics["sector"]))
            sectors = red["symbol"].map(sector_of).value_counts()
            if not sectors.empty and sectors.iloc[0] >= 2:
                top_name, top_n = sectors.index[0], int(sectors.iloc[0])
                if top_n / len(red) >= th["red_cluster_share"]:
                    out.append(Insight(f"Cảnh báo đỏ **tập trung** ở ngành **{top_name}** "
                                       f"({top_n}/{len(red)} mã đỏ).", "bad"))
                else:
                    out.append(Insight(f"{len(red)} mã cảnh báo đỏ **rải rác ở nhiều ngành**; nhiều nhất là "
                                       f"{top_name} ({top_n} mã).", "warn"))
        elif red.empty:
            out.append(Insight("Không có mã nào bị cảnh báo đỏ ở phiên này.", "good"))

    # Độ phủ dữ liệu
    if len(metrics):
        coverage = len(eligible) / len(metrics)
        if coverage < th["coverage_low"]:
            out.append(Insight(f"Chỉ {_pct(coverage)} số mã đủ dữ liệu để chấm điểm — các so sánh trên mang "
                               "tính tham khảo.", "warn"))
    return out


# --------------------------------------------------------------------------
# 2. Hồ sơ một mã
# --------------------------------------------------------------------------
def _change_text(change: float, up: str = "tăng", down: str = "giảm") -> str:
    """Diễn đạt mức thay đổi: % khi vừa phải, "gấp N lần" khi rất lớn."""
    multiple = change + 1
    if multiple >= THRESHOLDS["big_multiple"]:
        return f"{up} mạnh, gấp {_vn(multiple, 0 if multiple >= 10 else 1)} lần"
    if multiple > 0 and multiple <= 1 / THRESHOLDS["big_multiple"]:
        return f"{down} mạnh, chỉ còn {_pct(multiple)}"
    return f"{up if change > 0 else down} {_pct(abs(change))}"


def _trend(series: pd.Series, recent: int = 20, base: int = 60) -> float | None:
    """Thay đổi của trung bình `recent` phiên gần nhất so với `base` phiên trước đó."""
    values = series.dropna()
    if len(values) < recent + max(10, base // 3):
        return None
    now = values.tail(recent).mean()
    before = values.iloc[-(recent + base):-recent].mean()
    if not _ok(before) or before <= 0:
        return None
    return float(now / before - 1)


def stock_insights(symbol: str, row: pd.Series, metrics: pd.DataFrame, history: pd.DataFrame,
                   level: str | None, reason: str | None = None) -> list[Insight]:
    out: list[Insight] = []
    th = THRESHOLDS
    scored = metrics.dropna(subset=["score"])
    if _ok(row.get("score")) and len(scored) >= 10:
        share_better = float((scored["score"] > row["score"]).mean())  # tỷ lệ mã tốt hơn
        points = _vn(row["score"])
        if share_better <= th["top_group"]:
            out.append(Insight(f"{symbol} thuộc nhóm **{_pct(th['top_group'])} thanh khoản tốt nhất**, đạt "
                               f"**{points} điểm**.", "good"))
        elif share_better >= 1 - th["top_group"]:
            out.append(Insight(f"{symbol} thuộc nhóm **{_pct(th['top_group'])} thanh khoản kém nhất**, đạt "
                               f"**{points} điểm**.", "bad"))
        else:
            out.append(Insight(f"{symbol} thuộc nhóm **thanh khoản trung bình**, đạt **{points} điểm** "
                               f"(xếp trên {_pct(1 - share_better)} số mã)."))
    elif row.get("status") == "Tran san lien tuc":
        ceil, floor = float(row.get("ceil_days") or 0), float(row.get("floor_days") or 0)
        out.append(Insight(
            f"{symbol} **kẹt trần/sàn liên tục**: đóng cửa ở giá trần {ceil:.0f} và giá sàn {floor:.0f} trong "
            "20 phiên gần nhất. Spread không ước lượng được nên chưa chấm Score — đây là nhóm **rủi ro "
            "thanh khoản cao nhất**, lệnh bên kia gần như không khớp được ở mức giá mong muốn.", "bad"))
    elif not _ok(row.get("score")):
        out.append(Insight(f"{symbol} chưa đủ dữ liệu đầu vào nên không có Score.", "warn"))

    if not history.empty:
        spread_trend = _trend(history["spread_daily"])
        if spread_trend is not None and abs(spread_trend) >= th["trend_change"]:
            out.append(Insight(
                f"Spread ước lượng đang **{_change_text(spread_trend)}** (trung bình 20 phiên so với "
                "60 phiên trước đó).", "warn" if spread_trend > 0 else "good"))
        volume_ok = history["volume"].notna() & (history["volume"] >= 0)
        value_trend = _trend(history["value"].where(volume_ok))
        if value_trend is not None and abs(value_trend) >= th["trend_change"]:
            out.append(Insight(
                f"Giá trị giao dịch **{_change_text(value_trend)}** "
                "(trung bình 20 phiên so với 60 phiên trước đó).", "good" if value_trend > 0 else "warn"))
        recent = history.tail(20)
        spread_days = recent["spread_daily"].dropna()
        if len(spread_days) >= 10:
            zero = float((spread_days == 0).mean())
            if zero >= th["zero_spread_share"]:
                out.append(Insight(f"{_pct(zero)} số ngày gần đây có spread ước lượng bằng 0 — với mã này, "
                                   "ước lượng Corwin–Schultz kém tin cậy, nên đọc cùng Amihud và ADV.", "warn"))
    if _ok(row.get("zero_days")) and row["zero_days"] >= th["no_trade_share"]:
        out.append(Insight(f"{_pct(row['zero_days'])} số phiên gần đây **không có giao dịch**.", "bad"))
    detail = f" Cụ thể: {reason}." if reason else ""   # app truyền bản rút gọn; PDF truyền bản đầy đủ
    locked = row.get("status") == "Tran san lien tuc" or (reason or "").startswith("Đóng cửa ở giá")
    if level == "Do" and locked:
        if row.get("status") != "Tran san lien tuc":   # nhận xét kẹt trần/sàn ở trên chưa có thì nêu ở đây
            out.append(Insight(f"Mã đang bị **cảnh báo đỏ** vì kẹt trần/sàn.{detail}", "bad"))
    elif level == "Do":
        out.append(Insight("Mã đang bị **cảnh báo đỏ**: ít nhất hai chỉ số thanh khoản cùng xấu đi bất thường "
                           f"so với lịch sử của chính mã.{detail}", "bad"))
    elif level == "Vang":
        out.append(Insight(f"Mã đang bị **cảnh báo vàng**: một chỉ số thanh khoản xấu đi bất thường.{detail}", "warn"))
    elif level == "Thong bao" and reason:
        out.append(Insight(f"Giao dịch **sôi động bất thường** (thông báo, không phải rủi ro): {reason}.", "neutral"))
    return out


# --------------------------------------------------------------------------
# 3. Chi phí giao dịch
# --------------------------------------------------------------------------
def split_scenario(ratio: float, half: float, sigma: float, fixed: float, y: float = 1.0) -> tuple[int, float, float]:
    """Kịch bản chia lệnh: số phiên k để mỗi phiên <= ngưỡng tham gia, chi phí trước/sau (giá không đổi)."""
    k = max(1, math.ceil(ratio / THRESHOLDS["split_participation"]))
    before = half + y * sigma * math.sqrt(ratio) + fixed
    after = half + y * sigma * math.sqrt(ratio / k) + fixed
    return k, before, after


def cost_insights(*, symbol: str, ratio: float, half: float, sigma: float, fixed: float,
                  base_total: float, impact: float, window: int,
                  window_costs: dict[int, float]) -> list[Insight]:
    out: list[Insight] = []
    if base_total > 0:
        shares = {"tác động giá": impact / base_total, "nửa spread": half / base_total, "phí và thuế": fixed / base_total}
        main = max(shares, key=shares.get)
        out.append(Insight(f"Ở kịch bản cơ sở, **{main}** chiếm phần lớn nhất ({_pct(shares[main])} tổng chi phí)."))
    if ratio > THRESHOLDS["split_participation"]:
        k, before, after = split_scenario(ratio, half, sigma, fixed)
        out.append(Insight(
            f"Lệnh bằng {_pct(ratio, 1)} ADV. Nếu chia thành **{k} phiên** (mỗi phiên ≤ "
            f"{_pct(THRESHOLDS['split_participation'])} ADV), chi phí cơ sở ước tính giảm từ {_pct(before, 2)} "
            f"xuống {_pct(after, 2)} — với giả định giá không biến động giữa các phiên.", "warn"))
    else:
        out.append(Insight(f"Lệnh chỉ bằng {_pct(ratio, 1)} ADV — đủ nhỏ để giả định khớp trong một phiên hợp lý.",
                           "good"))
    valid = {w: c for w, c in window_costs.items() if _ok(c)}
    if len(valid) >= 2:
        low, high = min(valid.values()), max(valid.values())
        spread_rel = (high - low) / low if low > 0 else 0
        windows = " / ".join(str(w) for w in sorted(valid))
        tone = "warn" if spread_rel > 0.2 else "neutral"
        out.append(Insight(
            f"Với cửa sổ {windows} phiên, chi phí cơ sở dao động **{_pct(low, 2)} – {_pct(high, 2)}**"
            + (" — kết quả khá nhạy với giả định, nên đọc như một khoảng." if spread_rel > 0.2
               else " — kết quả ít nhạy với cửa sổ."), tone))
    return out


# --------------------------------------------------------------------------
# 4. Mô phỏng danh mục
# --------------------------------------------------------------------------
def portfolio_insights(book: pd.DataFrame, levels: dict[str, str]) -> list[Insight]:
    out: list[Insight] = []
    th = THRESHOLDS
    if book.empty:
        return out
    d20 = book["d20"].astype("float64")
    sessions = book["s20"].astype("float64") if "s20" in book else np.ceil(d20.clip(lower=1e-9))
    stuck = book[sessions > th["stuck_days"]]
    if len(stuck):
        names = ", ".join(stuck["symbol"].head(3))
        out.append(Insight(f"**{len(stuck)}/{len(book)} mã** cần hơn {th['stuck_days']} phiên để thoát hết ở mức "
                           f"20% ADV ({names}{'…' if len(stuck) > 3 else ''}).", "bad"))
    else:
        out.append(Insight(f"Mọi mã đều thoát được trong {th['stuck_days']} phiên ở mức tham gia 20% ADV.", "good"))
    if d20.notna().sum() >= 2 and d20.sum() > 0:
        top = book.loc[d20.idxmax()]
        share = float(top["d20"] / d20.sum())
        if share >= 0.5:
            out.append(Insight(f"**{top['symbol']}** chiếm {_pct(share)} tổng thời gian bán ra của danh mục — "
                               "đây là vị thế quyết định tốc độ thoát.", "warn"))
    market = book["market"].astype("float64")
    if market.notna().any() and market.sum() > 0:
        weights = market / market.sum()
        heavy = weights.idxmax()
        if weights[heavy] > th["weight_high"]:
            out.append(Insight(f"Danh mục tập trung: **{book.loc[heavy, 'symbol']}** chiếm "
                               f"{_pct(weights[heavy])} giá trị thị trường."))
    red = [s for s in book["symbol"] if levels.get(s) == "Do"]
    yellow = [s for s in book["symbol"] if levels.get(s) == "Vang"]
    if red or yellow:
        parts = ([f"{len(red)} mã đỏ ({', '.join(red)})"] if red else []) + \
                ([f"{len(yellow)} mã vàng ({', '.join(yellow)})"] if yellow else [])
        out.append(Insight("Trong danh mục có " + " và ".join(parts) + " theo cảnh báo thanh khoản.",
                           "bad" if red else "warn"))
    odd = int((book["qty"] % 100 != 0).sum())
    if odd:
        out.append(Insight(f"{odd} mã có phần lô lẻ — khi bán thực tế, phần này thường khớp chậm và giá kém hơn."))
    missing = int(d20.isna().sum())
    if missing:
        out.append(Insight(f"{missing} mã không đủ dữ liệu ADV nên chưa ước tính được thời gian thoát.", "warn"))
    return out


def window_cost(half: float, sigma: float | None, fixed: float, ratio: float | None) -> float:
    """Chi phí cơ sở (Y = 1) cho một bộ ADV/σ — dùng để so độ nhạy theo cửa sổ."""
    if not _ok(sigma) or not _ok(ratio):
        return np.nan
    return half + sigma * math.sqrt(ratio) + fixed


# --------------------------------------------------------------------------
# 5. Nhận xét mở rộng cho báo cáo PDF
# --------------------------------------------------------------------------
def peer_insights(symbol: str, row: pd.Series, metrics: pd.DataFrame) -> list[Insight]:
    """So sánh một mã với trung vị ngành, sàn và toàn thị trường."""
    out: list[Insight] = []
    eligible = metrics[metrics["status"].eq("Du du lieu")]
    peers = eligible[eligible["sector"].eq(row.get("sector"))]
    if len(peers) >= 5 and _ok(row.get("score")):
        sector_median = peers["score"].median()
        gap = row["score"] - sector_median
        if abs(gap) >= 5:
            out.append(Insight(
                f"Score {'cao' if gap > 0 else 'thấp'} hơn trung vị ngành {row['sector']} "
                f"**{_vn(abs(gap))} điểm** ({_vn(row['score'])} so với {_vn(sector_median)}, {len(peers)} mã).",
                "good" if gap > 0 else "warn"))
        else:
            out.append(Insight(f"Score tương đương trung vị ngành {row['sector']} "
                               f"({_vn(row['score'])} so với {_vn(sector_median)})."))
        rank = int((peers["adv_value"] > row["adv_value"]).sum()) + 1 if _ok(row.get("adv_value")) else None
        if rank:
            out.append(Insight(f"Về giá trị giao dịch bình quân, {symbol} đứng **thứ {rank}/{len(peers)}** "
                               f"trong ngành {row['sector']}."))
    if _ok(row.get("spread")) and len(eligible) >= 10:
        market_spread = eligible["spread"].mean()
        if market_spread > 0:
            rel = row["spread"] / market_spread - 1
            if abs(rel) >= 0.2:
                out.append(Insight(
                    f"Spread ước lượng {'cao' if rel > 0 else 'thấp'} hơn trung bình thị trường "
                    f"**{_pct(abs(rel))}** ({_pct(row['spread'], 2)} so với {_pct(market_spread, 2)}).",
                    "warn" if rel > 0 else "good"))
    if _ok(row.get("daily_volatility")) and len(eligible) >= 10:
        vol_median = eligible["daily_volatility"].median()
        if vol_median > 0 and row["daily_volatility"] > 1.5 * vol_median:
            out.append(Insight(f"Biến động giá ngày ({_pct(row['daily_volatility'], 2)}) cao gấp "
                               f"{_vn(row['daily_volatility'] / vol_median, 1)} lần trung vị thị trường — tác động "
                               "giá khi giao dịch khối lượng lớn sẽ cao hơn.", "warn"))
    return out


def size_insights(cost_rows: pd.DataFrame, cheap: float = 0.01) -> list[Insight]:
    """Nhận xét từ bảng chi phí theo quy mô lệnh (cột: pct_adv, value, base)."""
    out: list[Insight] = []
    if cost_rows.empty:
        return out
    ok = cost_rows[cost_rows["base"] <= cheap]
    if not ok.empty:
        top = ok.iloc[-1]
        out.append(Insight(f"Lệnh mua tới **{_pct(top['pct_adv'])} ADV** (khoảng {_vn(top['value'] / 1e6)} triệu đồng) "
                           f"có chi phí cơ sở ước tính không quá {_pct(cheap)}.", "good"))
    else:
        out.append(Insight(f"Ngay cả lệnh 1% ADV cũng có chi phí cơ sở trên {_pct(cheap)} — chi phí giao dịch "
                           "ngầm của mã này cao.", "warn"))
    last = cost_rows.iloc[-1]
    first = cost_rows.iloc[0]
    if first["base"] > 0:
        out.append(Insight(f"Tăng quy mô từ {_pct(first['pct_adv'])} lên {_pct(last['pct_adv'])} ADV làm chi phí cơ sở "
                           f"tăng từ {_pct(first['base'], 2)} lên {_pct(last['base'], 2)} "
                           f"(gấp {_vn(last['base'] / first['base'], 1)} lần)."))
    return out


# --------------------------------------------------------------------------
# 5. Dòng tiền và spread theo ngành (bản đồ nhiệt ngành × tháng)
# --------------------------------------------------------------------------
def sector_flow_insights(result: dict) -> list[Insight]:
    """Nhận xét từ bảng ngành × tháng: dòng tiền tháng gần nhất so với bình thường của chính ngành."""
    out: list[Insight] = []
    if not result:
        return out
    flow, spread = result["flow"], result["spread"]
    last = flow.columns[-1]
    latest = flow[last].dropna()
    if latest.empty:
        return out
    label = f"tháng {last.month}/{last.year}" + (" (đang diễn ra)" if result.get("partial") else "")
    hot, cold = latest.idxmax(), latest.idxmin()
    above = int((latest >= THRESHOLDS["market_high"]).sum())
    out.append(Insight(
        f"Trong {label}, **{above}/{len(latest)} ngành** có giá trị giao dịch bình quân phiên cao hơn 20% so với "
        f"mức thường thấy của chính ngành đó.", "neutral"))
    if latest[hot] >= THRESHOLDS["market_high"]:
        out.append(Insight(f"Dòng tiền đổ mạnh nhất vào **{hot}**: {_pct(latest[hot])} mức trung bình của ngành.",
                           "good"))
    if latest[cold] <= THRESHOLDS["market_low"]:
        out.append(Insight(f"**{cold}** đang trầm lắng nhất: giá trị giao dịch chỉ bằng {_pct(latest[cold])} "
                           "mức trung bình — lệnh lớn trong ngành này dễ tốn chi phí hơn bình thường.", "warn"))
    if spread.shape[1] >= 2:
        recent = spread[spread.columns[-1]]
        base = spread[spread.columns[:-1]].mean(axis=1)
        change = (recent / base - 1).replace([float("inf"), -float("inf")], float("nan")).dropna()
        change = change[base.reindex(change.index) > 0]
        if not change.empty and change.max() >= THRESHOLDS["trend_change"]:
            worst = change.idxmax()
            out.append(Insight(f"Spread trung vị của **{worst}** {_change_text(change[worst])} so với các tháng "
                               "trước — chi phí ngầm của ngành đang tăng.", "warn"))
    return out


def sector_context_insights(symbol: str, sector: str, trend: pd.DataFrame) -> list[Insight]:
    """Bối cảnh ngành của một mã (dùng trong báo cáo PDF)."""
    if trend is None or trend.empty or not _ok(trend["flow"].iloc[-1]):
        return []
    flow = float(trend["flow"].iloc[-1])
    tone = "good" if flow >= THRESHOLDS["market_high"] else "warn" if flow <= THRESHOLDS["market_low"] else "neutral"
    state = ("sôi động hơn bình thường" if tone == "good" else "trầm lắng hơn bình thường" if tone == "warn"
             else "ở mức bình thường")
    return [Insight(f"Ngành **{sector}** của {symbol} đang {state}: giá trị giao dịch bình quân phiên tháng gần nhất "
                    f"bằng {_pct(flow)} mức trung bình 12 tháng của ngành.", tone)]
