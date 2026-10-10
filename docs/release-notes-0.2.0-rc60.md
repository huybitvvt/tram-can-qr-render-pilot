Trạm Cân QR 0.2.0-rc60

### Cập nhật chính
- Khi chụp cân, ghi ảnh xuống máy trước rồi gửi yêu cầu AI ở nền. Ô đã chụp hiện **Ảnh đã lưu · chờ AI**; có thể chụp ô tiếp theo ngay sau khi lưu ảnh, không cần chờ AI trả số cân.
- Tự chọn ô còn thiếu tiếp theo. Mỗi ô giữ yêu cầu AI riêng; kết quả về muộn hoặc khác thứ tự không điền vào ảnh khác. Không cho lưu phiếu hoặc chụp đè ô còn đang chờ AI.
- Giữ ảnh độc lập nếu AI lỗi hoặc không đọc được số. Nếu ghi ảnh local thất bại, giữ ảnh trên màn hình và báo lỗi trước khi gọi AI.
- Thử lại tối đa 3 lần khi không phân giải được DNS Supabase, giữ nguyên mã phiếu trong các lần thử. Lỗi cuối hiển thị tên miền cần kiểm tra; dữ liệu chưa đồng bộ vẫn nằm trên máy.
- Nhận URL Supabase dán dạng chữ thường, có dấu nháy hoặc liên kết Markdown; báo rõ khi URL không hợp lệ.
- Bao gồm sửa đổi key Gemini của rc59.

### Cài đặt
Đóng ứng dụng, cài đè bản mới rồi mở lại. Dữ liệu và `config.env` được giữ nguyên. Không cần cập nhật Edge Function.

Ảnh và AI chạy độc lập; AI vẫn xử lý theo hàng đợi. Ngày, ca, máy, LSX và Mã SP tạm khoá khi còn ô chờ AI để giữ đúng thông tin của ảnh đang xử lý.

Nếu mạng vẫn lỗi DNS sau 3 lần thử, kiểm tra tên miền được báo và URL trong `config.env`, rồi bấm **Đồng bộ theo bộ lọc** lại khi mạng ổn định.
