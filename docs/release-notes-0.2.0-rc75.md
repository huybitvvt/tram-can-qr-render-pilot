# Trạm Cân QR 0.2.0-rc75 — YOLO local, nâng cấp tại chỗ

Bản này thay bộ nhận diện Gemini của ứng dụng chính bằng model YOLO CPU
`model_2` do người dùng cung cấp. Máy khách bấm **Cập nhật Trạm Cân QR** như
trước; không cần chuyển DB/ảnh hay cài Python/CUDA/key AI.

- Giữ AppId, `TramCanQR.exe`, shortcut, cổng mặc định `8080` và dữ liệu tại
  `%LOCALAPPDATA%\TramCanQR`. Dùng lại DB, ảnh, phiên nháp, cấu hình trạm,
  kết nối Supabase/kho và phiếu pending/failed.
- Cấu hình Gemini cũ được giữ nguyên trên đĩa. Bản Windows dùng model đóng
  gói và engine local dù config cũ còn ghi `gemini` hoặc đường dẫn model cũ.
- Trước lần mở rc75 đầu, sao lưu SQLite kể cả WAL và config vào thư mục
  `backups\before-local-rc75-*`; kiểm tra tính toàn vẹn DB trước khi vận hành.
  Ảnh dùng lại đường dẫn gốc, không bị bộ cài ghi đè.
- Nút **Chọn ảnh từ thiết bị** nhận JPG/PNG/WebP/BMP, tối đa 20 MB; dùng đúng
  ô lõi/SP đã chọn, chặn ô đang lưu/chờ AI. Ảnh lỗi không làm mất camera.
- Giữ hủy AI/bỏ ảnh, bảo vệ phản hồi muộn, lưu ảnh cùng lượt, lịch đồng bộ
  pending mỗi 600 giây khi AI rảnh và thao tác đẩy kho thủ công.
- Bộ cài và nút cập nhật giữ tên tải cố định. Những lần nâng cấp tiếp theo
  tiếp tục tải GitHub Latest, kiểm tra SHA-256, cài đè và mở lại ứng dụng.

**Cài đặt:** lưu xong lượt cân, bấm nút cập nhật cũ hoặc chạy
`TramCanQR-Setup-0.2.0-rc75.exe` bằng cùng tài khoản Windows, giữ đường dẫn
cài cũ. Chọn camera lại nếu ánh xạ trình duyệt trước đó dùng camera web.
Đối chiếu số/QR và thử lưu, đồng bộ một phiếu thực tế trước khi vận hành.

**Quay lại Gemini:** thoát `TramCanQR.exe`, cài lại bộ rc74 có số phiên bản.
Không khôi phục DB sao lưu đè lên DB đang dùng vì sẽ làm mất các phiếu mới.
Model/camera thực tế còn phụ thuộc góc chụp, ánh sáng và CPU tại xưởng.

## Kiểm thử

- 529 test Python và 136 test Node đạt.
- Edge/HTTP thật: chọn ảnh không cần camera, chặn tệp hỏng, chọn lại cùng
  ảnh cho SP, đọc 13,04 kg + QR và lưu đủ hai ảnh vào DB riêng.
- EXE chạy ngoài repo với dữ liệu trạm 04 giả lập: giữ đúng phiếu
  pending/failed, ảnh và cấu hình cũ; bản sao lưu DB/cấu hình khớp;
  model đóng gói đọc đúng 13,04 kg + QR dù config cũ còn chọn Gemini.
- Script cập nhật rc74 và rc75 đều nhận bản mới, kiểm tra hash trước khi
  đóng app; bài thử giả lập chặn hash sai trước khi cài, giữ DB/ảnh/config.

[Tải bộ cài](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/latest/download/TramCanQR-Setup.exe) ·
[Nút cập nhật](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/latest/download/CAP-NHAT-BAN-MOI.cmd) ·
[Hướng dẫn](../packaging/HUONG-DAN-KHACH-HANG.md)
