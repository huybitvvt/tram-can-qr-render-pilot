# Kiểm chứng rc93 — 14/11/2026

## Phương án chọn và phạm vi

Giữ PP-OCRv6 Small, thêm bộ phân loại LED riêng cùng kiểm tra hình học và
đồng thuận ở nhiều mức ngưỡng. Đây là phương án triển khai có kết quả tốt
nhất trong các cấu hình đã thử ở dự án, không phải tuyên bố tốt nhất cho mọi
camera hoặc mọi model trên thị trường.

Các đối chứng đã thử:

- Small/Medium hiện có: đều nhận sai 7,10 thành 1,10 trên clip mới.
- PP-OCRv4/v5 English và PP-OCRv6 Tiny: vẫn nhận sai nhiều mẫu 7 → 1.
- CRNN LCD pretrained của OICWS: không có chuỗi nào hợp lệ theo chế độ cân
  hai số thập phân trên 60 crop mới và 176 crop cũ; miền dữ liệu khác.
- SVTR chuyên bảy đoạn từ Tinnci/anshin cải thiện clip 7,10, nhưng có lỗi
  chữ số khác và repository chưa công bố license. Chỉ dùng đối chứng cục bộ,
  không đưa mã/trọng số của nguồn này vào bộ cài.
- Model CTC tự huấn luyện nhanh từ dữ liệu tổng hợp chưa hội tụ đủ và bị loại.
- Bộ phân loại glyph nhỏ tự huấn luyện có thể xác minh 7 với kiểm tra nét
  ngang trên, trong khi giữ kết quả số 1 trên bộ ảnh cũ. Đã chọn hướng này.

Model hiện tại chỉ xử lý chữ số **đầu** 7 bị nhầm thành 1. Không tự đổi
`110 → 710` bằng quy tắc chữ; cần bằng chứng ảnh, hai phiếu classifier đủ
ngưỡng và hai lượt OCR xác định cùng phần số còn lại. Dấu vết kết quả cũ/mới
được giữ trong observations. Xem [model card](LED-GLYPH-MODEL.md).

