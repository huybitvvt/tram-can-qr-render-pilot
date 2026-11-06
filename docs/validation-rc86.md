# Kiểm chứng rc86 — 29/10/2026

## Kiểm tra tự động

- **580 test Python đạt, 3 test Paddle runtime cũ deselected** (như rc85):
  `test_reads_human_verified_full_factory_702_reference`,
  `test_reads_blurred_station_01_784_with_paddleocr_v6`,
  `test_factory_1304_reference_reads_top_gross_row`. Không tính ba test này là đạt.
- **164 test Node đạt**; gồm retry, kết quả đến muộn, số/ảnh local,
  định tuyến hàng hỏng và hiển thị khối lượng thực khi không có lõi.
- 14 test backend mới: NKM/NC/RM, một ảnh không có ảnh lõi, OCR đúng một lần,
  retry không trùng, hai lượt cùng loại khác mã, token sai/khác camera/trạm/nguồn/
  frame/hết hạn bị chặn, sai loại/đơn vị bị chặn, đổi loại không ghi đè cùng ID,
  production vẫn yêu cầu đủ cặp ảnh và backend ép đúng kho.
- Chạy riêng 29 test Windows app/installer sau tăng version: đạt.
- `pip check`, kiểm tra cú pháp và `git diff --check`: đạt.

## Edge với OCR thật

Source và EXE đóng gói, Trạm 05, profile thử riêng, cloud giả lập lỗi HTTP 503:

- Chọn lần lượt NKM, NKM, NC, RM; mỗi lần một snapshot OCR **13,04 kg** và
  một bản ghi local, không tạo ảnh lõi hoặc bản nháp ảnh mới.
- Browser canvas stream từ ảnh xưởng tham chiếu; hai lượt native dùng bridge
  giả lập DirectShow và Media Foundation, giữ đúng JPEG nguồn.
- Cố ý làm mất phản hồi sau khi backend đã ghi: số trên form còn trống, loại
  bị khóa, thử lại dùng đúng payload/ảnh/ID và không tạo bản ghi thứ hai.
- Không cho đổi mục khi ảnh hàng hỏng đang chờ lưu.
- Hai lượt NKM có mã riêng, đều xuất hiện trên danh sách và chọn được để đẩy kho.
- Danh sách không báo thiếu lõi cho hàng hỏng; khối lượng thực bằng số ảnh đọc.
- Modal nhập kho tự chọn và khóa **Kho hàng hỏng**, mã SP NKM.
- Desktop và viewport 375 px hiển thị mục mới, ẩn cặp ô lõi/SP.
- Không có JavaScript page error; chặn request browser ra ngoài loopback.
- Bản ghi, ảnh, bản nháp và config thử từ rc80 giữ nguyên.

Luồng cân thường của EXE cũng được smoke riêng bằng `--snapshot --offline
--native-recovery`, Trạm 10: xem kết quả tại `.test-tmp/rc86-frozen-production/`.

## Đóng gói

- PyInstaller + Inno Setup build đạt, không cài đè app vận hành.
- Bytecode/frontend trích từ EXE khớp source, gồm module `damaged_goods` mới.
- SHA model giữ nguyên; không kèm Gemini SDK, detector mới, DB hoặc config riêng.
- Storage/session/sync/API client khớp rc80; đường ghi kho chỉ thêm bước ép kho
  từ metadata hàng hỏng, ngoài phần định dạng giờ đã có ở rc85.
- Giữ AppId, đường dẫn dữ liệu và backup marker RapidOCR.
- Hai installer tên chung/tên phiên bản có cùng SHA; dung lượng **101.076.616 byte**.

```text
1b0408a407bcef26464f791497fa5c311631998e45747771752aed444ac3730b  TramCanQR-Setup-0.2.0-rc86.exe
```

Bộ cài local: `dist/installer/TramCanQR-Setup-0.2.0-rc86.exe` và
`dist/handoff-0.2.0-rc86/`. Chưa tạo tag/Release hoặc đẩy lên GitHub.

Artifacts kiểm chứng nằm trong `.test-tmp/rc86-source-damaged-reviewed/`,
`.test-tmp/rc86-frozen-damaged/`, `.test-tmp/rc86-frozen-production/`.
Không đưa artifacts/log/ảnh xưởng lên Git hoặc Release.

## Giới hạn

Chưa nghiệm thu camera USB/ánh sáng/driver thật tại xưởng; native bridge là giả lập.
Chưa ghi DB kho thật hoặc đồng bộ với tài khoản vận hành để thử.
Kiểm tra kho dùng request giả lập; ghi local, OCR và UI là đường thật.
Ảnh chụp thủ công không chứng minh cân ổn định hoặc OCR đúng mọi chữ số.
Lease sau claim giữ giới hạn retry hiện có (90 giây), không cam kết retry vô hạn.

Đếm cuộn realtime chỉ mới nghiên cứu nguồn mở và kiến trúc; chưa cài detector,
train model, benchmark FPS hoặc đo sai số đếm trên video xưởng.
