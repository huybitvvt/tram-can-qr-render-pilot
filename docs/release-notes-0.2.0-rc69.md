Trạm Cân QR 0.2.0-rc69

### Cập nhật chính
- Ô **Mã SP** ở phần nguồn cân hiện cả mã và tên sản phẩm: mỗi gợi ý có mã kèm tên bên dưới, gõ một phần tên cũng lọc ra đúng mã.
- Sau khi chọn, ô vẫn chỉ giữ mã SP (dùng để đối chiếu QR); tên sản phẩm hiện ngay dưới ô.
- Tên SP lấy từ bảng LSX gốc khi có cấu hình, nếu không thì lấy tên mới nhất của mã đó trong bảng `nhap_kho` của DB kho. Tên được nhớ 10 phút; mất mạng thì vẫn hiện mã như cũ.
- Bộ lọc bảng **Danh sách lần cân** (Ngày, Ca, Máy, Mã SP, Supabase, Đẩy kho, Lọc) gọn trên một hàng; màn hình hẹp tự xuống hàng.

### Cài đặt
Thoát hẳn ứng dụng, cài đè bản mới rồi mở lại. Nếu dùng tab trình duyệt, nhấn **Ctrl+F5** để tải giao diện mới. Giữ dữ liệu, cấu hình và các key đã lưu.

Giữ các cập nhật rc68: tách **Dùng key** và **Đổi key** cho key phụ Gemini.
