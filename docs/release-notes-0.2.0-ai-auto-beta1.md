# Cân AI tự động — 0.2.0-ai-auto-beta1

Bản thử nghiệm Windows x64 nhận diện số cân bằng YOLO CPU và QR bằng OpenCV,
không cần API Gemini, Python hoặc CUDA trên máy khách. Đã kèm checkpoint
`model_2`, SHA256 `9ed72153375c0ddfd42e247dc0453c95c3c1061b4ab66f397384aa6bb7c8a8e8`.

**Tải nhanh:** [TramCanQRAuto-Setup.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/download/v0.2.0-ai-auto-beta1/TramCanQRAuto-Setup.exe).

## Cài thử và quay lại

- Cài cạnh bản Gemini, AppId/EXE/shortcut/thư mục dữ liệu riêng.
- Bản thử mở `http://127.0.0.1:8081`; bản Gemini giữ `http://127.0.0.1:8080`.
- Đóng app đang dùng camera trước khi mở bản còn lại.
- Lần đầu tự sao chép thông tin trạm và kết nối Supabase/kho vào cấu hình
  `%LOCALAPPDATA%\TramCanQRAuto\config.env`; không sao chép key AI, DB hay ảnh.
- DB/ảnh thử nghiệm ở `%LOCALAPPDATA%\TramCanQRAuto\data`. Phiếu pending
  không tự chuyển sang DB Gemini khi quay lại.
- Không đổi Latest hoặc nút cập nhật Gemini: bản Gemini ổn định vẫn là rc74.

## Thay đổi

- Đóng gói mã CV từ `new_system`, checkpoint, Torch CPU và Ultralytics.
- Nối API camera, snapshot cùng frame nhận diện; chuyển nguồn xóa ảnh cũ,
  mất camera không dùng lại snapshot cũ. Preview không tự tạo phiếu cân.
- Lúc bấm chụp lấy frame camera mới nhất, không gắn QR/kết quả của preview
  cũ vào frame đó. Cả số cân và QR được đọc lại trên đúng ảnh vừa chụp.
- Preview dùng kết quả đệm, không gọi thêm inference qua `/api/analyze`.
- Không bỏ chữ số yếu để ghép thành một giá trị khác; thiếu số/QR cho chụp
  lại hoặc sửa tay. Cân nhiều hàng ưu tiên hàng gross trên cùng.
- Giữ lưu ảnh/binding cùng lượt, hủy AI, đồng bộ pending mỗi 600 giây khi
  AI rảnh, ngưỡng popup theo ô Tối đa cuộn/đợt và thao tác đẩy kho thủ công.

## Giới hạn thử nghiệm

Ảnh chuẩn do người vận hành xác nhận 13,04 kg được đọc đúng cùng QR.
Một ảnh lõi mờ chưa đọc đủ số được chặn, không suy đoán giá trị hoặc tự lưu.
Chưa xác nhận độ chính xác trên toàn bộ cân/camera/ánh sáng ở máy khách;
người vận hành phải đối chiếu số hiển thị và QR trước khi lưu. Lượt đo CPU
trên ảnh mẫu mất vài giây, phụ thuộc ảnh và số crop cần thử; đây chưa phải
cam kết tốc độ ở máy khách. Nhận diện không cần Internet, đồng bộ vẫn cần mạng.

Xem [hướng dẫn cài và quay lại Gemini](../packaging/HUONG-DAN-CAN-AI-TU-DONG.md).

## Build và kiểm tra

Giữ version kênh Gemini trong pyproject/installer cũ; version kênh thử riêng
nằm ở `windows_auto_app.py`, `TramCanQRAuto.iss` và `TramCanQRAuto.version`.

```powershell
npm ci --ignore-scripts
node --test tests/*.test.cjs
.venv\Scripts\python.exe -m pytest tests backend/tests -o addopts= -q
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/build_windows.ps1 -Variant AiAuto
.venv\Scripts\python.exe tools/verify_ai_auto.py
```

Chạy source local dùng `python -m roll_qr_scale.test_ui --weight-engine local-yolo
--digit-model model/best.pt`; `.env` Gemini cũ không tự chuyển thành kênh thử.

Build dùng PyInstaller `--clean`, checkpoint local và bản Torch CPU trong
môi trường build. Không dùng script release kênh Gemini vì script đó đặt Latest.
