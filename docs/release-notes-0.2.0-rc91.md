# 0.2.0-rc91

- Sửa lỗi đẩy lại phiếu khi chưa cấu hình key đọc Supabase: dùng kết nối API đồng bộ đã cấu hình để kiểm tra.
- Kiểm tra đúng mã QR trên toàn bộ trang kết quả; bỏ qua QR đã có, kể cả phiếu cloud mang event_id khác.
- Khi đọc cloud thất bại, giữ nguyên dữ liệu local và không gửi lại phiếu.

Kiểm chứng: 193 kiểm thử Python đạt; chạy thử ứng dụng đóng gói với cả kết nối Supabase trực tiếp và API không có key đọc riêng. Bộ cài kèm checksum SHA256.
