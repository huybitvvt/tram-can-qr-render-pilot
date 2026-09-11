# Hệ thống offline ghép QR với số cân

Một gateway có thể vận hành 1–3 trạm camera logic trong cùng giao diện web. Mỗi trạm giữ preview, ảnh đang kiểm tra và danh tính riêng; tác vụ QR/OCR của các trạm đi qua một hàng đợi FIFO dùng chung để các thư viện nhận dạng không chạy chồng nhau. `Space` chụp cân lõi; sau đó `P` chụp cân sản phẩm và đọc mã SP trong cùng ảnh thứ hai. `Enter` commit mã SP + hai số cân + hai ảnh vào cùng một event SQLite/outbox.

Mã nguồn được tách theo ranh giới triển khai:

- `frontend/`: giao diện chạy trong trình duyệt.
- `backend/src/`: API Python, nhận diện, SQLite và hàng đợi đồng bộ.
- `backend/supabase/`: migration và Edge Functions.
- `tests/`: kiểm thử tích hợp cho cả hai phần.

Cloudinary + Supabase là lớp đồng bộ tùy chọn. Khi không cấu hình API, ứng dụng không gửi ảnh/dữ liệu lên Supabase. Nếu có cấu hình, hệ thống vẫn commit SQLite trước rồi mới đồng bộ; mất mạng không làm mất lần cân. Retry chỉ được coi là lặp an toàn khi danh tính, mã SP, số cân và hash của cả hai ảnh thuộc cùng `event_id` khớp chính xác. Ở chế độ Gemini primary, mỗi lần nhấn `Space` gửi đúng ảnh cân lõi lên Google để đọc số; ảnh thứ hai được QR decoder đọc và giữ làm bằng chứng mã SP.

## Kiến trúc đã triển khai

```text
Trình duyệt: station-01 -> deviceId camera A --+
             station-02 -> deviceId camera B --+--> Space: ảnh cân lõi + số cân
             station-03 -> deviceId camera C --+          |
                                                           +--> P: cân SP + mã SP
                                                                    |
                                                     cùng một event_id
                                                                    |
                                                         Enter xác nhận
                                                           |
                         SQLite + ảnh local + outbox (commit trước)
                                                           |
                                      retry nền, không chặn thao tác
                                                           |
                         Supabase Edge Function (device token)
                              |                         |
                        PostgreSQL                  Cloudinary
              mã + cân + hai URL ảnh       core-weight + product-qr
```

Đầu đọc QR USB HID/COM và cân RS232/USB vẫn dùng được với chương trình desktop một camera `roll-qr-scale.exe`. Giao diện web nhiều camera hiện dùng camera-OCR và một SQLite/outbox chung trên gateway.

### Danh tính và chống ghép nhầm

- `gateway_id`: máy tính/gateway ổn định; `device_id` chỉ là bí danh tương thích dữ liệu cũ.
- `station_id`: vị trí cân logic, ví dụ `station-01`; không đổi theo lần cắm USB.
- `camera_id`: tên camera logic đã cấu hình cho trạm, ví dụ `camera-01`. Đây không phải `deviceId` do trình duyệt cấp.
- Browser `deviceId`: khóa phần cứng dùng để ánh xạ camera thật vào một trạm. Ánh xạ được lưu local theo `gateway_id`, không gửi lên cloud và không được gán đồng thời cho hai trạm.
- `event_id`: UUID của đúng một lần chụp; được tạo trước khi phân tích và giữ nguyên qua mọi retry.
- `analysis_id`: lần phân tích server-side gắn với `event_id + station_id + camera_id` và ảnh JPEG đã staging.
- `frame_sha256`: SHA-256 của đúng byte JPEG bằng chứng; `payload_hash` là SHA-256 của payload bất biến đã chuẩn hóa.

Cùng QR có thể được cân nhiều lần bằng các `event_id` mới. Retry giống hệt cùng `event_id` trả về bản ghi cũ và không thêm hàng; nếu đổi ảnh, cân, thời gian, gateway, trạm, camera hoặc analysis cho cùng ID, SQLite và Edge Function từ chối conflict thay vì ghép nhầm.

YOLOv8 không giải mã nội dung QR và cũng không đọc số cân. Nó chỉ cần thiết khi QR nhỏ, nghiêng, có nhiều QR hoặc nền phức tạp: YOLO tìm vùng tem, ZXing/OpenCV giải mã nội dung, PaddleOCR v6 đọc riêng vùng màn hình cân. QR to và rõ thì bỏ YOLO sẽ nhẹ và đơn giản hơn. Model `yolov8n.pt` mặc định không có class QR.

## 1. Cài gateway Windows

```powershell
python -m venv .venv --system-site-packages
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\verify_yolov8.py
```

Tải model recognition-only `PP-OCRv6_medium_rec` đúng một lần khi còn Internet:

```powershell
.\.venv\Scripts\python.exe tools\make_test_frame.py
.\.venv\Scripts\roll-qr-scale.exe --source data\test_frame.png --weight-input camera --weight-roi 0.26,0.59,0.74,0.91 --ocr-download --once
```

Sau khi lệnh này hoàn tất, bỏ `--ocr-download`; model chạy từ ổ đĩa local. Ứng dụng không tải pipeline phát hiện chữ vì ROI LED đã được xác định trước. Máy hiện tại chạy PaddlePaddle CPU, không có NVIDIA/CUDA.

### Bộ chạy Windows không cần Python

