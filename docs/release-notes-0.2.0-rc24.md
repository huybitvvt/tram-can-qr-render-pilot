# Trạm Cân QR 0.2.0-rc24

- Nút **Lưu** tạo phiếu cân chính thức khi có ít nhất một ảnh, kể cả lúc chưa đọc được QR hoặc một hay cả hai số cân. Số chưa đọc được để trống; phiếu tự ghi trạng thái và lý do lỗi.
- Phiếu và ảnh được ghi vào máy trước. Đồng bộ Supabase và Cloudinary chạy nền và tự thử lại nếu mất mạng. Ảnh AI lỗi vẫn được giữ riêng để đọc lại.
- Danh sách hiển thị đúng ảnh cân lõi hoặc ảnh cân sản phẩm đã chụp, kể cả khi ô cân tương ứng chưa đọc được số.
- Giữ các cải tiến cân tối đa bốn lượt, đếm số lượng trong ca và xác nhận đợt cân của bản trước.

**Cloud:** Migration `backend/supabase/migrations/20260924030000_allow_blank_ai_error_weights.sql` đã được áp dụng và Edge Function `ingest-measurement` đã được triển khai cho dự án Supabase `quetcanQR`. Nếu dùng dự án Supabase khác, cần áp dụng hai thay đổi đó trước khi cài máy khách. Installer giữ nguyên dữ liệu và `config.env` cũ.
