Trạm Cân QR 0.2.0-rc21

- Nút lưu của từng lần cân chỉ ghi lần đó; phím Enter cũng chỉ ghi lần đang chọn.
- Nếu chỉ có một ảnh hoặc AI không đọc được số, có thể lưu ảnh chờ riêng; ảnh còn lại được phép trống. Ảnh chờ được giữ trên máy và tự đồng bộ cloud.
- Giữ ảnh, QR và lý do lỗi của lần cân chưa lưu.
- Sau khi lưu hết dữ liệu trong phiếu, màn hình sẵn sàng cho cuộn tiếp theo.
- Cho xác nhận đợt cân khi số cuộn hiện có chưa đủ mốc.
- Giữ các kiểm tra dữ liệu của bảng ca_can khi nới điều kiện xác nhận.

Cài đè bản cũ và mở lại trình duyệt bằng Ctrl+F5. Dữ liệu cùng config.env được giữ nguyên.
Chức năng xác nhận đợt cân mới cần áp dụng migration Supabase đến 20260924020000_restore_weigh_batch_checks.sql và triển khai lại Edge Function ingest-measurement; bộ cài Windows không tự triển khai phần cloud.