Build bản portable và bộ cài bằng PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_windows.ps1
```

- Bản portable: `dist\TramCanQR\TramCanQR.exe` (phải giữ nguyên cả thư mục đi kèm).
- Bộ cài bản hiện tại: `dist\installer\TramCanQR-Setup-0.2.0-rc8.exe` khi máy build có Inno Setup 6.
- Dữ liệu vận hành được ghi tại `%LOCALAPPDATA%\TramCanQR`, không ghi vào thư mục cài đặt.
- Model OCR tiếng Anh và model QR demo được bundle để lần chạy đầu không cần tải Internet.

Khi bàn giao, chỉ gửi installer bản đúng phiên bản cùng
`packaging\HUONG-DAN-KHACH-HANG.md`, `packaging\customer-config.env.example` và
file SHA-256. Không gửi cả workspace, `data`, `runs`, `build`, `.test-tmp`,
database hoặc `.env` có secret. Installer hiện là bản pilot chưa ký
Authenticode; cần đối chiếu SHA-256 trước khi chạy.

## 2. Migration và deploy Supabase

Cần Node.js và một Supabase project. Với hệ thống đang chạy, dừng gateway và sao lưu SQLite + thư mục ảnh local, đồng thời tạo backup database Supabase trước khi nâng cấp. Sau đó chạy từ thư mục dự án theo đúng thứ tự: migration database trước, secret sau, Edge Function cuối.

```powershell
Set-Location backend
npx.cmd supabase@latest login
npx.cmd supabase@latest link --project-ref YOUR_PROJECT_REF
npx.cmd supabase@latest db push

$deviceToken = ..\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$lookupToken = ..\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
npx.cmd supabase@latest secrets set DEVICE_INGEST_TOKEN="$deviceToken"
npx.cmd supabase@latest secrets set DEVICE_LOOKUP_TOKEN="$lookupToken"
$cloudinaryCloudName = "YOUR_CLOUDINARY_CLOUD_NAME"
$cloudinaryApiKey = "YOUR_CLOUDINARY_API_KEY"
$cloudinaryApiSecret = "YOUR_CLOUDINARY_API_SECRET"
npx.cmd supabase@latest secrets set CLOUDINARY_CLOUD_NAME="$cloudinaryCloudName"
npx.cmd supabase@latest secrets set CLOUDINARY_API_KEY="$cloudinaryApiKey"
npx.cmd supabase@latest secrets set CLOUDINARY_API_SECRET="$cloudinaryApiSecret"
npx.cmd supabase@latest functions deploy ingest-measurement --no-verify-jwt --use-api
npx.cmd supabase@latest functions deploy lookup-roll --no-verify-jwt --use-api
Set-Location ..
```

`db push` áp dụng tuần tự toàn bộ [backend/supabase/migrations](backend/supabase/migrations), gồm schema ingest ban đầu, Cloudinary, bảng `can_tu_dong`, danh tính/hash, ảnh QR, kho OAuth Codex mã hóa, bảng một ảnh `can_kiem_kho` và bảng ảnh chờ `anh_can_cho_ai`. Build hiện tại không ghi bytes ảnh mới vào Supabase Storage để tránh vượt quota/egress Free plan. Nếu không dùng CLI, [backend/supabase_schema.sql](backend/supabase_schema.sql) là bản schema gộp để chạy có kiểm soát trong SQL Editor.

SQLite local tự thêm cột còn thiếu khi gateway mở database cũ và không xóa ảnh/bản ghi lịch sử. Hàng cũ giữ danh tính rỗng; hash được dựng lại từ hàng/ảnh hiện có khi có thể, còn ảnh legacy đã mất thì hash để rỗng thay vì bịa bằng chứng. `device_id` cloud cũ vẫn được đọc như fallback cho `gateway_id`, còn mọi capture mới phải mang bộ danh tính mới.

Schema tạo:

- `devices`: các gateway được phép ghi/được cập nhật thời điểm nhìn thấy.
- `rolls`: QR cuộn hàng và thời điểm nhìn thấy.
- `can_tu_dong`: lịch sử cân tự động append-only, unique theo `event_id`; ảnh cân lõi nằm trong `core_image_*`, ảnh QR thứ hai nằm trong `qr_image_*`. Các cột `image_*` vẫn trỏ ảnh cân lõi để tương thích bản cũ.
- `anh_can_cho_ai`: ảnh được tự lưu khi AI không đọc được/lỗi; QR có thể trống và không có cột số cân; trạng thái ban đầu là `awaiting_ai` để xử lý nối tiếp sau.
- `can_kiem_kho`: luồng song song chỉ chụp một ảnh/một khối lượng; lưu mã sản phẩm, khối lượng, khối lượng lõi nhập kèm, khối lượng bì và ảnh. Không tạo hoặc giả lập bước chụp cân lõi thứ hai.
- `measurements`: bảng cũ được giữ để tương thích; migration sao chép lịch sử sang `can_tu_dong` trước khi Edge Function chuyển bảng.
- `roll_scale_secrets`: chỉ service role được đọc/ghi; giữ payload OAuth Codex đã mã hóa để Render không mất đăng nhập khi redeploy.
- Bucket private `roll-captures` được giữ để tra cứu tương thích ảnh cũ; ingest mới không upload/download ảnh lên Supabase Storage. Ảnh được commit vào Render Persistent Disk trước khi gửi Cloudinary, nên lỗi Cloudinary/Supabase chỉ làm outbox retry, không làm mất ảnh hay row local.
- RLS bật; chỉ cấp `anon` quyền đọc hai bảng hiển thị trên giao diện. Mọi thao tác ghi vẫn phải đi qua Edge Function bằng device token.

Edge Function dùng secret key mặc định của môi trường Supabase (`SUPABASE_SECRET_KEYS`, có fallback cho project cũ dùng `SUPABASE_SERVICE_ROLE_KEY`) và ba secret Cloudinary. Gateway chỉ có `DEVICE_INGEST_TOKEN`; API secret Cloudinary và khóa bypass RLS không bao giờ đưa xuống trình duyệt/máy trạm.

Worker Render gọi `backup_maintenance` khi khởi động và mỗi 24 giờ. Worker đọc file local cũ ít nhất 7 ngày, chỉ gửi checksum + byte count (không gửi ảnh); Edge Function đối chiếu event/hash rồi mới xóa Cloudinary. Sau khi Edge xác nhận, worker xóa file local tương ứng, còn row cân vẫn giữ nguyên (URL ảnh được đặt null). Không tải bytes từ Supabase trong health check, không phát sinh egress định kỳ. Blueprint đã gắn Persistent Disk `/var/data`; nếu chạy ngoài Render phải trỏ `ROLL_SCALE_DATA_ROOT` vào ổ đĩa bền vững.

## 3. Cấu hình gateway

Không commit token vào Git. Với bản source/developer, đặt biến môi trường trong PowerShell:

```powershell
$env:ROLL_SCALE_API_URL = "https://YOUR_PROJECT_REF.supabase.co/functions/v1/ingest-measurement"
$env:ROLL_SCALE_LOOKUP_URL = "https://YOUR_PROJECT_REF.supabase.co/functions/v1/lookup-roll"
$env:ROLL_SCALE_DEVICE_TOKEN = $deviceToken
$env:ROLL_SCALE_LOOKUP_TOKEN = $lookupToken
$env:ROLL_SCALE_GATEWAY_ID = "gateway-01"
```

Giữ `ROLL_SCALE_GATEWAY_ID` ổn định cho đúng máy; không dùng ID trạm làm ID gateway. `ROLL_SCALE_DEVICE_ID` vẫn là alias tương thích nhưng không nên dùng cho cài đặt mới. Nếu mở cửa sổ PowerShell mới, phải đặt lại token hoặc lưu bằng cơ chế secret của Windows.

Với bản installer giao cho khách, dùng file `config.env` tại
`%LOCALAPPDATA%\TramCanQR\config.env` (mẫu là
`customer-config.env.example`). Chỉ đặt device/lookup token tối thiểu; không
đặt Cloudinary secret hoặc Supabase service-role key trên máy trạm.

## 4. Giao diện web 1/2/3 camera

Xem ranh giới an toàn và ma trận nghiệm thu đầy đủ tại [docs/multicamera_design.md](docs/multicamera_design.md).

Lệnh source mặc định vẫn chạy một trạm với ID `station-01` / `camera-01` để
giữ tương thích. Bản installer cho khách mặc định hiển thị ba trạm; số trạm
và ID được đặt trong `config.env`.

```powershell
.\.venv\Scripts\roll-test-ui.exe
```

Hai trạm:

```powershell
.\.venv\Scripts\roll-test-ui.exe `
  --gateway-id gateway-01 `
  --station-count 2 `
  --station-id station-01 --station-id station-02 `
  --camera-id camera-01 --camera-id camera-02 `
  --machine-id "Máy tái chế" --machine-id "Máy cách nhiệt"
```

