# Đếm cuộn ra máy từ video realtime

Tra cứu nguồn ngày 29/10/2026. Đây là đề xuất kỹ thuật, chưa tích hợp detector,
chưa tải weights hoặc train model, chưa đo trên video xưởng.

## Kết luận

Có thể xây dựng bằng nguồn mở. Cần **nhận diện cuộn → theo dõi ID qua các frame
→ xác nhận đi qua vùng/vạch ra máy đúng hướng → tăng bộ đếm một lần**.
Đếm số bounding box từng frame rồi cộng lại sẽ đếm trùng.

Đề xuất thử **RF-DETR Nano + ByteTrack + Supervision LineZone** làm nhánh
ưu tiên độ nhận diện; đối chứng **YOLOX-Nano/Tiny + cùng tracker/counter**
trên máy Windows CPU. Đây là lựa chọn để thử, chưa phải kết luận model tốt nhất.
Model thắng phải có ít cuộn đếm thiếu/trùng trên video xưởng và đáp ứng độ trễ thực tế.

## Nguồn có thể ghép

| Thành phần | Nguồn tác giả / giấy phép | Nhận định cho dự án |
| --- | --- | --- |
| RF-DETR Nano/Small | [Repo Roboflow](https://github.com/roboflow/rf-detr), Apache 2.0 cho các bản này | Có weights và fine-tuning. Nano khoảng 30,5M tham số; cần benchmark CPU. Không áp giấy phép này cho toàn bộ họ RF-DETR: Atto/Femto/Pico/XL/2XL được repo hiện tại ghi PML 1.0. |
| YOLOX-Nano/Tiny | [Repo Megvii](https://github.com/Megvii-BaseDetection/YOLOX), [Apache 2.0](https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE) | Có weights, triển khai ONNX/OpenVINO. Nano 0,91M, Tiny 5,06M tham số. Suy luận kỹ thuật: đáng thử nếu CPU hạn chế; chưa đo FPS trên máy khách. |
| ByteTrack | [Repo FoundationVision](https://github.com/FoundationVision/ByteTrack), MIT | Gán và giữ ID qua frame; cần detector cung cấp bounding box. Benchmark MOT17 của repo không chứng minh khả năng đếm cuộn xưởng. |
| Supervision | [Repo Roboflow](https://github.com/roboflow/supervision), MIT | Có công cụ xử lý video, vẽ kết quả và bộ đếm qua vạch. [LineZone](https://supervision.roboflow.com/0.22.0/detection/tools/line_zone/) nhận tracker ID và phân hướng qua vạch. Cần ghim phiên bản/API khi triển khai. |
| Ultralytics YOLO26 | [Docs tác giả](https://docs.ultralytics.com/), [giấy phép](https://www.ultralytics.com/license) | Có các luồng detect/track/count sẵn. AGPL-3.0 hoặc Enterprise; không chọn làm mặc định trước khi xác định cách phân phối ứng dụng. |

Các con số tham số là do repo công bố, không phải benchmark nội bộ. Không suy
FPS CPU từ latency GPU của tác giả. Bộ detector cần học/nhận diện được loại cuộn
thực tế; checkpoint COCO không chứng minh có sẵn lớp cuộn cách nhiệt của xưởng.

## Có model/dataset đúng vật thể không?

Tìm thấy dự án công khai [coil counting](https://universe.roboflow.com/yolo-hhkbh/coil-counting)
với nhãn `coil`, `longcoil`, công bố CC BY 4.0. Trang tổng quan có 34 ảnh; một
phiên bản dataset ghi 90 ảnh. Đây là nguồn tham khảo, chưa xác nhận ảnh tương đồng
với cuộn xưởng, quyền/phương thức tải weights offline, hoặc độ đúng tại xưởng.
Ví dụ deploy trên trang dùng API key/cloud nên không coi là model offline cắm vào
chạy ngay. Chỉ số mAP trên trang không dùng làm cam kết nghiệm thu.

Chưa tìm thấy bằng chứng về một model nguồn mở đã được kiểm chứng trên đúng
cuộn, góc máy và thao tác ra hàng của dự án này.

## Cách tích hợp đề xuất

1. Camera cố định nhìn cửa ra máy; chọn ROI và hướng ra. Video file và camera
   dùng chung pipeline, tính thời gian theo timestamp video.
2. Detector chỉ phát bounding box/cuộn và confidence trong ROI. Tracker giữ ID.
3. Bộ đếm xác nhận chuyển từ vùng A sang B theo hướng ra, có khoảng đệm quanh
   vạch. Một ID chỉ được ghi nhận một lần cho một lượt ra; tách đếm quay vào
   nếu quy trình cần. LineZone đơn thuần chưa giải quyết mọi trường hợp đi lui.
4. Xử lý cuộn đứng lâu, rung ngay vạch, che khuất, đẩy lùi và đổi ID. Nếu ID mất
   rồi sinh lại tại vạch thì phải có logic chống đếm trùng theo vị trí/thời gian;
   không chỉ dùng một tập hợp ID.
5. Ghi sự kiện gồm thời gian, máy, ID, hướng và ảnh bằng chứng. Khi mất camera
   báo gián đoạn, không tự bù số cuộn. Tách bộ đếm khỏi phiếu cân/đẩy kho.
6. Chạy worker riêng với hàng đợi giới hạn, không chặn OCR cân hoặc luồng lưu local.
   Ưu tiên ONNX Runtime đang có; phải kiểm chứng export và tốc độ của detector chọn.
   Không tự mở thêm tiến trình chiếm cùng camera USB.

Nếu vật thể ra từng chiếc, nền/góc máy cố định và ít che khuất, có thể đối chứng
thêm foreground/contour tracking bằng OpenCV để xem có cần model học sâu không.
Đây là giả thuyết phụ thuộc video, không phải phương án đã nghiệm thu.

## Dữ liệu cần để chọn phương án

- Video 3–5 phút từ đúng góc camera dự định đặt, có vài chục cuộn ra máy và
  số đếm tay làm chuẩn; thêm đoạn dừng, che khuất và quay lại nếu có.
- CPU/RAM, GPU nếu có, độ phân giải/FPS camera và tốc độ ra cuộn.
- Quy tắc nghiệp vụ: cuộn ra rồi quay vào có trừ không; cuộn ra lại tính mới
  không; đếm theo máy, ca hay LSX; cuộn dính/chồng nhau xử lý thế nào.

Thử video trước, so sánh cuộn thiếu/trùng, sai số tổng, độ trễ, FPS xử lý và CPU/RAM.
Sau đó mới chọn model, quyết định có cần gán nhãn/fine-tune và tích hợp camera live.
