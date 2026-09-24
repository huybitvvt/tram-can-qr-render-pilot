Trạm Cân QR 0.2.0-rc23

- Sửa API nhận diện để đọc được số cân ở lần 4; trước đây API từ chối lần này dù giao diện cho chụp.
- Xác nhận đợt cân chỉ lấy các cuộn chưa thuộc đợt trước. Xác nhận sớm không còn bỏ qua cuộn khi tạo đợt kế tiếp.
- Không tạo đợt xác nhận trống khi chưa có cuộn mới đã đồng bộ Supabase. Có thể tiếp tục lưu phiếu cân local bình thường.
- Màn hình xác nhận hiển thị số cuộn mới ước tính và phân biệt với mốc dự kiến. Danh sách hiển thị đúng 0 cuộn ở các đợt trống cũ.
- Làm rõ SỐ LƯỢNG TRONG CA: chỉ cộng phiếu cân đã lưu, không cộng lần bấm chụp hoặc ảnh chờ AI.

Đóng ứng dụng, cài đè bản mới và nhấn Ctrl+F5 trong trình duyệt. Dữ liệu và config.env được giữ nguyên. Phần sửa xác nhận đợt cân cần triển khai lại Edge Function `ingest-measurement`; không cần migration Supabase mới.