Ba trạm:

```powershell
.\.venv\Scripts\roll-test-ui.exe `
  --gateway-id gateway-01 `
  --station-count 3 `
  --station-id station-01 --station-id station-02 --station-id station-03 `
  --camera-id camera-01 --camera-id camera-02 --camera-id camera-03 `
  --weight-burst-frames 5 `
  --inference-queue-size 8 --auto-advance
```

Nếu bỏ các `--station-id` và `--camera-id`, chương trình tạo lần lượt `station-01..03` và `camera-01..03`. Nếu truyền `--machine-id`, mỗi máy được khóa vào đúng một trạm/camera và mỗi cờ phải lặp đúng bằng `--station-count`. `--auto-advance` là mặc định; dùng `--no-auto-advance` nếu muốn giữ nguyên trạm sau khi lưu.

Mở `http://127.0.0.1:8080` rồi vận hành như sau:

1. Cho phép quyền camera, bấm `Làm mới camera`, sau đó chọn đúng camera vật lý trong dropdown của từng trạm. Không dựa vào thứ tự camera `0/1/2` của hệ điều hành.
2. Ánh xạ browser `deviceId` được lưu trong `localStorage` theo `gateway_id`. Một camera vật lý không thể gán cho hai trạm. Nếu đổi browser/profile/cổng USB làm `deviceId` đổi, chọn lại camera.
3. Bấm `Mở camera đã gán`. Khi camera rớt kết nối, card chuyển sang `MẤT KẾT NỐI`; giao diện chỉ thử lại đúng `deviceId` đã gán và từ chối stream nếu browser trả nhầm camera. Sự kiện cắm/rút USB cũng kích hoạt làm mới và reconnect.
4. Chọn trạm bằng card hoặc phím `1`, `2`, `3`. `Space` luôn chụp bước còn thiếu kế tiếp theo thứ tự: lõi lần 1 → sản phẩm lần 1 → lõi lần 2 → sản phẩm lần 2. Khi AI đọc xong một bước, ảnh vẫn nằm trong ô bằng chứng nhưng khung lớn tự trở về camera live và chọn sẵn bước tiếp theo. Sau khi lưu xong phiên, thứ tự được đặt lại về lõi lần 1. QR được nhận diện độc lập từ ảnh hoặc có thể nhập/quét thủ công.
5. Kiểm tra hai số cân, hai preview bằng chứng và mã SP tự đọc. `Enter` chỉ lưu khi đủ hai số cân + hai ảnh + mã SP trong cùng event. Dùng `Bỏ lần đang xem` nếu thật sự muốn hủy cả phiên.
6. Sau khi SQLite commit thành công, tùy chọn auto-advance chọn trạm kế tiếp theo vòng tròn. Checkbox trên giao diện có thể đổi hành vi trong phiên hiện tại.

### Đọc đồng loạt bảng nhiều chỉ số

Chế độ này độc lập với luồng cân lõi/cân sản phẩm và chỉ hoạt động khi Gemini API
đang bật. Bấm `Bảng nhiều chỉ số`, mở camera cố định hoặc chọn một ảnh đúng góc lắp
thực tế, rồi thực hiện một lần:

