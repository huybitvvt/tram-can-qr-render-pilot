# Trạm Cân QR 0.2.0-rc77 — giảm giật preview và kết nối lại không cần thiết

- Preview lấy khung hình camera mới nhất, độc lập với luồng AI. Bản hiển thị
  có cạnh dài tối đa 960 px, JPEG 80, lấy ảnh cách nhau ít nhất 100 ms; không
  gửi chồng request. Ảnh chụp cân, chỉ lưu ảnh và kiểm kho lấy khung hình gốc.
- Driver thử lại trong tối đa 2 giây khi đọc hụt frame sau khi đã mở camera.
  Startup vẫn chịu timeout 20 giây của tiến trình cha. Camera treo khi đang
  đọc chịu watchdog 5 giây; đổi nguồn/dừng app hủy đọc qua polling 200 ms.
- Bỏ frame cũ trong mailbox rồi chờ frame mới, thay vì khởi động lại driver
  chỉ vì CPU vừa bận. Giữ giới hạn tuổi ảnh chụp 2 giây.
- Đổi nguồn đánh thức thời gian chờ reconnect; phản hồi preview của nguồn cũ
  không được vẽ hoặc đặt lịch tiếp sau khi đã đổi camera.
- Sửa nguồn USB `00`/`01` bị hủy nhầm; worker của bản Auto nhận đúng cờ
  `--camera-worker` và không nạp model/DB/web.

Giữ AppId, đường dẫn DB/ảnh/config, model, cổng 8080 và cơ chế cập nhật cũ.
Lưu xong lượt cân rồi bấm **Cập nhật Trạm Cân QR**, hoặc tải
[bộ cài rc77](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc77/TramCanQR-Setup-0.2.0-rc77.exe)
để cài đè. Không cần gỡ app hoặc xóa dữ liệu.

Kiểm chứng tại máy phát triển:

- 541 test Python toàn bộ, 41 test camera/khởi động (gồm test live camera
  ngoài testpaths mặc định) và 142 test Node đạt.
- Ép driver thoát lúc mở/đang chạy: HTTP còn hoạt động, tự kết nối lại,
  phiếu và ảnh cũ không đổi.
- Khóa AI trong smoke test HTTP: 19 frame preview khác nhau trong 3 giây,
  health endpoint chậm nhất 31 ms; giữ nguyên PID driver và kích thước ảnh
  chụp gốc. Đây là số đo mô phỏng trên máy phát triển.
- Edge thật hiển thị 13 frame preview khác nhau trong 2 giây khi AI bị chặn;
  mất nguồn mô phỏng rồi có lại tự hồi hình, không cần mở lại camera.
- Chọn ảnh lõi/SP, đọc model local và lưu đủ hai ảnh bằng Enter trên Edge
  đạt; script cập nhật rc74/hiện tại đều chọn rc77 và chặn tải sai hash.
- Worker trong EXE rc77 mở được video OpenCV, truyền đủ frame, dừng sạch và
  ghi được lỗi driver. EXE mở dữ liệu cũ trong thư mục thử riêng, giữ phiếu
  pending/failed, cả hai ảnh và cấu hình; bản sao lưu kiểm tra hợp lệ. Model
  kèm EXE đọc đúng 13,04 kg/QR. Mã backend nhúng khớp source hiện tại.

Test mô phỏng không xác nhận được chất lượng dây USB, nguồn điện hay driver
trên máy xưởng. Cần cài và kiểm tra trực tiếp tại máy bị chập chờn.
