# 0.2.0-rc86 — Cân hàng lỗi hỏng

- Thêm mục **Cân hàng lỗi hỏng**, chọn **NKM / NC / RM** tại ô mã QR/loại hàng.
- Bấm **Chụp và lưu hàng hỏng** để giữ một frame, OCR một lần và lưu local.
  Không chụp lõi; không trừ lõi hoặc bì. Chưa đọc được số thì chưa lưu phiếu.
- Mỗi lượt có ID/mã riêng; cân nhiều lượt cùng loại không bị gộp khi nhập kho.
- Lỗi nhận phản hồi giữ ảnh, loại hàng, nguồn và ID để thử lại.
  Chỉ hiện số đã lưu sau xác nhận local khớp. Ảnh thủ công không giả lập ổn định cân.
- Đẩy Supabase/nhập kho theo luồng hiện có. Giao diện và backend ép hàng hỏng vào
  **Kho hàng hỏng**; chặn trộn hàng hỏng với thành phẩm trong cùng lượt đẩy.
- Danh sách hiển thị loại hàng hỏng, một ảnh bằng chứng và khối lượng thực;
  không coi thiếu ảnh lõi là lỗi OCR.

Không đổi DB schema, module storage/session/sync/API client, engine hoặc model OCR.
Giữ AppId, dữ liệu/config vận hành và backup marker khi nâng cấp.
Không triển khai cloud hoặc ghi đè Release rc85.

Đếm cuộn realtime mới tra cứu và ghi đề xuất tại
[research-roll-counting-2026-10-29.md](research-roll-counting-2026-10-29.md).
Chưa thêm detector, train model hoặc nghiệm thu đếm trên video xưởng.
