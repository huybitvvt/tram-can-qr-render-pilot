# Trạm Cân QR 0.2.0-rc29

## Sửa lỗi

- Loại `AsyncHTTPTransport` khỏi cấu hình Gemini để tránh lỗi `cannot pickle 'SSLContext' object` khi yêu cầu fallback xử lý lỗi.
- Tắt nhận diện `aiohttp` tùy chọn của Gemini SDK trong ứng dụng, buộc SDK dùng HTTPX kể cả khi môi trường có module `aiohttp` không đầy đủ.
- Áp dụng cùng cấu hình cho đọc cân Gemini và kiểm tra API key.
