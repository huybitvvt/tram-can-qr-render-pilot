# Trạm Cân QR 0.2.0-rc34

Sửa luồng đọc QR lúc được lúc không và trường hợp máy đã đọc được mã nhưng ô QR vẫn hiện `--`.

- Ảnh cân sản phẩm và kiểm kho giữ cạnh dài tối đa 2.560 px, JPEG chất lượng 96%, thay cho 1.600 px/90%. Camera Full HD và 2K giữ nguyên kích thước khi chụp QR.
- Bộ giải mã local đọc ảnh trước khi ghép khung zoom cân và nén JPEG lần nữa. Khung QR trả về được quy đổi đúng sang ảnh bằng chứng.
- Nếu mã đã đọc bị chặn vì trùng phiếu hoặc trùng lượt cân, lý do và mã đã đọc hiện ngay ở ô QR. Quy tắc chống trùng được giữ nguyên.
- Phản hồi kiểm tra trùng đến muộn không xóa mã mới hoặc mã của lượt mới.
- Khi backend và trình duyệt đọc hai mã khác nhau, yêu cầu kiểm tra lại; không tự lấy mã trình duyệt thay cho kết quả xung đột.
- Camera live không còn hiển thị khung QR và khung zoom cân từ ảnh chụp trước đó. Vùng cân cố định vẫn được hiển thị.

Cài đè bộ cài mới để cập nhật. Cấu hình, ảnh và dữ liệu cân hiện có được giữ nguyên; bản này không cần migration database.

Kiểm tra bao gồm QR trên ảnh xưởng tham chiếu, ảnh ngang/dọc, tọa độ ảnh ghép, chụp Full HD/2K/4K, xung đột bộ đọc, chặn trùng và phản hồi đến muộn. Chưa xác minh trực tiếp camera và hai ảnh gốc của lần cân được báo lỗi.

Kết quả: 365 test Python và 58 test giao diện đạt. Bản EXE đóng gói khởi động thành công và giải mã đúng cả hai ảnh xưởng tham chiếu qua API local.

- [Tải bộ cài 0.2.0-rc34](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc34/TramCanQR-Setup-0.2.0-rc34.exe)
- [Tải công cụ cập nhật](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/latest/download/CAP-NHAT-BAN-MOI.cmd)
