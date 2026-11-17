# LiquiSense — Radar thanh khoản cổ phiếu Việt Nam

[![Mở ứng dụng](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://nhipnk-liquisense.streamlit.app/)

**Ứng dụng trực tuyến:** https://nhipnk-liquisense.streamlit.app/

Đồ án cá nhân học phần *Gói phần mềm ứng dụng trong tài chính 1*.

LiquiSense đo thanh khoản của khoảng 1.560 cổ phiếu trên HOSE, HNX và UPCoM. Dữ liệu lấy từ SSI FastConnect Data. Ứng dụng giúp nhà đầu tư cá nhân trả lời ba câu hỏi trước khi đặt lệnh:

1. Thanh khoản của mã này đang ở mức nào so với toàn thị trường, so với ngành và so với chính nó trước đây?
2. Một lệnh có quy mô nhất định sẽ tốn bao nhiêu chi phí ẩn, gồm chênh lệch mua–bán và tác động giá?
3. Cần bao nhiêu phiên để mua hoặc bán hết lệnh đó, có tính thanh toán T+2?

> Công cụ phân tích học thuật, **không phải khuyến nghị đầu tư**. Mọi chỉ số, chi phí và số phiên đều là ước lượng từ dữ liệu lịch sử.

---

## Mục lục
1. [Tính năng](#1-tính-năng)
2. [Chạy lại trên máy của bạn (tái lập kết quả)](#2-chạy-lại-trên-máy-của-bạn-tái-lập-kết-quả)
3. [Tải dữ liệu mới từ SSI (tùy chọn)](#3-tải-dữ-liệu-mới-từ-ssi-tùy-chọn)
4. [Các script dòng lệnh](#4-các-script-dòng-lệnh)
5. [Phương pháp](#5-phương-pháp)
6. [Kết quả kiểm định ngoài mẫu và giới hạn](#6-kết-quả-kiểm-định-ngoài-mẫu-và-giới-hạn)
7. [Cấu trúc mã nguồn](#7-cấu-trúc-mã-nguồn)
8. [Kiểm thử](#8-kiểm-thử)
9. [Triển khai và cập nhật tự động](#9-triển-khai-và-cập-nhật-tự-động)
10. [Bảo mật](#10-bảo-mật)
11. [Tài liệu tham khảo](#11-tài-liệu-tham-khảo)

---

## 1. Tính năng

| Trang | Nội dung |
|---|---|
| **Giới thiệu** | Mục tiêu, đối tượng người dùng và các bước bắt đầu nhanh (bấm để chuyển tới trang tương ứng). |
| **Tổng quan** | Bức tranh thanh khoản toàn thị trường: chỉ số chính, heatmap ngành × sàn, dòng tiền và spread theo ngành từng tháng, phân bố Score, danh sách cảnh báo mới nhất kèm lý do cụ thể, báo cáo chất lượng dữ liệu. |
| **Thanh khoản** | Bảng xếp hạng Score (lọc theo sàn, ngành, tầng, màu cảnh báo; xuất CSV) và hồ sơ từng mã: chỉ số, nhận xét tự động, lý do cảnh báo, biểu đồ lịch sử spread/Amihud/giá trị giao dịch, **xuất báo cáo PDF** có trang bìa. |
| **Chi phí giao dịch** | Nhập khối lượng mua/bán để ước tính chi phí theo ba kịch bản (thấp/cơ sở/cao) và số phiên khớp hết ở mức 10/20/30% ADV, có tính T+2. |
| **Mô phỏng danh mục** | Nhập danh mục tự chọn; xem số phiên cần để thoát từng vị thế và cả danh mục, các mã khó thoát và mã đang bị cảnh báo. |

Thời gian phân tích có hai chế độ: chọn **một ngày** (chỉ số tính trên 20 phiên kết thúc ở ngày đó) hoặc chọn **một khoảng** (ví dụ 1 tháng, 3 tháng, 1 năm; chỉ số, Score và chi phí tính trên toàn bộ khoảng). Giao diện hoàn toàn bằng tiếng Việt, có chế độ sáng và tối, mọi mốc thời gian theo giờ Việt Nam.

---

## 2. Chạy lại trên máy của bạn (tái lập kết quả)

Repo đã có sẵn toàn bộ dữ liệu SSI đã tải (`data/daily_bars_*.parquet`, từ 04/01/2021), nên **không cần khóa API** vẫn chạy được ứng dụng, kiểm thử và kiểm định với đúng dữ liệu của đồ án.

### 2.1. Yêu cầu
- Python **3.10 trở lên** (đã kiểm tra trên 3.12 và 3.13).
- Git.
- Khoảng 2 GB RAM trống cho lần chạy đầu.

### 2.2. Cài đặt

**Windows (PowerShell):**
```powershell
git clone https://github.com/nhipnk/Liquisense.git
cd Liquisense
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
> Nếu PowerShell báo lỗi “running scripts is disabled”, chạy `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` một lần, hoặc dùng thẳng `.\.venv\Scripts\python.exe` thay cho `python` ở các lệnh bên dưới.

**macOS / Linux:**
```bash
git clone https://github.com/nhipnk/Liquisense.git
cd Liquisense
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2.3. Mở ứng dụng
```bash
python -m streamlit run src/liquisense/app.py
```
Mở trình duyệt tại **http://localhost:8501**.

**Lần mở đầu tiên** ứng dụng phải tính bảng chỉ số cho mọi mã và mọi phiên, mất khoảng 1–2 phút, màn hình sẽ hiện thông báo chờ. Kết quả được lưu vào `data/cache/`, nên các lần mở sau chỉ mất vài giây. Có thể tính trước bằng:
```bash
python scripts/precompute.py
```

### 2.4. Chạy kiểm thử
```bash
python -m pytest -q
```
Kết quả mong đợi: tất cả test đều qua (`72 passed`). Kiểm thử không gọi SSI và không cần mạng.

### 2.5. Tái lập kết quả kiểm định ngoài mẫu (mục 6)
```bash
python scripts/kiem_dinh.py
```
Script mất khoảng vài phút với 5 năm dữ liệu. Kết quả được ghi vào `data/kiem_dinh_score.csv`, `data/kiem_dinh_so_phien.csv` và `data/kiem_dinh_canh_bao.csv`; ứng dụng tự đọc và hiển thị ở tab **Thanh khoản → Phương pháp & giới hạn**.

### 2.6. Tái lập tình huống trong báo cáo
```bash
python scripts/tinh_huong.py VCB FPT 500000
```
Lệnh này in số phiên, chi phí và mức dao động giá khi bán 500.000 cổ phiếu mỗi mã. Thêm `--csv data/tinh_huong.csv` để lưu ra file, hoặc `--mua` để xét lệnh mua.

### 2.7. Nếu không có dữ liệu
Nếu thư mục `data/` trống, ứng dụng tự dùng dữ liệu **mẫu tổng hợp** gồm 6 mã giả AAA…FFF, đủ để xem giao diện. Đây không phải dữ liệu thật.

---

## 3. Tải dữ liệu mới từ SSI (tùy chọn)

Chỉ cần khi muốn tự tải thêm dữ liệu. Cần tài khoản **SSI FastConnect Data** (chỉ quyền đọc dữ liệu thị trường, không cần OTP).

1. Sao chép file mẫu và điền khóa:
   ```powershell
   copy .env.example .env      # macOS/Linux: cp .env.example .env
   ```
   Mở `.env`, điền `SSI_API_KEY` và `SSI_API_SECRET` (và `SSI_CLIENT_ID` nếu tài khoản có). **Không commit file `.env`**; file này đã nằm trong `.gitignore`.
2. Chạy cập nhật:
   ```bash
   python scripts/update.py                     # cập nhật thường: tải lại 7 ngày gần nhất
   python scripts/update.py --from-date 2026-01-01 --to-date 2026-01-31   # tải bù một khoảng
   python scripts/update.py --so-nam 5          # kéo dài lịch sử lên 5 năm
   python scripts/update.py --chi-ma-loi        # chỉ tải lại các mã bị lỗi ở lần trước
   ```

Các biến môi trường tùy chọn (đặt trong `.env`):

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `LIQUISENSE_DATA_DIR` | `data` | Thư mục kho dữ liệu |
| `LIQUISENSE_RATE_LIMIT` | `5` | Số yêu cầu mỗi giây gửi tới SSI |
| `LIQUISENSE_HISTORY_YEARS` | `1` | Số năm lịch sử tải cho mã mới |
| `LIQUISENSE_CACHE_URL` | trống | Địa chỉ bảng tính sẵn trên GitHub Release (chỉ dùng khi triển khai cloud) |

Muốn tự động cập nhật trên Windows mà không dùng GitHub Actions: `powershell -ExecutionPolicy Bypass -File .\scheduler\register_task.ps1` (chạy 16:00 thứ Hai–thứ Sáu).

---

## 4. Các script dòng lệnh

| Script | Công dụng |
|---|---|
| `scripts/update.py` | Tải dữ liệu từ SSI, làm sạch, ghi kho Parquet, ghi nhật ký chất lượng dữ liệu |
| `scripts/precompute.py` | Tính sẵn bảng chỉ số và cảnh báo phiên mới nhất |
| `scripts/kiem_dinh.py` | Kiểm định ngoài mẫu (mục 6) |
| `scripts/tinh_huong.py` | Tình huống “bán/mua Q cổ phiếu mất bao lâu, tốn bao nhiêu” |
| `scripts/dong_goi_cache.py` | Đóng gói bảng tính sẵn để tải lên GitHub Release (dùng trong workflow) |

---

## 5. Phương pháp

Mọi chỉ số tính trên **giá đã điều chỉnh** theo sự kiện quyền do SSI cung cấp.

**Kỳ phân tích:**
- Chọn **một ngày** thì mọi chỉ số, Score và hạng tính trên 20 phiên kết thúc ở ngày đó.
- Chọn **một khoảng** thì spread, Amihud, ADV, biến động, tỷ lệ ngày không giao dịch, Score, hạng và chi phí giao dịch đều tính trên **toàn bộ khoảng** (cần ít nhất 10 phiên hợp lệ).
- Riêng **cảnh báo** luôn xét 20 phiên gần nhất tính đến ngày cuối kỳ, vì cảnh báo nói về tình trạng hiện tại của mã.

| Chỉ số | Cách tính | Ý nghĩa |
|---|---|---|
| **Spread ước lượng** | Corwin & Schultz (2012) từ giá cao/thấp của hai phiên liên tiếp; ước lượng âm đặt về 0, lấy trung bình 20 phiên. Bỏ phiên chạm trần/sàn và phiên có sự kiện quyền. | Chi phí của một lệnh nhỏ (độ chặt) |
| **Amihud** | \|lợi suất ngày\| / giá trị giao dịch (tỷ đồng), lợi suất = giá đóng cửa / giá đóng cửa phiên trước − 1 | Lệnh lớn đẩy giá bao nhiêu (độ sâu) |
| **ADV** | Khối lượng và giá trị giao dịch bình quân phiên. Phiên mã không có giao dịch được tính bằng 0. | Quy mô thị trường hấp thụ được (độ rộng) |
| **Tỷ lệ ngày không giao dịch** | Số phiên không khớp lệnh / tổng số phiên | Mức độ giao dịch thưa thớt |
| **Score (0–100)** | 30% spread + 30% Amihud + 30% ADV giá trị + 10% ngày không giao dịch, theo **thứ hạng phần trăm** trong các mã đủ dữ liệu. Xếp hạng đồng hạng khi bằng điểm. | Thanh khoản tương đối, không phải xác suất |

**Vì sao chọn trọng số 30/30/30/10:** thanh khoản có ba chiều chính là độ chặt, độ sâu và độ rộng (Kyle, 1985; Sarr & Lybek, 2002). Không có căn cứ để ưu tiên chiều nào nên ba chiều được chia đều. Tỷ lệ ngày không giao dịch (Lesmond, Ogden & Trzcinka, 1999) bằng 0 với đa số mã nên chỉ giữ 10% để tách nhóm mã ít giao dịch. Khi đổi sang 4 bộ trọng số khác, tương quan hạng Spearman với Score hiện tại vẫn rất gần 1 và nhóm 20% tốt nhất trùng phần lớn, nên kết luận không phụ thuộc vào trọng số cụ thể (bảng độ nhạy trong app, mục Phương pháp & giới hạn).

**Chi phí giao dịch** = nửa spread + tác động giá Y·σ·√(Q/ADV) + phí môi giới 0,15% + thuế bán 0,1%. Ba kịch bản dùng Y = 0,5 / 1 / 1,5 (mô hình căn bậc hai).

**Số phiên khớp hết** = Q / (p × ADV) với tỷ lệ tham gia p = 10%, 20% hoặc 30% mỗi phiên, làm tròn lên. Thanh toán theo T+2.

**Cảnh báo** dùng robust z-score so với 60 phiên trước của chính mã:
- **Đỏ** khi ít nhất hai chỉ số cùng xấu đi với |z| > 2, hoặc khi mã đóng cửa ở giá trần/sàn từ 8/20 phiên trở lên ("kẹt trần/sàn liên tục": không ước lượng được spread và là nhóm rủi ro thanh khoản cao nhất).
- **Vàng** khi có một chỉ số xấu đi.
- **Bất thường** khi giá trị giao dịch tăng đột biến. Đây là thông báo, không phải rủi ro.

**Xử lý dữ liệu:**
- Loại bản ghi trùng; không nội suy giá.
- Chèn các phiên mã không có giao dịch, vì SSI không trả nến cho những phiên này.
- Nhận diện phiên chạm trần/sàn bằng cách quy giá điều chỉnh về giá gốc.
- Phát hiện khi SSI điều chỉnh lại lịch sử giá sau sự kiện quyền và đưa dữ liệu cũ về cùng thang giá (`data/dieu_chinh_gia.csv`).
- Báo cáo chất lượng dữ liệu ghi ở `data/chat_luong_du_lieu.csv` và hiển thị trong app.

---

## 6. Kết quả kiểm định ngoài mẫu và giới hạn

Kiểm định chỉ dùng dữ liệu **đến phiên t** để dự báo, rồi so với **20 phiên thực tế sau t**; các phiên này không tham gia tính dự báo. Phép kiểm tra lặp lại trên 72 mốc từ 02/2021 đến 10/2026. Số liệu dưới đây là kết quả chạy ngày 15/11/2026; chạy lại `scripts/kiem_dinh.py` sẽ ra kết quả cập nhật.

| Kiểm tra | Kết quả | Diễn giải |
|---|---|---|
| Score tại t so với thanh khoản 20 phiên sau (Spearman) | Score 0,92 · Amihud 0,90 · giá trị giao dịch 0,86 · **spread 0,13** | Score xếp hạng thanh khoản tương lai tốt, nhưng **gần như không dự báo được spread** |
| Mã top 20% vẫn ở top 20% sau 20 phiên | 76% | Xếp hạng khá ổn định |
| Lệnh = 1 × ADV, mỗi phiên bán 20% khối lượng thực tế | Dự báo 5 phiên, thực tế trung vị 6 phiên; 40% xong đúng hạn | Số phiên bán hết **lạc quan có hệ thống** |
| Cảnh báo đỏ: giá trị giao dịch 20 phiên sau thấp hơn mức lúc cảnh báo | 52%, so với 55% ở nhóm không cảnh báo | Cảnh báo **mô tả** suy giảm đã xảy ra, **không dự báo** suy giảm tiếp theo |

**Giới hạn cần biết:**
- **Spread Corwin–Schultz trên dữ liệu ngày ở Việt Nam rất nhiễu**, do biên độ trần/sàn và bước giá lớn so với giá cổ phiếu. Nên đọc spread như chỉ báo tương đối, không phải con số chính xác. Không có dữ liệu sổ lệnh để đối chiếu, vì Stream API của SSI cần OTP.
- **Số phiên tính theo ADV trung bình**, trong khi khối lượng phân phối lệch phải, nên thực tế thường lâu hơn khoảng 1 phiên. App và báo cáo PDF đều ghi chú điểm này.
- Cảnh báo là tín hiệu để xem kỹ trước khi đặt lệnh, không phải dự báo.
- Mô hình tác động giá căn bậc hai và hệ số Y lấy từ tài liệu quốc tế, chưa hiệu chỉnh riêng cho thị trường Việt Nam.

Tài liệu kiểm thử các tình huống lỗi (mất mạng, thiếu hoặc sai khóa, hết hạn token, giới hạn tần suất, dữ liệu rỗng, file hỏng): [`docs/kiem_thu_tinh_huong_loi.md`](docs/kiem_thu_tinh_huong_loi.md).

---

## 7. Cấu trúc mã nguồn

```
src/liquisense/
├── app.py              # Điểm vào Streamlit: đầu trang, chọn thời gian, điều hướng trang
├── ui/
│   ├── common.py       # Định dạng số, CSS, bộ chọn thời gian, bộ lọc, nạp dữ liệu
│   ├── intro.py        # Trang Giới thiệu
│   ├── overview.py     # Trang Tổng quan
│   ├── liquidity.py    # Trang Thanh khoản (xếp hạng, hồ sơ mã, phương pháp, kiểm định)
│   ├── cost.py         # Trang Chi phí giao dịch
│   └── portfolio.py    # Trang Mô phỏng danh mục
├── finance.py          # Spread, Amihud, ADV, trần/sàn, Score, chi phí, số phiên
├── analytics.py        # Cảnh báo robust z-score
├── snapshot.py         # Bảng chỉ số lịch sử, chỉ số theo ngày/khoảng, bộ nhớ đệm
├── insights.py         # Nhận xét tự động
├── sector_flow.py      # Dòng tiền và spread theo ngành từng tháng
├── scenario.py         # Tình huống đặt lệnh lớn
├── validation.py       # Kiểm định ngoài mẫu
├── report.py           # Báo cáo PDF (reportlab + matplotlib)
└── data/
    ├── ssi_source.py   # Kết nối chỉ đọc tới SSI FastConnect Data
    ├── update.py       # Job cập nhật, thử lại, phát hiện điều chỉnh giá
    ├── clean.py        # Làm sạch và báo cáo chất lượng dữ liệu
    ├── storage.py      # Kho Parquet theo ngày, nhật ký job
    └── sample.py       # Dữ liệu mẫu tổng hợp
scripts/                # Các script dòng lệnh (mục 4)
tests/                  # Kiểm thử (mục 8)
docs/                   # Tài liệu kiểm thử tình huống lỗi
data/                   # Kho dữ liệu SSI (Parquet), nhật ký, kết quả kiểm định
.github/workflows/      # Cập nhật dữ liệu tự động hằng ngày
```

Nhóm API SSI sử dụng (chỉ đọc): xác thực, danh sách mã theo sàn, nến ngày (`get_ohlc_all`), dữ liệu tham chiếu (giá tham chiếu/trần/sàn), sự kiện quyền. Repo không chứa client đặt lệnh; có test quét mã nguồn để chặn việc này.

---

## 8. Kiểm thử

```bash
python -m pytest -q
```

| Nhóm | File |
|---|---|
| Công thức tài chính, trần/sàn, giá điều chỉnh | `test_finance.py`, `test_real_data.py` (dữ liệu SSI thật của FPT, PMJ, ANV) |
| Làm sạch và chất lượng dữ liệu | `test_clean.py`, `test_quality.py`, `test_storage.py` |
| Job cập nhật, điều chỉnh giá | `test_update.py`, `test_price_rescale.py`, `test_ssi_source.py` |
| Tình huống lỗi | `test_failures.py` |
| Chỉ số, Score, độ nhạy trọng số, kẹt trần/sàn | `test_snapshot.py`, `test_scenario.py` |
| Nhận xét, báo cáo PDF, kiểm định | `test_insights.py`, `test_report.py`, `test_validation.py` |
| An toàn (không có mã đặt lệnh) | `test_no_trading_code.py` |

---

## 9. Triển khai và cập nhật tự động

- **GitHub Actions** (`.github/workflows/cap-nhat-du-lieu.yml`) chạy lúc 16:05 giờ Việt Nam, thứ Hai–thứ Sáu. Workflow tải dữ liệu SSI bằng khóa lưu trong GitHub Secrets, tính sẵn bảng chỉ số, tải lên GitHub Release `cache`, rồi commit dữ liệu mới.
- **Streamlit Community Cloud** tự nhận commit mới và khởi động lại app. Khi khởi động, app tải bảng tính sẵn từ Release (biến `LIQUISENSE_CACHE_URL` trong Secrets của Streamlit) nên mở được ngay; nếu tải không được thì app tự tính lại.

Tự triển khai bản riêng:
1. Fork repo.
2. Thêm `SSI_API_KEY`, `SSI_API_SECRET` vào **Settings → Secrets and variables → Actions**.
3. Bật **Settings → Actions → General → Read and write permissions**.
4. Chạy workflow một lần ở tab **Actions**.
5. Tạo app trên https://share.streamlit.io với **Main file path** `src/liquisense/app.py`, Python 3.12, và Secrets:
   ```toml
   LIQUISENSE_CACHE_URL = "https://github.com/<tài-khoản>/<repo>/releases/download/cache"
   ```

---

## 10. Bảo mật

- Khóa SSI chỉ nằm trong `.env` trên máy cá nhân (đã bị `.gitignore` chặn) hoặc trong GitHub Secrets. Ứng dụng web **không** cần và không đọc khóa SSI.
- Log và nhật ký job không ghi nội dung lỗi của SDK, vì có thể chứa token.
- Chỉ dùng dữ liệu thị trường công khai; không có chức năng đặt lệnh hay đọc tài khoản giao dịch.

---

## 11. Tài liệu tham khảo

- Amihud, Y. (2002). Illiquidity and stock returns: cross-section and time-series effects. *Journal of Financial Markets*, 5(1), 31–56.
- Corwin, S. A., & Schultz, P. (2012). A simple way to estimate bid-ask spreads from daily high and low prices. *The Journal of Finance*, 67(2), 719–760.
- Kyle, A. S. (1985). Continuous auctions and insider trading. *Econometrica*, 53(6), 1315–1335.
- Lesmond, D. A., Ogden, J. P., & Trzcinka, C. A. (1999). A new estimate of transaction costs. *The Review of Financial Studies*, 12(5), 1113–1141.
- Sarr, A., & Lybek, T. (2002). Measuring liquidity in financial markets. *IMF Working Paper* 02/232.
- SSI FastConnect Data API và SSI Python SDK — tài liệu chính thức của Công ty Cổ phần Chứng khoán SSI.
