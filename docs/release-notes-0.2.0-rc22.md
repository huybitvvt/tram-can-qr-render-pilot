Trạm Cân QR 0.2.0-rc22

- Sau khi lưu thành công từng lần cân, dọn ảnh và thông tin của đúng lần đó khỏi màn hình để cân tiếp. Lần khác chưa lưu vẫn được giữ nguyên.
- Nút lưu của lần đã lưu không còn hiện lại.
- Lưu ảnh chờ thành công cũng dọn ảnh khỏi màn hình; nếu ghi local thất bại, ảnh vẫn còn để thử lại.
- Thử lại ảnh chờ dùng cùng mã sự kiện, tránh tạo hai bản ghi nếu phản hồi mạng bị mất sau khi backend đã lưu.
- Bản ghi có trạng thái “Đang chờ” đã nằm trong DB local; dịch vụ nền tiếp tục gửi lên Supabase và Cloudinary.

Đóng ứng dụng, cài đè bản mới và nhấn Ctrl+F5 trong trình duyệt. Dữ liệu và config.env được giữ nguyên. Không cần migration Supabase mới so với rc21.
