Trạm Cân QR 0.2.0-rc64

### Cập nhật chính
- Thêm **Key phụ Gemini** dùng chung cho ca ngày và ca đêm. Giữ hai key theo ca đang có khi nâng cấp.
- Vào **Cài đặt → Key phụ Gemini** để dán, kiểm tra và lưu key thứ ba. Key phụ phải khác hai key đang gán cho ca.
- Nút **Đổi sang key phụ** ngay trên thanh thao tác hoán đổi key phụ với key của ca đang chọn. Key cũ của ca trở thành key phụ; key gán cho ca còn lại giữ nguyên. Áp dụng cho cả 12C1 và 12C2; HC1/HC2 dùng vị trí ca ngày, HC3 dùng vị trí ca đêm.
- Hoán đổi áp dụng cho yêu cầu AI tiếp theo, không cần đợi AI rảnh và không gọi lại Google để kiểm tra key đã lưu. Yêu cầu đang chạy vẫn hoàn tất với key cũ.
- Ba vị trí key được lưu chung trong một bản ghi mã hóa trên Supabase và giữ qua khởi động lại. Bấm lặp hoặc thử lại cùng yêu cầu sau lỗi mạng không đổi ngược hai key.
- Lỗi của yêu cầu cũ đang chạy không đánh dấu nhầm key vừa đổi là hỏng.

### Cài đặt
Thoát hẳn ứng dụng rồi cài đè bản mới. Dữ liệu và `config.env` được giữ nguyên. Không cần cập nhật Edge Function. Sau khi cài, lưu key thứ ba tại **Cài đặt → Key phụ Gemini** một lần.

Các thay đổi cân lõi trống bằng 0, chọn tất cả theo bộ lọc và phiếu đủ số cuộn khi QR trùng từ rc63 vẫn được giữ.
