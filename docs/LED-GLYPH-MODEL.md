# LED glyph verifier v2

Model dự án tự huấn luyện, dùng kết hợp với kiểm tra hình học LED bảy đoạn để
xác minh chữ số `7` khi PP-OCRv6 Small nhận nhầm thành `1` hoặc `2` (hoặc hai
lượt màu/xám mâu thuẫn `1/7`, `2/7`, `1/2/7`) tại vị trí chữ số đầu hoặc chữ
số hàng đơn vị đứng ngay trước dấu thập phân (ví dụ `7.xx`, `17.xx`).

- Phiên bản: `led-glyph-v2`.
- Tệp: `backend/src/tramcan_rapidocr/led_glyph.onnx`, 830.634 byte.
- SHA-256: `4e46936cdd17df01c95ca96bb6631bec54ef951966a845f738b61eaf0784aaa6`.
- Input: mask ảnh xám `float32`, `[batch, 1, 48, 32]`, khoảng 0–1.
- Output: logits cho chữ số 0–9 và một lớp tổ hợp đoạn không hợp lệ (`invalid-pattern`).
- Kiến trúc giữ nguyên bản v1: ba lớp convolution, một lớp fully connected 64 chiều
  và lớp phân loại 11 lớp.
- Chạy bằng ONNX Runtime CPU có sẵn; runtime không cần PyTorch/ONNX exporter.
- Nạp model có đối chiếu manifest `led_glyph.json` và SHA-256, không tự tải model khi chạy.

## Dữ liệu và quy trình

`tools/train_led_glyph.py` tạo ảnh bảy đoạn cân bằng theo 11 nhãn, thay độ
rộng, độ dày, nghiêng, xoay, blur, độ phân giải và ngưỡng. Bản v2 bổ sung:

- **Dấu chấm thập phân ở góc dưới-phải đối xứng trên tất cả 11 nhãn** (có và
  không có cầu sáng dính liền chân chữ số) để model bất biến với dấu chấm sát
  chân số `7.` và `2.`, buộc model phân biệt thuần túy theo cấu trúc 7 đoạn.
- **Mô phỏng quầng nở LED (halation/bloom)** và biên độ sáng từng đoạn trước khi
  thu nhỏ và phân ngưỡng.

Không dùng ảnh hoặc nhãn xưởng, không dùng trọng số của model tải ngoài để
huấn luyện.

Seed `20261126`; 15 epoch, 16.500 mẫu mới mỗi epoch (247.500 mẫu tổng hợp).
Hai tập tổng hợp độc lập được theo dõi trong huấn luyện (epoch 15):

- Tập không chấm thập phân: **1.075/1.100** đúng.
- Tập có dấu chấm thập phân sát góc dưới-phải: **1.079/1.100** đúng (**0** ca
  nhầm `7 → 2`, **0** ca nhầm `2 → 7`, **0** ca nhầm `1 → 7`).

Các con số tổng hợp này không thay thế đo lường thực địa tại xưởng.

Môi trường huấn luyện: Python 3.12, PyTorch 2.12.1+cpu, NumPy 2.3.5,
OpenCV 4.10.0; export ONNX 1.17.0, opset 17. Tool huấn luyện nằm tại
`tools/train_led_glyph.py`; phụ thuộc huấn luyện không thêm vào `pyproject.toml`
của bộ cài.

Ví dụ chạy lại trong môi trường phát triển riêng:

```powershell
$env:PYTHONPATH = "backend/src;.local/ocr-research-20261114/export-deps"
.\.venv\Scripts\python.exe tools/train_led_glyph.py --output .local/led-glyph-training-v2
```

Tool ghi trọng số, ONNX, lịch sử và phiên bản thư viện vào thư mục output;
không ghi đè model đang đóng gói. Đối chiếu lại regressions và checksum trước
khi cập nhật model trong sản phẩm.

## Điều kiện quyết định

