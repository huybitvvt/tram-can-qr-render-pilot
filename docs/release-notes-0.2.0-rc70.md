Trạm Cân QR 0.2.0-rc70

### Cập nhật chính

- AI không đọc được ảnh lõi: tự đặt cân lõi bằng 0 và ghi dấu `CORE_AUTO_ZERO` trong phiếu. Cân SP thiếu hoặc QR thiếu vẫn là dòng lỗi.
- Thêm **Sửa tay** tại bảng **Danh sách lần cân**: sửa QR, cân lõi, cân SP và trạng thái lỗi trên đúng dòng. Giữ hai ảnh, thời gian và danh tính lượt cân; giữ metadata bì/ngày/ca/máy/LSX.
- Không chấp nhận cân SP trống, số âm, NaN/vô cực hoặc cân lõi lớn hơn cân SP khi sửa tay. Lỗi chất lượng ghi tay được giữ khi sửa thông tin khác.
- Đọc lại QR dùng cùng bộ đọc local/trình duyệt như lúc chụp, trên ảnh SP của đúng lượt; không chạy lại AI cân. Đọc riêng từng trường trên ảnh nháp có thể hoàn tất phiếu từ đủ hai ảnh và số cân đã đọc.
- Phím Space/Enter/Backspace trong hộp sửa không kích hoạt luồng chụp/lưu/bỏ ảnh đang cân.
- Nếu cập nhật cloud lỗi, giữ thay đổi local và báo cần đồng bộ lại.

### Cài đặt

Thoát hẳn ứng dụng, cài đè `TramCanQR-Setup-0.2.0-rc70.exe`, mở lại rồi nhấn **Ctrl+F5** trên tab trình duyệt. Dữ liệu, cấu hình và key đã lưu được giữ nguyên.

Máy khách có thể bấm **Cập nhật Trạm Cân QR** trên Desktop hoặc tải bộ cài tại GitHub Releases.

### Kiểm tra

197 test Python và 120 test Node đã qua. Đã kiểm tra thao tác sửa tay trên Edge; mã backend và giao diện trong EXE khớp bản đã kiểm thử. SHA-256 của bộ cài nằm trong `SHA256SUMS.txt` đính kèm release.
