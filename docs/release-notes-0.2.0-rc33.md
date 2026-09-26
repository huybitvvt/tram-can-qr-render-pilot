# Ghi chú phát hành phiên bản 0.2.0-rc33

- Tắt tiến trình tự đồng bộ Supabase/Cloudinary khi ứng dụng chạy và khi lưu phiếu. Dữ liệu vẫn được ghi bền vững vào SQLite và ảnh local trên từng máy.
- Thêm mục **Đồng bộ local → Supabase / Cloudinary** trong tab **Danh sách**. Người dùng xem trước số dòng chờ rồi xác nhận đồng bộ thủ công.
- Lọc chính xác theo khoảng ngày, ca, mã sản phẩm, máy, lệnh sản xuất và phạm vi phiếu cân/ảnh lỗi, cân kiểm kho hoặc tất cả. Bản ghi không có thông tin của một bộ lọc được chọn sẽ không được gửi.
- Hiện tiến độ thành công, lỗi và bản ghi còn chờ; cho phép chọn lại bộ lọc để thử lại. Trường hợp Supabase đã nhận nhưng Cloudinary còn chờ cũng được đưa vào lượt thủ công.

**Cập nhật:** Đóng Trạm Cân QR, dùng nút **Cập nhật Trạm Cân QR** trên Desktop hoặc cài đè `TramCanQR-Setup-0.2.0-rc33.exe`. Sau khi mở lại, dữ liệu đã lưu trên máy vẫn còn. Vào tab **Danh sách** để đồng bộ khi cần; mỗi máy cần thực hiện riêng cho dữ liệu local của máy đó.
