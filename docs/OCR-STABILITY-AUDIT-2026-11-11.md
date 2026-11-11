# Kiểm tra OCR cân và Small/Medium — 11/11/2026

Đã xác nhận một lỗi trong tiền xử lý ảnh của ứng dụng: dùng ngưỡng kênh
xanh lá để xác định biên LED đỏ có thể cắt mất chữ số đầu vẫn còn trên ảnh.
Đã sửa tại `backend/src/tramcan_rapidocr/regions.py` để tính ngưỡng trên kênh đỏ.
Chưa xác nhận đây là nguyên nhân duy nhất của hai video tại máy xưởng.

## Bằng chứng và phạm vi

- Hai MP4 được cung cấp dài 46,33 và 49,70 giây, 720×1280, khoảng 30 fps.
  Đây là video điện thoại quay màn hình ứng dụng, không phải camera gốc.
- Video có hiện tượng số đúng 1,06/1,08 xen kẽ không có kết quả, cả DirectShow
  và trình duyệt. Cả hai đều hiển thị vùng LED chọn bằng tay.
- Trích 184 vùng hiển thị LED, lấy mỗi 15 khung hình. Chấm 176 mẫu đã đối
  chiếu, loại 8 mẫu trong khoảng đổi giá trị ở video 1. Không coi các mẫu
  tương quan từ hai cảnh là phép đo độ chính xác tại xưởng.
- Model Small với source trước và sau sửa đều đúng 79/79 và 97/97 mẫu được
  chấm. Không tái hiện lỗi của camera gốc từ các crop quay lại màn hình này.
  Việc quay màn hình, phóng hình và nén video đã thay đổi đầu vào.

## Lỗi tái hiện được bằng model thật

Tạo ảnh bảy đoạn với chữ số đầu vẫn có kênh đỏ 180–200 nhưng kênh xanh lá
0–25; các chữ số còn lại sáng hơn ở kênh xanh lá. Source cũ cắt mất chữ số đầu:

| Ảnh tổng hợp gốc | OCR sau bước cắt cũ | Kết quả cũ | Sau sửa |
| --- | --- | --- | --- |
| 1,06 | `06` | Từ chối | 1,06 |
| 1,08 | `08` | Từ chối | 1,08 |
| 2,08 | `08` | Từ chối | 2,08 |
| 7,08 | `08` | Từ chối | 7,08 |
| 13,04 | `304` | Sai thành 3,04 | 13,04 |

15 trường hợp nhận diện thật mới đều thất bại trước sửa và đạt sau sửa.
Đây là lỗi do ảnh đầu vào bị cắt sai; không chứng minh model upstream bị hỏng.
Việc mất kết quả làm bộ đọc live xóa chuỗi xác nhận, nên số đúng trước đó
không đủ để đạt ổn định nếu các lần đọc bị ngắt quãng.

Thay đổi giữ nguyên hai lượt OCR màu/xám, ngưỡng tin cậy và điều kiện live:
ít nhất ba kết quả bằng nhau trong ít nhất 450 ms. Không thay thế chữ số,
không giữ số cũ để chụp và không thay đổi đồng bộ hoặc dữ liệu nghiệp vụ.

## Phiên bản và khuyến nghị model

Đối chiếu GitHub Releases API và PyPI ngày 11/11/2026: RapidOCR mới nhất
vẫn là **3.10.0**, phát hành 08/10/2026, đúng bản repo ghim. Medium là cấu hình
lớn hơn của cùng PP-OCRv6, không phải bản vá mới cho hiện tượng trong video.
Các file Small/Medium tải để thử đều được kiểm tra SHA256 theo manifest repo.
Không xác minh được phiên bản hoặc checksum của EXE đang chạy trong video.

Theo [bảng thử của tác giả RapidOCR](https://rapidai.github.io/RapidOCRDocs/latest/blog/2026/06/18/rapidocr-%E9%9B%86%E6%88%90-pp-ocrv6-rec-%E6%A8%A1%E5%9E%8B%E8%AE%B0%E5%BD%95/),
với RapidOCR + ONNX Runtime trên CPU:

| Chỉ số | Small | Medium |
| --- | ---: | ---: |
| Đúng toàn chuỗi | 84,19% | 86,13% |
| Đúng ký tự | 95,15% | 94,91% |
| Thời gian nhận diện | 14,3 ms | 51,5 ms |
| Dung lượng model tác giả nêu | Khoảng 20 MB | Khoảng 73 MB |

Medium tăng 1,94 điểm phần trăm về đúng toàn chuỗi và chậm khoảng 3,6 lần
trong phép đo đó. Bộ dữ liệu là `SWHL/text_rec_test_dataset`, không phải bộ
nghiệm thu số cân LED. Không suy từ bảng này rằng Medium chắc chắn ổn định
hơn trên camera cụ thể. Dung lượng file không phải phép đo RAM khi chạy.

Đã thử cả hai profile với 16 crop chọn đều từ hai video trên i3-1215U,
ONNX Runtime, hai thread và hai lượt OCR mỗi crop. Kết quả chi tiết ở
`.local/ocr-investigation-20261111/profiles.jsonl`; đây là thử cục bộ,
không so trực tiếp thời gian với một lượt OCR trong bảng của tác giả.

| Thử cục bộ với source đã sửa | Small | Medium |
| --- | ---: | ---: |
| Đọc đúng | 16/16 | 16/16 |
| Trung vị mỗi crop, hai lượt OCR | 62,3 ms | 1.945,0 ms |
| Lâu nhất, gồm lần đầu | 300,0 ms | 3.191,7 ms |
| Số lượt trên 2,5 giây | 0 | 3 |

Đây là thời gian của toàn bộ `read_crop`, không phải chỉ riêng phép suy luận.
Chưa đo RAM đỉnh. Các lượt Medium trên 2,5 giây vượt điều kiện độ mới mà live
hiện tại cho phép; tăng model có thể làm khó đạt ổn định vì chậm xử lý.

Khuyến nghị hiện tại: giữ Small cho live sau khi sửa bước cắt ảnh. Chưa có
bằng chứng đủ để đổi mặc định sang Medium. Cần đánh giá trên ảnh/luồng camera
gốc gồm số âm, số 0, đổi giá trị, LED thiếu nét và ánh sáng thực tế trước khi
chọn Medium hoặc dùng Medium xác nhận bổ sung.

## Kiểm chứng source trước khi đóng gói

- Môi trường thử riêng trong `.local/ocr-investigation-20261111/venv`, cài
  dependencies đúng `pyproject.toml`; không nâng cấp `.venv` sẵn có.
- 102 test Python đạt: OCR với model Small thật, live/capture và cân hàng hỏng.
  Trong đó có 19 trường hợp mới về chữ số đỏ ít xanh lá, dấu âm/dấu thập phân
  và live ổn định khi màu chữ số thay đổi; có kiểm tra lấy đúng ảnh đã đọc.
- 9 test Node cho lấy số live và từ chối kết quả cũ/thay camera/vùng LED đạt.
- `pip check` và `git diff --check` đạt.
- Chưa build, phát hành hoặc cài đè ứng dụng. Chưa thử camera USB thật hoặc
  đo vận hành cả ca. Chưa thể khẳng định đã xử lý mọi nguyên nhân trong video.

Nguồn phiên bản: [RapidOCR Releases](https://github.com/RapidAI/RapidOCR/releases/tag/v3.10.0),
[PyPI](https://pypi.org/project/rapidocr/).

Kết quả đóng gói và kiểm chứng bản phát hành rc92 được ghi riêng tại
[validation-rc92.md](validation-rc92.md).
