# Trạm cân QR Việt Nhật IPT — hướng dẫn cài đặt

Phiên bản: `0.2.0-rc77` — bản chạy thử nghiệm thu tại xưởng.

## 1. Cài đặt

1. Đóng bản đang chạy, sau đó chạy file `TramCanQR-Setup-0.2.0-rc77.exe`
   trên Windows 10/11 64-bit. Có thể cài đè bản cũ; `config.env` và dữ liệu
   trong `%LOCALAPPDATA%\TramCanQR` được giữ nguyên.
2. Ở lần cài đầu, chọn đúng **Trạm 01**, **Trạm 02**, **Trạm 03** hoặc
   **Trạm 04**. Trang chọn trạm được bỏ qua khi máy đã có `config.env`.
3. Installer tự mở file cấu hình. Điền kết nối Supabase/kho nếu cần đồng bộ, bấm **Ctrl+S** rồi
   đóng Notepad. Ứng dụng sẽ tự mở sau đó.
4. Nếu Windows SmartScreen cảnh báo, đối chiếu SHA-256 với file
   `SHA256SUMS.txt` do đơn vị triển khai gửi trước khi tiếp tục.
5. Nếu ứng dụng chưa tự mở, mở **Trạm cân QR** từ Desktop. Trình duyệt sẽ mở địa chỉ
   `http://127.0.0.1:8080`.
6. Chọn camera USB trong ứng dụng. Nhận diện chạy trên CPU, model đã kèm bộ cài; không cần key Gemini hoặc cài Python/CUDA.

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

### Chuyển từ Gemini sang local, giữ dữ liệu

Bấm **Cập nhật Trạm Cân QR** như trước hoặc cài đè bộ cài rc77. Dùng cùng tài
khoản Windows, giữ nguyên thư mục cài cũ; không cần gỡ ứng dụng. Lưu xong
lượt cân đang làm trước khi cập nhật. App vẫn là `TramCanQR.exe`, cổng `8080`,
DB/ảnh/cấu hình vẫn ở `%LOCALAPPDATA%\TramCanQR`. Không di chuyển hay nhập
lại dữ liệu. Các phiếu pending/failed và thông tin trạm/Supabase/kho được giữ.

Trước lần mở bản local đầu tiên (từ rc75), ứng dụng sao lưu SQLite (kể cả WAL) và cấu hình
vào `%LOCALAPPDATA%\TramCanQR\backups\before-local-rc75-*`. Ảnh dùng lại
đường dẫn gốc, không bị bộ cài ghi đè. Nếu sao lưu không thành công, ứng dụng
báo lỗi và chưa mở DB để vận hành. Các lần cập nhật sau vẫn dùng nút cũ.

Nếu cần quay lại Gemini, thoát `TramCanQR.exe`, cài lại bộ rc74 có số phiên
bản rồi mở ứng dụng. DB/ảnh vẫn dùng chung; cấu hình Gemini cũ không bị xóa.
Không chép đè DB từ bản sao lưu lên DB đang dùng vì sẽ mất các phiếu mới.
Bản thử riêng `TramCanQRAuto` không được gộp DB vào bản chính này.

### Camera và log lỗi

Từ rc76, driver camera Windows chạy trong tiến trình riêng. Danh sách USB
liệt kê các cổng để chọn, không mở thử đồng thời nhiều driver. Nếu một cổng
báo lỗi/không có hình, chọn lại đúng camera (thường USB 0 hoặc 1) và bấm Mở
camera. Thoát bản Gemini/beta1 nếu bản đó còn giữ camera.

Từ rc77, hình xem trước lấy trực tiếp từ camera, không chờ AI đọc số cân.
Ảnh xem trước được thu nhỏ để giảm tải; ảnh chụp phiếu cân/kiểm kho vẫn lấy
khung hình gốc. Driver thử lại khi hụt frame ngắn; mất kết nối thật sẽ tự mở
lại camera. Không chụp nếu không còn ảnh mới.

Nếu app vẫn tự tắt, lấy phần cuối `logs/app.log`, `logs/camera-driver.log`
và `logs/native-crash.log` trong `%LOCALAPPDATA%\TramCanQR` để kiểm tra.
Không xóa DB/ảnh hoặc gửi file cấu hình có key/token.

