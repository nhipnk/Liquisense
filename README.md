# LiquiSense

LiquiSense là dashboard nghiên cứu thanh khoản cổ phiếu Việt Nam, dùng dữ liệu
thị trường SSI FastConnect. Ứng dụng trả lời ba câu hỏi: thanh khoản mã đang ở
mức nào, chi phí giao dịch ước tính theo kịch bản ra sao, và cần bao nhiêu ngày
để thanh lý một vị thế giả lập.

> **Công cụ học thuật, không phải khuyến nghị đầu tư.** Số liệu chi phí và thời
> gian thanh lý chỉ là ước tính; không đảm bảo lệnh có thể khớp.

## Trạng thái tính năng

- Dashboard Streamlit có giao diện sáng/tối, lọc sàn/ngành/ngày, bảng xếp hạng,
  heatmap, cảnh báo, mô phỏng chi phí, danh mục nhập tay và lịch sử chỉ số.
- Xuất báo cáo CSV cho bảng xếp hạng, kịch bản chi phí, danh mục và lịch sử.
- Dữ liệu demo được tạo xác định, có nhãn rõ ràng; chạy được mà không cần API key.
- Job SSI dùng duy nhất `Auth` + client `Data` để đọc dữ liệu. Dashboard không
  xác thực SSI. Không có client đặt lệnh, danh mục tài khoản hay WebSocket giao dịch.
- Dữ liệu tổng mua/tổng bán chưa được xác minh ý nghĩa nên chưa được dùng.
- Sổ lệnh, nến 1 phút, kiểm định ngoài mẫu và báo cáo PDF chưa nằm trong bản đầu.

## Cấu trúc

```text
src/liquisense/
├── analytics.py             # Cảnh báo thống kê
├── app.py                   # Giao diện Streamlit
├── finance.py               # Spread, Amihud, ADV, score, chi phí, DTL
└── data/
    ├── clean.py             # Làm sạch OHLCV
    ├── sample.py            # Sinh dữ liệu demo
    ├── ssi_source.py        # Kết nối chỉ đọc tới SSI SDK
    ├── storage.py           # Parquet, nhật ký job
    └── update.py            # Job cập nhật và chạy bù
tests/                       # Công thức, dữ liệu, lưu trữ, an toàn
scheduler/                   # Tạo lịch Windows Task Scheduler
data_sample/                 # Hướng dẫn về dữ liệu demo
```

## Cài đặt trên Windows

Yêu cầu Python 3.11 trở lên (SDK hiện yêu cầu Python >= 3.10).

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Mở dashboard bằng dữ liệu mẫu:

```powershell
python -m streamlit run .\src\liquisense\app.py --server.address 127.0.0.1
```

Dashboard mặc định chỉ lắng nghe trên máy cục bộ, không mở ra mạng LAN.

## Kết nối SSI (tùy chọn)

1. Tạo file `.env` trong thư mục dự án bằng cách sao chép `.env.example`.
2. Tự điền `SSI_API_KEY` và `SSI_API_SECRET` trực tiếp trong file cục bộ. Không
   gửi khóa qua chat, không chụp màn hình/đưa vào báo cáo, không commit `.env`.
3. `SSI_CLIENT_ID` được để tùy chọn theo `Config` của SDK; chỉ điền nếu thông tin
   tài khoản/tài liệu SSI của bạn yêu cầu.
4. Chạy thủ công sau phiên:

```powershell
python .\scripts\update.py
```

Tải lại từ một ngày cụ thể để bù dữ liệu cũ:

```powershell
python .\scripts\update.py --from-date 2026-01-01 --to-date 2026-01-31
```

`--from-date` sẽ truy xuất lại khoảng chỉ định đến `--to-date` (mặc định là ngày
hôm nay), ghi đè idempotent theo ngày và mã. Job thường ngày lấy lại 7 ngày gần
nhất để bù dữ liệu trễ; nếu nghỉ job lâu hơn, hãy truyền `--from-date`.

