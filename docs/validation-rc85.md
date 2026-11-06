# Kiểm chứng rc85 — 27/10/2026

Worktree `E:\tram-can-qr-rc82`, branch `release/rc85-manual-snapshot`.
Nền rc84: `b3c514dea911b4544f09bf68029e62fdf6f26f11`.

## Tự động

- 566 test Python đạt. Loại 3 test runtime Paddle cũ không thuộc engine
  đóng gói: `test_reads_human_verified_full_factory_702_reference`,
  `test_reads_blurred_station_01_784_with_paddleocr_v6`,
  `test_factory_1304_reference_reads_top_gross_row`. Không tính chúng là đạt.
- 157 test Node đạt. Có kiểm tra giữ ảnh ngay khi OCR còn chờ, live trả muộn,
  hủy ảnh trong khi chờ, timeout/retake, hết hạn, ảnh đã dùng và đổi vùng.
- Token snapshot không đòi chuỗi live ổn định, không ghép được sang ảnh,
  camera, trạm, nguồn hoặc ô khác. Chụp lại 150 lần không làm đầy hàng đợi.
- Chụp/đọc xem trước không ghi DB. Space ghi đúng ảnh/số local; retry dùng
  cùng ID và không chạy OCR/QR/cloud trước xác nhận lưu.
- Giờ đẩy dùng timestamp đã lưu, UTC+7; thiếu/không rõ múi giờ không tự
  suy đoán. CSV, giao diện và bản in được kiểm tra.
- `pip check`, cú pháp Python và `git diff --check` đạt.
- 14 trường hợp updater đạt: rc74/79/80/82/83/84/current chọn rc85;
  checksum sai bị chặn trước khi đóng app. DB/config/ảnh giả lập giữ nguyên.

## Edge và model thật

- Source Trạm 10 và EXE đóng gói Trạm 05 đều đọc ảnh xưởng 13,04 bằng
  PP-OCRv6 Small. Browser chặn request ngoài loopback; cloud giả lập trả 503.
- Bấm giữ ảnh trước khi đạt ổn định live, kết quả snapshot `stable=false`.
  Giữ hơn 3 giây không gửi thêm request live; Space lấy đúng ảnh/số và lưu
  local, chỉ chọn ô kế tiếp sau xác nhận. Lấy lại cùng ảnh cho ô khác bị chặn.
- Tiếp tục live, chọn vùng, đổi chính sách thập phân và dừng camera đạt.
- Bridge native giả lập: snapshot dùng đúng JPEG nguồn, tiếp tục live và
  mở lại đúng nguồn khi mất hình đạt; các ô cân đã lấy được giữ nguyên.
- Lưu phiếu qua giao diện khi cloud lỗi đạt; DB/config/ảnh/bản nháp cũ trong
  profile thử giữ nguyên. Không có lỗi JavaScript.
- In phiếu từ dữ liệu kho giả lập: đúng tên mới, chữ ký Công nhân SX, giờ
  `08:02:03` cho timestamp `2026-10-27T01:02:03Z`. Đã xem ảnh bản in và tạo PDF.

Artifacts trong `.test-tmp/rc85-source-snapshot-13/` và
`.test-tmp/rc85-frozen-snapshot/`; không đưa lên Git/Release.

## Đóng gói

- Build EXE và Inno Setup đạt; không cài đè ứng dụng vận hành.
- Bytecode/frontend trích từ EXE khớp source; SHA model khớp manifest.
- Storage/session/sync/API client giữ nguyên rc80. AST của đường ghi kho
  giữ nguyên; warehouse chỉ thay phần định dạng/xuất giờ CSV.
- Không kèm DB/config riêng hoặc Gemini SDK. AppId, đường dẫn, backup marker
  và cấu hình nâng cấp giữ nguyên.
- Installer tên chung và tên phiên bản giống nhau, 101.073.937 byte/file.
- File rc84 cũ vẫn có SHA `e242bbbecc22ac1d53ec600ef8b2cd286bd2b6604df2b35f653990cd1d642bb2`.

```text
16a559ca799e207401be042ea412828292a9aa088a11ad400ca7ee90804ac205  TramCanQR-Setup-0.2.0-rc85.exe
```

Bộ cài local: `dist/handoff-0.2.0-rc85/`.
Tag phát hành: `v0.2.0-rc85`.
Trang phát hành: https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/tag/v0.2.0-rc85

## Giới hạn

Không nghiệm thu camera USB/driver, ánh sáng hoặc độ đúng OCR trên toàn ca
sản xuất tại xưởng. Camera browser dùng canvas stream từ ảnh tham chiếu;
native camera dùng bridge mô phỏng, không coi là thử phần cứng thật.
Giữ ảnh chỉ cố định bằng chứng; người vận hành vẫn phải đối chiếu chữ số.

Không tìm được nguồn trưởng máy trong source/schema đã kiểm tra; đã bỏ qua
phần tự điền tên theo xác nhận của người dùng. Chữ ký Công nhân SX để ghi tay.
