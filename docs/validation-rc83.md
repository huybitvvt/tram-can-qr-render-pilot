# Kiểm chứng rc83 — 24/10/2026

Nền rc82: `2761efe2fbb1a0c622d4439d22e13032fa3c27e5`.
Thực hiện trên branch `release/rc83-offline-stability` tại `E:\tram-can-qr-rc82`.
Không đọc `.env` hoặc mở DB/config vận hành; chỉ dùng profile trong `.test-tmp/`.

## Logic và dữ liệu

- 547 test Python đạt, 3 test Paddle runtime cũ deselected; 151 test Node đạt.
  `pip check`, kiểm tra cú pháp và `git diff --check` đạt.
- Kiểm tra chuỗi số giống nhau với nhịp 20/100/180/200/225/240/500 ms: đạt
  ổn định khi đủ số mẫu và thời gian; không còn kẹt vì ba mẫu cuối quá gần nhau.
- Số mới hủy ổn định cũ; token cũ không được lấy lại khi số quay về nhưng chưa ổn định.
- Lấy số local không gọi lại OCR, cloud, QR decoder hoặc hàng đợi inference.
- Ảnh khác khung hình đã OCR bị từ chối; xác nhận sai event/ô không điền số.
- Gửi lại đúng ảnh/ID không tạo ảnh nháp trùng. Lỗi ghi đĩa thử lại được.
- Mở lại DB kiểm tra ảnh và giá trị đã lưu; backend chỉ báo thành công sau ghi local.
- QR trả muộn không ghi đè mã nhập tay hoặc ảnh đã thay. Request treo có timeout.
- Dừng camera hủy lượt tự mở lại đang chờ.

## Model thật và giao diện

- Edge headless + PP-OCRv6 Small thật; cloud cấu hình tới server giả trả HTTP 503,
  browser chặn lưu lượng ngoài loopback. Đây là mô phỏng mất dịch vụ mạng,
  không ngắt card mạng của máy phát triển.
- 6,86 kg: Space dùng lại đúng frame, lưu ảnh/số trên máy, chuyển ô tiếp theo.
- Đổi sang cảnh cân 13,04 kg: số live đổi và đạt ổn định; ô trước giữ nguyên.
- Lưu phiếu qua chính giao diện, gồm kiểm tra QR local, khi cloud không hoạt động.
- Vùng LED kéo tay, Auto LED, cấu hình thập phân và Dừng camera hoạt động.
- DB/config/ảnh/bản nháp cũ trong profile giả lập giữ nguyên; preview không ghi DB.
- Chạy lại bằng EXE đóng gói trong Edge: đạt tất cả các bước trên, không lỗi JS.
  Chuyển 6,86 → 13,04 và đạt ổn định trong 1.562 ms ở lượt thử này; đây là số đo
  của máy phát triển, không phải cam kết độ trễ trên mọi máy xưởng.
- Mô phỏng bridge camera native ngừng trả frame: giao diện mở lại đúng nguồn,
  OCR tiếp tục và các ô đã lấy không đổi. Không dùng mô phỏng này để kết luận
  driver/camera USB thật đã được nghiệm thu.

## Bộ cài và updater

- PyInstaller 6.21.0 + Inno Setup build thành công. Trích xuất EXE đối chiếu
  bytecode các module và nội dung frontend với source hiện tại, khớp.
- SHA-256 model khớp bản trial/rc82; không kèm Gemini SDK, Paddle runtime, Torch,
  DB hoặc cấu hình riêng. Source storage/session/sync/api_client/warehouse không
  đổi so với rc80; không migration/schema mới.
- Updater rc74/rc79/rc80/rc82/current chọn rc83, kiểm tra checksum rồi mới đóng,
  cài và mở lại. Checksum sai bị chặn trước khi đóng app. DB/config/ảnh trong
  harness giữ nguyên. Không cài đè bản vận hành trên máy phát triển.
- Hai installer tên chung và có phiên bản có cùng hash; mỗi file 101.056.651 byte.

```text
dc2e366a9b0fbb2c1f02a743d955e9a4bd6084b8dd98891c63877f6fb4a35598
```

Ảnh và log chi tiết nằm trong `.test-tmp/`; không đưa ảnh xưởng vào Git/Release.

## Giới hạn

- Video thử phát từ ảnh thực tế để có số đối chiếu; chưa nghiệm thu camera USB thật
  tại xưởng và chưa định lượng tỷ lệ OCR sai trên toàn bộ ca sản xuất.
- Ba test model Paddle runtime cũ được loại khỏi lượt chạy ONNX, không báo đã đạt.
- Model không thay đổi. Số OCR ổn định vẫn có thể sai; không tự tạo số bằng lấy
  trung bình hoặc sửa chữ số dựa trên giá trị trước đó.
- Kiểm tra trùng QR offline chỉ thấy dữ liệu đã có trên máy hiện tại.
