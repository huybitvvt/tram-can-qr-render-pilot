# Kiểm chứng rc82 — 24/10/2026

Nền: rc80 (`a4c2fdf0ad4627e04a398e5c2a53edd2524deca8`). Thực hiện trong
worktree `E:\tram-can-qr-rc82`, không mở DB/config vận hành của người dùng.

## Hồi quy

- 534 test Python đạt trong lượt chạy toàn bộ luồng phù hợp với runtime mới;
  2 test camera bridge bổ sung đạt: tổng 536 test. Ba test chạy model Paddle
  runtime cũ được loại khỏi lượt chạy ONNX; không báo ba test này đã đạt.
- 144 test Node đạt, gồm Space không chụp/đọc lại, từ chối số cũ/đổi nguồn,
  đổi ROI/đơn vị, camera dừng/paused và claim theo đúng ô/cuộn/trạm/camera.
- `pip check`, cú pháp Python/JS, `git diff --check` đạt.
- Source storage, station_session, sync, api_client, warehouse đối chiếu nguyên
  vẹn với rc80. Không có migration/schema mới hoặc thay đường dẫn dữ liệu.

## Model và giao diện thật

- Chạy Edge headless với PP-OCRv6 Small thật từ bộ model của trial1;
  không dùng mock OCR để xác nhận kết quả. Cảnh camera lấy từ backup,
  bỏ panel zoom trùng lặp phía dưới.
- Số live 6,86 ổn định; Space đưa số vào ô trong thời gian kiểm tra dưới
  1,5 giây, kết quả backend có `live_reused=true`, ảnh trùng chính xác khung
  hình đã đọc, không chạy lại OCR cho bước lấy số.
- Thử kéo chọn vùng qua phần letterbox, xóa về Auto LED, đổi cách đọc
  thập phân, dừng camera; không có lỗi JavaScript.
- Chạy lại cùng phép thử với EXE đóng gói, đạt. Camera nguồn canvas trong
  bài thử dùng ảnh thật để có kết quả đối chiếu; đây không phải nghiệm thu
  USB/ánh sáng/góc camera tại xưởng.
- Tiến trình camera DirectShow của EXE thật mở driver và báo thiếu thiết
  bị đúng cách với Camera 9; thao tác dừng trả về khoảng 32 ms, backend còn
  phục vụ bình thường. Không thay thế việc nghiệm thu camera thật của xưởng.
- Camera bridge dùng PNG lossless trước OCR; test so pixel đã giải mã với
  pixel gốc khớp hoàn toàn. Ảnh bằng chứng vẫn đi qua luồng lưu rc80.

## Giữ dữ liệu và updater

- Khởi động EXE với profile giả lập rc80 có config Gemini/key không hợp lệ,
  mã trạm 02, DB/ảnh/bản nháp sẵn có. Runtime chọn `rapidocr`, không bật Gemini.
- Config và hash ảnh cũ giữ nguyên, DB snapshot chứa bản ghi và bản nháp cũ.
- Preview live không làm tăng số bản ghi hoặc photo_drafts. Sau lấy số,
  có thể ghi phiếu mới bên cạnh bản ghi rc80; bản ghi cũ giữ nguyên giá trị.
- SQLite backup được thử với WAL đang có dữ liệu chưa checkpoint; DB hỏng
  bị dừng, không tạo marker sao lưu thành công.
- Updater rc74/rc79/rc80/current được thử trên harness cô lập: chọn rc82,
  xác minh hash, đóng/cài/mở. Hash giả bị từ chối trước khi dừng app; DB/config/
  ảnh bảo vệ trong harness không đổi. Không chạy installer để ghi đè ứng
  dụng vận hành trên máy phát triển.

## Gói phát hành

- PyInstaller và Inno Setup build thành công. Mã nhúng EXE và hai file frontend
  khớp source được kiểm chứng bằng trích xuất archive và so bytecode.
- Hai model Small có SHA-256 đúng manifest/trial1. Không kèm Torch, Paddle
  runtime, Ultralytics hoặc Gemini SDK.
- Không kèm `.env`, `.env.local`, `config.env`, DB, token hoặc metadata phiên.
- Installer có số phiên bản và tên chung khớp hash trong SHA256SUMS.txt;
  updater đóng gói khớp file source.

Artifacts chi tiết và screenshot chứa ảnh xưởng chỉ giữ ở `.test-tmp/`,
không đưa vào Git/Release. Bản tích hợp cần được người vận hành kiểm tra lại
với camera thật sau cập nhật; không suy mức chính xác từ sự ổn định ba frame.
