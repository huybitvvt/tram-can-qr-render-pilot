Trạm Cân QR 0.2.0-rc18

- Hai lượt có đủ bốn ảnh, mã QR và lý do lỗi có thể lưu dù AI không đọc được số cân.
- Nếu ảnh không đạt kiểm tra chất lượng, phiếu đánh dấu Có lỗi và có lý do vẫn được lưu; bản ghi có dấu PHOTO_QUALITY_OVERRIDE=1 để đối soát.
- Phiếu bình thường tiếp tục kiểm tra chất lượng ảnh trước khi lưu.

Cài đè bản cũ và mở lại trình duyệt bằng Ctrl+F5. Dữ liệu cùng config.env được giữ nguyên.
