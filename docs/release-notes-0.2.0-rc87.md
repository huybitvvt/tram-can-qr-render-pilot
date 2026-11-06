# 0.2.0-rc87 — Cân hàng hỏng + đếm cuộn thử

## Bộ cài Windows

- [TramCanQR-Setup.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc87/TramCanQR-Setup.exe)
- [TramCanQR-Setup-0.2.0-rc87.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc87/TramCanQR-Setup-0.2.0-rc87.exe)
- [CAP-NHAT-BAN-MOI.cmd](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc87/CAP-NHAT-BAN-MOI.cmd)

Hai EXE giống nhau, chỉ tải một. Cài đè giữ DB/config/định danh trạm cũ.

## Đếm cuộn (thử)

- Thêm mục đếm từ video hoặc camera hiện tại. Chọn vùng ra máy, vạch và hướng.
- RF-DETR Nano ONNX + ByteTrack + Supervision LineZone chạy offline/CPU;
  thêm chế độ chuyển động cho camera cố định để thử tại cửa ra máy.
- Tăng số khi vật được theo dõi đi qua vạch đúng hướng; có vùng đệm, xác nhận
  nhiều frame, không cộng lại cùng ID khi đi lui rồi đi ra.
- Tạm dừng/tiếp tục, dừng lượt, lịch sử local, CSV và ảnh nhỏ bằng chứng.
  Frame gửi lại dùng cùng số thứ tự/ảnh/thời gian, không cộng trùng.
- Worker riêng, hàng đợi giới hạn, timeout có thể dừng tiến trình nhận diện.
  Không dùng hàng đợi OCR cân; kết quả đếm không tạo phiếu cân hoặc tự đẩy kho.
- Model có sẵn trong bộ cài, không tải lúc mở app tại xưởng.

**Giới hạn quan trọng:** RF-DETR COCO chưa huấn luyện riêng cho cuộn xưởng.
Ba ảnh thử vẫn có vùng nhận nhầm đồ vật khác; không coi số bounding box là số cuộn.
Ảnh tĩnh chỉ thử nhận diện. Video biết số lượng dùng để kiểm tra đường đếm là video
tổng hợp từ ảnh tham chiếu, không phải video sản xuất thật. Camera native dùng bridge
mô phỏng. Cần đối chiếu số tay/video xưởng trước khi dùng số đếm chính thức.
Chế độ chuyển động có thể đếm người hoặc vật khác đi qua vùng; camera phải cố định.
Không tự bù đoạn mất hình, không tự trừ số khi vật quay vào.

## Cân hàng lỗi hỏng (đã làm ở rc86, gộp trong bộ cài này)

- Chọn NKM / NC / RM ở mục Cân hàng lỗi hỏng.
- Chụp một ảnh để đọc và lưu local; không chụp/trừ lõi hoặc bì.
- Mỗi lần cân có mã riêng, thử lưu lại giữ đúng ảnh/ID.
- Đẩy Supabase và Nhập kho theo luồng cũ; ép loại kho **Kho hàng hỏng**.

Giữ engine/model OCR cân, AppId, DB schema, storage/session/sync và cấu hình nâng cấp.
Không triển khai lại cloud Render. Không ghi đè asset các bản đã phát hành.
