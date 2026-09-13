# Chi phí Gemini cho một lần nhận diện

Ngày đo: 2026-08-04  
Hai chế độ production:

| Chế độ | Model | Input / 1M token | Output + thinking / 1M token |
|---|---|---:|---:|
| Nhanh | `gemini-3.5-flash-lite` | `$0.30` | `$2.50` |
| Chính xác | `gemini-3.1-pro-preview` | `$2.00` | `$12.00` |

## Token đo trực tiếp từ API

Các số dưới đây lấy từ `usage_metadata` do Gemini trả về khi chạy chính prompt
production trên ảnh `factory_scale_13_04_reference.jpg`:

| Chế độ | Input | Output | Thinking | Tổng | Chi phí paid tier/request |
|---|---:|---:|---:|---:|---:|
| Nhanh — mỗi lần nhấn Space/chọn ảnh: 1 ảnh đầy đủ | 1.278 | 70 | 0 | 1.348 | `$0.0005584` |

Công thức:

```text
cost_usd = input_tokens × 0.30 / 1,000,000
         + (output_tokens + thinking_tokens) × 2.50 / 1,000,000
```

Ví dụ một lần nhấn `Space` (một ảnh đầy đủ):

```text
1,278 × 0.30 / 1,000,000 + 70 × 2.50 / 1,000,000
= $0.0005584 cho một lần bấm chụp
```

Nếu chạy 500 lần/ngày trên paid tier với đúng mức token đã đo:

- 1 ảnh/request: `$0.2792/ngày`, khoảng `$8.376/30 ngày`.

Chế độ **Chính xác** dùng Pro với thinking trung bình nên số thinking token thay đổi theo
ảnh. Chi phí chính xác của từng request phải tính từ `usage_metadata` thực tế:

```text
cost_usd = input_tokens × 2.00 / 1,000,000
         + (output_tokens + thinking_tokens) × 12.00 / 1,000,000
```

Free Tier có thể áp dụng cho Flash-Lite theo quota của project. Google hiện
không cung cấp Free Tier cho `gemini-3.1-pro-preview`; chế độ Chính xác cần bật
billing. Ứng dụng trả các trường `gemini_input_tokens`,
`gemini_output_tokens`, `gemini_thinking_tokens` và `gemini_total_tokens` để đối
soát từng request; token có thể thay đổi theo kích thước/tỷ lệ ảnh và phản hồi.

## Key dự phòng và đồng hồ quota

Đặt `ROLL_SCALE_GEMINI_BACKUP_API_KEY` (hoặc mở Cài đặt → Key ca đêm) để backend
tự chuyển sang key thứ hai khi key đang dùng trả lỗi API, ví dụ key bị thu hồi
hoặc không hợp lệ. Key lỗi được quarantine cho đến khi tiến trình khởi động lại
hoặc bạn lưu key mới; backend không thử lại key lỗi trên từng lần chụp. Key dự
phòng không làm tăng quota nếu hai key cùng thuộc một project, vì Gemini áp hạn
mức theo project.

`/api/status` và thanh nhỏ trên giao diện hiển thị số request mà tiến trình đã
ghi nhận trong khoảng một phút và 24 giờ gần nhất. Trường `quota.keys.day` và
`quota.keys.night` tách riêng RPM, TPM đầu vào và RPD theo key; đây là số liệu
cục bộ để cảnh báo sớm, không phải số dư quota chính thức (các client khác trong
cùng project không được biết). Hạn mức thực tế thay đổi theo model, project và
tier, nên cần đối chiếu Google AI Studio.

Nguồn đơn giá chính thức:

- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/tokens
