@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv-pilot\Scripts\python.exe" (
  echo Chua cai dat. Hay chay CAI-DAT-LAN-DAU.cmd truoc.
  pause
  exit /b 1
)

set "CONFIG_FILE=%LOCALAPPDATA%\TramCanQR\config.env"
if not exist "%CONFIG_FILE%" (
  echo Chua co config.env. Hay chay CAI-DAT-LAN-DAU.cmd truoc.
  pause
  exit /b 1
)

findstr /C:"replace-with-key-" "%CONFIG_FILE%" >nul
if not errorlevel 1 (
  echo Chua dien Gemini API key.
  start "" notepad.exe "%CONFIG_FILE%"
  pause
  exit /b 1
)

echo Dang khoi dong. Khong dong cua so nay trong luc test.
".venv-pilot\Scripts\python.exe" -m roll_qr_scale.windows_app
if errorlevel 1 (
  echo.
  echo Khoi dong loi. Gui file %%LOCALAPPDATA%%\TramCanQR\logs\app.log cho ky thuat.
  pause
  exit /b 1
)
