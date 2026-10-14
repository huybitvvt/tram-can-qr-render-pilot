Trạm Cân QR 0.2.0-rc71

### Cập nhật chính

- Ô **Tối đa cuộn/đợt** là ngưỡng nhắc đẩy kho. Khi đủ phiếu hợp lệ đã đồng bộ Supabase và còn chờ đẩy kho, hiện **Đã đủ … cuộn, vui lòng đẩy kho**.
- Đếm toàn bộ dữ liệu theo Ngày/Ca/Máy/LSX/Mã SP của phần nguồn cân phía trên, không phụ thuộc 50 dòng đang hiển thị hoặc bộ lọc bảng dưới. Không dùng số **Số lượng trong ca** làm ngưỡng.
- Không tính phiếu pending/failed/local, phiếu lỗi, phiếu thiếu QR/số cân hoặc phiếu đã đẩy kho. Nhận biết ngay khi đồng bộ xong qua bộ đếm tự cập nhật, không cần lưu thêm cuộn hoặc bấm Làm mới.
- Popup hiển thị số cuộn chờ, ngưỡng và nguồn cân; bấm **Đã hiểu** để tiếp tục. Không tự đẩy kho hoặc ghi xác nhận đợt cân.
- Cùng một đợt chờ không bị nhắc liên tục hay nhắc lại sau khi tải trang. Đồng bộ thêm phiếu, kể cả phản hồi đến lệch thứ tự, không làm lặp popup; sau khi đẩy kho, đợt mới đủ số lượng sẽ được nhắc.
- Chờ hộp thoại khác hoặc thao tác ghi ảnh/lưu phiếu kết thúc trước khi hiện popup. Enter/Space/Backspace trong popup không kích hoạt chụp/lưu/bỏ ảnh; Tab giữ trong hộp thoại.
- Lịch đồng bộ vẫn là 10 phút/lần khi AI rảnh. Nút **Xác nhận đợt cân** vẫn cho xác nhận thủ công.

### Kiểm tra

200 test Python và 128 test Node đã qua. Kiểm tra trên Edge: 74 phiếu local, ngưỡng 30, có 29 phiếu đã đồng bộ thì không báo; phiếu thứ 30 đồng bộ xong thì hiện popup. Giữ nguyên lượt cân đang mở, không lặp sau tải trang, và nhắc đúng đợt tiếp theo sau khi đẩy kho.

### Cập nhật máy khách

Bấm **Cập nhật Trạm Cân QR** trên Desktop hoặc cài đè `TramCanQR-Setup-0.2.0-rc71.exe`, mở lại ứng dụng rồi nhấn **Ctrl+F5**. Dữ liệu, cấu hình và các key đã lưu được giữ nguyên.
