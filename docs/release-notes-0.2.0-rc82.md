# Trạm Cân QR rc82 — OCR local và Space lấy số live

**Thay phần đọc cân Gemini của rc80 bằng RapidOCR + PP-OCRv6 Small đã thử tại xưởng.**
Model đi kèm bộ cài, chạy CPU/offline, không cần Python, GPU hay key để đọc cân.

## Dùng trên máy đang có rc80

Hoàn tất lượt cân đang làm → bấm **Cập nhật Trạm Cân QR** hoặc tải
[CAP-NHAT-BAN-MOI.cmd](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc82/CAP-NHAT-BAN-MOI.cmd).
Updater tải và xác minh SHA-256 trước khi đóng/cài đè/mở lại ứng dụng.
Nếu trình duyệt còn hiện bản cũ, nhấn **Ctrl+F5**.

Cài mới hoặc cài đè thủ công:
[TramCanQR-Setup.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-rc82/TramCanQR-Setup.exe).
Hai file EXE có tên chung và có số phiên bản là cùng một bộ cài; chỉ cần một file.

## Lấy số cân

- Giữ camera USB theo số thứ tự, DirectShow/Media Foundation, Mở/Dừng; có thêm
  lựa chọn Trình duyệt để tiếp tục dùng danh sách camera/nguồn ảo của rc80.
- Giữ **Chọn vùng số cân** bằng chuột, **Tự tìm LED đỏ**, **Cân luôn có 2 số thập phân**,
  mở ảnh thử và xem chuỗi OCR. Vùng LED bằng tay được nhớ theo nguồn camera.
- Camera đọc liên tục. Sau ba lần cùng số, giao diện hiện **ỔN ĐỊNH**.
- Chọn ô cân lõi/SP/cuộn cần lấy → **Space** điền ngay số đang đọc và giữ đúng
  ảnh của lần đọc. Không chụp lại rồi chạy OCR cho thao tác Space.
- Camera/vùng/cách đọc thay đổi, số chưa ổn định hoặc kết quả cũ sẽ chờ số mới.
- Xem live và mở ảnh thử không tự ghi phiếu. Space/nút lấy số lưu ảnh tạm;
  Lưu/Enter xác nhận phiếu theo luồng hiện có.

## Chức năng và dữ liệu rc80

Giữ QR, phiếu nhiều cuộn, cặp lõi–sản phẩm, trạng thái/lý do lỗi, ghi chú, kiểm kho,
danh sách/sửa/đọc lại, lọc bản ghi, đồng bộ Supabase, đẩy kho, chống trùng và bản nháp.
Đọc lại số cân sử dụng OCR local. Model không tạo số 0 khi live chưa đọc được.

Giữ AppId, EXE, thư mục cài, kênh cập nhật và dữ liệu ở `%LOCALAPPDATA%\TramCanQR`.
Config cũ không bị viết đè; rc82 tự chọn OCR local dù config còn ghi Gemini/YOLO.
Lần đầu tạo bản sao DB hiện tại (gồm WAL), config và metadata phiên chờ ở
`backups\before-rapidocr-rc82-*`. Ảnh giữ nguyên đường dẫn; không phục hồi DB cũ
ghi đè các lượt cân mới. Storage/schema, phiên cân, sync và module kho giữ rc80.

Giao diện vẫn ở `http://127.0.0.1:8080` trên máy khách. Nhận diện không cần mạng;
đồng bộ cloud và tải cập nhật cần mạng. Bộ cài không kèm Gemini SDK.
Không thay đổi/triển khai lại các dịch vụ Render hay schema cloud hiện hữu.

## Phạm vi kiểm chứng

- Kiểm thử hồi quy các luồng lưu, phiên, QR, kho, đồng bộ và nâng cấp.
- Edge + model thật: live 6,86; Space dùng lại kết quả với ảnh đúng khung hình;
  thao tác vùng LED/thập phân; không có lỗi JavaScript.
- Preview không tạo thêm bản ghi/ảnh nháp. Config, bản ghi, ảnh và bản nháp cũ
  giữ nguyên; có thể lưu phiếu mới bên cạnh dữ liệu đó.
- Updater rc74/rc79/rc80 chọn rc82; checksum giả bị chặn trước khi đóng ứng dụng.
- Model/ngưỡng đọc theo trial1; thời gian ổn định chỉ là kiểm tra các khung hình
  đồng ý với nhau. Model vẫn có thể nhầm chữ số; đối chiếu trước khi lưu phiếu.
- Camera USB thực tế của mỗi xưởng cần kiểm tra sau cập nhật. Bản trial1 được
  người vận hành xác nhận tại xưởng; bản tích hợp rc82 được thử trên máy phát triển.

[Hướng dẫn đầy đủ](https://github.com/huybitvvt/tram-can-qr-render-pilot/blob/main/packaging/HUONG-DAN-KHACH-HANG.md).
