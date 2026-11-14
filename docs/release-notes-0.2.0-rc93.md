# Trạm Cân QR rc93 — xử lý chữ số đầu 7 đọc thành 1

rc93 kết hợp PP-OCRv6 Small với bộ phân loại chữ số LED nhỏ chạy ONNX trên
CPU. Khi OCR có chữ số đầu 1 nhưng ảnh có nét ngang trên, bộ kiểm tra đọc
lại hình dạng chữ số ở ba mức ngưỡng. Chỉ nhận 7 khi ít nhất hai mức đạt
ngưỡng 0,99, không có phân loại chắc chắn mâu thuẫn, số ô chữ số khớp và hai
lượt OCR thống nhất phần còn lại của số cân. Trường hợp còn mơ hồ bị từ chối.

Model bổ sung 830.634 byte, được huấn luyện từ ảnh bảy đoạn tổng hợp do dự án
tạo, không dùng ảnh xưởng để huấn luyện. Không cần Internet, GPU hoặc SDK AI
mới. Không lấy số từ lịch sử và không thay điều kiện live ổn định, frame token,
ảnh bằng chứng, lưu SQLite hoặc đồng bộ.

Phạm vi sửa là chữ số đầu 7 bị nhận thành 1; không khẳng định giải quyết mọi
vị trí chữ số, mọi kiểu màn hình hoặc trường hợp ảnh camera không còn đủ nét
phân biệt.

## Nhận diện live

Mở camera là ứng dụng đọc và hiển thị số liên tục, không cần bấm để gọi OCR.
Khi số đạt **ỔN ĐỊNH**, nhấn **Space** để lấy đúng số và ảnh đã đọc vào ô cân
được chọn. **Chụp ảnh / Giữ ảnh** là lựa chọn lấy thủ công khi cần; điều kiện
live, số mới và danh tính camera/ROI vẫn được kiểm tra như rc92.

## Bằng chứng trên dữ liệu hiện có

| Bộ ảnh | rc92 | rc93 |
| --- | --- | --- |
| 60 crop lấy mỗi ba frame video mới, LED 7,10 | 10 đúng; 35 sai; 15 từ chối | 51 đúng; 0 sai; 9 từ chối |
| Toàn bộ 177 frame có ô LED trong video mới | 29 đúng; 104 sai; 44 từ chối | 146 đúng; 0 sai; 31 từ chối |
| 176 crop số 1 từ hai video cũ | 176 đúng | 176 đúng |

60 crop nằm trong bộ 177, không cộng chúng thành hai tập độc lập. Video là
điện thoại quay màn hình; các frame tương quan và đã dùng để phát triển/đối
chứng. Không suy các số đếm này thành tỷ lệ đúng tại xưởng hoặc cam kết không
bao giờ nhận sai. Chưa có video camera gốc, thử USB thật hoặc vận hành cả ca.

## Lấy đúng dữ liệu khi báo lỗi

Bấm **Xuất ảnh + OCR** ở cạnh **Xem chuỗi OCR**. Trình duyệt tải một tệp JSON
chứa đúng ảnh đã gửi OCR, ROI, chuỗi nhận diện, lý do từ chối và phiên bản app.
Tệp vẫn xuất được khi không đọc ra số; thao tác này không tạo phiếu cân hoặc
gửi ảnh lên cloud. Tệp có ảnh camera, nên chỉ gửi cho người hỗ trợ dự án.

## Cài đặt và cập nhật

Đóng ứng dụng, bấm **Cập nhật Trạm Cân QR** hoặc tải một trong hai bộ cài:

- [TramCanQR-Setup.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc93/TramCanQR-Setup.exe)
- [TramCanQR-Setup-0.2.0-rc93.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc93/TramCanQR-Setup-0.2.0-rc93.exe)
- [CAP-NHAT-BAN-MOI.cmd](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc93/CAP-NHAT-BAN-MOI.cmd)
- [SHA256SUMS.txt](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc93/SHA256SUMS.txt)

Hai bộ cài có cùng nội dung; chỉ tải một. Cài đè, mở lại ứng dụng và nhấn
**Ctrl+F5** trên trang đang mở. Phiên bản phải là **0.2.0-rc93**. Dữ liệu,
ảnh, cấu hình và mã trạm được giữ nguyên. Đối chiếu cân thật khi vận hành.

Xem [kiểm chứng và giới hạn rc93](validation-rc93.md),
[nguồn gốc model](LED-GLYPH-MODEL.md) và
[điều tra 7/1](OCR-7-1-AUDIT-2026-11-14.md).
