# LED glyph verifier v1

Model dự án tự huấn luyện, dành riêng việc xác minh chữ số đầu 7 khi
PP-OCRv6 đã nhận thành 1 hoặc hai lượt màu/xám mâu thuẫn 1/7.

- Tệp: `backend/src/tramcan_rapidocr/led_glyph.onnx`, 830.634 byte.
- SHA-256: `61e7d8535a2179eea573131dd8f0565f047f7a5edf54e2b5ac2b1b47dcbebbc4`.
- Input: mask ảnh xám `float32`, `[batch, 1, 48, 32]`, khoảng 0–1.
- Output: logits cho chữ số 0–9 và một lớp tổ hợp đoạn không hợp lệ.
- Ba lớp convolution, một lớp fully connected 64 chiều và lớp phân loại.
- Chạy bằng ONNX Runtime CPU có sẵn; runtime không cần PyTorch/ONNX exporter.
- Nạp model có đối chiếu manifest và SHA-256, không tự tải model khi chạy.

## Dữ liệu và quy trình

`tools/train_led_glyph.py` tạo ảnh bảy đoạn cân bằng theo 11 nhãn, thay độ
rộng, độ dày, nghiêng, xoay, blur, độ phân giải và ngưỡng. Có biến thể thân
phải liên tục/chân ngắn của chữ số 1 và 7. Không dùng ảnh hoặc nhãn xưởng,
không dùng trọng số của model tải ngoài để huấn luyện.

Seed 20261114; 12 epoch, 11.000 mẫu mới mỗi epoch. Một tập tổng hợp riêng
1.100 mẫu được theo dõi trong huấn luyện, epoch cuối đúng 1.088/1.100. Con số
này không mô tả độ đúng trên ảnh xưởng. Trọng số được export ở epoch 12.

Môi trường huấn luyện: Python 3.12, PyTorch 2.12.1+cpu, NumPy 2.3.5,
OpenCV 4.10.0; export ONNX 1.17.0, opset 17. Tool huấn luyện đã được đưa vào
repo; phụ thuộc huấn luyện không thêm vào `pyproject.toml` của bộ cài.

Ví dụ, trong môi trường phát triển riêng đã cài các phụ thuộc trên:

```powershell
python tools/train_led_glyph.py --output .local/led-glyph-training
```

Tool ghi trọng số, ONNX, lịch sử và phiên bản thư viện vào thư mục output;
không ghi đè model đang đóng gói. Seed và phiên bản giúp tái lập thí nghiệm;
không cam kết bit-identical trên mọi CPU/thư viện. Đối chiếu lại regressions
và checksum trước khi thay model trong sản phẩm.

## Điều kiện quyết định

Ứng dụng giữ hai lượt OCR ban đầu. Chỉ xét verifier khi các kết quả hợp lệ
có chữ số đầu thuộc 1/7, cùng dấu và thống nhất toàn bộ phần còn lại.

Ảnh phải có LED đỏ, tách được đủ ô chữ số và có nét ngang trên đủ rõ. Bộ kiểm
tra deskew từ hình học, giữ ảnh gốc, rồi phân loại ở ngưỡng Otsu × 1,0 / 1,1 /
1,2. Cần ít nhất hai phiếu 7 trên 0,99, không có chữ số khác được phân loại
chắc chắn mâu thuẫn. Hai lượt OCR vẫn phải đủ tin cậy để xác định phần còn
lại; một lượt OCR không đủ để tạo số mới. Giữ raw text cũ và dấu vết phân loại
trong kết quả chẩn đoán, không che việc OCR ban đầu đã đọc `110`.

Các mức ngưỡng của cùng một ảnh có tương quan; đây là kiểm tra độ bền phân
vùng, không phải ba chứng cứ thống kê độc lập. Confidence của CNN và OCR chưa
được hiệu chuẩn thành xác suất đúng ở xưởng.

## Giới hạn

Các video 1,06/1,08 và 7,10 được dùng làm bộ phát triển/đối chứng, không dùng
làm input huấn luyện. Việc chọn ngưỡng và kiến trúc đã tham khảo kết quả trên
những video này; chúng không phải tập kiểm tra thực địa chưa từng thấy.

Model không thể khôi phục chắc chắn nét ngang của số 7 nếu nét đó thực sự
vắng trên camera. Chưa đánh giá mọi kiểu LED, độ chói, dấu âm, góc camera và
vị trí chữ số trên dữ liệu xưởng. Vẫn có thể có lỗi ngoài tập kiểm tra; bản thử
cần được đối chiếu ở một trạm trước khi mở rộng.

Các ứng viên SVTR/CRNN tải từ GitHub chỉ nằm trong `.local` để đối chứng;
không sao chép mã hoặc trọng số của chúng vào model này hay bộ cài.
