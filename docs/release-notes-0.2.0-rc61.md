Trạm Cân QR 0.2.0-rc61

### Cập nhật chính
- Tự đẩy các dòng **Chờ đồng bộ** lên Supabase mỗi 10 phút, chỉ bắt đầu gửi khi AI rảnh và hàng đợi AI trống. Không cần mở tab Danh sách hoặc bấm nút đồng bộ.
- Khi AI bắt đầu chạy giữa đợt, gửi xong phiếu đang gửi rồi tạm dừng. Tiếp tục các dòng còn chờ khi AI rảnh, kể cả sau khi AI báo lỗi.
- Kiểm tra lại trạng thái từng dòng trước khi gửi, tránh gửi lại dòng đã được đồng bộ thủ công. Giữ quy tắc không gửi phiếu có lỗi cân/QR. Các dòng đã đồng bộ, lỗi đồng bộ và chỉ lưu local không được chọn tự động.
- Gửi dữ liệu Supabase, không đẩy ảnh lên Cloudinary. Ảnh nháp chưa thành phiếu cân vẫn giữ trên máy. Không tự nhập kho hay đổi trạng thái nhập kho.
- Giữ nút đồng bộ thủ công để xử lý ngay hoặc thử lại các dòng lỗi mạng. Dữ liệu và ảnh vẫn giữ local nếu gửi thất bại.
- Thử lại tối đa 3 lần lỗi DNS khi đọc/lưu key Gemini đã mã hóa. Báo đúng tên miền đang lỗi, nhận URL dán dạng Markdown hoặc có dấu nháy. Không đổi key đang dùng nếu lưu thất bại.

### Cài đặt
Đóng ứng dụng, cài đè bản mới rồi mở lại. Giữ nguyên dữ liệu và `config.env`; không cần cập nhật Edge Function.

Tự đồng bộ mặc định bật khi có URL Supabase và token thiết bị. Đợt đầu đến hạn sau 10 phút kể từ khi mở ứng dụng. Nếu muốn tắt, thêm `ROLL_SCALE_AUTO_SYNC=0` vào `config.env` rồi khởi động lại. Với mã nguồn có thể dùng `--no-auto-sync`.

Mất mạng/DNS thật sự vẫn cần khôi phục kết nối. Thử lại DNS không thay thế việc sửa cấu hình hoặc đường truyền.
