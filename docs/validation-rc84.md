# Kiểm chứng rc84 — 24/10/2026

Nền rc83: `a50a0e67020df3dcbb3f55f7d0aa9a4a92f48741`.
Branch `release/rc84-ten-stations` tại `E:\tram-can-qr-rc82`.

- Bộ cài mở rộng danh sách từ Trạm 01–04 lên 01–10. Số trạm 10 không bị thêm
  số 0 ở đầu thành 010; mỗi máy vẫn có `ROLL_SCALE_STATION_COUNT=1`.
- 31 test installer/runtime/định danh đạt, gồm khởi tạo đủ 10 profile qua chính
  parser runtime và xác nhận trạm/camera trong service.
- Logic giữ cấu hình cũ, AppId, thư mục cài và đường dẫn dữ liệu không đổi.
- OCR, frontend, storage, session, sync và warehouse không đổi so với rc83.

- Kiểm tra bằng Inno Setup thật với cùng mã Pascal của trang chọn trạm, trong
  harness không cài đặt: danh sách có 10 mục, chọn mục cuối trả suffix `10`.
  Ở DPI của máy thử, vùng danh sách cao 434 px, mỗi mục 38 px: đủ hiện 10 mục.
  Harness chạy silent, dừng chủ động trước cài đặt; không ghi cấu hình vận hành.
- Build EXE và installer thành công. Trích xuất bytecode/frontend đối chiếu source
  khớp; checksum model không đổi, không kèm DB/cấu hình riêng.
- EXE thật + Edge + model thật với profile Trạm 10: `/api/status` trả đúng
  `gateway-10`, `station-10`, `camera-10`. Đọc 6,86 kg, Space lấy số/lưu local,
  chọn ô tiếp theo và lưu phiếu qua giao diện khi cloud mô phỏng trả lỗi đều đạt.
  Không lỗi JavaScript; dữ liệu/config/ảnh/bản nháp cũ trong profile thử giữ nguyên.
- Hai file EXE tên chung và tên có phiên bản giống nhau: 101.051.330 byte/file.
- Updater rc74/rc79/rc80/rc82/rc83/current chọn rc84; checksum sai bị chặn trước
  khi đóng app. DB/config/ảnh trong harness giữ nguyên.

```text
SHA-256: e242bbbecc22ac1d53ec600ef8b2cd286bd2b6604df2b35f653990cd1d642bb2
```

Chỉ dùng profile kiểm thử trong `.test-tmp/`; không đọc `.env` hoặc dùng
DB/config vận hành. Việc hỗ trợ 10 máy là 10 định danh độc lập, không phải
10 camera trong một tiến trình ứng dụng.
