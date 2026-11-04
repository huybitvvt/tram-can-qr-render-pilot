# 0.2.0-rc88 — Cải thiện OCR nhầm số đầu 7 thành 2

## Cập nhật máy xưởng

Đóng ứng dụng, bấm **Cập nhật Trạm Cân QR**, rồi mở lại trang cân và nhấn
**Ctrl+F5**. Hoặc tải một trong hai bộ cài sau và cài đè:

- [TramCanQR-Setup.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc88/TramCanQR-Setup.exe)
- [TramCanQR-Setup-0.2.0-rc88.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc88/TramCanQR-Setup-0.2.0-rc88.exe)
- [CAP-NHAT-BAN-MOI.cmd](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc88/CAP-NHAT-BAN-MOI.cmd)
- [SHA256SUMS.txt](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc88/SHA256SUMS.txt)

Hai EXE giống nhau; chỉ cần tải một. Cài đè giữ dữ liệu, ảnh, cấu hình và mã trạm.
Sau cập nhật, phiên bản ứng dụng phải là **0.2.0-rc88**.

## Thay đổi OCR

- Cắt bớt nền tối quanh dãy LED, giữ viền và nét số từ ảnh camera.
- Dùng ảnh màu đã cắt và ảnh xám thông thường thay cho tăng tương phản CLAHE
  trên kênh xanh lá, nhằm giảm lỗi `708` bị nhận thành `208`.
- Vẫn dùng model PP-OCRv6 Small, hai lượt nhận diện mỗi vùng LED.
- Không tự đổi chữ số, không giữ số cũ khi mất hình, không hạ ngưỡng tin cậy
  hay nới điều kiện xác nhận cân ổn định.

## Kết quả và giới hạn

Trên 31 mẫu từ video quay màn hình do người dùng cung cấp:

| Kết quả | rc87 | rc88 |
| --- | ---: | ---: |
| Đọc đúng 7.08 | 13 | 27 |
| Không chấp nhận kết quả | 14 | 4 |
| Đọc sai thành 2.08 | 4 | 0 |

96 ảnh số tổng hợp có nhiều số đầu `2` và `7` đều đọc đúng. Ảnh tham chiếu
13.04 vẫn đọc đúng với tìm LED tự động. Ảnh 7.02 cũ trước đây đọc nhầm 2.02
nay bị từ chối; chưa đọc đúng được ảnh đó.

112 kiểm tra OCR/live/cân hàng hỏng/bộ cài đã pass trên Python 3.12. Luồng cập
nhật mô phỏng từ rc87 lên rc88 giữ DB/config/ảnh và chặn tải về sai checksum.

Đây là kiểm tra từ một video quay lại màn hình và ảnh tổng hợp, chưa chứng minh
độ chính xác trên luồng camera gốc hoặc vận hành 24/24. Vẫn phải đối chiếu số
trên cân trước khi lưu. Xem [phân tích kỹ thuật](RC87-LEADING-7-OCR.md).

Giữ các chức năng rc87, bao gồm cân hàng hỏng và đếm cuộn thử. Không thay đổi
schema SQLite, cấu hình đồng bộ, nhận diện trạm hoặc triển khai lại cloud.