1. Nhập tên chỉ số, ví dụ `Screw 1 - Temp 1`, bấm `Gán vùng`, rồi kéo khung chỉ
   quanh đúng một hàng số LED đang sáng. Không khoanh cả bộ điều khiển, hàng
   setpoint phía dưới, đèn trạng thái hoặc nút bấm.
2. Lặp lại cho tối đa 24 chỉ số. Cấu hình được lưu theo `station_id` trong
   `/var/data/captures/panel-regions.json` khi Render có Persistent Disk, đồng thời
   có bản cache trong trình duyệt để dùng khi API tạm mất kết nối.
3. Bấm `Đọc tất cả vùng`. Backend crop mọi vùng từ cùng một khung hình và gửi trong
   một request Gemini; kết quả trả về theo đúng tên từng chỉ số. Vùng không chắc chắn
   hiển thị `--`, không tự đoán.

Camera Wi-Fi/IP có thể dùng chung cho cân, QR và bảng nhiều chỉ số, hoặc chỉ dành cho
bảng. Thiết lập một lần trên từng PC vận hành:

1. Đặt camera EZVIZ và PC trong cùng mạng LAN. Giữ IP camera ổn định bằng DHCP
   reservation; không mở/forward cổng 554 ra Internet.
2. Cài và mở SplitCam trên PC. Trên trang web bấm `Mở camera`, nhập IP camera và mã
   xác thực 6 ký tự, rồi bấm `Tạo & sao chép RTSP`. Trang chỉ tạo URL trong bộ nhớ và
   clipboard của máy khách.
3. Trong SplitCam chọn `Media Layers +` → `IP Camera`, dán URL, bấm `Add` và kiểm tra
   đã có hình. Quay lại web, chọn camera ảo SplitCam, chọn `Cân + QR và Bảng nhiều chỉ
   số`, rồi bấm `Xác nhận kết nối`.
4. Nếu muốn giữ camera cân USB và chỉ dùng EZVIZ cho bảng, chọn `Chỉ Bảng nhiều chỉ
   số`. Có thể đổi lại nguồn tại phần `Nguồn camera cho bảng`.

Render redeploy không cần biến môi trường RTSP và không kết nối thẳng vào camera LAN.
Cấu hình nguồn nằm trong SplitCam, còn ánh xạ `deviceId` chỉ lưu trong browser profile
trên PC khách; vì vậy cùng PC + cùng browser profile thì không phải nhập lại mã sau
redeploy. Máy khách mới vẫn phải cài SplitCam và thêm RTSP một lần.

Không ghi URL RTSP, mã xác thực hoặc ảnh tem thiết bị vào Render Environment, Git hay
nội dung chat. Mã xác thực trong khung thiết lập bị xóa khi đóng và không được gửi tới
Render/Supabase; lưu ý clipboard tạm thời chứa URL đầy đủ sau khi bấm sao chép.

Camera phải giữ nguyên vị trí sau khi gán. Nếu camera bị xoay, zoom, đổi độ phân giải
hoặc bảng bị dịch chuyển, xóa và gán lại vùng. Mỗi ảnh gửi Gemini gồm crop gốc và bản
lọc LED đỏ/xanh để giảm nhầm các đoạn số xám chưa sáng.

Nút `Dùng ảnh demo kho` nạp QR `ROLL-WAREHOUSE-002015` và cân `20.15 kg` vào trạm đang chọn. Chọn tệp ảnh cũng tự phân tích tại trạm đang chọn. Khi đã cấu hình cloud, outbox gửi nền sau commit local; lỗi mạng không làm request lưu tại trạm thất bại. YOLO là tùy chọn, còn QR rõ được ZXing/OpenCV giải mã trực tiếp.

Token Supabase chỉ nằm trong backend Python, không được đưa xuống JavaScript. Camera trình duyệt hoạt động trên `localhost`; mặc định server không mở ra mạng LAN. Các preview camera có thể chạy đồng thời nhưng CPU QR/OCR cố ý chỉ có một worker, vì vậy phải đo thông lượng thực tế trước khi dùng ba camera.

Sau khi camera đã bắt cố định, nên cấu hình ROI hàng gross riêng cho từng trạm để không dò lại vùng LED mỗi lần:

```powershell
.\.venv\Scripts\roll-test-ui.exe `
  --station-count 3 `
  --weight-roi 0.4500,0.8000,0.5400,0.8500 `
  --weight-roi 0.4450,0.7950,0.5350,0.8450 `
  --weight-roi 0.4550,0.8050,0.5450,0.8550 `
  --weight-burst-frames 5
