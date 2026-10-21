# Trạm Cân QR 0.2.0-rc79 — chốt số cân live, giữ camera khi mạng chậm

- Space ưu tiên kết quả YOLO live đủ tin cậy và ảnh gốc tương ứng, không
  chạy thêm model hoặc chờ FIFO. Áp dụng cân lõi, SP, các lần cân và kiểm kho.
  Ảnh phải còn mới trong 2 giây, camera còn kết nối và vẫn có frame mới.
  Nếu không đủ điều kiện, chụp ảnh mới và nhận diện theo luồng cũ.
- Token do backend cấp gắn với hash ảnh và mã trạm/camera, hết hạn sau 60
  giây. Không tin số cân gửi từ trình duyệt. Giữ kiểm tra chất lượng, chữ số,
  phiên cân và lưu ảnh trước khi chốt kết quả.
- Live tìm màn hình cân một lần rồi đọc vùng đó trên từng frame. Mỗi lượt
  kiểm tra vị trí/màu và tính lại vùng theo các chữ số hiện tại; mất dấu hoặc
  kết quả yếu sẽ dò đầy đủ. Bỏ quét QR theo từng ô ảnh ở live; nhận diện ảnh
  mới khi cần vẫn quét đầy đủ. Nếu QR live bị thiếu, cân SP/kiểm kho dò QR
  đầy đủ trên ảnh đã chốt mà không chạy thêm YOLO. Giới hạn CPU tối đa 2 luồng.
- Tối đa 2 yêu cầu tải dữ liệu cloud và 2 yêu cầu cần nhận diện/dò QR lại để
  chừa kết nối HTTP cho camera/lưu ảnh. Request camera quá 5 giây bị hủy để
  vòng lấy hình tự thử lại. Camera USB và xử lý local không cần Internet.

Lưu xong lượt cân rồi bấm **Cập nhật Trạm Cân QR**, hoặc tải
[bộ cài rc79](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc79/TramCanQR-Setup-0.2.0-rc79.exe)
để cài đè. Giữ DB, ảnh, config và cổng `8080` của bản cũ.

Kiểm chứng tại máy phát triển: 571 test Python và 148 test Node đạt. Test
backend kiểm tra ghép đúng ảnh/kết quả,
fallback, timeout, thay nguồn và token; test giao diện kiểm tra chốt live và
giới hạn kết nối. Edge thật với YOLO CPU đọc 13,04 kg/QR, Space chốt lõi/SP
không thêm lượt inference; preview tiếp tục khi giữ 6 request dữ liệu mạng,
tự hồi sau offline/online và sau một request preview bị treo.
Script cập nhật rc74/hiện tại chọn đúng rc79 và chặn tải sai hash trước khi
đóng app; dữ liệu/cấu hình/ảnh được giữ.

Chưa thử rút dây mạng trực tiếp trên máy xưởng. Mô phỏng xác nhận khả năng
hoạt động của app; cần log máy xưởng nếu vẫn mất hình sau cập nhật.
