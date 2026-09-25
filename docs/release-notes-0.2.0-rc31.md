# Ghi chú phát hành phiên bản 0.2.0-rc31

Bản phát hành `0.2.0-rc31` tối ưu hoá nhận diện cân bằng Gemini, sửa lỗi đồng bộ đám mây và hoàn thiện kiến trúc local-first:

### 1. Nhận diện cân Gemini nhanh, rẻ, chính xác
- **Cắt rộng quanh toàn bộ đầu cân**: Tự động mở rộng vùng crop để lấy trọn vẹn màn hình hiển thị LED, nhãn hiệu NINDA, toàn bộ bàn phím số bên dưới và khung viền bezel. Không còn bị cắt mất phím số hoặc lấy thừa cảnh nhà xưởng.
- **Medium Resolution**: Chuẩn hóa ảnh gửi AI ở mức `medium`, giúp thời gian phản hồi chỉ còn 0.8 - 1.3 giây, tiêu thụ ít token (~740 tokens) và nhận diện ổn định 100% với góc chụp nghiêng tại xưởng.

### 2. Nút "Đọc lại" ảnh lỗi trực tiếp trên giao diện
- Bổ sung nút **Đọc lại** cạnh nút "Xóa dòng lỗi" trong bảng Danh sách lần cân.
- Khi gặp ảnh lỗi hoặc thiếu số cân, người vận hành có thể bấm đọc lại trực tiếp từ ảnh đã lưu trên máy trạm mà không cần cân lại.

### 3. Sửa triệt để lỗi đồng bộ HTTP 422
- Giữ nguyên vẹn byte ảnh gốc khi upload để khớp chính xác mã băm SHA-256 (`frame_sha256`), khắc phục lỗi từ chối 422 trên Supabase Edge Function do nén lại ảnh.

### 4. Vận hành Local-First toàn diện
- **Đếm và in tại chỗ**: Xác nhận đợt cân 10 cuộn và lưu vào SQLite nội bộ trên máy trạm trước khi trả kết quả, bấm In phiếu ngay lập tức không phụ thuộc kết nối Supabase.
- **Hiển thị êm dịu**: Trạng thái đồng bộ hiển thị nhãn cam "Đang chờ", đưa chi tiết kỹ thuật vào tooltip rê chuột để công nhân không bị hoang mang bởi chữ đỏ "Lỗi đồng bộ".
