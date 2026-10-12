Trạm Cân QR 0.2.0-rc65

### Cập nhật chính
- **Lệnh sản xuất** và **Mã SP** đều cho gõ tay hoặc bấm nút **▾** để xổ danh sách gợi ý.
- Bấm mũi tên xem toàn bộ gợi ý đã tải; gõ trong ô để lọc. Có thể dùng mã ngoài danh sách, kể cả khi không có gợi ý từ DB.
- Chọn bằng chuột hoặc phím **↑/↓**, **Enter**. **Escape**, **Tab** hoặc bấm ra ngoài đóng danh sách.
- Danh sách tải lại không ghi đè Lệnh SX hoặc Mã SP đang nhập tay, kể cả khi DB chỉ trả về một mã sản phẩm.
- Giữ khóa thông tin ca, máy, LSX và Mã SP khi đang có ảnh chờ AI; nút xổ danh sách tuân theo cùng trạng thái khóa.

### Cài đặt
Thoát hẳn ứng dụng, cài đè bản mới rồi mở lại. Nếu đang dùng tab trình duyệt, nhấn **Ctrl+F5** để tải giao diện mới. Dữ liệu và `config.env` được giữ nguyên. Không cần cập nhật Edge Function.

Giữ các thay đổi của rc63/rc64 về cân lõi trống bằng 0, chọn theo bộ lọc, phiếu đủ số cuộn khi QR trùng và ba Gemini key luân chuyển.
