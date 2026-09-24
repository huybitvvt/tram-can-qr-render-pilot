# Trạm cân QR Việt Nhật IPT — hướng dẫn cài đặt

Phiên bản: `0.2.0-rc23` — bản chạy thử nghiệm thu tại xưởng.

## 1. Cài đặt

1. Đóng bản đang chạy, sau đó chạy file `TramCanQR-Setup-0.2.0-rc23.exe`
   trên Windows 10/11 64-bit. Có thể cài đè bản cũ; `config.env` và dữ liệu
   trong `%LOCALAPPDATA%\TramCanQR` được giữ nguyên.
2. Ở lần cài đầu, chọn đúng **Trạm 01**, **Trạm 02**, **Trạm 03** hoặc
   **Trạm 04**. Trang chọn trạm được bỏ qua khi máy đã có `config.env`.
3. Installer tự mở file cấu hình. Điền Supabase/Gemini, bấm **Ctrl+S** rồi
   đóng Notepad. Ứng dụng sẽ tự mở sau đó.
4. Nếu Windows SmartScreen cảnh báo, đối chiếu SHA-256 với file
   `SHA256SUMS.txt` do đơn vị triển khai gửi trước khi tiếp tục.
5. Nếu ứng dụng chưa tự mở, mở **Trạm cân QR** từ Desktop. Trình duyệt sẽ mở địa chỉ
   `http://127.0.0.1:8080`.
6. Cho phép Chrome/Edge sử dụng camera khi trình duyệt hỏi.

Không cần cài Python. Không đổi tên, di chuyển hoặc xóa thư mục `_internal`
trong bản portable.

### Cập nhật bằng nút trên Desktop

Sau khi lưu xong lượt cân đang làm, bấm **Cập nhật Trạm Cân QR**. Nút kiểm tra
GitHub Release, chỉ tải khi có phiên bản mới hơn, kiểm tra SHA-256 của bộ cài,
đóng ứng dụng, cài đè và mở lại. Máy cần có Internet. Nếu tải hoặc kiểm tra
thất bại, ứng dụng đang chạy sẽ không bị đóng; cửa sổ cập nhật sẽ báo lỗi.
`config.env`, SQLite và ảnh trong `%LOCALAPPDATA%\TramCanQR` được giữ nguyên.

Nếu máy đang dùng nút từ bộ cài cũ và nút không hoạt động, thay file
`CAP-NHAT-BAN-MOI.cmd` trong `%LOCALAPPDATA%\Programs\TramCanQR` bằng file
cập nhật mới do đơn vị triển khai cung cấp, rồi bấm lại nút trên Desktop.
Chỉ cần thay file này một lần; những bản cài tiếp theo sẽ tự mang nút mới.

### Lưu từng lần cân

Trong mỗi thẻ **Lần 1**, **Lần 2**, bấm nút lưu ngay dưới thẻ để chỉ lưu
lần đó. Nhấn **Enter** hoặc nút **Lưu tất các lần** để lưu mọi lần đang có
dữ liệu; lần đã đủ điều kiện được ghi thành phiếu cân, lần mới có ảnh được
ghi thành ảnh chờ. Khi đủ dữ liệu, nút riêng ghi **Lưu phiếu cân**. Nếu mới có một ảnh hoặc
AI chưa đọc được số, nút ghi **Lưu ảnh chờ**: ảnh được giữ trên máy và tự đồng
bộ lên cloud, dù ô ảnh còn lại trống. Ảnh chờ chưa phải phiếu cân hoàn chỉnh.
Sau khi lưu thành công, ảnh của đúng lần đó biến mất để cân tiếp; lần khác
chưa lưu vẫn còn. Dòng **Đang chờ** trong danh sách nghĩa là bản ghi đã nằm
trong DB local và đang chờ Supabase/Cloudinary xác nhận đồng bộ. Nếu màn hình
báo chưa lưu được ảnh, giữ nguyên ảnh và bấm lại nút để thử lại.
Xác nhận số cuộn là thao tác riêng, không ngăn lưu từng lần cân hay ảnh chờ.

