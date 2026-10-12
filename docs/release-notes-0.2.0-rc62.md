Trạm Cân QR 0.2.0-rc62

### Cập nhật chính
- Khôi phục ô **Ghi chú** dưới khung camera: chữ đậm, chọn cỡ chữ 14–24, tự lưu trên máy, F5 không mất. Ghi chú cũ trên máy (nếu có) hiện lại.
- Đang gõ trong ô Ghi chú thì phím Backspace không bỏ ảnh cân.
- Khôi phục kiểm tra tiến trình đồng bộ Supabase khi mở trang.

### Cài đặt
Đóng ứng dụng, cài đè bản mới. Dữ liệu và `config.env` được giữ nguyên. Không cần cập nhật Edge Function.

Nếu ứng dụng báo `source code string cannot contain null bytes` khi mở, bản cài trên máy đã bị hỏng file: chạy trực tiếp `TramCanQR-Setup-0.2.0-rc62.exe` để cài đè, không dùng `CAP-NHAT-BAN-MOI.cmd`.
