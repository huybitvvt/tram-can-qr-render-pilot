Trạm Cân QR 0.2.0-rc47

### Cập nhật chính
- Nút **Đẩy kho** thay cho Đẩy Supabase trên danh sách lần cân.
- Xác nhận nhập kho vừa đẩy phiếu cân lên Supabase cân AI (logic cũ), vừa ghi `phieu_nhap` / `nhap_kho`.
- Cập nhật trạng thái cân AI thành **Đã nhập kho** kèm mã phiếu.
- Cần cấu hình `SUPABASE_KHO_*` (DB kho) và `ROLL_SCALE_SUPABASE_*` (DB cân AI).

### Cài đặt
Đóng ứng dụng, cài đè bản mới. Dữ liệu và `config.env` được giữ nguyên.