```

Các tọa độ trên chỉ minh họa. Mỗi `--weight-roi` phải ôm riêng hàng gross, không chứa hai hàng `0.00` phía dưới. Thứ tự ROI phải khớp thứ tự `--station-id`. Nếu không cấu hình, backend dùng consensus vị trí LED trên toàn burst. ROI nguồn có lõi nét LED thấp hơn 16 px bị từ chối thay vì phóng lớn rồi đoán; khi lắp thật vẫn nên đạt 35 px trở lên.

Chạy giao diện với pipeline YOLO-first sau khi có `best.pt`:

```powershell
.\.venv\Scripts\roll-test-ui.exe --yolo-model models\qr_demo_synthetic.pt --yolo-imgsz 320
```

Chạy nhanh bằng dòng lệnh:

```powershell
.\.venv\Scripts\python.exe tools\make_test_frame.py
.\.venv\Scripts\roll-qr-scale.exe --source data\test_frame.png --weight-input camera --weight-roi 0.26,0.59,0.74,0.91 --once
```

Kết quả kiểm tra chuẩn là `QR='ROLL-DEMO-0001' WEIGHT=125.4 kg STABLE=True`. Tọa độ ROI trên chỉ dành cho ảnh demo.

Nếu đã cấu hình Supabase, lệnh trên ghi local rồi gọi Edge Function. Nếu chưa cấu hình, nó chỉ ghi `data\measurements.db` và `data\captures`.

## 5. Chạy đầu đọc QR, camera và cân thật

### Camera đọc cả QR và màn hình cân

Đây là luồng đúng cho yêu cầu không nhập cân và không chạy AI liên tục:

```powershell
.\.venv\Scripts\roll-qr-scale.exe --source 0 --qr-input camera --weight-input camera --weight-roi 0.40,0.58,0.82,0.86 --ocr-min-confidence 0.60
```

`--weight-roi` là `x1,y1,x2,y2` theo tỷ lệ khung hình từ 0 đến 1. Bốn số trong ví dụ chỉ minh họa; phải thay bằng vùng ô vàng `WEIGHT OCR ROI` ôm sát phần chữ số trên màn hình cân thật và không chứa chữ/nút/đơn vị nếu có thể.

Thao tác mỗi lần cân:

1. Đặt hàng và tem QR trong khung hình, chờ số cân đứng yên.
2. Nhấn `Space`: ứng dụng chụp đúng một ảnh rồi đọc QR + số cân offline.
3. Kiểm tra mã, số cân và độ tin cậy trên cửa sổ.
4. Đúng thì nhấn `Enter` để lưu; sai thì chỉnh vị trí/ánh sáng và nhấn `Space` chụp lại.

Camera có thể mở cả ca, nhưng YOLO/PaddleOCR không chạy liên tục. Chế độ `local`/`hybrid` chỉ lấy burst khi bấm chụp; mặc định chụp 5 frame rồi chọn đúng 3 frame đầu–giữa–cuối. Chế độ `gemini` ưu tiên camera 1920×1080 và gửi toàn ảnh JPEG cạnh tối đa 1600 px ở media resolution cao trong lần gọi đầu tiên. Nếu Gemini trả kết quả hợp lệ nhưng không đọc được toàn ảnh, backend mới tự dò LED và thử lại crop đúng một lần; lỗi mạng/timeout không bị gọi lặp. Chế độ CLI `roll-qr-scale` vẫn đọc một ảnh như trước.

### Gemini fallback tùy chọn

Không đặt API key trên dòng lệnh hoặc trong JavaScript. Với source/developer, đặt key trong biến môi trường của tiến trình rồi bật fallback:

```powershell
$env:ROLL_SCALE_GEMINI_API_KEY = "YOUR_GOOGLE_AI_STUDIO_KEY"
$env:ROLL_SCALE_WEIGHT_ENGINE = "gemini"
$env:ROLL_SCALE_GEMINI_MODEL = "gemini-3.5-flash-lite"
$env:ROLL_SCALE_GEMINI_37_MODEL = "gemini-3.7-flash"
$env:ROLL_SCALE_GEMINI_ACCURATE_MODEL = "gemini-3.1-pro-preview"
$env:ROLL_SCALE_GEMINI_TIMEOUT = "10.0"
$env:ROLL_SCALE_GEMINI_37_TIMEOUT = "30.0"
$env:ROLL_SCALE_GEMINI_ACCURATE_TIMEOUT = "30.0"
.\.venv\Scripts\roll-test-ui.exe
```

Giao diện có bốn profile Gemini độc lập: `fast` dùng Gemini 3.5 Flash-Lite với
thinking `minimal`; `flash31` dùng Gemini 3.1 Flash-Lite và là mặc định ổn định;
`flash37` dùng Gemini 3.7 Flash với thinking `low`; và `accurate` dùng model Pro
với thinking `medium`.
Lựa chọn model không thay đổi luồng QR độc lập hoặc quy tắc chỉ gửi Supabase
sau khi đủ hai ảnh cân và mã sản phẩm.

`ROLL_SCALE_WEIGHT_ENGINE` có ba chế độ: `local` chỉ dùng Paddle, `hybrid`
dùng Paddle trước rồi Gemini xác nhận ứng viên local, và `gemini` dùng Gemini
làm bộ đọc chính. Ở chế độ `gemini`, mỗi lần chụp gửi một ảnh bằng chứng toàn
khung; Gemini tự tìm màn hình cân trong ngữ cảnh ảnh. Crop LED chỉ là retry.
Paddle không preload hoặc suy luận. Mã SP do BarcodeDetector trên trình duyệt
và ZXing backend đọc độc lập; nếu hai nguồn khác nhau, hệ thống không tự điền mã.

Luồng hybrid chấp nhận theo kiểu fail-closed:

1. PaddleOCR local đọc ba frame trong một batch. Nếu 3/3 khớp, chốt ngay và không gọi mạng.
2. Nếu local chỉ có một ứng viên duy nhất đạt 2/3, Gemini đọc ba frame đầy đủ.
3. Chỉ chốt khi Gemini trả đúng định dạng hai số thập phân, ba ảnh đồng nhất và giá trị khớp tuyệt đối ứng viên local.
4. Gemini lỗi, timeout, trả khác local hoặc không có ứng viên local thì không lưu tự động; giao diện giữ trạng thái cần kiểm tra.

Ngưỡng OCR `0.60` chỉ là cổng loại kết quả Paddle quá yếu, không phải xác suất hệ thống đúng 60%. Điều kiện quyết định chính là đồng thuận số tuyệt đối qua các frame. Free tier/quota và đơn giá Gemini có thể thay đổi. Ảnh camera vẫn được xử lý qua dịch vụ cloud khi bật Gemini, nên chỉ bật sau khi khách hàng chấp thuận chính sách dữ liệu và không coi cloud là phụ thuộc bắt buộc.

### Codex đăng nhập ChatGPT

Gemini API vẫn là lựa chọn mặc định và không bị thay thế. Máy local mặc định
dùng Codex CLI đã đăng nhập:

```powershell
codex login --device-auth
codex login status
$env:ROLL_SCALE_WEIGHT_ENGINE = "gemini"
$env:ROLL_SCALE_CODEX_ENABLED = "true"
.\.venv\Scripts\roll-test-ui.exe
```

Trong giao diện chọn `AI -> Codex · ChatGPT`; có thể đổi lại `Gemini API` bất
cứ lúc nào. Codex chỉ đọc ảnh cân, còn QR vẫn do bộ giải mã QR độc lập xử lý.
Mỗi lần gọi dùng thư mục tạm, sandbox read-only, không nạp cấu hình/rules cá
nhân và không lưu session. Không sao chép hoặc đưa `~/.codex/auth.json` lên Git.

Render dùng device-code OAuth trực tiếp trên web (`ROLL_SCALE_CODEX_MODE=oauth`).
Sau khi chạy migration và deploy lại `ingest-measurement`, bấm `Đăng nhập
ChatGPT / Codex`, nhập mã trên trang OpenAI rồi xác nhận. Token không được trả
về browser; backend mã hóa toàn bộ payload bằng Fernet trước khi gửi qua Edge
Function vào `roll_scale_secrets`. Mặc định khóa được dẫn xuất từ
`ROLL_SCALE_DEVICE_TOKEN`; nếu đặt `ROLL_SCALE_CODEX_TOKEN_KEY` riêng thì phải
giữ nguyên khóa đó qua mọi lần deploy. Đây là tích hợp endpoint ChatGPT nội bộ,
không phải OpenAI API ổn định dành cho production; OpenAI có thể thay đổi luồng
hoặc giới hạn tài khoản. Khi Codex lỗi, chọn lại Gemini API để tiếp tục vận hành.

Hai mục `Key ca ngày · 12C1` và `Key ca đêm · 12C2` cho phép quản trị thay key
mà không sửa biến môi trường và không redeploy. Backend tự chọn key từ ca của
từng request; không có nút chuyển key thủ công nên hai ca không thể dùng nhầm
key do trạng thái chung. Hai key được giữ riêng trong kho bí mật Supabase qua
các lần deploy. Backend kiểm tra key mới
trực tiếp với Google; chỉ khi hợp lệ mới
mã hóa Fernet và lưu qua Edge Function vào `roll_scale_secrets`, sau đó thay cả
reader Nhanh và Chính xác trong tiến trình đang chạy. Key hiện tại không bao giờ
được trả về browser. Nếu Supabase/Google lỗi, key cũ tiếp tục được dùng.

### Đọc cân qua RS232/USB

Phương án production ưu tiên: đầu đọc QR USB HID, cân ở `COM3`, camera bằng chứng số 0. Cấu hình scanner tự gửi phím `Enter` sau mỗi mã:

```powershell
.\.venv\Scripts\roll-qr-scale.exe --source 0 --qr-input hid --serial-port COM3 --baudrate 9600 --unit kg
```

Nếu đầu đọc QR xuất virtual COM ở `COM4`:

```powershell
.\.venv\Scripts\roll-qr-scale.exe --source 0 --qr-input serial --qr-serial-port COM4 --qr-baudrate 9600 --serial-port COM3 --baudrate 9600
```

Giữ cửa sổ camera được focus khi dùng scanner HID. Quét QR, chờ cân hiện `STABLE`, rồi nhấn `Space`. Chế độ HID dùng `Esc` để thoát vì ký tự `Q` có thể nằm trong mã QR. Sau khi lưu thành công, scanner được xóa trạng thái và bắt buộc quét cuộn tiếp theo.

Bật camera đọc dự phòng khi scanner chưa có mã:

```powershell
.\.venv\Scripts\roll-qr-scale.exe --source 0 --qr-input hid --camera-qr-fallback --serial-port COM3
```

Chạy camera-only để POC, không cần scanner:

```powershell
.\.venv\Scripts\roll-qr-scale.exe --source 0 --qr-input camera --serial-port COM3
```

Nếu chưa nối cân, có thể nhập cân tay trong chế độ camera. Chế độ HID chiếm bàn phím nên khi demo không có cân serial phải truyền cân ban đầu bằng `--weight 125.4`.

Gateway lấy trung vị ba mẫu cân gần nhất và mặc định yêu cầu độ lệch không quá `0.02 kg`:

```powershell
.\.venv\Scripts\roll-qr-scale.exe --source 0 --serial-port COM3 --stable-samples 5 --stability-tolerance 0.01
```

Gateway cho phép chụp liên tiếp cùng một QR: mỗi khung hình mới tạo một `event_id`, bản ghi Supabase và ảnh Cloudinary riêng. Trong `--duplicate-window` (mặc định 5 giây), hệ thống chỉ chặn khi đúng cùng một khung hình bị gửi lại; retry cloud bằng cùng `event_id` cũng không tạo bản ghi trùng.

Liệt kê cổng COM:

```powershell
Get-CimInstance Win32_SerialPort | Select-Object DeviceID,Name
```

## 6. Offline và retry

- Camera-OCR: `Space` chụp/đọc, `Enter` xác nhận rồi lưu SQLite và ảnh.
- Serial/manual: `Space` lưu SQLite và ảnh như trước.
- Bản ghi cần gửi có trạng thái `pending`.
- Mạng lỗi chuyển thành `failed`, lưu `sync_error`, tăng `retry_count`.
- Retry theo exponential backoff từ 2 giây, tối đa 5 phút.
- Khi Supabase xác nhận, trạng thái thành `synced` và lưu `remote_id`.
- Outbox lấy `gateway_id/station_id/camera_id` từ chính hàng đã commit; ID truyền vào worker chỉ là fallback cho dữ liệu legacy.
- Edge Function chỉ xử lý lặp an toàn khi cùng `event_id` có payload/hash/danh tính giống hệt; khác biệt trả conflict thay vì overwrite.

Ép gửi lại toàn bộ outbox mà không cần mở camera:

```powershell
.\.venv\Scripts\roll-qr-scale.exe --sync-only
```

Kiểm tra outbox:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect(r'data/measurements.db'); print(c.execute('select id,qr_code,weight,unit,sync_status,retry_count,sync_error from measurements order by id desc').fetchall())"
```

