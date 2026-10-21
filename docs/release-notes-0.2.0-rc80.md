Trạm Cân QR 0.2.0-rc80 — khôi phục luồng Gemini của rc74.

- Khôi phục giao diện và nhận diện bằng API Gemini như rc74; không chạy YOLO local nền.
- Dùng số phiên bản rc80 để máy rc75–rc79 nhận được bản phục hồi qua nút **Cập nhật Trạm Cân QR** hiện tại.
- Giữ nguyên config.env, danh tính trạm/camera, dữ liệu SQLite, ảnh và cấu hình Supabase/kho. Không khôi phục DB cũ đè lên dữ liệu phát sinh ở rc75–rc79.
- Đọc lại Gemini key từ cấu hình/kho key mã hóa đã dùng ở rc74. Không cần sửa config nếu key cũ và kết nối vẫn còn hoạt động.
- Trước lần khởi động đầu, tự sao lưu DB hiện tại (gồm WAL) và config tại `%LOCALAPPDATA%\TramCanQR\backups\before-gemini-rc80-*`.

Lưu xong lượt cân đang làm, bấm **Cập nhật Trạm Cân QR**, chờ ứng dụng mở lại. Nếu đang giữ tab cũ, nhấn **Ctrl+F5**. Gemini cần Internet và API key còn hiệu lực/quota.
