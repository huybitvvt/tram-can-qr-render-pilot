# Kiểm chứng rc94 — 26/11/2026

## Nguyên nhân gốc và giải pháp chọn

Qua phân tích ảnh thực tế từ xưởng (`data/factory_scale_diagnostic_station-01.jpg`
và 942 ảnh `/product-weight/` từ backup xưởng), lỗi chữ số `7` thỉnh thoảng bị đọc
nhầm thành `2` xuất phát từ hai nguyên nhân cộng hưởng:

1. **Vật lý màn hình LED 7 đoạn nghiêng:** ở các số dạng `7.xx` hoặc `17.xx`, chấm
   thập phân đỏ (`.`) nằm sát chân dưới-phải thanh `c` của số `7`. Khi lóa sáng
   (halation/bloom) và nén JPEG, chấm `.` nối vào đáy thanh `c` tạo đường móc dưới
   khiến `PP-OCRv6 Small` nhận nhầm thành `2` (bỏ chấm, chế độ `fixed-2` ra `2.xx`
   hoặc `12.xx`).
2. **Khoảng trống phạm vi hậu kiểm rc93:** `LeadingLEDVerifier` trong rc93 chỉ kích
   hoạt khi `unsigned[0] in '17'`, bỏ qua hoàn toàn mọi kết quả OCR ra `'2'` cũng
   như vị trí hàng đơn vị trước dấu thập phân (`17.xx → 12.xx`).

Giải pháp triển khai trong `0.2.0-rc94` (không dùng quy tắc thay chữ số mù, không
dùng lịch sử cân, không tăng độ nặng runtime):

- Nâng cấp `tools/train_led_glyph.py` và huấn luyện lại `led-glyph-v2` (830.634 byte,
  SHA-256 `4e46936cdd17df01c95ca96bb6631bec54ef951966a845f738b61eaf0784aaa6`) từ
  16.500 mẫu bảy đoạn **100% tổng hợp** (`seed=20261126`, 15 epoch), bổ sung chấm
  thập phân `.` + cầu sáng bloom đối xứng cho đủ 11 lớp (`0–9` và `invalid-pattern`).
  Kết quả validation cuối epoch 15: `plain = 1075/1100`, `dotted = 1079/1100`,
  `dotted_c7_2 = 0`, `dotted_c2_7 = 0`, `dotted_c1_7 = 0`, `dotted_c7_1 = 1`.
- Nâng cấp `backend/src/tramcan_rapidocr/leading_led.py`:
  - Bao phủ chữ số đầu `1/2/7` và chữ số hàng đơn vị sát dấu thập phân `2/7`.
  - Khóa hai lớp: yêu cầu `>= 2` ngưỡng đạt `>= max(0.99, min_confidence)` không mâu
    thuẫn **và** hình học `has_seven_geometry` (`has_top_bar`, `lower_left_ink < 0.20`,
    `mid_left_ink < 0.28`, `lower_right_ink >= 0.20`) khi có `'2'`. Ca mơ hồ bị chặn
    an toàn (`ambiguous-leading-led`).
  - Bảo toàn LED đỏ chạm sát mép ROI (chỉ xóa thành phần viền toàn khung hoặc không
    có sắc đỏ), nối khe dọc có điều kiện cho bảng LED nét rời, và nhánh fallback tách
    bloom (`t=1.3/1.4`, kênh `green`) chỉ chạy khi ngưỡng chính bị dính chữ số.

## Kết quả đối chứng trên ảnh nhà máy thật & video hồi quy

| Tập dữ liệu | Số mẫu | rc93: đúng / sai / từ chối | rc94: đúng / sai / từ chối |
| --- | ---: | --- | --- |
| `data/factory_scale_diagnostic_station-01.jpg` (`7.84`) | 1 | 0 / **1 (`2.84`)** / 0 | **1 (`7.84`) / 0 / 0** |
| `data/factory_scale_diagnostic.jpg` (`20.15`) & `factory_scale_13_04_reference.jpg` (`13.04`) | 2 | 2 / 0 / 0 | **2 / 0 / 0** |
| `data/factory_scale_7_02_full_reference.jpg` (`7.02` crop) | 1 | 0 / 0 / 1 | **0 / 0 / 1** |
| Video hồi quy `7.10` (`video_710_177`) | 177 | 146 / 0 / 31 | **150 / 0 / 27** |
| Video hồi quy `1.06/1.08` (`video_1xx_176`) | 176 | 176 / 0 / 0 | **176 / 0 / 0** |
| Ảnh nhà máy thật `7.xx` — cùng 100 ảnh đầu | 100 | 57 / **7 (`7→2`)** / 36 | **74 / 0 / 26** |
| Toàn bộ ảnh nhà máy thật `7.xx` (`factory_lead7`) | 299 | *(mẫu 250 ảnh: 21 sai `7→2`)* | **225 / 0 / 74** |
| Toàn bộ ảnh nhà máy chứa `7` khác vị trí đầu (`factory_other7`) | 9 | 9 / 0 / 0 | **9 / 0 / 0** |
| Ảnh nhà máy chứa `2` (`12.xx`, `13.02`) — cùng 100 ảnh đầu | 100 | 90 / 0 / 10 | **98 / 0 / 2** |
| Toàn bộ ảnh nhà máy chứa `2` (`factory_other2`) | 321 | — | **316 / 0 / 5** |
| Ảnh nhà máy không chứa `7`/`2` (`factory_other`) | 100 | 95 / 0 / 5 | **96 / 0 / 4** |
| Stress test tổng hợp chấm thập phân (`7.84`, `2.84`, `17.08`, `12.08`) | 270 | — | **270 / 0 / 0** |

