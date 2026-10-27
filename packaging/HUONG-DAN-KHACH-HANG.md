# Trạm Cân QR — rc85 giữ ảnh cân thủ công

## Nâng cấp máy đang dùng rc80/rc82

1. Hoàn tất/lưu lượt cân đang làm và đóng bản OCR thử nếu đang mở cùng camera.
2. Bấm shortcut **Cập nhật Trạm Cân QR**. File cập nhật tự tải bản mới, kiểm tra
   SHA-256, đóng ứng dụng, cài đè rồi mở lại.
3. Hoặc tải **TramCanQR-Setup.exe** về cài đè đúng thư mục hiện tại.
4. Nếu trình duyệt còn hiện giao diện cũ, nhấn **Ctrl+F5**.

Không cần cài Python, GPU, API key, sao chép `.env` hoặc xóa dữ liệu.

## Cân khi mất Internet

- Mở ứng dụng tại `http://127.0.0.1:8080`, chọn đúng camera và vùng số cân.
- Chờ số ổn định, chọn ô và nhấn **Space**. Khi hiện **ĐÃ LƯU LOCAL**, số và
  ảnh đã được ghi trên máy; ứng dụng tự chọn ô còn thiếu tiếp theo.
- Đọc QR chạy sau bước lưu local. Nếu chưa có mã, dùng máy quét hoặc nhập mã
  rồi bấm **Lưu phiếu cân**. Phiếu được ghi local; Supabase đồng bộ sau khi có mạng.
- Nếu báo chưa xác nhận lưu local, Space thử lại đúng ảnh/ID. Bấm **Bỏ** để lấy
  ảnh mới. Không coi ảnh đang hiển thị là đã lưu khi chưa có xác nhận thành công.
- Camera DirectShow/Media Foundation mất hình sẽ thử mở lại đúng camera tối đa
  hai lần. Nếu vẫn lỗi, kiểm tra USB rồi bấm **Mở camera**. Các ô đã lấy được giữ.
- Lệnh sản xuất cần được chọn sẵn hoặc nhập tay nếu không tải được danh mục lúc
  mất mạng. Việc nhập kho và xác minh QR trên các máy khác cần mạng/đồng bộ sau.

## Giữ ảnh khi cân dao động

1. Bấm **Chụp ảnh / Giữ ảnh** ngay cạnh nút camera. Khung hình được giữ lại,
   OCR đọc một lần trên chính ảnh đó; các ô cân chưa thay đổi.
2. Kiểm tra số trên ảnh. Chọn ô cân lõi/SP cần lấy rồi nhấn **Space** hoặc
   nút **Chụp cân lõi / Chụp cân SP**. Chỉ khi hiện **ĐÃ LƯU LOCAL** thì ảnh
   và số đã ghi trên máy. Đây là lấy số thủ công, không xác nhận cân ổn định.
3. Bấm **Chụp lại** để lấy ảnh mới cho ô tiếp theo, hoặc **Tiếp tục live**.
   Mỗi ảnh chỉ dùng cho một ô cân; ảnh giữ quá 10 phút phải chụp lại.

## Phiếu đẩy kho

Bản in có tên **Phiếu đẩy kho từ trạm cân AI**, chữ ký **Công nhân SX** và
cột **Giờ đẩy** (giờ Việt Nam), lấy từ thời điểm đẩy kho đã lưu. Dòng cũ thiếu
thời điểm hiện `--`. Tên công nhân để ký/ghi tay; chưa tự điền trưởng máy.

Cài cho tài khoản Windows hiện tại. Bộ cài chưa ký số; chỉ dùng file từ repo
phát hành và checksum đi kèm, không tắt Defender.

## Dữ liệu cũ

DB, ảnh, bản nháp, metadata phiên, cấu hình trạm/cloud/kho vẫn ở
`%LOCALAPPDATA%\TramCanQR`. Tên EXE/thư mục cài/AppId/kênh cập nhật giữ như rc80.
Lần đầu rc82 sao lưu DB hiện tại (gồm WAL), config và metadata phiên chờ tại
`backups\before-rapidocr-rc82-*`; ảnh được giữ nguyên đường dẫn gốc.

Không lấy DB của bản cũ ghi đè lên dữ liệu hiện tại. Không đổi/xóa file
`config.env` khi nâng cấp. Dù config cũ còn ghi Gemini/YOLO, rc82 tự chọn OCR local
ở lúc khởi động; không dùng key Gemini để đọc cân.

## Camera và lấy số

1. Mở **Tram Can QR**. Giao diện ở `http://127.0.0.1:8080` trên chính máy xưởng.
2. Chọn **Camera 0**, **DirectShow**, bấm **Mở camera**. Thiếu hình: thử Camera 1/2
   hoặc đổi sang **Media Foundation** rồi mở lại. **Dừng** nhả camera.
