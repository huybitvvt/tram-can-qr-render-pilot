# Trạm Cân QR 0.2.0-rc30

## Sửa lỗi

- Gemini tự thử lại lỗi máy chủ tạm thời `502/503/504` và timeout tối đa hai lần, với exponential backoff và jitter.
- Sau các lần thử lại, ứng dụng tiếp tục luồng khóa Gemini dự phòng hoặc giữ kết quả OCR local.
- Không thử lại lỗi quota `429`, vì lỗi này cần quota khả dụng hoặc khóa khác.