### Stress offline nhiều camera

Lệnh sau không dùng camera, Internet, Supabase hoặc Cloudinary. Nó tạo 100 event xác định theo vòng tròn trên ba trạm, retry giống hệt từng event, thử một conflict khác danh tính, ép 100 lần gửi thất bại bằng sender giả rồi bật sender giả trở lại để vét sạch outbox:

```powershell
$runDir = "runs\multicamera-offline-20260802"
.\.venv\Scripts\python.exe tools\stress_test_multicamera.py --run-dir $runDir
Get-Content "$runDir\multicamera_stress.json"
```

`--run-dir` là bắt buộc; script không có thư mục output ngầm và chỉ giữ file JSON `multicamera_stress.json` trong thư mục đã chỉ định. Mặc định là `--event-count 100 --station-count 3`; chỉ nhận 1–3 trạm. Exit code `0` khi `accepted=true`, `2` khi các bất biến không đạt.

Report ghi `station_counts`, `unique_events`, `duplicate_retries`, `identity_conflicts_rejected`, `cross_identity_mismatches`, `pending_before_recovery`, `synced_after_recovery`, `pending_after_recovery`, thời gian chạy và kết quả `accepted`. Gate mặc định yêu cầu phân bố `34/33/33`, đúng 100 hàng duy nhất, 100 retry không thêm hàng, conflict chéo danh tính bị chặn, pending trước recovery bằng 100 và sau recovery có 100 hàng synced/pending bằng 0.