### Chụp tiếp khi AI đang đọc

Nhấn Space để chụp ô đang chọn. Sau khi ảnh được ghi xuống máy, ô đó hiện
**Ảnh đã lưu · chờ AI** và tự chọn ô còn thiếu tiếp theo. Có thể chụp tiếp ngay;
số cân tự điền vào đúng ô khi AI trả kết quả. Ô đang chờ AI chưa cho lưu phiếu
hoặc chụp đè. Ngày, ca, máy, LSX và Mã SP tạm khoá cho đến khi AI đọc xong.
Nếu AI lỗi, ảnh vẫn được giữ trên máy để đọc lại trong Danh sách.

Nếu AI chạy lâu hoặc treo, bấm **Hủy AI, bỏ ảnh** ngay trên ô đang chờ,
hoặc chọn ô đó rồi bấm **Bỏ** / **Backspace**. Chỉ bỏ ô đang chọn; ảnh và
số cân ở ô còn lại được giữ nguyên. Sau khi bỏ có thể chụp lại, kết quả AI
cũ trả về muộn không điền vào ảnh mới. Yêu cầu chưa gửi AI sẽ được gỡ khỏi
hàng đợi. Ảnh gốc đã lưu trên máy vẫn được giữ làm bản sao dự phòng.
Không cho bỏ lượt đã lưu phiếu hoặc trong lúc đang ghi ảnh/phiếu.

### Lưu từng lần cân

Trong mỗi thẻ **Lần 1**, **Lần 2**, bấm nút lưu ngay dưới thẻ để chỉ lưu
lần đó. Nhấn **Enter** hoặc nút **Lưu tất các lần** để lưu mọi lần đang có
dữ liệu. Mỗi lượt cần đủ hai ảnh lõi và SP. Nút **Lưu phiếu cân** ghi phiếu
chính thức cả khi chưa đọc được QR hoặc cân SP; hệ thống ghi trạng thái/lý do
lỗi. Nếu AI không đọc được ảnh lõi, cân lõi tự đặt 0; cân SP không đọc được
vẫn để trống. Ảnh lỗi AI vẫn được giữ riêng để đọc lại,
nhưng nút Lưu tạo phiếu cân chính thức.
Sau khi lưu thành công, ảnh của đúng lần đó biến mất để cân tiếp; lần khác
chưa lưu vẫn còn. Dòng **Đang chờ** trong danh sách nghĩa là bản ghi đã nằm
trong DB local và cần được đồng bộ thủ công lên Supabase/Cloudinary. Nếu màn hình
báo chưa lưu được ảnh, giữ nguyên ảnh và bấm lại nút để thử lại.
Xác nhận số cuộn là thao tác riêng, không ngăn lưu từng lần cân hay ảnh chờ.

### Sửa QR hoặc số cân trong bảng dưới

Tại **Danh sách lần cân**, bấm **Sửa tay** trên đúng dòng cần xử lý. Quét/nhập
Mã QR, kiểm tra cân lõi và cân SP rồi bấm **Lưu sửa**. Mã SP tự lấy từ Mã QR.
Cân lõi thiếu mặc định 0; bắt buộc có QR và cân SP, cân lõi không được lớn hơn
cân SP. Hai ảnh, thời gian chụp và danh tính lượt cân được giữ nguyên.
Lỗi thiếu QR/số cân được xoá sau khi sửa đủ; lỗi chất lượng ghi tay vẫn giữ
trừ khi người vận hành đổi Trạng thái lỗi.

Muốn đọc lại QR từ ảnh đã lưu: **Ảnh SP → Quét QR**. Bộ đọc giống lúc quét
camera; thao tác chỉ cập nhật QR của dòng đó, không chạy lại AI cân. Nếu QR
vẫn không đọc được, dùng **Sửa tay**. Thiếu QR hoặc cân SP vẫn là dòng lỗi.

### Popup nhắc đẩy kho

Ô nhỏ **Tối đa cuộn/đợt** là ngưỡng nhắc (ví dụ 30), không lấy số lớn ở
**Số lượng trong ca**. Khi có đủ phiếu hợp lệ đã đồng bộ Supabase và còn
chờ đẩy kho theo Ngày/Ca/Máy/LSX/Mã SP đang chọn, ứng dụng hiện
**Đã đủ 30 cuộn, vui lòng đẩy kho**. Popup ghi rõ số cuộn và nguồn cân.
Bấm **Đã hiểu**, kiểm tra bảng dưới và thao tác đẩy kho như bình thường.

