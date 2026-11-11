# Trạm Cân QR 0.2.0-rc92 — Sửa lỗi cắt chữ số LED đỏ

Sửa bước cắt vùng số có thể bỏ mất chữ số LED đỏ vẫn hiện trên ảnh khi các
chữ số có độ sáng/màu khác nhau. Trường hợp tái hiện bằng model thật gồm
1,06/1,08 bị đọc thiếu thành `06`/`08`, và 13,04 bị đọc sai thành 3,04.

- Xác định biên LED bằng kênh đỏ thay cho ngưỡng kênh xanh lá.
- Giữ RapidOCR 3.10.0 + PP-OCRv6 Small chạy offline trên CPU.
- Giữ ngưỡng tin cậy, điều kiện số ổn định và ảnh đúng khung hình đã đọc.
- Giữ các chức năng rc91, cấu hình, mã trạm, dữ liệu, ảnh và đồng bộ hiện có.

## Cập nhật máy xưởng

Đóng ứng dụng và bấm **Cập nhật Trạm Cân QR**, hoặc tải một trong hai bộ cài:

- [TramCanQR-Setup.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc92/TramCanQR-Setup.exe)
- [TramCanQR-Setup-0.2.0-rc92.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc92/TramCanQR-Setup-0.2.0-rc92.exe)
- [CAP-NHAT-BAN-MOI.cmd](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc92/CAP-NHAT-BAN-MOI.cmd)
- [SHA256SUMS.txt](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc92/SHA256SUMS.txt)

Hai bộ cài có cùng nội dung; chỉ cần tải một. Sau cập nhật, mở lại trang và
nhấn **Ctrl+F5**; phiên bản ứng dụng phải là **0.2.0-rc92**.

## Phạm vi kiểm chứng

131 test Python đạt; toàn bộ test Node có 173 đạt, 1 bỏ qua. 28 trường hợp
updater giả lập đạt. EXE đọc đúng 20/20 ảnh hồi quy; Edge với model thật đã
kiểm tra live, Space và lưu phiếu local khi cloud mất kết nối. Xem
[kiểm chứng rc92](validation-rc92.md).

Đã thêm kiểm thử giữ chữ số đỏ ít xanh lá, dấu âm/dấu thập phân và live ổn
định khi màu chữ số thay đổi. 176 mẫu được chấm từ hai video quay màn hình
đọc đúng; đây không phải đánh giá trên luồng camera gốc tại xưởng.

Chưa xác nhận đã xử lý mọi nguyên nhân trong hai video hoặc vận hành cả ca.
Đối chiếu số cân trước khi lưu, đặc biệt khi thiếu nét, đổi giá trị hoặc thay
đổi ánh sáng. Xem [phân tích OCR](OCR-STABILITY-AUDIT-2026-11-11.md).
