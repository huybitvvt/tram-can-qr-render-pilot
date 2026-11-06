# Trạm Cân QR rc84 — hỗ trợ 10 máy trạm

Bộ cài cho chọn **Trạm 01–10** khi cài mới, thay cho 01–04.
Mỗi máy tính chọn một số trạm khác nhau và tiếp tục chạy một trạm độc lập.

- Máy thứ 10 chọn **Trạm 10**: cấu hình sinh ra là `gateway-10`, `station-10`,
  `camera-10`, với `ROLL_SCALE_STATION_COUNT=1`.
- Máy đã có ứng dụng giữ nguyên số trạm, cấu hình và dữ liệu khi cập nhật.
- Giữ nguyên OCR RapidOCR + PP-OCRv6 Small và các sửa lỗi lưu local/ổn định của rc83.

## Tải và cài

- Cài máy mới hoặc cài đè: tải **TramCanQR-Setup.exe** hoặc
  **TramCanQR-Setup-0.2.0-rc84.exe**; chỉ cần một file EXE.
- Máy đã cài: dùng **CAP-NHAT-BAN-MOI.cmd** nếu muốn cập nhật lên rc84.
- Mỗi máy mới chọn đúng một trạm riêng từ 01 đến 10. Chọn trạm chỉ thiết lập
  định danh local; cấu hình thông tin đồng bộ theo trạm nếu cần Supabase.

Chi tiết kiểm chứng: `docs/validation-rc84.md`.