3. Chọn **Trình duyệt** nếu muốn dùng danh sách camera/nguồn ảo của rc80.
   Có thể tiếp tục sử dụng cách gán camera và camera ảo đã có.
4. Bấm **Chọn vùng số cân**, kéo bao trọn đúng một dòng số, gồm chữ số đầu/cuối
   và dấu thập phân. Tránh lấy lẫn Tare/Net. **Esc** hủy thao tác chọn.
5. Hoặc bấm **Tự tìm LED đỏ** để phần mềm tự tìm vùng. Vùng chọn bằng tay
   được nhớ theo trạm/camera/driver trên trình duyệt hiện tại.
6. **Cân luôn có 2 số thập phân** mặc định bật, như bản Small đã thử tại xưởng:
   chuỗi `633` được diễn giải là `6,33 kg`. Tắt nếu muốn bắt buộc OCR thấy dấu
   thập phân và đủ hai số sau dấu. Đơn vị OCR hiện là **kg**.
7. Chờ hiện **ỔN ĐỊNH** sau ba lần đọc cùng số. Chọn ô **Cân lõi/Cân SP** của
   cuộn cần lấy, nhấn **Space** hoặc nút đọc ô cân. Số hiện tại được điền ngay;
   ảnh bằng chứng và số đến từ cùng khung hình, không OCR lại sau khi chụp.
8. Đối chiếu ảnh, số và QR. Lưu từng cuộn hoặc Enter/Lưu tất cả theo luồng rc80.

Đổi camera, dừng camera, đổi vùng hoặc đổi cách đọc thập phân sẽ bỏ kết quả live
cũ và chờ số mới. Kết quả quá 2,3 giây trên giao diện không được dùng cho Space.
Camera đổi vị trí thì chọn lại vùng LED.

**Xem chuỗi OCR** hiển thị kết quả đọc thô. **Mở ảnh thử…** chỉ đọc ảnh có sẵn,
không tự lưu phiếu; ảnh thử không được coi là kết quả live ổn định.
Ảnh backup có panel zoom phía dưới dễ hơn ảnh camera gốc; nên thử cảnh gốc.

## Các chức năng cũ

Giữ QR/máy quét QR, nhiều cuộn và cặp lõi–sản phẩm, trạng thái/lý do lỗi,
ghi chú, kiểm kho, danh sách, sửa/đọc lại, lọc bản ghi, đồng bộ Supabase,
đẩy kho, xử lý trùng và bản nháp. Luồng ghi/sync dữ liệu giữ như rc80.
Live preview không tự tạo phiếu hay ảnh chụp. Space/nút lấy số mới lưu ảnh
tạm; nút Lưu/Enter xác nhận phiếu theo luồng cũ.

Nhận diện chạy offline bằng **RapidOCR + PP-OCRv6 Small, CPU**. Internet cần
khi đồng bộ cloud hoặc tải cập nhật. Không cần trả phí API để đọc cân.

Model vẫn có thể nhầm chữ số dù ba khung hình cùng kết quả. Luôn đối chiếu số
trước khi lưu; nếu sai, chỉnh vùng/ánh sáng/góc camera hoặc nhập số đã đối chiếu.

## Cài máy mới

Windows 10/11 x64 → chạy **TramCanQR-Setup.exe** → chọn đúng trạm 01–10.
Mỗi máy tính chọn một số trạm khác nhau. Ví dụ máy thứ 10 chọn **Trạm 10**,
ứng dụng tạo `gateway-10`, `station-10`, `camera-10`; mỗi máy vẫn chạy một trạm.
Lần cài đầu tạo cấu hình riêng. Điền bộ Supabase/kho của trạm nếu cần đồng bộ;
không sao chép cấu hình nhận dạng trạm khác. Máy chỉ đọc cân local không cần key.

## Khi không có hình

- Đóng ứng dụng khác đang chiếm camera rồi mở lại; thử đúng số camera/driver.
- Kiểm tra Windows Settings → Privacy → Camera → cho phép desktop apps.
- Camera trình duyệt cần cho phép quyền camera ở Edge/Chrome.
- Nếu nguồn camera thay đổi, bấm Làm mới/gán lại nguồn hoặc dùng camera USB theo số.
- Đóng tab trình duyệt không đồng nghĩa thoát backend; camera native tự nhả
  khi không còn được trang giao diện hỏi hình trong khoảng 8 giây.

Log ứng dụng: `%LOCALAPPDATA%\TramCanQR\logs\app.log`.
Không gửi nội dung `config.env` hoặc API/token cho người không có quyền.
