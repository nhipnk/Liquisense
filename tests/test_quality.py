import pandas as pd

from liquisense.data.clean import append_quality_log, clean_with_report, read_quality_log, store_quality
from liquisense.data.storage import write_daily_bars


def _bar(**kw):
    base = {"date": "2026-11-02", "symbol": "AAA", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
            "volume": 1000, "ceil_px": 11.0, "floor_px": 9.0}
    base.update(kw)
    return base


def test_each_bad_record_counted_once_and_removed():
    frame = pd.DataFrame([
        _bar(),                                   # hợp lệ
        _bar(symbol="BBB", close="abc"),          # lỗi kiểu
        _bar(symbol="CCC", low=-1, high=-0.5),    # giá <= 0 (và cao < thấp: chỉ đếm lỗi đầu)
        _bar(symbol="DDD", high=8.0),             # cao < thấp
        _bar(symbol="EEE", open=12.0, high=11.0), # giá mở ngoài biên độ
        _bar(symbol="FFF", volume=-5),            # khối lượng âm
        _bar(symbol="GGG", close=11.5, high=12.0),# ngoài trần
        _bar(symbol="AAA", close=10.6),           # trùng mã–ngày
        _bar(date=None, symbol="HHH"),            # thiếu ngày
    ])
    cleaned, report = clean_with_report(frame)
    assert report["raw_rows"] == 9 and report["kept_rows"] == 2
    assert (report["bad_type"], report["non_positive_price"], report["high_below_low"]) == (1, 1, 1)
    assert (report["open_close_outside"], report["negative_volume"], report["outside_band"]) == (1, 1, 1)
    assert (report["duplicate"], report["missing_key"]) == (1, 1)
    assert cleaned.loc[cleaned["symbol"] == "AAA", "close"].iloc[0] == 10.6  # giữ bản mới nhất
    ggg = cleaned[cleaned["symbol"] == "GGG"].iloc[0]          # giá đã điều chỉnh: giữ nguyên cả trần/sàn
    assert ggg["ceil_px"] == 11.0 and report["outside_band"] == 1


def test_write_counts_replaced_and_log_roundtrip(tmp_path):
    write_daily_bars(pd.DataFrame([_bar()]), tmp_path)
    report = {}
    write_daily_bars(pd.DataFrame([_bar(close=10.2), _bar(symbol="BBB")]), tmp_path, report)
    assert report["replaced"] == 1 and report["kept_rows"] == 2
    append_quality_log(tmp_path, report, run="hang_ngay", replaced=report["replaced"])
    log = read_quality_log(tmp_path)
    assert len(log) == 1 and log["ghi_de_ban_cu"].iloc[0] == 1 and "+07:00" in log["thoi_diem"].iloc[0]


def test_store_quality_finds_gaps_and_late_symbols():
    rows = [{"date": d, "symbol": "AAA", "volume": 1} for d in ("2026-11-02", "2026-11-03", "2026-11-04")]
    rows += [{"date": "2026-11-02", "symbol": "BBB", "volume": 0}, {"date": "2026-11-04", "symbol": "BBB", "volume": 5}]
    rows += [{"date": "2026-11-02", "symbol": "CCC", "volume": 3}]
    q = store_quality(pd.DataFrame(rows))
    assert q["sessions"] == 3 and q["symbols_with_gaps"] == 1 and q["missing_sessions"] == 1
    assert q["late_list"] == ["CCC"] and q["zero_volume_rows"] == 1 and q["duplicates"] == 0
