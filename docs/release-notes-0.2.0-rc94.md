# Trạm Cân QR rc94 — xử lý chữ số 7 đọc thành 2 và 7 đọc thành 1

rc94 nâng cấp bộ hậu kiểm chữ số LED của PP-OCRv6 Small lên **`led-glyph-v2`**
(chạy thuần ONNX trên CPU). Ngoài xử lý `7 → 1` của rc93, rc94 xử lý nguyên nhân
vật lý khiến chữ số `7` đứng ngay trước dấu thập phân (`7.xx`, `17.xx`) bị lóa đỏ
nối liền chấm `.` vào chân thanh `c` khiến OCR nhận nhầm thành `2` (`2.xx`, `12.xx`).

Cơ chế hậu kiểm hai lớp trong rc94:

- Huấn luyện lại model `led-glyph-v2` (830.634 byte, 100% dữ liệu bảy đoạn tổng hợp
  không rò rỉ ảnh xưởng) với dữ liệu tăng cường chấm thập phân `.` và cầu sáng
  bloom/halation đối xứng cho cả 11 lớp (`0–9` và `invalid-pattern`).
- Khi OCR có chữ số nghi ngờ ở vị trí đầu (`1 / 2 / 7`) hoặc hàng đơn vị sát dấu
  thập phân (`2 / 7`), ứng dụng tách ô LED đa ngưỡng (có nhánh tách bloom có điều
  kiện và bảo toàn chữ số đỏ sát mép ROI) và yêu cầu đồng thời: **≥ 2 ngưỡng
  classifier đạt `>= max(0.99, min_confidence)`**, không có phân loại chắc chắn mâu
  thuẫn, **hình học 7 đoạn thỏa `has_seven_geometry`** (có thanh ngang trên `a`,
  trống dưới-trái `e`, trống giữa-trái `g`, có chân dưới-phải `c`), và các lượt OCR
  thống nhất phần số còn lại.
- Mọi ảnh mờ, vỡ nét hoặc còn mơ hồ đều bị từ chối an toàn (`ambiguous-leading-led`),
  tuyệt đối không thay thế mù hay suy đoán từ lịch sử cân.
- Không cần Internet, GPU hay SDK AI mới; giữ nguyên điều kiện live ổn định,
  frame token, ảnh bằng chứng, SQLite, đồng bộ Supabase và đẩy kho của rc80/rc93.

## Bằng chứng trên dữ liệu thực tế và hồi quy

| Bộ dữ liệu kiểm định | rc93 | rc94 (`led-glyph-v2`) |
| --- | --- | --- |
| Ảnh chẩn đoán xưởng `station-01` (`7.84`) | **SAI `2.84`** | **ĐÚNG `7.84`** (`verified-leading-led`) |
| Ảnh nhà máy thật `7.xx` — đối chiếu 1:1 (100 ảnh đầu) | 57 đúng; **7 sai (`7→2`)**; 36 từ chối | **74 đúng; 0 sai; 26 từ chối** |
| Toàn bộ 299 ảnh nhà máy thật `7.xx` (`factory_lead7`) | *(mẫu 250 ảnh: 21 sai `7→2`)* | **225 đúng; 0 sai; 74 từ chối** |
| Toàn bộ 9 ảnh nhà máy chứa số `7` vị trí khác (`factory_other7`) | 9 đúng; 0 sai | **9 đúng; 0 sai** |
| Ảnh nhà máy chứa số `2` (`12.xx`, `13.02`) — đối chiếu 1:1 (100 ảnh đầu) | 90 đúng; 0 sai; 10 từ chối | **98 đúng; 0 sai; 2 từ chối** |
| Toàn bộ 321 ảnh nhà máy chứa số `2` (`factory_other2`) | — | **316 đúng; 0 sai; 5 từ chối** |
| 100 ảnh nhà máy không chứa `7`/`2` (`factory_other`) | 95 đúng; 0 sai; 5 từ chối | **96 đúng; 0 sai; 4 từ chối** |
| Toàn bộ 177 frame video hồi quy `7.10` | 146 đúng; 0 sai; 31 từ chối | **150 đúng; 0 sai; 27 từ chối** |
| Toàn bộ 176 frame video hồi quy `1.06/1.08` | 176 đúng; 0 sai | **176 đúng; 0 sai** |
| 270 mẫu tổng hợp chấm thập phân (`7.84`, `2.84`, `17.08`, `12.08`) | — | **270 đúng; 0 sai; 0 từ chối** |

Các số liệu trên được đo trên 1.082 ảnh/frame nhà máy & video hiện có cùng 270 mẫu
tổng hợp (0 ca nhận sai). Với máy/camera mới có góc lắp hoặc đèn LED khác hẳn, vẫn
cần đối chiếu số cân thật trước khi lưu; trường hợp mờ/mâu thuẫn hệ thống ưu tiên từ
chối để chờ khung hình rõ hơn.

## Cài đặt và cập nhật

Đóng ứng dụng, bấm **Cập nhật Trạm Cân QR** trên màn hình Desktop hoặc tải một
trong hai bộ cài:

- [TramCanQR-Setup.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc94/TramCanQR-Setup.exe)
- [TramCanQR-Setup-0.2.0-rc94.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc94/TramCanQR-Setup-0.2.0-rc94.exe)
- [CAP-NHAT-BAN-MOI.cmd](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc94/CAP-NHAT-BAN-MOI.cmd)
- [SHA256SUMS.txt](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc94/SHA256SUMS.txt)

Hai bộ cài có cùng nội dung; chỉ cần tải một. Cài đè (không gỡ bản cũ), mở lại ứng
dụng và nhấn **Ctrl+F5** trên trang đang mở. Phiên bản phải là **0.2.0-rc94**. Dữ
liệu, ảnh, cấu hình (`config.env`) và mã trạm được giữ nguyên.

Xem [kiểm chứng và giới hạn rc94](validation-rc94.md) và
[nguồn gốc model](LED-GLYPH-MODEL.md).