## 7. YOLOv8 fallback

Pipeline mục tiêu khi có model custom:

```text
Camera → YOLO class qr → crop/upscale → ZXing/OpenCV → QR text → cân → Space → Supabase
```

Tạo dữ liệu tổng hợp để kiểm tra kỹ thuật pipeline:

```powershell
.\.venv\Scripts\python.exe tools\generate_synthetic_qr_dataset.py
.\.venv\Scripts\python.exe tools\train_qr_detector.py --device cpu
```

Dữ liệu tổng hợp không đủ để nghiệm thu tại xưởng. Trước production phải thu ảnh đúng camera, khoảng cách, loại cuộn, ánh sáng và độ cong của tem; gán nhãn bounding box class `qr`, trộn với dữ liệu tổng hợp rồi fine-tune theo [config/qr_dataset.yaml](config/qr_dataset.yaml).

Model demo hiện tại đã train 12 epoch trên dữ liệu tổng hợp. Validation của chính tập tổng hợp đạt `mAP50=0.995`, nhưng chưa có kiểm thử trên ảnh xưởng nên chưa được coi là model production.

Thu tối thiểu 300 ảnh thật từ ít nhất hai ngày/ca. Trong giao diện, sau mỗi lần nhận diện hãy sửa QR/số cân theo giá trị thật rồi bấm `Lưu mẫu đã kiểm tra`. Phải giữ cả trường hợp đọc được và không đọc được; nhãn tự động chỉ là nhãn nháp, cần duyệt lại bounding box trước khi train.

```powershell
.\.venv\Scripts\python.exe tools\prepare_factory_qr_dataset.py
.\.venv\Scripts\python.exe tools\train_qr_detector.py --data config\qr_factory_dataset.yaml --model models\qr_demo_synthetic.pt --epochs 80 --imgsz 640 --device cpu --name factory-v1
```

Script chuẩn bị dữ liệu tách train/validation theo ngày hoặc `session_id`, không chia ngẫu nhiên các frame gần giống nhau vào hai tập. Việc này tránh điểm validation cao giả do rò rỉ dữ liệu.

Ngoài tập train/validation, giữ riêng ít nhất 100 ảnh ở `dataset\factory_acceptance` với `images\` và `metadata\`. Mỗi metadata phải có `expected_qr_code`, `expected_weight`, `unit`. Không dùng tập này để train. Chạy nghiệm thu fail-closed:

```powershell
.\.venv\Scripts\python.exe tools\evaluate_factory_acceptance.py `
  --dataset dataset\factory_acceptance `
  --model runs\qr\factory-v1\weights\best.pt