Để tạo lịch tự động trên Windows, chạy PowerShell tại thư mục dự án:

```powershell
powershell -ExecutionPolicy Bypass -File .\scheduler\register_task.ps1
```

Task chạy 16:00 từ thứ Hai đến thứ Sáu, bật chạy bù nếu máy lỡ lịch. Hãy đảm bảo
Python environment và file `.env` vẫn tồn tại tại vị trí dự án.

## Dữ liệu, công thức và giới hạn

- Kho thật được ghi thành `data/daily_bars_YYYY-MM-DD.parquet`; nhật ký chạy ở
  `data/job_runs.csv`. `data/` đã bị loại khỏi Git.
- Corwin–Schultz loại ngày chạm trần/sàn và ngày sự kiện quyền; làm mượt 20 phiên,
  cần ít nhất 10 quan sát. Giá trị 0 không có nghĩa thanh khoản hoàn hảo.
- Amihud dùng `abs(close/ref_px - 1) / value * 1e9`; chỉ tính ngày có giá trị giao
  dịch dương và không có sự kiện quyền.
- ADV khối lượng dùng cho tác động giá và DTL; ADV giá trị dùng cho điểm thanh
  khoản. Điểm 0–100 là thứ hạng tương đối, không phải xác suất.
- Chi phí dùng nửa spread + tác động giá căn bậc hai (Y = 0,5 / 1 / 1,5) + phí,
  thuế. Phí mặc định 0,15%, thuế bán 0,1%; người dùng có thể thay đổi trên UI.
- Các ngưỡng chi phí, tác động giá và cảnh báo mới là giả định nghiên cứu; cần
  hiệu chỉnh/kiểm chứng với dữ liệu thật trước khi diễn giải.
- Z-score robust dùng epsilon phân vị 1% của phân phối dương toàn universe trong
  tháng trước; nếu spread và Amihud có tương quan hạng trên 0,7, chúng chỉ được
  tính như một bằng chứng khi phân loại cảnh báo đỏ.
- Chưa xác nhận được SSI có điều chỉnh `ref_price` vào ngày giao dịch không hưởng
  quyền; các ngày sự kiện quyền được loại khỏi Amihud/biến động để giảm sai lệch,
  nhưng đây chưa thay thế việc đối chiếu endpoint trên dữ liệu thật.
- Tính năng trạng thái mã niêm yết/đình chỉ, phân tầng 1.600 mã, dòng tiền ngoại
  và danh mục ký quỹ thật chưa được xây dựng. Không suy đoán trạng thái khi SSI
  không trả trường xác nhận.
- Endpoint nến phút và sổ lệnh không được gọi trong job đầu; dữ liệu mẫu không
  thay thế dữ liệu thị trường.

## Kiểm thử

```powershell
pytest
```

Kiểm thử an toàn quét AST trong `src/` để chặn import client giao dịch và hàm đặt,
sửa, hủy lệnh; đồng thời xác nhận `.env.example` không chứa khóa ký lệnh.

## Tài liệu SSI tham khảo

- [SSI Python SDK - Cài đặt và yêu cầu](https://developers.ssi.com.vn/docs/sdk/python/installation-requirements)
- [SSI Python SDK - Cấu hình](https://developers.ssi.com.vn/docs/sdk/python/configuration)
- [SSI Python SDK - Client classes](https://developers.ssi.com.vn/docs/sdk/python/client-classes)
- [SSI Python SDK - Service classes](https://developers.ssi.com.vn/docs/sdk/python/service-classes)

Job dùng `get_securities_info_by_board`, `get_ohlc_all`, `get_master_data_historical`
và `get_corporate_actions_historical`. SSI giới hạn truy vấn corporate actions
theo cửa sổ tối đa 5 ngày; job tự chia nhỏ khoảng ngày trước khi ghép cờ sự kiện.