## 2. Danh tính từng trạm

Mỗi máy chạy đúng một gateway, một trạm và một camera độc lập. Bốn máy đều mở
cùng URL local `http://127.0.0.1:8080`; hậu tố danh tính trong `config.env`
phải khác nhau:

| Máy | Gateway | Station | Camera |
| --- | --- | --- | --- |
| 01 | `gateway-01` | `station-01` | `camera-01` |
| 02 | `gateway-02` | `station-02` | `camera-02` |
| 03 | `gateway-03` | `station-03` | `camera-03` |
| 04 | `gateway-04` | `station-04` | `camera-04` |

Installer tự tạo file:

```text
%LOCALAPPDATA%\TramCanQR\config.env
```

Giữ `ROLL_SCALE_STATION_COUNT=1`. Mỗi máy điền **bộ URL/token Supabase riêng**
và **Gemini key riêng** được cấp cho đúng trạm đó. Đóng ứng dụng rồi mở lại sau
khi sửa. Không sao chép nguyên `config.env` từ máy 01 sang máy khác vì sẽ làm
trùng danh tính và gửi dữ liệu sang sai Supabase.

Mỗi camera chỉ được gán cho một trạm. Trên giao diện, chọn đúng camera ở từng
thẻ trạm rồi bấm **Mở camera đã gán**. Trình duyệt lưu ánh xạ này trên chính
máy khách.

Với `local`/`hybrid`, mặc định mỗi lần chụp dùng 5 frame và PaddleOCR chọn 3
frame đầu–giữa–cuối. Với `gemini`, mỗi lần chụp gửi một ảnh bằng chứng đã nén;
backend crop vùng LED trước khi gọi Gemini. Có thể giữ cấu hình:

```text
ROLL_SCALE_WEIGHT_BURST_FRAMES=5
```

Gemini mặc định tắt. Chỉ đơn vị triển khai được bật sau khi khách hàng chấp
thuận việc gửi ảnh camera tới Google và cấp key bằng kênh riêng:

```text
ROLL_SCALE_GEMINI_ENABLED=true
ROLL_SCALE_WEIGHT_ENGINE=hybrid
ROLL_SCALE_GEMINI_API_KEY=replace-with-key-for-this-station
# Tùy chọn: key thứ hai; tự chuyển khi key trên trả lỗi API và quarantine key
# lỗi cho tới khi khởi động lại hoặc lưu key mới.
# ROLL_SCALE_GEMINI_BACKUP_API_KEY=replace-with-second-key-for-this-station
ROLL_SCALE_GEMINI_MODEL=gemini-3.5-flash-lite
ROLL_SCALE_GEMINI_ACCURATE_MODEL=gemini-3.1-pro-preview
ROLL_SCALE_GEMINI_TIMEOUT=10.0
ROLL_SCALE_GEMINI_ACCURATE_TIMEOUT=30.0
```

Ở chế độ `hybrid`, Gemini chỉ xác nhận ứng viên đa số từ PaddleOCR; kết quả
cloud đơn lẻ hoặc khác local luôn bị giữ lại để người vận hành kiểm tra.

Trên giao diện, chọn **Nhanh** để dùng `gemini-3.5-flash-lite` với thinking
tối thiểu; chọn **Chính xác** để dùng `gemini-3.1-pro-preview` với thinking
trung bình. Model Pro không có Free Tier trên Gemini API và cần bật billing.
Mỗi lần chụp ở cả hai chế độ vẫn chỉ gửi đúng một ảnh. Timeout mặc định lần
lượt là 10 giây và 30 giây.