```

Mặc định chỉ đạt khi 100% ảnh nghiệm thu đọc đúng tuyệt đối QR, số cân sai lệch không quá `0.001`, và ảnh vượt kiểm tra độ phân giải/độ sáng/độ nét. Một ca lỗi làm lệnh trả exit code `2` và chi tiết nằm tại `runs\factory_acceptance.json`.

```powershell
.\.venv\Scripts\roll-qr-scale.exe --source 0 --serial-port COM3 --yolo-model runs\qr\yolov8n\weights\best.pt --yolo-mode first
```

## 8. Checklist chạy thật tại xưởng

`multicamera_stress.json` chỉ nghiệm thu logic SQLite/outbox/danh tính với ảnh và sender giả. Kết quả `accepted=true` không chứng minh camera/USB, browser, OCR/QR, cân, mạng hoặc cloud thật đạt yêu cầu. Không được dùng report offline này làm biên bản nghiệm thu phần cứng hay cho phép production.

Trước khi vận hành chính thức phải nghiệm thu lại tại đúng máy, hub USB, 1/2/3 camera, cân và điều kiện xưởng sẽ triển khai:

1. Gắn cố định camera để một frame chứa trọn tem QR và màn hình cân; ưu tiên 1080p, không dùng autofocus liên tục nếu làm ảnh dao động.
2. Khóa vị trí cân, khoảng cách và ánh sáng; tránh phản xạ trực tiếp trên tem và LED.
3. Chụp thử ở mức cân thấp/cao, tem thẳng/nghiêng/cong/bẩn và ánh sáng đầu/giữa/cuối ca.
4. Xác nhận ảnh không bị chặn bởi kiểm tra chất lượng và ô xanh/vàng bao đúng QR/màn hình LED.
5. Chạy bộ nghiệm thu held-out ở trên; không chấp nhận sửa tay để làm đẹp kết quả test.
6. Thử mất mạng/mất điện: bản ghi phải còn trong SQLite/outbox và tự đồng bộ lại.
7. Chạy song song với quy trình cũ ít nhất một ca, đối chiếu từng lần cân trước khi bỏ quy trình cũ.
8. Với nhiều camera, xác nhận từng `deviceId` đúng trạm, rút/cắm lại từng camera và kiểm tra reconnect không chuyển nhầm card; thử lại sau khi restart browser và gateway.
9. Mở đồng thời toàn bộ preview ở độ phân giải dự kiến để kiểm tra băng thông USB, nguồn hub, nhiệt độ và tốc độ FIFO QR/OCR; chạy xen kẽ `Space`/`Enter` đủ lâu trên cả ba trạm.
10. Đối chiếu `gateway_id/station_id/camera_id/event_id` của từng ảnh local với hàng cloud sau một lần outage/recovery thật; không chấp nhận mất, trùng hoặc ghép chéo trạm.

Ứng dụng chặn lưu khi thiếu QR, thiếu số cân hoặc ảnh không đạt chất lượng. Nhân sự vẫn phải kiểm tra rồi nhấn `Enter`; đây là lớp chống ghi sai, không phải cam kết AI không bao giờ lỗi.

## 9. Tra cứu số cân bằng QR

Tra cứu một mã từ dòng lệnh:

```powershell
.\.venv\Scripts\roll-lookup.exe --qr "ROLL-DEMO-0001"
```

Đầu đọc QR USB HID thường tự gửi `Enter`, nên có thể chạy chế độ nhập liên tục:

```powershell
.\.venv\Scripts\roll-lookup.exe
```

Hoặc mở giao diện tra cứu nội bộ, sau đó vào `http://127.0.0.1:8080` và quét QR vào ô đang focus:

```powershell
.\.venv\Scripts\roll-lookup.exe --serve
```

Ứng dụng trả về lần cân `confirmed` mới nhất theo `captured_at`, gồm gross, tare, net, thời điểm, tổng số lần cân và URL ảnh Cloudinary trong thời gian giữ 7 ngày. Sau retention, row vẫn tra cứu được nhưng ảnh có thể không còn URL. Toàn bộ lịch sử production nằm trong `can_tu_dong`; index tra cứu bảo đảm dữ liệu offline gửi lên muộn không thay thế nhầm lần cân mới hơn.

Token tra cứu tách khỏi token ghi dữ liệu. Giao diện local proxy request qua Python nên không đưa token vào JavaScript. Mặc định chỉ bind `127.0.0.1`; không dùng `--host 0.0.0.0` ra mạng xưởng khi chưa có HTTPS, đăng nhập và kiểm soát firewall.

Có thể giải mã QR từ một ảnh rồi tra cứu:

```powershell
.\.venv\Scripts\roll-lookup.exe --image data\test_frame.png
```

## 10. Google Colab

[YOLOv8_QR_Can_Colab.ipynb](YOLOv8_QR_Can_Colab.ipynb) dùng để demo webcam trình duyệt hoặc huấn luyện. Colab không truy cập trực tiếp COM/USB của cân tại xưởng, nên không dùng làm runtime production.

## 11. Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests\test_multicamera_stress.py -q
```

Test bao phủ QR HID, capture gate, chống trùng/danh tính, session nhiều trạm, hàng đợi inference FIFO, ZXing/OpenCV/YOLO fallback, parser cân serial, ROI + OCR số cân, SQLite, outbox retry/recovery, HTTP upload ảnh, lookup API client và callback Colab/Supabase.

## 12. Luồng vận hành hoàn chỉnh

1. Công nhân chọn đúng trạm, đặt cuộn hàng lên cân và đưa QR + màn hình cân vào đúng camera đã ánh xạ.
2. Nhấn `Space`: ảnh của riêng trạm đó được đóng băng, gắn danh tính và đưa vào FIFO nhận dạng offline.
3. Công nhân đối chiếu rồi nhấn `Enter`; ảnh + QR + số cân + danh tính được commit vào SQLite. Auto-advance có thể chuyển sang trạm kế tiếp sau commit thành công.
4. Outbox tự gửi sự kiện lên Edge Function; Supabase lưu row/metadata, Cloudinary lưu ảnh delivery và Render Persistent Disk giữ evidence độc lập trong 7 ngày. Cloudinary lỗi thì sự kiện ở outbox để retry.
5. Ở trạm tra cứu, người dùng quét cùng QR bằng đầu đọc USB.
6. `lookup-roll` trả lần cân hợp lệ mới nhất và ảnh bằng chứng.

## Thông tin phần cứng vẫn cần để lắp thật

1. Ảnh gốc từ camera thật có cả QR và màn hình cân, không nén qua Zalo/Messenger.
2. Vị trí ROI màn hình cân và dạng hiển thị thực tế: LCD/LED 7 đoạn, số chữ số, dấu thập phân, đơn vị.
3. Nếu dùng cổng cân: model cân, baud rate và vài dòng raw output.
4. Quy tắc nghiệp vụ gross/net/tare và có cho phép cân lại cùng QR hay không.

Lưu ý giấy phép: Ultralytics phát hành code/model theo AGPL-3.0; hệ thống nội bộ đóng nguồn hoặc thương mại cần rà soát Enterprise License trước production.
