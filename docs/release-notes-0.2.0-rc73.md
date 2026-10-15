Trạm Cân QR 0.2.0-rc73

### Cập nhật chính

- Nút **Hủy AI, bỏ ảnh** được phép bấm khi ô đang chờ AI, kể cả AI chạy lâu hoặc treo. Chỉ bỏ ô được chọn, giữ ảnh/số cân ở ô còn lại và cho chụp lại.
- Nút **Bỏ** và phím **Backspace** cũng bỏ được ô đang chờ AI. Lượt đã lưu phiếu hoặc đang ghi ảnh/phiếu vẫn được bảo vệ.
- Hủy kết nối/yêu cầu trên trình duyệt, gỡ yêu cầu chưa gửi khỏi hàng đợi và giải phóng chỗ cho lượt đọc mới. Dịch vụ AI đã nhận yêu cầu có thể vẫn xử lý đến khi hoàn tất hoặc hết hạn; kết quả trả muộn bị bỏ qua.
- Backend kiểm tra mã ảnh đã lưu trước khi ghi bằng chứng AI; kết quả từ ảnh cũ không được ghi đè ảnh chụp lại. Ảnh gốc đã lưu trên máy vẫn giữ làm bản sao dự phòng.
- Ghi nhận hủy ngay cả khi backend chưa tạo phiên phân tích, không để yêu cầu cũ chiếm lại phiên sau khi đã bấm Bỏ. Hủy ảnh SP hoặc lượt cân khác không hủy phiên cân lõi đang giữ.
- Không thay đổi lịch đồng bộ Supabase hoặc ngưỡng nhắc đẩy kho.

### Kiểm tra

222 test Python và 135 test Node đã qua. Kiểm tra Edge với AI giả lập trả chậm qua HTTP thật: nút Hủy AI hoạt động khi đang chờ; chụp lại trước khi kết quả cũ trả về; giữ nguyên ảnh lõi và số cân ở ô còn lại; chặn ảnh bằng chứng cũ phía backend; Backspace hủy được ô cân lõi đang chờ; không tạo phiếu cân ngoài ý muốn và không có lỗi JavaScript.

### Cập nhật máy khách

Bấm **Cập nhật Trạm Cân QR** trên Desktop hoặc cài đè `TramCanQR-Setup-0.2.0-rc73.exe`, mở lại rồi nhấn **Ctrl+F5**. Không cần migration hoặc cập nhật Edge Function Supabase.
