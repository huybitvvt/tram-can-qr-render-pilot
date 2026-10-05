Trạm Cân QR 0.2.0-rc37

### Cập nhật chính
- Chỉ lưu phiếu khi lần cân đã có đủ ảnh lõi và ảnh sản phẩm.
- Enter lưu những lần đủ ảnh. Lần chưa đủ ảnh được dồn lên thành lần 1 và lần 2; ô trống vẫn hiện ở phía sau.
- Sửa lỗi đẩy Supabase `measurement_insert_failed` khi bỏ qua Cloudinary: cột `image_path` không còn bị ghi null.

### Cài đặt
Đóng ứng dụng, cài đè bản mới. Dữ liệu và `config.env` được giữ nguyên.
