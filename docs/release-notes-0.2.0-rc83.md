# Trạm Cân QR rc83 — lấy số và lưu local khi mất mạng

rc83 tiếp tục dùng RapidOCR 3.10.0 + PP-OCRv6 Small ONNX trên CPU. Giữ nguyên
model của rc82, tên ứng dụng, AppId, đường dẫn dữ liệu và cấu hình hiện có.

- Sửa lỗi không đạt ổn định khi OCR đọc nhanh: đo thời gian của cả chuỗi số
  không đổi, thay vì chỉ ba mẫu cuối. Vẫn yêu cầu ít nhất ba mẫu và 0,45 giây;
  số đổi, đọc hụt, đổi nguồn/vùng LED hoặc kết quả cũ phải kiểm tra lại.
- Space lưu đúng ảnh đã OCR và số cân qua một request local; chỉ xác nhận
  thành công sau khi ảnh và giá trị đã ghi trên máy. Tự chọn ô còn thiếu kế tiếp.
- Đọc QR chạy sau, không giữ bước lấy số. Giữ khả năng quét/nhập mã thủ công.
- Kiểm tra QR trước lưu phiếu dùng DB local, không chờ truy vấn Supabase.
  Kiểm tra này không thay thế đối soát QR trên những máy chưa đồng bộ.
- Thêm thời hạn chờ cho đọc live, lấy ảnh camera và thao tác local; khi lỗi
  giữ ảnh/ID để thử lại. Danh sách tải lại ở nền sau khi lưu phiếu.
- Camera native mất hình tự thử mở lại đúng camera tối đa hai lần, không tự
  đổi camera hay driver. Dừng/đổi nguồn sẽ hủy lượt mở lại đang chờ.

Supabase tiếp tục là bước đồng bộ sau; mất mạng không được coi là lỗi lưu local.
Không đổi DB schema hoặc source storage/session/sync/warehouse của rc80.

## Tải và cài

- Máy đang có ứng dụng: chạy **CAP-NHAT-BAN-MOI.cmd**.
- Cài mới/cài đè: tải **TramCanQR-Setup.exe** hoặc
  **TramCanQR-Setup-0.2.0-rc83.exe**; chỉ cần một file EXE.
- Lưu lượt đang làm, đóng app thử đang dùng cùng camera trước khi cập nhật.
- Nếu trình duyệt giữ giao diện cũ, nhấn **Ctrl+F5**.

Kiểm chứng chi tiết: `docs/validation-rc83.md`. Đã thử bằng model thật, Edge và
profile riêng; camera USB/ánh sáng thực tế tại xưởng vẫn cần người vận hành kiểm tra.
