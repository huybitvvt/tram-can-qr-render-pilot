@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================
echo   TRẠM CÂN QR - TỰ ĐỘNG TẢI VÀ CÀI BẢN MỚI TỪ GITHUB
echo ========================================================
echo.

echo [1/3] Đang đóng phần mềm Trạm Cân QR cũ nếu đang chạy...
taskkill /F /IM TramCanQR.exe /T >nul 2>&1
timeout /t 1 >nul

echo.
echo [2/3] Đang tải bản cài mới nhất từ GitHub...
set "SETUP_URL=https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/latest/download/TramCanQR-Setup.exe"
set "TEMP_SETUP=%TEMP%\TramCanQR-Setup.exe"

if exist "%TEMP_SETUP%" del /f /q "%TEMP_SETUP%" >nul 2>&1

curl.exe -fSL --progress-bar -o "%TEMP_SETUP%" "%SETUP_URL%"
if errorlevel 1 (
    echo.
    echo [LỖI] Không tải được bản mới từ GitHub.
    echo Vui lòng kiểm tra lại kết nối mạng Internet hoặc truy cập link sau:
    echo %SETUP_URL%
    pause
    exit /b 1
)

echo.
echo [3/3] Tải xong thành công! Đang khởi động trình cài đặt...
echo Ghi chú: Cài đè sẽ GIỮ NGUYÊN cấu hình config.env và dữ liệu cân cũ.
echo.
start "" "%TEMP_SETUP%"
exit /b 0
