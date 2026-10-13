Trạm Cân QR 0.2.0-rc67

### Cập nhật chính
- Thanh **Số lượng trong ca** lấy theo ngày, ca, máy, LSX và Mã SP đang chọn ở khu vực cân phía trên. Bộ lọc danh sách phía dưới không đổi số đếm này.
- Số đếm cập nhật sau khi lưu phiếu local, không cần chờ Supabase; tự đọc lại mỗi 2 giây khi đang mở tab Phiếu cân. Khi đổi nguồn cân hoặc quay lại tab, lấy lại số mới. Kết quả cũ trả về chậm không ghi đè số của nguồn mới.
- Chỉ đếm phiếu đã bấm **Lưu**. Ảnh mới chụp, ảnh chờ AI và ảnh AI lỗi chưa lưu phiếu không tăng số cuộn. Khi tải số đếm lỗi, giữ số gần nhất và báo chưa cập nhật, không chuyển thành 0.
- Bỏ bảng **Ảnh tạm chưa lưu phiếu**. Ảnh chưa bấm Lưu giữ trong ô cân phía trên, kể cả khi AI đọc lỗi. Danh sách lần cân và tab Danh sách chỉ hiện phiếu đã lưu.
- Mỗi cuộn phải có đủ **ảnh lõi và ảnh SP** mới được lưu phiếu, kể cả khi AI lỗi. Chặn thiếu ảnh ở giao diện và API; không tạo phiếu từ ảnh đơn. Cuộn nào đủ hai ảnh được lưu riêng, không cần hoàn tất cả bốn cuộn.
- Giữ sao lưu ảnh ngầm trên máy. Khi AI lỗi, thông báo rõ ảnh vẫn ở ô cân để đọc lại hoặc nhập tay rồi bấm Lưu phiếu; không hướng nhân viên tìm ảnh tạm ở bảng dưới.

### Cài đặt
Thoát hẳn ứng dụng, cài đè bản mới rồi mở lại. Nếu dùng tab trình duyệt, nhấn **Ctrl+F5** để tải giao diện mới. Dữ liệu và `config.env` được giữ nguyên. Không cần cập nhật Edge Function.

Giữ các thay đổi trước đó về lõi trống bằng 0, chọn theo bộ lọc, phiếu đủ số cuộn khi QR trùng, ba Gemini key luân chuyển, ô LSX/Mã SP vừa gõ tay vừa xổ danh sách và tự đồng bộ 10 phút khi AI rảnh.
