Trạm Cân QR 0.2.0-rc48

### Cập nhật chính
- Bản Windows chấp nhận `SUPABASE_KHO_DB_LABEL`, `SUPABASE_KHO_URL`, `SUPABASE_KHO_KEY` trong `config.env`.
- Đẩy kho xác nhận QR đã lưu trên Supabase cân AI trước khi ghi DB kho; không báo hoàn tất khi chưa xác nhận trạng thái cân AI.
- Cập nhật trạng thái cân AI qua API thiết bị, không cần service-role key trên máy khách.
- Sau khi kho đã nhận nhưng mạng lỗi ở bước cập nhật cân AI, bấm lại để dùng lại đúng phiếu và QR, không tạo trùng.
- Kho nhận phiếu `chua_chot`, QR **Đang chờ**; thao tác này chưa chốt phiếu kho.
- Đọc đủ các trang phiếu cân và dùng tên kho từ phiếu nhập nếu DB kho không có danh mục `quan_ly_kho`.

### Triển khai
1. Triển khai Edge Function `ingest-measurement` từ source bản này lên đúng Supabase cân AI trước khi cài bộ mới. Giữ token thiết bị hiện tại; không có migration mới.
2. Đóng ứng dụng, cài đè bộ mới. Dữ liệu và `config.env` được giữ nguyên.
3. Giữ cấu hình cân AI; thêm ba biến `SUPABASE_KHO_*` bằng URL/key DB kho được cấp, rồi mở lại ứng dụng. Key kho cần quyền đọc/ghi theo RLS trên `phieu_nhap`, `nhap_kho`.

### Kiểm tra triển khai API
Chạy tại thư mục source bằng tài khoản có quyền project cân AI:

```powershell
npx.cmd supabase functions deploy ingest-measurement --project-ref YOUR_WEIGH_PROJECT_REF --no-verify-jwt --workdir backend
```

API vẫn kiểm tra `x-device-token` trước khi xử lý yêu cầu. Không đưa token hoặc key thật lên Git.
