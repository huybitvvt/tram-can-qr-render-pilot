# Trạm Cân QR 0.2.0-rc25

- Có thể chọn **Antigravity · Google** trong menu AI, đăng nhập bằng tài khoản Google trên máy local và dùng CLI `agy` để đọc ảnh cân.
- Ưu tiên **Gemini 3.5 Flash Low**. Ứng dụng kiểm tra `agy models` trước khi đọc; nếu tài khoản không có 3.5, tự dùng 3.6/3.7/3.8 Flash Low khả dụng và hiện model thực tế. Một model khác được cấu hình thủ công mà không có trên tài khoản sẽ báo lỗi rõ ràng.
- Bộ cài có tác vụ tùy chọn **Cài Antigravity CLI**. Người dùng có thể chạy lại trình cài CLI từ menu Start; tài khoản Google cần đăng nhập trên chính máy đó.
- Giữ luồng lưu phiếu cân chính thức khi có ít nhất một ảnh, kể cả AI hoặc QR chưa đọc được. Phiếu và ảnh được ghi local trước rồi đồng bộ cloud trong nền.

Antigravity CLI cần Internet và quyền dùng model trên tài khoản Google của máy khách. Installer giữ nguyên dữ liệu và `config.env` khi cài đè.