Phiếu chưa đồng bộ, phiếu lỗi, ảnh chưa lưu thành phiếu và phiếu đã đẩy kho
không tính vào ngưỡng này. Cùng một đợt chờ không bị nhắc liên tục, kể cả
khi tải lại trang; sau khi đẩy kho, đợt tiếp theo đủ cuộn sẽ được nhắc lại.
Lịch tự đồng bộ vẫn là 10 phút/lần khi AI rảnh. Nút **Xác nhận đợt cân**
trong bảng lịch sử vẫn dùng được khi cần xác nhận thủ công.

### Đồng bộ thủ công

Từ bản `0.2.0-rc33`, ứng dụng không tự gửi dữ liệu local lên Supabase hoặc
Cloudinary. Sau khi lưu phiếu, mở tab **Danh sách**. Chọn **Từ ngày**, **Đến
ngày**, và nếu cần thì chọn **Ca**, nhập **Mã sản phẩm**, **Máy**, **Lệnh sản
xuất**. Tại mục **Đồng bộ local → Supabase / Cloudinary**, chọn phạm vi **Phiếu
cân và ảnh lỗi**, **Cân kiểm kho** hoặc **Tất cả dữ liệu local**. Bấm **Xem số
dòng chờ** để kiểm tra, rồi bấm **Đồng bộ theo bộ lọc** và xác nhận. Giữ ứng dụng
mở đến khi tiến độ kết thúc. Dòng báo lỗi hoặc còn chờ có thể đồng bộ lại bằng
cùng bộ lọc sau khi xử lý nguyên nhân. Bộ lọc máy, ca, LSX yêu cầu bản ghi có
đúng thông tin tương ứng; để trống nếu muốn lấy mọi bản ghi trong khoảng ngày.
Để trống **Mã sản phẩm** nếu cần đồng bộ cả xác nhận đợt cân.

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
được cấp cho đúng trạm đó. Nhận diện local không cần key Gemini. Đóng ứng dụng rồi mở lại sau
khi sửa. Không sao chép nguyên `config.env` từ máy 01 sang máy khác vì sẽ làm
trùng danh tính và gửi dữ liệu sang sai Supabase.

Mỗi camera chỉ được gán cho một trạm. Trên giao diện, chọn đúng camera ở từng
thẻ trạm rồi bấm **Mở camera đã gán**. Trình duyệt lưu ánh xạ này trên chính
máy khách.

Ô **Lệnh sản xuất** và **Mã SP** đều cho gõ tay hoặc bấm **▾** để xổ danh sách
gợi ý. Gõ để lọc, dùng **↑/↓** và **Enter** để chọn; vẫn nhập được mã ngoài
danh sách. Bấm **Áp dụng** để dùng thông tin đã chọn cho lần cân.

### Đẩy cân AI và kho chờ

Giữ nguyên `ROLL_SCALE_API_URL` và `ROLL_SCALE_DEVICE_TOKEN` của Supabase cân
AI. Thêm ba dòng sau vào `config.env`, thay URL và key kho bằng giá trị được cấp:

```dotenv
SUPABASE_KHO_DB_LABEL="kho"
SUPABASE_KHO_URL=https://YOUR_KHO_PROJECT_REF.supabase.co
SUPABASE_KHO_KEY=replace-with-kho-anon-or-publishable-key
```

Đóng ứng dụng rồi mở lại. Tại **Đẩy kho**, chọn kho thành phẩm, ngày, ca, máy,
mã SP và số cuộn; kiểm tra QR rồi bấm **Nhập kho**. Phần mềm xác nhận các QR
đã có trên Supabase cân AI trước khi tạo phiếu kho. `phieu_nhap` có trạng thái
`chua_chot`, các dòng `nhap_kho` là **Đang chờ**. Trạng thái **Đã nhập kho**
bên cân AI nghĩa là đã chuyển sang kho chờ; thao tác này chưa chốt phiếu kho.

