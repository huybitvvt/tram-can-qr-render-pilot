@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================
echo   TRAM CAN QR - DAY CODE VA PHAT HANH BAN MOI LEN GITHUB
echo ========================================================
echo.

set /p COMMIT_MSG="Nhap ghi chu cap nhat (de trong neu dung mac dinh): "
if "%COMMIT_MSG%"=="" (
    set "COMMIT_MSG=Cap nhat ban moi nhat"
)

echo.
echo [1/3] Dang commit va day ma nguon len GitHub...
git add .
git commit -m "%COMMIT_MSG%"
git push origin main
if errorlevel 1 (
    echo.
    echo [CANH BAO] Push git that bai hoac khong co thay doi moi.
)

echo.
echo [2/3] Dang phat hanh ban cai (.exe) len GitHub Release...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tools\release_github.ps1"
if errorlevel 1 (
    echo.
    echo Phat hanh Release that bai. Vui long kiem tra lai mang hoac gh auth.
    pause
    exit /b 1
)

echo.
echo [3/3] HOAN TAT! Ban moi da san sang tren GitHub.
pause
exit /b 0
