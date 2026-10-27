# Trạm Cân QR 0.2.0-rc85

Ngày cập nhật: 27/10/2026. Nền rc84: `b3c514dea911b4544f09bf68029e62fdf6f26f11`.

## Giữ ảnh cân thủ công

- Thêm **Chụp ảnh / Giữ ảnh** ở cụm camera. Bấm để giữ ngay khung hình và
  chạy OCR một lần trên ảnh đó, không tự điền ô cân hoặc tự lưu phiếu.
- Khi cân dao động, người vận hành kiểm tra ảnh/số, chọn ô rồi nhấn Space
  hoặc nút Chụp cân lõi/SP. Luồng này cho lấy số thủ công mà không yêu cầu
  ổn định theo thời gian; không gắn nhãn số đã ổn định.
- Số luôn gắn với đúng ảnh, trạm, camera và ô cân. Kết quả live trả muộn
  không thay được ảnh/số đang giữ. Lưu ảnh/số xuống local trước khi điền ô.
- Có **Chụp lại** và **Tiếp tục live**. Một ảnh dùng cho một ô; giữ quá
  10 phút phải chụp lại. Lỗi ghi local vẫn thử lại cùng ảnh/ID theo thời hạn
  lease hiện có. `MANUAL_SNAPSHOT=1` được giữ trong thông tin OCR.
- Dừng/đổi camera, đổi vùng hoặc chính sách thập phân hủy ảnh đang giữ.
  Đọc live bình thường vẫn yêu cầu chuỗi số ổn định như rc84.

## Phiếu đẩy kho

- Đổi tiêu đề thành **Phiếu đẩy kho từ trạm cân AI**.
- Đổi chữ ký **Người đẩy kho** thành **Công nhân SX**.
- Bổ sung **Giờ đẩy** trên danh sách tổng hợp, bản in/PDF và CSV. Dùng
  thời điểm đẩy đã lưu, hiển thị theo giờ Việt Nam; dữ liệu cũ thiếu giờ
  hiện `--`, không dùng giờ in thay cho giờ đẩy.
- Tên Công nhân SX để ký/ghi tay; bản này chưa tích hợp nguồn trưởng máy.

## Phạm vi

Giữ RapidOCR + PP-OCRv6 Small, offline/CPU, 10 định danh trạm độc lập.
Không đổi DB schema, storage/session/sync/API client hoặc đường ghi kho.
Chỉ bổ sung định dạng giờ ở phần xuất CSV của module warehouse.
Giữ AppId, đường dẫn cài/dữ liệu, cấu hình cũ và marker backup rc82.

## Tải và cập nhật

- [Bộ cài TramCanQR-Setup.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc85/TramCanQR-Setup.exe)
- [Cập nhật một lần bấm](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc85/CAP-NHAT-BAN-MOI.cmd)
- [SHA256SUMS.txt](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc85/SHA256SUMS.txt)

Máy đang dùng có thể chạy **Cập nhật Trạm Cân QR** hoặc cài đè bộ cài mới.
Hai file EXE tên chung/tên phiên bản giống nhau; chỉ cần tải một file.
Dung lượng: 101.073.937 byte. SHA-256:

```text
16a559ca799e207401be042ea412828292a9aa088a11ad400ca7ee90804ac205
```

## Kiểm chứng

566 test Python và 157 test Node đạt; 3 test runtime Paddle cũ không chạy.
EXE + Edge + model thật: giữ ảnh, lấy số, lưu local khi cloud lỗi và in PDF đạt.
Chưa nghiệm thu camera USB, driver, ánh sáng hoặc độ đúng OCR trên cả ca
sản xuất tại xưởng. Xem [biên bản kiểm chứng](https://github.com/huybitvvt/tram-can-qr-render-pilot/blob/v0.2.0-rc85/docs/validation-rc85.md).