Bản pilot dùng đúng một camera nhưng để Gemini đọc trực tiếp thì đổi
`ROLL_SCALE_WEIGHT_ENGINE=gemini`. Paddle không khởi tạo. Gemini chỉ đọc số
cân từ vùng LED đã crop, không suy đoán mã SP. Nếu crop không đọc được, backend
thử lại ảnh toàn khung đúng một lần; lỗi mạng/timeout không bị gọi lặp. Ở lần chụp cân sản phẩm, mã QR
được trình duyệt và ZXing backend đọc độc lập. Hai bộ giải mã khớp thì tự điền;
nếu xung đột thì hệ thống để trống và yêu cầu người vận hành kiểm tra.

Sau khi camera đã được bắt cố định, đơn vị triển khai nên hiệu chỉnh ROI hàng
số gross cho từng trạm và điền vào `config.env`; ROI cũng được dùng để tăng tốc
Gemini. Nếu chưa cấu hình, backend tự dò LED. Mỗi ROI có dạng
`x1,y1,x2,y2` từ 0 đến 1; các trạm ngăn cách bằng dấu chấm phẩy:

### Codex · ChatGPT

Codex là lựa chọn AI độc lập với Gemini. Trên máy local, cài Codex CLI và đăng
nhập đúng tài khoản ChatGPT trước khi dùng:

```powershell
codex login --device-auth
codex login status
```

Mở menu **AI** trên giao diện, chọn **Codex · ChatGPT**, rồi bấm **Đăng nhập
Codex**. Nút này mở lại cửa sổ đăng nhập CLI nếu tài khoản chưa được xác nhận;
không cần dán API key Codex vào `config.env`. Nếu Codex chưa cài, giao diện sẽ
hiện hướng dẫn cài CLI; có thể chọn lại **Gemini API** để cân tiếp.

Antigravity là lựa chọn AI thứ ba (sau Gemini API và Codex). Cần cài CLI
`agy` trên đúng máy chạy backend; trong menu **AI**, chọn **Antigravity · Google**,
bấm **Đăng nhập Antigravity**, hoàn tất Google login ở cửa sổ mới rồi bấm lại
để kiểm tra. Antigravity không dùng model Gemini 3.5 Flash-Lite; muốn dùng
model đó hãy chọn Gemini API.

```text
ROLL_SCALE_WEIGHT_ROIS=0.4500,0.8000,0.5400,0.8500;0.4450,0.7950,0.5350,0.8450;0.4550,0.8050,0.5450,0.8550
```

Các số trên chỉ minh họa, không sao chép sang xưởng. ROI phải ôm sát duy nhất
hàng gross, không chứa bàn phím hoặc hai hàng `0.00` phía dưới. Số ROI phải
bằng `ROLL_SCALE_STATION_COUNT` và đúng thứ tự `ROLL_SCALE_STATION_IDS`.

## 3. Vận hành

- Máy local chỉ có một trạm nên không cần chuyển trạm bằng phím số.
- Ô **Ca** luôn có lựa chọn **Ca chuẩn Đà Nẵng**. Ô **Máy** cho chọn trong
  danh sách hoặc gõ tên máy mới, kể cả khi trạm đã có tên máy mặc định trong
  cấu hình. Nhập **LSX** rồi bấm **Áp dụng** trước khi cân.
- Ô **Tối đa cuộn/đợt** lưu riêng cho từng máy: mặc định máy cách nhiệt 30,
  máy bao bì 16, ca chuẩn Đà Nẵng 10. Có thể giảm mức này, nhưng không vượt
  giới hạn của từng máy. Nếu Đà Nẵng
  dùng ca khác, đặt ô này về 10 cho từng máy.
- Bấm **Xác nhận đợt cân** để chốt số cuộn thực tế đã đồng bộ, kể cả trước
  mức tối đa. Đợt sau tiếp tục từ mốc đã chốt; các đợt cũ vẫn giữ nguyên.
- Chọn **2 lần · 4 cân**. Bấm ô cần chụp hoặc dùng `Space` để lần lượt cân lõi
  cặp 1, lõi cặp 2, thành phẩm cặp 1, thành phẩm cặp 2. Có thể bấm trực tiếp
  ô thành phẩm của cặp đã có lõi khi thành phẩm ra sớm. Với camera, ứng dụng
  đếm ngược 3 giây rồi mới lấy ảnh; số đếm không còn chạy sau lúc chụp.
