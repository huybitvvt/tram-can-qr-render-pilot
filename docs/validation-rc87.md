# Kiểm chứng rc87 — 29/10/2026

## Kiểm tra tự động

- 607 test Python đạt; 3 test Paddle runtime cũ deselected như rc85/rc86,
  không tính là đạt: `test_reads_human_verified_full_factory_702_reference`,
  `test_reads_blurred_station_01_784_with_paddleocr_v6`,
  `test_factory_1304_reference_reads_top_gross_row`.
- 170 test Node đạt. Có 27 test backend mới và 6 test giao diện mới cho bộ đếm.
- ByteTrack + Supervision LineZone thật được kiểm tra bốn hướng, sai hướng,
  đứng yên, rung sát vạch, đi lui rồi đi ra, hai vật song song, gián đoạn nguồn,
  và cấu hình sai. Đi lui không trừ tổng; cùng ID chỉ đếm một lần trong lượt.
- Retry frame giữ nguyên ảnh/thời gian/số thứ tự; request sai nguồn/trạm/camera,
  đến muộn hoặc đổi ảnh bị chặn. Lỗi ghi đĩa giữ kết quả để retry, không chạy lại
  tracker và không báo số mới trước khi ghi local. Timeout nhận diện dừng worker.
- Kiểm tra tải lại lịch sử từ sự kiện đã ghi khi summary chưa cập nhật.
- Có 1.416 cảnh báo DeprecationWarning từ phép cross-product hai chiều trong
  Supervision 0.23.0 với NumPy 2.4.6. Test vẫn đạt; không báo các cảnh báo là lỗi
  đã sửa. Bản triển khai ghim các phiên bản này.
- `pip check`, cú pháp Python/JavaScript và `git diff --check` đạt.

## Thử trên Edge bằng model thật

Profile thử riêng; chặn request browser ra ngoài loopback; cloud giả lập HTTP 503.
Không sửa profile/config/DB vận hành trên máy phát triển.

RF-DETR Nano ONNX thật, CPU Intel i3-1215U, hai thread inference, ảnh thu nhỏ
tối đa 768 px trước khi gửi. Bộ detector nhận input RGB 384×384, chuẩn hóa
ImageNet, sigmoid logits; không coi nhãn COCO là nhãn cuộn đã được huấn luyện.

| Ảnh tham chiếu | Số vùng vật thể trả về (ngưỡng 0,15) | Số qua vạch | Thời gian source |
| --- | --- | --- | --- |
| factory_scale_13_04_reference.jpg | 2 | 0 | 406,0 ms |
| factory_scale_7_02_full_reference.jpg | 2 | 0 | 274,4 ms |
| factory_scale_diagnostic_station-01.jpg | 2 | 0 | 381,2 ms |

Đây là số vùng vật thể, không phải số cuộn đúng: có vùng bắt vào cân/đồ vật,
model chưa nhận ổn định đúng cuộn trên cả ba ảnh. Không suy độ đúng từ số box.
Ảnh tĩnh không tạo sự kiện đếm hoặc bản ghi cân.

Video WebM tổng hợp từ ảnh cuộn tham chiếu, nền cố định, một vật di chuyển qua
vạch trái → phải, có đoạn trống cho học nền:

- Chế độ chuyển động + ByteTrack + LineZone trả **1**, đúng số đặt trước.
- Tạm dừng không tăng tiến trình video; tiếp tục không lặp sự kiện.
- Dừng ở cuối video, không tua vòng. Lịch sử, JSON local, ảnh nhỏ và CSV có một sự kiện.
- Bridge camera native mô phỏng cảnh đứng yên qua hơn 12 frame: số đếm 0.
- Không tạo phiếu cân/bản nháp ảnh mới; bản ghi, ảnh, bản nháp và config thử cũ giữ nguyên.
- Giao diện desktop và 375 px được chụp kiểm tra, không có JavaScript page error.
- Kết thúc đếm rồi quay về Phiếu cân hiển thị lại đúng giao diện cân.

Artifacts source trong `.test-tmp/rc87-counter-source-final/`.

## EXE đóng gói và nâng cấp

- PyInstaller + Inno Setup build đạt. Không cài đè ứng dụng đang vận hành để thử.
- EXE chạy với profile riêng tại `.test-tmp/rc87-counter-frozen/`: ba ảnh thật
  vẫn trả hai vùng vật thể/ảnh và số qua vạch 0; thời gian lần lượt 357,3 / 269,6 /
  281,3 ms. Không diễn giải số box thành số cuộn đúng.
- EXE xử lý video tổng hợp biết trước một vật: kết quả 1, tạm dừng/tiếp tục và
  CSV đạt. Native bridge mô phỏng đứng yên cho kết quả 0. Không có JavaScript error.
- EXE Trạm 05 cân hàng hỏng NKM/NKM/NC/RM đều đọc 13,04 kg, không có ảnh lõi,
  thử lại sau mất xác nhận không trùng, modal kho ép đúng Kho hàng hỏng.
  EXE Trạm 10 cân thường với snapshot/offline và phục hồi native mô phỏng đạt;
  bản in/PDF giữ đúng tên phiếu, Công nhân SX và giờ Việt Nam.
- Bytecode/frontend trong EXE khớp source, gồm module và file giao diện bộ đếm.
  SHA model OCR cân giữ nguyên; SHA model RF-DETR khớp manifest. Có giấy phép
  Apache-2.0/MIT và nguồn model. Không kèm DB/config riêng, Gemini SDK hoặc Torch.
- Storage/session/sync/API client khớp rc80; thay đổi ghi kho chỉ là bước định
  tuyến hàng hỏng đã có từ rc86, ngoài phần xuất giờ CSV từ rc85.
- 18 trường hợp updater đạt: rc74/79/80/82/83/84/85/86/current chọn rc87,
  xác minh checksum rồi mới đóng/cài/mở app. Checksum sai bị chặn trước đóng app;
  DB/config/ảnh giả lập giữ nguyên.
- Hai EXE cài đặt giống nhau; dung lượng **224.264.048 byte/file**.

```text
1ec5303ab01b883e451fcb30987eb691f4b6238e1a80f3ed9acad5fd3376aa84  TramCanQR-Setup-0.2.0-rc87.exe
```

Handoff local: `dist/handoff-0.2.0-rc87/`.
Model RF-DETR ONNX không đưa vào Git; có sẵn trong bộ cài, không tải tại startup.
Artifacts/log/ảnh thử trong `.test-tmp/`, không đưa lên Git hoặc Release.

## Giới hạn nghiệm thu

Chưa có video sản xuất thật, chưa test camera USB/ánh sáng/driver thật tại xưởng.
Chưa đo số thiếu/trùng trong cả ca. Video biết số lượng là video tổng hợp;
native camera dùng bridge giả lập. Chế độ chuyển động có thể đếm người/vật khác
trong ROI, cần camera cố định và vùng ra máy riêng.

RF-DETR COCO chưa fine-tune cho cuộn. Chỉ phát hành tính năng đếm dưới nhãn
**thử nghiệm**; mặc định chuyển động để thử với camera cố định. Không tự tạo
phiếu cân, chốt kho, hoặc dùng số đếm thay kiểm tra của người vận hành.
Đoạn mất hình/tạm dừng không được tự bù. Đổi ID sau che khuất kéo dài vẫn có thể
gây sai; không cam kết chống trùng cho mọi lần đổi ID hoặc người đẩy cuộn quay lại.

Không triển khai lại cloud Render; cấu hình repo tắt tự động deploy.
