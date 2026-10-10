Trạm Cân QR 0.2.0-rc59

### Cập nhật chính
- Khi đổi key Gemini, nhận đầy đủ key `AQ.`/`AIza`, tự bỏ dấu nháy bao ngoài và tên biến cấu hình khi dán dòng `GEMINI_API_KEY=...` hoặc `ROLL_SCALE_GEMINI_API_KEY=...`.
- Chặn chuỗi key đã che hoặc chứa ký tự lạ trước khi gửi Google.
- Kiểm tra bằng một yêu cầu sinh nội dung ngắn trên model cân đang cấu hình, thay cho lấy thông tin của model khác. Giới hạn thời gian và không tự lặp yêu cầu kiểm tra.
- Thông báo rõ khi Google từ chối key, thiếu quyền, hết hạn mức, model không khả dụng hoặc lỗi kết nối; không đưa JSON lỗi thô lên giao diện.
- Chỉ lưu và áp dụng key sau khi kiểm tra thành công; giữ nguyên cả hai key cũ nếu kiểm tra thất bại. Đổi key ca ngày/ca đêm độc lập, không cần khởi động lại.

### Cài đặt
Đóng ứng dụng, cài đè bản mới. Dữ liệu và `config.env` được giữ nguyên. Không cần cập nhật Edge Function.

Nếu key mới vẫn bị Google từ chối, sao chép lại đầy đủ key hoặc tạo key mới tại Google AI Studio. Bản này không thể khôi phục key đã bị Google thu hồi/chặn.