Ứng dụng giữ hai lượt OCR ban đầu (`red-row` và `gray`). Chỉ xét verifier khi
các kết quả hợp lệ có cùng dấu, cùng độ dài/vị trí dấu thập phân và chỉ liên
quan đến `1/2/7` tại chữ số đầu hoặc `2/7` tại chữ số hàng đơn vị đứng ngay
trước dấu thập phân, trong khi hai lượt OCR thống nhất toàn bộ các chữ số còn
lại.

Các lớp bảo vệ trong `backend/src/tramcan_rapidocr/leading_led.py`:

1. **Tách dòng và ký tự an toàn:**
   - Chỉ xóa thành phần chạm biên khi đó là viền toàn cạnh (`w == width` hoặc
     `h == height`) hoặc viền sáng không có sắc đỏ LED; không xóa nhầm chữ số
     LED đỏ nằm sát mép ROI.
   - Đóng khe dọc hẹp (`width = 1`) chỉ để xác định đúng chiều cao dãy số khi
     các đoạn dọc trên/dưới tách nét rõ, giữ nguyên mask ký tự gốc để phân loại.
   - Chạy bộ ngưỡng chính Otsu × `1.0 / 1.1 / 1.2`; chỉ bật bổ sung tách chói
     (`1.3 / 1.4` và lõi kênh xanh lá `1.1 / 1.2 / 1.3`) khi các ngưỡng chính
     bị dính khối chữ số (`0 < count < digits`).
2. **Kiểm tra hình học bảy đoạn (`has_seven_geometry`):**
   - Để phân biệt chắc chắn `7` (`abc`) với `2` (`abdeg`) và `1` (`bc`), ký tự
     phải đồng thời có nét ngang trên (`a`), có thân dọc dưới-phải (`c`), **không**
     có nét dọc dưới-trái (`e`) và **không** có nét ngang giữa bên trái (`g`).
   - Số `2` thật (có nét `e`/`g`) không vượt qua cổng hình học này nên giữ
     nguyên kết quả `2.xx` / `12.xx` bình thường.
3. **Đồng thuận đa ngưỡng và cơ chế phủ quyết (Veto):**
   - Chỉ xác nhận `7` (`verified-leading-led`) khi có ít nhất **2** mức ngưỡng
     đạt đồng thời `has_seven_geometry` và `led-glyph-v2` phân loại `7` ở mức
     `≥ max(0.99, min_confidence)`, không có mức nào phân loại chắc chắn chữ số
     khác, và có đủ 2 lượt OCR độc lập thống nhất phần còn lại (ít nhất một lượt
     `≥ min_confidence`).
   - Khi một kết quả đồng thuận (`1.xx` / `12.xx`) có kiểm tra ở biên nhưng mọi
     lượt phân loại đều xác nhận đúng chữ số OCR ban đầu (không có dự đoán `7`),
     hệ thống giữ nguyên kết quả đúng đó.
   - Khi bằng chứng hình học mâu thuẫn với `1`/`2` nhưng chưa đủ ngưỡng chắc
     chắn `7`, hệ thống **từ chối (`ambiguous-leading-led`)** thay vì để lọt số
     sai. Raw text OCR ban đầu và toàn bộ dấu vết phân loại luôn được giữ trong
     `observations`.

## Giới hạn

- Ảnh xưởng từ backup và video 1,06/1,08, 7,10 chỉ dùng làm bộ kiểm chứng độc
  lập/hồi quy, không đưa vào huấn luyện.
- Model không thể khôi phục chắc chắn nét phân biệt của số `7` nếu nét đó bị
  che hoặc mất hoàn toàn trên khung hình camera gốc, hoặc khi OCR sai vị trí
  dấu thập phân (ví dụ `70.2` ở ảnh `factory_scale_7_02_full_reference.jpg`).
- Vẫn cần đối chiếu thực tế trên một trạm tại xưởng trước khi triển khai rộng.
