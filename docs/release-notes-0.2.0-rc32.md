# Ghi chú phát hành phiên bản 0.2.0-rc32

Bản này sửa lỗi camera trống và nút chụp bị khóa khi ứng dụng khôi phục một phiên AI đang phân tích dở.

- Sau khi khởi động lại, tác vụ AI của tiến trình cũ được đánh dấu là đã gián đoạn. Ảnh đã chụp vẫn được giữ trong vùng staging để không mất dữ liệu ngoài ý muốn.
- Nút **Bỏ** hoạt động với phiên cũ ngay cả khi trình duyệt không còn ảnh xem lại. Ứng dụng chỉ hủy đúng `event_id` đang hiển thị rồi mở lại camera.
- Nếu trạm đã chuyển sang phiên khác, thao tác Bỏ bị từ chối để tránh xóa nhầm phiên mới.
- Giao diện hiển thị lý do phiên bị gián đoạn và giữ camera khóa cho tới khi phiên cũ được xử lý.

**Cập nhật:** Đóng Trạm Cân QR, dùng nút **Cập nhật Trạm Cân QR** trên Desktop hoặc cài đè `TramCanQR-Setup-0.2.0-rc32.exe`. Sau khi mở lại, nếu có thông báo phiên cũ, bấm **Bỏ** rồi chọn camera và bấm **Mở camera**. Bỏ sẽ hủy ảnh/phiên chưa lưu của lượt đó; các phiếu đã lưu và cấu hình được giữ nguyên.