Độ trễ nhánh hậu kiểm `LeadingLEDVerifier.verify()` đo riêng trên CPU: trung vị
**15,51 ms**, tối đa **18,24 ms**.

*Giới hạn:* Các số liệu trên được đo trên 1.082 ảnh/frame nhà máy & video sẵn có và
270 mẫu tổng hợp; không thay thế việc đối chiếu trực tiếp khi đưa vào camera mới
có góc lắp hoặc phần cứng màn hình LED khác hoàn toàn.

## Kiểm tra tự động

- **Python pytest:** **192/192 đạt** (`tests/test_leading_led.py` 61 ca,
  `test_rapidocr_regions.py`, `test_local_live.py`, `test_damaged_goods.py`,
  `test_windows_app.py`, `test_windows_installer.py`).
- **Node test suite (`node --test tests/*.test.cjs`):** **176 đạt, 0 thất bại, 2 bỏ qua**
  (các ca PGlite tùy chọn).
- **Updater giả lập (`tools/smoke_windows_updater.py`):** **32/32 đạt** (bao gồm
  `rc74..rc93 → 0.2.0-rc94` và chặn tải sai SHA-256 trước khi đóng app; bảo toàn
  DB/config/ảnh).
- `pip check` và `git diff --check` đạt.

## EXE đóng băng và giao diện Edge

Đã chạy `dist/TramCanQR/TramCanQR.exe` (0.2.0-rc94) qua Microsoft Edge headless
trong thư mục người dùng cô lập, cấu hình cloud giả lập mất mạng (`--offline`):

- **Cảnh `7.84 → 13.04`** (`data/factory_scale_diagnostic_station-01.jpg` chuyển sang
  `data/factory_scale_13_04_reference.jpg`): đọc đúng `7.84`, đạt ổn định, Space lấy
  đúng ảnh/số không gọi OCR lại, chuyển sống sang `13.04` trong `1.797 ms`, xuất JSON
  chẩn đoán khớp byte ảnh, lưu phiếu qua UI, bảo toàn DB/config/photo/draft `rc80`,
  0 lỗi JS (`browser_errors: []`).
- **Cảnh `7.10`** (`.local/ocr-research-20261114/integration-scene.jpg`): đọc đúng
  `7.10`, toàn bộ kiểm tra live/Space/UI/chẩn đoán/bảo toàn dữ liệu đạt, 0 lỗi JS.

## Bộ cài cuối

- Build PyInstaller 6.21.0 + Inno Setup 6 đạt; EXE và installer mang phiên bản
  `0.2.0-rc94`.
- `tools/verify_windows_rapidocr.py` đạt: toàn bộ module nhúng & frontend khớp
  source; SHA-256 model RapidOCR, roll-counter và `led-glyph-v2` khớp tuyệt đối;
  kiểm tra AST/verbatim xác nhận lõi `rc80` (`station_session`, `sync`, `storage`,
  `api_client`, `warehouse`) được bảo toàn; không kèm SDK Gemini, PyTorch, cấu hình
  riêng hay DB.
- Hai tệp installer có cùng nội dung, kích thước **249.282.573 byte**:

```text
6fab64e33c6793bd46291c588c4ba7c0ecfb06ab21a467174c231025cdb7a66e  TramCanQR-Setup-0.2.0-rc94.exe
6fab64e33c6793bd46291c588c4ba7c0ecfb06ab21a467174c231025cdb7a66e  TramCanQR-Setup.exe
```

Bộ bàn giao: `dist/handoff-0.2.0-rc94/`, sẵn sàng phát hành lên GitHub Release
`v0.2.0-rc94` (`latest`) để máy xưởng bấm **Cập nhật Trạm Cân QR**.
