Trạm Cân QR 0.2.0-rc66

### Cập nhật chính
- Tách phiếu cân đã lưu khỏi ảnh sao lưu tạm. Bấm **Đẩy Supabase** hoặc **Làm mới danh sách** không đưa ảnh của lượt chưa lưu vào bảng phiếu cân.
- Nút **Đẩy Supabase** chỉ lấy các phiếu đã lưu theo bộ lọc hoặc các dòng đã chọn. Giữ nguyên ảnh, số cân, QR và thông tin ngày, ca, máy, LSX, Mã SP của lượt đang cân phía trên.
- Bộ lọc danh sách phía dưới hoạt động độc lập; bấm **Lọc** không đổi thông tin của lượt đang cân hoặc tải lại LSX đang nhập.
- Có mục thu gọn **Ảnh tạm chưa lưu phiếu** để tìm lại ảnh cũ và dùng chức năng đọc lại/xóa đã có. Ảnh của lượt đang mở được giữ ở phía trên và không lặp lại trong mục này. Ảnh tạm không được tính vào số phiếu đã lưu hoặc chọn để đẩy kho.
- Giữ sao lưu ảnh trên máy để tránh mất ảnh khi AI lỗi. Không thay đổi lịch tự đồng bộ 10 phút khi AI rảnh.

### Cài đặt
Thoát hẳn ứng dụng, cài đè bản mới rồi mở lại. Nếu dùng tab trình duyệt, nhấn **Ctrl+F5** để tải giao diện mới. Dữ liệu và `config.env` được giữ nguyên. Không cần cập nhật Edge Function.

Giữ các thay đổi rc63–rc65 về lõi trống bằng 0, chọn theo bộ lọc, phiếu đủ số cuộn khi QR trùng, ba Gemini key luân chuyển và ô LSX/Mã SP vừa gõ tay vừa xổ danh sách.
