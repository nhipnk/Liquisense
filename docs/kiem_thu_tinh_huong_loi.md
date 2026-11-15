# Kiểm thử các tình huống lỗi

Tài liệu này ghi lại cách LiquiSense xử lý các sự cố khi tải dữ liệu từ SSI FastConnect và khi đọc kho dữ liệu, kèm cách tự kiểm tra lại.

- **Kiểm thử tự động:** `tests/test_failures.py`. Không gọi SSI thật, mọi client đều là giả lập.
- **Chạy:** `python -m pytest tests/test_failures.py -v`

## Nguyên tắc chung

1. **Không bao giờ ghi khóa hay token ra log.** Khi lỗi, `job_runs.csv` và log chỉ ghi *tên loại lỗi* (ví dụ `ConnectionError`), không ghi nội dung, vì thông báo lỗi của SDK có thể chứa header `Authorization`.
2. **Không ghi đè dữ liệu tốt bằng dữ liệu rỗng.** Nếu SSI không trả danh sách mã, job dừng trước khi ghi bất cứ thứ gì.
3. **Lỗi từng mã không làm hỏng cả lần chạy.**
   - Mã lỗi được lưu vào `data/ma_loi.txt`. Lệnh `update.py --chi-ma-loi` chỉ tải lại các mã đó.
   - Mã không có nến (tạm ngừng hoặc hủy niêm yết) không bị tính là lỗi.
4. **Trạng thái job rõ ràng.**

   | Trạng thái | Khi nào |
   |---|---|
   | `success` | 0 mã lỗi |
   | `partial` | Có mã lỗi |
   | `error` | Không đăng nhập được, danh sách mã rỗng, hoặc tất cả các mã đều lỗi |

## Bảng tình huống

| # | Tình huống | Cách tái hiện thủ công | Hành vi của hệ thống | Kiểm thử tự động |
|---|---|---|---|---|
| 1 | Thiếu khóa API | Xóa dòng `SSI_API_KEY` trong `.env`, chạy `update.py` | Dừng ngay với thông báo "Thiếu SSI_API_KEY hoặc SSI_API_SECRET. Hãy tạo .env từ .env.example." Không gọi mạng. | `test_missing_key_gives_clear_message` |
| 2 | Sai khóa / khóa bị thu hồi | Sửa một ký tự trong `SSI_API_SECRET` | Thử đăng nhập lại đúng 3 lần, sau đó dừng với `AuthenticationError`. `job_runs.csv` ghi `error`, không lộ khóa. | `test_wrong_key_stops_after_three_attempts` |
| 3 | Token hết hạn khi đang tải (job 5 năm chạy nhiều giờ) | Tự xảy ra sau khoảng 15 phút | Tự lấy token mới trước khi hết hạn 2 phút, và tự lấy lại khi SSI báo 401. Log ghi "Lấy token SSI mới…". | `test_token_is_renewed_before_it_expires`, `test_call_relogs_in_after_authentication_error` |
| 4 | Mất mạng chập chờn | Tắt Wi-Fi vài giây giữa chừng | Mỗi lệnh gọi thử lại 3 lần, chờ 2 giây rồi 4 giây. Nếu mạng có lại thì chạy tiếp bình thường. | `test_transient_network_error_is_retried` |
| 5 | Mất mạng hẳn | Tắt Wi-Fi trước khi chạy | Đăng nhập thất bại, job ghi `error (ConnectionError)` và không tạo file dữ liệu nào. Nếu mất mạng giữa chừng, phần đã tải vẫn được lưu và các mã lỗi được ghi vào `ma_loi.txt`. | `test_login_network_failure_logs_error_without_details`, `test_network_down_raises_after_retries` |
| 6 | Bị giới hạn tần suất (HTTP 429) | Đặt `LIQUISENSE_RATE_LIMIT=50` trong `.env` | Chờ 3 giây, 6 giây rồi 9 giây và thử lại. Mặc định chỉ gửi 5 yêu cầu mỗi giây để tránh bị chặn. | `test_rate_limit_waits_and_retries` |
| 7 | SSI trả danh sách mã rỗng | Giả lập trong test | Dừng job với thông báo "SSI không trả về danh sách mã; dừng job để tránh ghi dữ liệu rỗng". | `test_empty_universe_stops_job` |
| 8 | Mọi mã đều lỗi | Giả lập trong test | Trạng thái `error`. Toàn bộ mã được ghi vào `ma_loi.txt` để thử lại. Thông điệp lỗi không chứa token. | `test_every_symbol_failing_is_error_and_secret_not_logged` |
| 9 | File dữ liệu hỏng (mất điện khi đang ghi, đồng bộ lỗi) | Mở một file `daily_bars_*.parquet` bằng Notepad, xóa vài ký tự rồi lưu | App bỏ qua file đó kèm cảnh báo trong log, không bị sập. Lần tải lại ngày đó sẽ đổi tên file hỏng thành `.hong` và ghi bản mới. | `test_corrupt_partition_is_skipped_and_rewritten` |
| 10 | Bị ngắt khi đang ghi file | Giả lập trong test | Ghi ra file `.tmp` trước rồi mới đổi tên, nên file cũ vẫn còn nguyên. | `test_write_is_atomic` |
| 11 | Một mã không có nến (tạm ngừng hoặc hủy niêm yết) | Có sẵn trong dữ liệu thật | Không tính là lỗi. Trạng thái vẫn là `success`, kèm ghi chú "N mã không có nến…". | `test_update_retries_recent_gap_and_logs_empty_security` |
| 12 | Một mã lỗi tạm thời | Giả lập trong test | Mã được ghi vào `ma_loi.txt`. Lần chạy `--chi-ma-loi` chỉ tải lại mã đó, thành công thì xóa khỏi danh sách. | `test_failed_symbols_are_saved_and_retried` |
| 13 | GitHub Actions thiếu Secrets | Xóa secret `SSI_API_KEY` trên GitHub | Bước cập nhật báo lỗi như tình huống 1. Workflow đỏ, không commit dữ liệu. App trên Streamlit vẫn chạy với dữ liệu cũ. | Kiểm tra thủ công trên GitHub |
| 14 | App mở khi chưa có dữ liệu | Đổi `LIQUISENSE_DATA_DIR` sang thư mục trống | Không sập: dùng dữ liệu mẫu tổng hợp (6 mã giả AAA…FFF) để giao diện vẫn chạy. | `test_empty_store_falls_back_to_sample` |

## Ghi nhận kiểm thử thủ công

Điền vào bảng sau khi tự chạy thử trên máy:

| Ngày | # | Kết quả quan sát | Đạt? |
|---|---|---|---|
| | 1 | | |
| | 2 | | |
| | 5 | | |
| | 9 | | |