Nếu kho đã nhận nhưng cập nhật cân AI lỗi, giữ bộ lọc và bấm **Nhập kho** lại.
Phần mềm dùng lại phiếu gắn với đúng lần cân đó, không thêm QR trùng.
Nếu key kho bị chặn quyền ghi, đơn vị triển khai cần kiểm tra RLS/quyền của
key trên `phieu_nhap` và `nhap_kho`.

Supabase cân AI cần Edge Function `ingest-measurement` bản rc48 trở lên để
cập nhật trạng thái bằng token thiết bị; đơn vị triển khai cập nhật API một
lần trước khi dùng bộ cài mới. Không cần thêm service-role key cân AI vào máy khách.

### Nhận diện YOLO local

Bản rc75 thay bộ nhận diện Gemini bằng model YOLO CPU đã kiểm thử trên ảnh
13,04 kg. Bản Windows dùng model đóng gói kể cả khi cấu hình cũ còn
`ROLL_SCALE_WEIGHT_ENGINE=gemini`; không cần sửa hoặc xóa key cũ.
Cân/QR chạy không cần mạng; đồng bộ Supabase và đẩy kho vẫn cần mạng.

Chọn ô lõi hoặc SP, bấm **Chọn ảnh từ thiết bị** để thử JPG/PNG/WebP/BMP
(tối đa 20 MB). Ảnh đi qua cùng luồng nhận diện và lưu phiếu như camera.
Chọn lại **Mở camera** để cân bằng USB. Ảnh thử không tự tạo phiếu; kiểm tra
kết quả rồi bấm Lưu khi muốn ghi phiếu chính thức.

## 3. Vận hành

- Máy local chỉ có một trạm nên không cần chuyển trạm bằng phím số.
- Ô **Ca** luôn có lựa chọn **Ca chuẩn Đà Nẵng**. Ô **Máy** cho chọn trong
  danh sách hoặc gõ tên máy mới, kể cả khi trạm đã có tên máy mặc định trong
  cấu hình. Nhập **LSX** rồi bấm **Áp dụng** trước khi cân.
- Ô **Tối đa cuộn/đợt** là ngưỡng nhắc đẩy kho, lưu riêng cho từng máy;
  không phải số cuộn cố định mỗi xe. Máy cách nhiệt, máy bao bì và máy khác
  đều cho nhập 1–30, mặc định 30 nếu chưa đặt mức. Không còn tự ép về 16.
  Mức đã nhập tay được giữ nguyên, kể cả 16; muốn nhắc ở 24 thì nhập 24.
  Ca chuẩn Đà Nẵng vẫn giữ giới hạn 10. Nếu Đà Nẵng dùng ca khác,
  đặt ô này về 10 cho từng máy.
- Bấm **Xác nhận đợt cân** để chốt số cuộn thực tế đã đồng bộ, kể cả trước
  mức tối đa. Đợt sau tiếp tục từ mốc đã chốt; các đợt cũ vẫn giữ nguyên.
- Chọn **2 lần · 4 cân**. Bấm ô cần chụp hoặc dùng `Space` để lần lượt cân lõi
  cặp 1, lõi cặp 2, thành phẩm cặp 1, thành phẩm cặp 2. Có thể bấm trực tiếp
  ô thành phẩm của cặp đã có lõi khi thành phẩm ra sớm. Với camera, ứng dụng
  lấy khung hình mới khi bấm chụp và đọc số/QR trên đúng ảnh đó.
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
  Nếu mạng lỗi, chọn lại bộ lọc rồi bấm đồng bộ thủ công; khi mở lại ứng dụng, bản ghi còn chờ vẫn
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

Khi có URL Supabase và token thiết bị, chương trình tự đẩy các dòng **Chờ đồng bộ**
mỗi 10 phút khi AI rảnh. AI chạy lại thì tạm dừng gửi các dòng tiếp theo. Phiếu
có lỗi cân/QR và ảnh nháp chưa thành phiếu giữ trên máy. Chỉ gửi dữ liệu Supabase,
không tự nhập kho hoặc đẩy ảnh Cloudinary. Dòng lỗi mạng cần dùng nút đồng bộ thủ
công để thử lại. Có thể tắt lịch tự đẩy bằng `ROLL_SCALE_AUTO_SYNC=0` trong
`config.env`, sau đó thoát hẳn ứng dụng và mở lại.

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
