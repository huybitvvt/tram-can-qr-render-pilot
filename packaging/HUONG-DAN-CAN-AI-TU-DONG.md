# Cân AI tự động — bản thử nghiệm 0.2.0-ai-auto-beta1

Nhận diện số cân và QR trên máy Windows bằng YOLO CPU, không cần key Gemini,
không cần cài Python hoặc CUDA. Model số cân đã nằm trong bộ cài.
Đồng bộ Supabase và đẩy kho vẫn cần mạng cùng cấu hình riêng của trạm.

## Cài thử và quay lại bản Gemini

1. Đóng cửa sổ camera của bản Gemini và thoát chương trình đó để nhả camera USB.
2. Cài `TramCanQRAuto-Setup.exe`, mở shortcut **Cân AI tự động (thử nghiệm)**.
3. Giao diện mở tại **http://127.0.0.1:8081**. Chọn đúng camera rồi chụp thử
   lõi và sản phẩm; đối chiếu trực tiếp số trên cân, QR và ảnh trước khi lưu.
4. Nếu cần quay lại: thoát `TramCanQRAuto.exe`, mở shortcut **Tram Can QR**
   cũ tại **http://127.0.0.1:8080**. Không cần gỡ hoặc cài đè bản Gemini.

Hai bản có bộ cài, shortcut, cổng và dữ liệu riêng. Bản này không thay đổi bản
Gemini hoặc URL cập nhật của bản Gemini. Tên “tự động” chỉ việc nhận diện local;
người vận hành vẫn chụp, kiểm tra và bấm lưu, không tự chốt xe hoặc tự đẩy kho.

## Cấu hình và dữ liệu

- Chương trình: `%LOCALAPPDATA%\Programs\TramCanQRAuto`.
- Cấu hình: `%LOCALAPPDATA%\TramCanQRAuto\config.env`.
- DB và ảnh: `%LOCALAPPDATA%\TramCanQRAuto\data`.
- Log: `%LOCALAPPDATA%\TramCanQRAuto\logs\app.log`.
- Bản Gemini giữ nguyên trong `%LOCALAPPDATA%\TramCanQR`.

Lần mở đầu, nếu tìm thấy cấu hình Gemini, ứng dụng sao chép thông tin trạm,
kết nối Supabase và kho vào **cấu hình riêng**. Không sao chép key AI, DB hoặc
ảnh cũ. Nếu không có cấu hình cũ, bộ cài cho chọn Trạm 01–04; thêm URL/token
Supabase được cấp vào cấu hình mới nếu muốn đồng bộ. Không gửi file cấu hình
có token/key lên GitHub. Thay cấu hình xong cần thoát và mở lại ứng dụng.

Ảnh và phiếu lưu ở bản thử vẫn nằm trong thư mục thử nghiệm khi quay lại Gemini.
Các phiếu đã đồng bộ còn trên Supabase; các phiếu chưa đồng bộ không tự chuyển
sang DB của Gemini. Xử lý các phiếu chờ trước khi dừng thử. Lịch tự đồng bộ vẫn
mỗi 600 giây khi AI rảnh và chỉ lấy dòng pending.

## Hiệu chỉnh và xử lý lỗi

Cân hiện dùng hai chữ số thập phân. Các giá trị mặc định:

```env
ROLL_SCALE_DIGIT_CONFIDENCE=0.2
ROLL_SCALE_DIGIT_INFERENCE_CONFIDENCE=0.35
ROLL_SCALE_DIGIT_IMAGE_SIZE=640
ROLL_SCALE_DECIMAL_PLACES=2
ROLL_SCALE_CAMERA_WIDTH=1920
ROLL_SCALE_CAMERA_HEIGHT=1080
ROLL_SCALE_CAMERA_RECOGNITION_MAX_EDGE=960
ROLL_SCALE_CAMERA_SOURCE=0
ROLL_SCALE_LIVE_INFERENCE_FPS=2
ROLL_SCALE_PORT=8081
```

Model được nạp từ bộ cài, không cần đặt `ROLL_SCALE_DIGIT_MODEL`.
Muốn dùng model khác, đặt đường dẫn tuyệt đối tới checkpoint tương thích.
Nếu camera không mở, đóng app khác đang dùng camera rồi chọn lại nguồn USB.
Nếu số/QR không rõ hoặc confidence thấp, sửa tay hoặc chụp lại; không tự coi
kết quả đó là số cân hợp lệ. Độ chính xác và tốc độ còn phụ thuộc camera,
ánh sáng và CPU của máy khách; cần kiểm tra thực tế trước khi dùng vận hành.
