# Trạm Cân QR 0.2.0-rc76 — giữ app chạy khi driver camera lỗi

Khắc phục trường hợp OpenCV báo `Unknown C++ exception` lúc mở/đổi camera
trên máy xưởng, sau đó app mất kết nối cổng 8080.

- Trên Windows, mở/đọc/đóng camera trong tiến trình phụ. Driver lỗi hoặc
  treo không chạy trong tiến trình web/model/DB; app vẫn cho chọn lại camera.
- Không mở thử nhiều camera từ các luồng HTTP khi làm mới danh sách. Chọn
  đúng Camera USB 0/1 để mở; cổng không có camera sẽ báo không kết nối.
- Đổi nguồn hủy lần mở camera cũ; không dùng lại ảnh/QR/số cân của nguồn cũ.
  Truyền ảnh BGR nguyên vẹn, hàng đợi chỉ giữ khung hình mới nhất và kiểm tra
  thời gian chụp, không thêm nén ảnh giữa camera và model.
- Ghi log từ trước khi nạp thư viện nhận diện. Lỗi native của app nằm ở
  `logs/native-crash.log`, lỗi driver ở `logs/camera-driver.log`.
- Mở lại app đang có đăng nhập dùng đúng thông tin xác thực khi kiểm tra
  server cũ, tránh khởi động thêm server khi `/api/status` yêu cầu đăng nhập.

Giữ model `best.pt`, quy tắc cân/QR, đồng bộ, DB/ảnh/config, AppId,
`TramCanQR.exe`, cổng 8080 và nút cập nhật. Không cần gỡ hoặc xóa dữ liệu.
Lưu xong lượt cân rồi bấm **Cập nhật Trạm Cân QR**; mở lại camera sau cập nhật.

Kiểm tra trước phát hành:

- 534 test Python và 136 test Node đạt; sau thay đổi chờ khung hình đầu,
  chạy lại 20 test camera/khởi động, đều đạt.
- Ép tiến trình camera thoát lúc mở và lúc đang chạy: HTTP vẫn phản hồi,
  đổi lại nguồn được, tự kết nối lại, không đổi phiếu/ảnh cũ.
- EXE rc76 đọc được camera USB thật trên máy phát triển; đường camera phụ
  truyền đủ khung hình, đóng sạch và ghi được lỗi vào `camera-driver.log`.
- EXE mở dữ liệu Gemini cũ trong thư mục thử riêng, giữ nguyên phiếu
  pending/failed, ảnh, cấu hình trạm/kết nối và kiểm tra được bản sao lưu.
  Model kèm EXE đọc ảnh chuẩn 13,04 kg và đúng QR, không gọi Gemini.
- Kiểm tra trình duyệt: chọn ảnh lõi/SP, đọc model local và lưu đủ hai ảnh.
  Script cập nhật rc74 và script hiện tại đều chọn rc76, kiểm tra SHA-256,
  cài/mở lại; tải sai hash bị chặn trước khi đóng app.
- Mã nhúng backend/entry và frontend khớp source; model đúng SHA-256;
  gói không chứa DB/config riêng; hash bộ cài và bản tên cố định khớp nhau.

Cần kiểm tra lại camera trên máy xưởng DELL bị lỗi; kiểm tra camera USB thật
ở trên thực hiện trên máy phát triển, chưa xác nhận driver của máy DELL.
