# Trạm cân QR — sửa source và tạo bản chạy mới

File `.exe` đã cài **không tự thay đổi** khi sửa `.py`. Có hai cách chạy:

- Chạy source editable: sửa backend trong `backend\src\roll_qr_scale` hoặc giao
  diện trong `frontend\index.html`, đóng cửa sổ đang
  chạy rồi mở lại `CHAY-TRAM-CAN.cmd`; code mới có hiệu lực ngay.
- Phát hành cho máy khách: chạy `BUILD-BAN-MOI.cmd`, sau đó gửi installer mới
  trong `dist\installer` và cài đè bản cũ.

## 1. Cài môi trường một lần

Giải nén source vào thư mục cố định, ví dụ `C:\TramCanQR-Source`, rồi chạy:

```text
CAI-DAT-LAN-DAU.cmd
```

File này tạo `.venv-pilot`, cài thư viện và gắn source bằng `pip install -e`.
API key/config thật vẫn nằm riêng tại
`%LOCALAPPDATA%\TramCanQR\config.env`.

## 2. Sửa và chạy thử ngay

1. Sửa backend trong `backend\src\roll_qr_scale` hoặc giao diện trong
   `frontend\index.html` bằng VS Code.
2. Đóng cửa sổ `CHAY-TRAM-CAN.cmd`/`TramCanQR` đang chạy.
3. Chạy lại `CHAY-TRAM-CAN.cmd`.
4. Mở `http://127.0.0.1:8080` và nhấn `Ctrl+F5`.

Không cần chạy lại `CAI-DAT-LAN-DAU.cmd` sau mỗi lần sửa code, trừ khi thay
đổi danh sách thư viện.

## 3. Tạo EXE/installer mới

Cài **Inno Setup 6** nếu muốn có file installer, sau đó chạy:

```text
BUILD-BAN-MOI.cmd
```

Script tự chạy test rồi tạo:

```text
dist\TramCanQR\TramCanQR.exe
dist\installer\TramCanQR-Setup-0.2.0-rc27.exe
```

Nếu test hoặc build lỗi, không gửi lại file EXE/installer cũ. Trước mỗi đợt
phát hành chính thức cần tăng version trong `pyproject.toml`,
`packaging\TramCanQR.iss`, `packaging\TramCanQR.version` và đường dẫn version
trong `tools\build_windows.ps1`.

## 4. Cập nhật máy khách

Sau khi build và kiểm tra installer, phát hành bằng `tools\release_github.ps1`.
Release phải chứa installer có số phiên bản và `SHA256SUMS.txt` khớp với file
đó. Nút **Cập nhật Trạm Cân QR** trong bản đã cài lấy bản mới nhất từ GitHub
Release, kiểm tra hash rồi cài đè im lặng và mở lại ứng dụng. Nếu người dùng
có nút cũ bị lỗi, gửi riêng `packaging\CAP-NHAT-BAN-MOI.cmd` để thay file cùng
tên trong thư mục cài đặt một lần.

`git pull` chỉ cập nhật source trên máy phát triển; nó không thay đổi EXE đã
đóng gói trên máy khách. Sau khi cập nhật, mở lại trình duyệt hoặc nhấn
`Ctrl+F5` để tải giao diện mới.

Installer giữ nguyên `%LOCALAPPDATA%\TramCanQR\config.env`, SQLite, ảnh và cấu
hình Supabase. Không chép riêng file `.py` vào thư mục đã cài vì PyInstaller đã
đóng source vào `_internal`.

## Những gì không nằm trong gói

- Không có `.env`/`config.env` chứa token thật.
- Không có SQLite, WAL, ảnh chụp vận hành hoặc dữ liệu cloud.
- Không có `build`, `dist`, `.venv`, `.test-tmp`, `runs` và cache Python.
- Bộ ảnh xưởng đầy đủ để nghiệm thu/training phải được chuyển riêng theo
  quyền truy cập của nhà máy; không đưa tự động vào ZIP mã nguồn.

Nếu cần cloud local, dùng `.env.example` làm mẫu placeholder và cấp token
thiết bị qua kênh bảo mật. Không đưa Cloudinary API secret hoặc Supabase
service-role key xuống gateway/máy khách.

## Ranh giới bàn giao

Bên phát triển nhận mã nguồn, test và model demo để sửa. Bên triển khai giữ
quyền phát hành installer, quản lý secret, dữ liệu nghiệm thu và ký số. Không
coi bộ test synthetic hoặc report stress logic là nghiệm thu phần cứng 2–3
camera tại xưởng.
