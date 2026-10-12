Trạm Cân QR 0.2.0-rc63

### Cập nhật chính
- Ảnh cân lõi có màn hình trống được tính bằng 0 khi AI xác nhận không có chữ số. Áp dụng cho mọi lần cân và đọc lại ảnh lõi. Lỗi mạng, ảnh mờ hoặc khuất vẫn báo không đọc được; cân sản phẩm vẫn cần số cân.
- **Chọn tất cả theo bộ lọc** lấy toàn bộ dòng hợp lệ khớp ngày, ca, máy, LSX, mã SP và trạng thái đang lọc, kể cả ngoài 50 dòng đang hiển thị. Không cần đổi bộ lọc Đẩy kho để chọn dòng. Có thể chọn dòng đã đẩy kho cho thao tác Supabase; Nhập kho chỉ lấy dòng còn chờ.
- Phiếu và tổng hợp CSV/JSON tính đủ số cuộn đã chọn, gồm cả mã QR trùng. Mã trùng không ghi thêm dòng vào bảng `nhap_kho`; vẫn lập phiếu và xác nhận xử lý khi cả phiếu đều trùng.
- Thử lại sau lỗi cập nhật trạng thái cân AI dùng lại phiếu đã lập, không tạo thêm phiếu hoặc dòng kho trùng.

### Cài đặt
Thoát hẳn ứng dụng rồi cài đè bản mới. Dữ liệu và `config.env` được giữ nguyên. Không cần cập nhật Edge Function.
