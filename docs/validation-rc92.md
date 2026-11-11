# Kiểm chứng rc92 — 11/11/2026

## Source và cập nhật

- 131 test Python đạt: OCR Small với model thật, live/capture, cân hàng hỏng,
  cấu hình/backup Windows và bộ cài.
- Toàn bộ test Node: 173 đạt, 1 bỏ qua, 0 thất bại.
- 28 trường hợp updater giả lập đạt, gồm rc88/rc89/rc90/rc91 lên rc92;
  checksum sai bị chặn trước khi đóng app. DB/config/ảnh giả lập giữ nguyên.
- `pip check` và `git diff --check` đạt. Môi trường build riêng dùng đúng
  dependencies của `pyproject.toml` và PyInstaller 6.21.0.
- Script build nhận thêm `-PythonPath` để chọn rõ môi trường build; mặc định
  vẫn tìm `.venv`/`.venv-pilot` như trước.

## EXE với model thật

- EXE trả đúng 20/20 ảnh bảy đoạn tổng hợp gồm 1,06; 1,08; 2,08; 7,08; 13,04
  với nhiều mức kênh xanh lá ở chữ số đầu. Đây là kiểm tra qua HTTP thật tới
  ứng dụng đóng gói, không dùng reader giả.
- Ba frame cùng giá trị 1,06 nhưng màu chữ số thay đổi đạt ổn định ở frame 3;
  hai frame đầu không bị báo ổn định. Cấu hình thử giữ nguyên.
- Edge headless với ảnh tham chiếu 13,04, model thật và cloud giả lập mất mạng:
  live đạt ổn định; Space lấy đúng ảnh/số đã đọc; lưu phiếu local qua UI đạt.
  Preview không tự ghi phiếu hoặc ảnh. Giữ bản ghi, ảnh, cấu hình và draft cũ.
- Chọn vùng LED thủ công, tìm LED tự động, đổi chế độ thập phân và dừng camera
  đạt; không có JavaScript page error. Phục hồi camera native được giả lập bằng
  bridge, không coi là thử USB/driver thật.
- Luồng đẩy lại Supabase trên EXE đạt với cả kết nối trực tiếp và API-only:
  kiểm tra QR chính xác, chỉ gửi QR thiếu, retry không gửi trùng. Dùng HTTP cloud
  giả lập; không tác động dữ liệu hoặc cấu hình cloud thật.
- Thử giữ ảnh thủ công trên Edge: ảnh chờ hơn TTL live vẫn lấy đúng số/ảnh;
  không lấy lại cùng ảnh vào ô tiếp theo; tiếp tục live và lưu phiếu local đạt.

Artifacts cục bộ: `.local/release-rc92/`, gồm build log, ảnh/PDF Edge,
`frozen-regression/result.json`, `frozen-edge/result.json` và log updater/sync.
Không đưa ảnh xưởng, profile thử, DB hoặc cấu hình riêng vào Git.

## Bộ cài

- Build sạch bằng PyInstaller và Inno Setup đạt. EXE và installer đều báo
  phiên bản 0.2.0-rc92. Không cài đè ứng dụng đang vận hành để thử.
- `tools/verify_windows_rapidocr.py` đạt: mã Python nhúng và frontend khớp
  source; model OCR/counter đúng SHA256; không kèm DB/config riêng hoặc
  Gemini SDK. Hai bộ cài giống nhau, mỗi file 248.495.310 byte.
- Đối chiếu phần lưu trữ/API/đồng bộ với rc80 qua verifier đạt theo các thay
  đổi đã có ở rc89–rc91; đợt này không sửa schema hoặc triển khai lại cloud.

```text
87528bbda16845f976d067742678f6b86105c508ab5f0a6a71614aa131705eaa  TramCanQR-Setup-0.2.0-rc92.exe
87528bbda16845f976d067742678f6b86105c508ab5f0a6a71614aa131705eaa  TramCanQR-Setup.exe
```

## Giới hạn

176 mẫu trích từ hai video quay màn hình đọc đúng với source đã sửa. Chưa có
luồng camera gốc để chứng minh đã hết mọi nguyên nhân mất số tại xưởng.
Không có phép đo độ đúng/vận hành cả ca hoặc thử camera USB thật.
Giữ Small, ngưỡng tin cậy và điều kiện xác nhận cân ổn định; không giữ số cũ
để cho phép chụp khi OCR mất kết quả.
