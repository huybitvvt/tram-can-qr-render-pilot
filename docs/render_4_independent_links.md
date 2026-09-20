# Triển khai 4 link Render độc lập

`render.yaml` tạo bốn web service. Mỗi service chỉ phục vụ một trạm và có
process, hàng đợi nhận diện, SQLite/outbox, thư mục ảnh và Persistent Disk riêng.

| Link | Render service | `gateway_id` | `station_id` | Persistent Disk |
| --- | --- | --- | --- | --- |
| 1 | `tram-can-qr-pilot` | `render-pilot-01` | `station-01` | `tram-can-qr-data` |
| 2 | `tram-can-qr-pilot-02` | `render-pilot-02` | `station-02` | `tram-can-qr-data-02` |
| 3 | `tram-can-qr-pilot-03` | `render-pilot-03` | `station-03` | `tram-can-qr-data-03` |
| 4 | `tram-can-qr-pilot-04` | `render-pilot-04` | `station-04` | `tram-can-qr-data-04` |

Tên service đầu tiên được giữ nguyên để URL và disk hiện có không bị thay thế.
Mỗi service đặt `ROLL_SCALE_STATION_COUNT=1`; không cấu hình bốn station trong
cùng một process.

## Lưu và xóa ảnh sau 7 ngày

Cả bốn service đều đặt `ROLL_SCALE_LOCAL_RETENTION_DAYS=7`. Ảnh được commit vào
Persistent Disk riêng trước, nên lỗi Supabase/Cloudinary không làm mất ảnh local.
Maintenance chạy khi service khởi động và mỗi 24 giờ. Ảnh đủ ít nhất 7 ngày chỉ
được xóa sau khi API đối chiếu đúng event/checksum và xác nhận release; nếu API
lỗi hoặc không xác nhận thì file được giữ lại để thử tiếp. Việc release chỉ xóa
file/URL ảnh, không xóa hàng dữ liệu cân.

## Trình tự chuyển đổi

1. Thực hiện ngoài ca. Trên service hiện tại, chờ outbox về `0`, sao lưu SQLite
   và ảnh trên disk trước khi đổi cấu hình từ hai station về một station.
2. Sync Blueprint từ `render.yaml`. Không xóa service hoặc disk cũ.
3. Với Blueprint đã tồn tại, Render không hỏi lại các biến `sync: false` khi
   cập nhật. Mở **Environment** của từng service mới và đặt đủ:
   `ROLL_SCALE_GEMINI_API_KEY`, `ROLL_SCALE_GEMINI_BACKUP_API_KEY`,
   `ROLL_SCALE_API_URL`, `ROLL_SCALE_DEVICE_TOKEN`, `ROLL_SCALE_LOOKUP_URL` và
   `ROLL_SCALE_LOOKUP_TOKEN`.
4. Đặt `ROLL_SCALE_WEB_PASSWORD` cho từng service bằng Render Environment. Có
   thể dùng cùng mật khẩu vận hành, nhưng không ghi mật khẩu vào Git hoặc file
   tài liệu.
5. Auto-deploy đã tắt để một commit lỗi không tự triển khai lên cả bốn link.
   Deploy thủ công theo thứ tự 01 -> 02 -> 03 -> 04; chỉ chuyển sang link tiếp
   theo khi `/api/health` của link hiện tại trả HTTP `200`.
6. Mở từng URL trên đúng máy vận hành, cho phép camera và gán đúng camera của
   trạm đó. Vì mỗi URL có origin riêng, ánh xạ camera trong browser cũng tách
   riêng.

## Kiểm tra cô lập trước khi giao khách

1. Mở đồng thời cả bốn link và xác nhận mỗi link chỉ hiện đúng một station.
2. Chụp và lưu một event riêng trên từng link. So khớp `gateway_id`, `station_id`
   và `camera_id` trên Supabase.
3. Restart riêng service 04 trong Render. Trong thời gian service 04 restart,
   ba endpoint health của service 01-03 vẫn phải trả `200` và vẫn lưu local được.
4. Ngắt API Supabase thử nghiệm trên một service bằng cách dùng URL sai có kiểm
   soát. Event của service đó phải nằm trong outbox riêng; ba service còn lại
   vẫn đồng bộ bình thường. Khôi phục URL và xác nhận outbox được gửi hết.
5. Deploy một bản mới lên service 01 trước. Chỉ rollout ba service còn lại sau
   khi kiểm tra chụp, lưu, tra cứu và outbox trên service 01.

## Ranh giới còn dùng chung

Bốn process không thể kéo sập lẫn nhau và disk không dùng chung. Supabase vẫn là
kho tổng hợp chung, nên sự cố Supabase có thể làm cả bốn tạm ngừng đồng bộ/tra
cứu; thao tác commit local vẫn tiếp tục và outbox sẽ retry. Nếu bốn service dùng
chung một Gemini key thì quota AI vẫn dùng chung. Muốn cô lập quota AI, cấp key
Gemini khác nhau cho từng service.

Bốn web service và bốn Persistent Disk phát sinh chi phí riêng trên Render.