- Khi cặp 1 đã có ảnh thành phẩm, số cân
  thành phẩm và mã QR, có thể lưu ngay; lõi cặp 2 vẫn chờ thành phẩm và không
  bị xóa. Nếu chưa cân lõi, vẫn lưu được thành phẩm; danh sách hiện ô lõi trống.
- `Backspace`: bỏ ngay lần đang xem, không hỏi xác nhận. Khi đang đặt con trỏ
  trong ô QR hoặc số cân, Backspace vẫn chỉ xóa ký tự như bình thường. Khi bỏ
  một ảnh/lượt lỗi, cặp đó tự chuyển về **Không lỗi** và xóa lý do lỗi cũ.
- Kiểm tra các số cân và ảnh đã chụp cùng mã SP trước khi lưu.
- `Enter`: lưu các cặp đã đủ dữ liệu, mỗi cặp là một event riêng. Số cân vượt
  ngưỡng cũ không tạo cảnh báo chặn lưu; vẫn kiểm tra ảnh và số cân trước khi lưu.
- Sau khi lưu, kiểm tra ngay dòng mới trong danh sách bên dưới. Trạng thái
  **Đang chờ** nghĩa là phiếu và ảnh đã lưu trên máy, đang gửi cloud ở nền.
  Bấm **Làm mới danh sách** để xem khi trạng thái chuyển thành **Đã đồng bộ**.
  Nếu mạng lỗi, ứng dụng tự thử lại; khi mở lại ứng dụng, bản ghi còn chờ vẫn
  được gửi tiếp. Giữ máy chạy và có mạng đến khi các dòng cần gửi đã đồng bộ.

Dữ liệu local, ảnh, SQLite và log nằm tại:

```text
%LOCALAPPDATA%\TramCanQR
```

Sao lưu toàn bộ thư mục này trước khi đổi máy, gỡ ứng dụng hoặc nâng cấp.

Đóng tab trình duyệt chưa dừng gateway nền. Trước khi khởi động lại hoặc nâng
cấp, mở **Task Manager**, chọn `TramCanQR.exe` và bấm **End task**; sau đó mở
lại shortcut. Không chạy hai bản gateway cùng lúc trên cổng 8080.

## 4. Đồng bộ cloud

Cloud là tùy chọn. Khi chưa cấu hình API, ứng dụng vẫn lưu local. Token ingest
và lookup riêng của từng trạm phải được đơn vị triển khai chuyển bằng kênh
riêng rồi điền vào `config.env` trên đúng máy.

Không đặt Cloudinary API secret, Supabase service-role key hoặc bất kỳ secret
quản trị nào trên máy khách. Máy khách chỉ dùng token thiết bị có quyền tối
thiểu.

## 5. Kiểm tra bàn giao tại xưởng

Trước khi ký nghiệm thu, thực hiện tối thiểu:

1. Chụp 100 lượt bằng ảnh thật độc lập ở đúng vị trí lắp đặt.
2. Kiểm tra đủ QR, cân, ảnh và đúng trạm/camera của từng lượt.
3. Thử mất mạng, retry, rút/cắm lại từng camera và khởi động lại máy.
4. Chạy liên tục ít nhất 60 phút trên đúng máy và hub USB sẽ sử dụng.
5. Xác nhận outbox về 0 sau khi mạng phục hồi.

Nếu số cân hoặc QR sai, không lưu tiếp hàng loạt. Giữ nguyên ảnh lỗi và file
log `%LOCALAPPDATA%\TramCanQR\logs\app.log` để hiệu chỉnh.

Hệ thống cố ý không tự nhận khi lõi nét LED nguồn thấp hơn 16 px hoặc các frame
không đồng thuận. Đây là trạng thái cần chỉnh lại góc/độ phân giải camera, không
được hạ ngưỡng để ép lưu.
