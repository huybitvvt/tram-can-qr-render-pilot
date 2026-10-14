Trạm Cân QR 0.2.0-rc72

### Cập nhật chính

- Bỏ quy tắc ép máy bao bì và máy không phải cách nhiệt về tối đa 16 cuộn/đợt, đồng nhất giao diện, backend local và Edge Function Supabase.
- Ô **Tối đa cuộn/đợt** cho nhập 1–30 ở các ca thông thường, mặc định 30 nếu chưa đặt mức. Mức đã nhập tay được giữ nguyên, kể cả 16; nhập 24 thì nhắc khi đủ 24 phiếu hợp lệ đã đồng bộ và còn chờ đẩy kho. Ca chuẩn Đà Nẵng vẫn giữ giới hạn 10.
- Không tự chốt xe hoặc tự mở **Xác nhận đợt cân**. Nhắc đẩy kho và xác nhận thủ công tiếp tục là hai thao tác riêng.
- Hộp **Xác nhận đợt cân** báo rõ xác nhận thủ công; không còn ghi “Đã đạt tối đa” khi số cuộn thực tế ít hơn ngưỡng. Khi chưa lấy được số phiếu, không hiển thị ngưỡng như số lượng thực tế.
- Đồng bộ tự động vẫn 10 phút/lần khi AI rảnh. Giữ dữ liệu, cấu hình, key và lịch sử đã lưu.

### Kiểm tra

204 test Python và 129 test Node đã qua. Trên Edge, máy bao bì đặt ngưỡng 24 không báo ở 16 hoặc 23 phiếu đã đồng bộ; phiếu thứ 24 đồng bộ xong mới bật nhắc đẩy kho. Không nhắc lặp sau tải trang, giữ lượt cân đang mở, nhắc đúng đợt tiếp theo. Xác nhận thủ công đợt 2 cuộn hiển thị đúng 2, không báo đã đạt tối đa và không tự tạo đợt.

### Cập nhật cloud và máy khách

Cập nhật Edge Function `ingest-measurement` trước khi dùng xác nhận đợt trên 16 cuộn. Không cần migration DB.

Bấm **Cập nhật Trạm Cân QR** trên Desktop hoặc cài đè `TramCanQR-Setup-0.2.0-rc72.exe`, mở lại ứng dụng rồi nhấn **Ctrl+F5**. Kiểm tra ô **Tối đa cuộn/đợt** và nhập mức muốn nhắc cho máy đang chọn.
