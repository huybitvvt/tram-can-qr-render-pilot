Trạm Cân QR 0.2.0-rc49

### Cập nhật chính
- Tổng hợp đẩy kho ghi thẳng file CSV/JSON vào thư mục máy (`%LOCALAPPDATA%\TramCanQR\exports\`), không tải Excel qua trình duyệt.
- Mỗi lần đẩy kho thành công tự cập nhật `tong-hop-day-kho.csv` / `.json`.
- Popup tổng hợp đọc từ đĩa; nút **Mở thư mục Excel** mở folder exports.
- Có thể đổi thư mục bằng `ROLL_SCALE_NHAP_KHO_EXPORT_DIR`.
- Giữ các sửa Windows/dual Supabase của rc48.

### Cài đặt
Đóng ứng dụng, cài đè bản mới. Dữ liệu và `config.env` được giữ nguyên.