Nguồn tham khảo:
[RapidOCR](https://github.com/RapidAI/RapidOCR),
[SVTR đối chứng](https://github.com/Tinnci/anshin/tree/826522b57ff4a11ae42c54d49ca821ba4eeb1d33/seven_segment_ocr),
[CRNN LCD đối chứng](https://github.com/OICWS/lcd-digit-recognition),
[SSOCR](https://www.unix-ag.uni-kl.de/~auerswal/ssocr/).

## Ảnh hồi quy với model thật

| Dữ liệu | rc92: đúng / sai / từ chối | rc93: đúng / sai / từ chối |
| --- | --- | --- |
| 60 crop, mỗi ba frame clip mới | 10 / 35 / 15 | 51 / 0 / 9 |
| 177 frame có preview LED của clip mới | 29 / 104 / 44 | 146 / 0 / 31 |
| 176 crop 1,06 / 1,08 từ hai clip cũ | 176 / 0 / 0 | 176 / 0 / 0 |

Đã xem contact sheet của toàn bộ 177 crop mới; loại 4/181 frame không có ô
preview LED. 60 mẫu nằm trong 177 mẫu, không cộng thành hai tập độc lập.
Đây là điện thoại quay màn hình, các frame tương quan và đã dùng để chọn
phương án/ngưỡng. Không coi chúng là tập nghiệm thu camera gốc hoặc suy tỷ lệ
đúng ngoài xưởng. Chưa có ảnh/video gốc để kiểm chứng độc lập.

- 200 panel tổng hợp từ 1,00–1,99 và 7,00–7,99: đúng 200/200 ở bản guard đầu.
- Bản guard cuối: 144 panel gồm các số đầu 1/7, 13,04 và 71,04, ba mức
  kích thước/blur và ba màu LED: đúng 144/144. Không dùng ảnh này để huấn luyện
  classifier; dữ liệu tổng hợp không thay thế dữ liệu xưởng.
- Chuỗi 177 crop phát lại lấy mỗi sáu frame, đặt trên canvas cùng kích thước,
  gọi `LocalLiveReader.preview` ở thời gian nguồn (~5 fps): rc93 có 7 lần
  trạng thái ổn định đúng, lần đầu khoảng 2,21 giây; không có ổn định sai.
  rc92 có 16 lần ổn định sai 1,10 và không có ổn định đúng trong lượt đó.
  Đây là mô phỏng từ crop quay màn hình, không phải đo camera vật lý.

Một lượt đo 177 crop: rc93 trung vị khoảng 83 ms, P95 khoảng 124 ms; rc92
trung vị khoảng 80 ms, P95 khoảng 117 ms. Có tác vụ khác chạy cùng máy, nên
chỉ dùng để kiểm tra không có mức tăng độ trễ lớn; không coi là benchmark
CPU đã kiểm soát. Không tăng TTL live để bù nhận diện chậm.

## Kiểm tra tự động

- 157 test Python của OCR, guard mới, live/capture, hàng hỏng, runtime và
  installer Windows đạt. Bao gồm 26 ca guard mới: 1 thật, chữ số khác, dấu,
  phần số còn lại mâu thuẫn, thiếu lượt OCR, thiếu phiếu threshold, phân loại
  mâu thuẫn và cấu hình confidence cao hơn mặc định.
- Toàn bộ test Node: 176 đạt, 1 bỏ qua, 0 thất bại. Có kiểm tra file chẩn đoán
  giữ đúng ảnh/kết quả bị từ chối, không chứa token hoặc phiếu, từ chối frame
  của camera/ROI cũ.
- 30 ca updater giả lập đạt, gồm rc92 → rc93 và checksum sai bị chặn trước
  khi đóng app; dữ liệu DB/config/ảnh giả lập được giữ.
- `pip check` và `git diff --check` đạt.

Đã thử chạy toàn bộ repo trong môi trường build offline: 641 đạt, 33 thất
bại và 19 lỗi setup do thiếu các thành phần legacy Google SDK, YOLO và model
Paddle. Chạy lại nhóm liên quan trong môi trường legacy có sẵn: 127 đạt,
3 thất bại vì thiếu model `PP-OCRv6_medium_rec` của Paddle. Các lỗi thiếu
model này không được đánh dấu thành pass. Chưa có kết quả toàn bộ suite xanh
trong một môi trường đầy đủ. Ba ca phụ thuộc runtime Paddle cũ cần bổ sung
đúng model trước khi chạy lại.

## EXE và giao diện

Đã chạy `dist/TramCanQR/TramCanQR.exe` qua HTTP và Edge với model thật trong
thư mục user thử riêng, cấu hình cloud giả lập mất mạng:

- Ảnh tham chiếu ghép từ crop clip mới đọc 7,10 và đạt ổn định. Cùng ảnh đó,
  source rc92 đọc 1,10. Ảnh ghép chỉ là regression scene cho luồng UI.
- Space lấy đúng ảnh/số đã đọc, không gọi thêm OCR. Lưu phiếu qua UI đạt.
- Preview không tự tạo phiếu/ảnh, bản ghi/ảnh/config/draft thử cũ giữ nguyên.
- Xuất ảnh + OCR tải JSON có cùng byte ảnh đầu vào và số 7,10; không xuất live
  token. Thao tác export không tạo phiếu.
- Chọn vùng LED, tìm LED tự động, đổi chế độ thập phân và dừng camera đạt.
- Không có JavaScript page error. Chưa thử USB/driver thật trong lượt này.

Artifacts riêng: `.local/ocr-research-20261114/` và `.local/release-rc93/`.
Không thêm video/ảnh xưởng, file chẩn đoán hoặc DB thử vào Git.

## Bộ cài cuối

- Build PyInstaller và Inno Setup đạt; EXE/installer là 0.2.0-rc93.
- `tools/verify_windows_rapidocr.py` đạt: module Python nhúng/frontend khớp
  source; model OCR/counter/glyph đúng SHA-256; không kèm SDK Gemini, PyTorch,
  cấu hình riêng hoặc DB. Kiểm tra AST xác nhận storage/API/sync/schema giữ
  phạm vi các thay đổi đã có từ rc89–rc91.
- Hai tên installer có cùng nội dung, mỗi file 249.295.758 byte.
- Không chạy installer trên ứng dụng vận hành hoặc triển khai cloud. Bộ cài
  được chuẩn bị cho kênh cập nhật GitHub theo yêu cầu phát hành ngày 14/11/2026.

```text
09dd7ecfb769d2618c2f1c5765b8cc17b51519e6c7147990173f81eacc06192d  TramCanQR-Setup-0.2.0-rc93.exe
09dd7ecfb769d2618c2f1c5765b8cc17b51519e6c7147990173f81eacc06192d  TramCanQR-Setup.exe
```

Bộ bàn giao: `dist/handoff-0.2.0-rc93/`, có installer, SHA256SUMS và hướng dẫn.
Bộ cài được phát hành qua GitHub latest để máy xưởng cập nhật bằng shortcut
hiện có. Các đường dẫn `.local` chỉ là artifacts riêng của máy phát triển.

Lệnh kiểm chứng chính (từ repo root):

```powershell
$pythonOcrCheck = '.\.local\ocr-investigation-20261111\venv\Scripts\python.exe'
& $pythonOcrCheck -m pytest tests/test_leading_led.py tests/test_rapidocr_regions.py tests/test_local_live.py tests/test_damaged_goods.py tests/test_windows_app.py tests/test_windows_installer.py -p no:cacheprovider
node --test tests/*.test.cjs
& $pythonOcrCheck tools/verify_windows_rapidocr.py
& $pythonOcrCheck tools/smoke_rapidocr_workflow.py --exe dist/TramCanQR/TramCanQR.exe --image .local/ocr-research-20261114/integration-scene.jpg --expect 7.10 --out .local/release-rc93/frozen-edge --offline
& $pythonOcrCheck tools/evaluate_led_regression.py --samples .local/ocr-research-20261114/dense/samples.json --output .local/release-rc93/dense-recheck.json --baseline
```
