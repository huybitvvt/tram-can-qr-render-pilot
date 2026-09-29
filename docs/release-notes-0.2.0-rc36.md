Trạm Cân QR 0.2.0-rc36

### Cập nhật chính
- **Đẩy Supabase** chỉ đẩy đúng snapshot khớp bộ lọc lúc bấm; bỏ quét lại cuối lượt để tổng số không tăng dần khi còn dòng lỗi/pending.
- Vẫn xếp hàng chờ khi bấm đẩy bộ lọc khác trong lúc đang chạy.
- Sửa 404 `/favicon.ico`: phục vụ logo, tìm path chắc hơn (kể cả bản đóng gói), hỗ trợ cả `HEAD`.

### Cài đặt
Đóng ứng dụng, cài đè bản mới. Dữ liệu và `config.env` được giữ nguyên.
