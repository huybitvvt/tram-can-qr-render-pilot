Trạm Cân QR 0.2.0-rc35

### Cập nhật chính
- Thêm bộ lọc Ngày / Ca / Máy và nút **Đẩy Supabase** ngay trên Danh sách lần cân.
- Đẩy thủ công chỉ ghi số liệu lên Supabase, **không** upload ảnh lên Cloudinary.
- Đẩy lần lượt theo hàng chờ; cuối lượt quét lại bộ lọc để không miss dòng mới lưu trong lúc đang đẩy.
- Edge Function `ingest-measurement` hỗ trợ `skip_cloudinary` (cần deploy lại function trên Supabase).

### Cài đặt
Đóng ứng dụng, cài đè bản mới. Dữ liệu và `config.env` được giữ nguyên.
