$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

# 1. Doc phien ban tu packaging\TramCanQR.iss
$issPath = Join-Path $projectRoot "packaging\TramCanQR.iss"
if (-not (Test-Path -LiteralPath $issPath)) {
    throw "Khong tim thay $issPath"
}
$match = (Get-Content -LiteralPath $issPath) | Select-String -Pattern '#define MyAppVersion "([^"]+)"'
if (-not $match) {
    throw "Khong doc duoc MyAppVersion trong $issPath"
}
$version = $match.Matches[0].Groups[1].Value
$tag = "v$version"
Write-Host ">>> Dang chuan bi phat hanh phien ban: $tag" -ForegroundColor Cyan

# 2. Kiem tra file bo cai
$installerDir = Join-Path $projectRoot "dist\installer"
$versionedInstaller = Join-Path $installerDir "TramCanQR-Setup-$version.exe"
$genericInstaller = Join-Path $installerDir "TramCanQR-Setup.exe"

if (-not (Test-Path -LiteralPath $versionedInstaller)) {
    Write-Host ">>> Chua co file $versionedInstaller, dang chay build..." -ForegroundColor Yellow
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot "tools\build_windows.ps1")
}

if (-not (Test-Path -LiteralPath $versionedInstaller)) {
    throw "Khong tim thay $versionedInstaller sau khi build"
}

Copy-Item -LiteralPath $versionedInstaller -Destination $genericInstaller -Force

# 3. Tao hoac cap nhat GitHub Release
Write-Host ">>> Dang day Release len GitHub..." -ForegroundColor Cyan

$releaseNotes = @"
Phiên bản $version của Trạm Cân QR Việt Nhật IPT.

### Các cập nhật chính:
- Luồng cân 4 lượt cho 2 cặp lõi - thành phẩm (cân 2 lõi trước, thành phẩm cân sau).
- Hỗ trợ nút lưu riêng từng cặp (Lưu riêng cặp 1, Lưu riêng cặp 2).
- Có thể lưu thành phẩm khi chưa cân lõi; lượt cân lõi còn thiếu được hiển thị rõ.
- Danh sách hiện bản ghi local ngay sau khi lưu, kể cả lúc đồng bộ cloud chậm.
- Bỏ cảnh báo và chặn lưu khi cân lõi quá 1.2 kg.
- Ô chọn Máy dạng danh sách gợi ý 5 máy xưởng và cho gõ tay tự do.
- Luôn có lựa chọn Ca chuẩn Đà Nẵng; ô Máy gõ tay không còn bị machine_id khóa hoặc ghi đè.
- Máy mặc định và LSX được giữ đúng theo từng trạm; ca đã chọn không bị gợi ý LSX đổi lại.
- Nút Lưu trả kết quả sau khi ghi local; ảnh và phiếu cân được gửi cloud ở nền, tự thử lại sau lỗi mạng hoặc khi mở lại ứng dụng.
- Khi bấm Bỏ ảnh/lượt lỗi, cặp tự chuyển về Không lỗi và xóa lý do lỗi cũ.
- Dữ liệu cũ và config.env được giữ nguyên khi cài đè.

### Tải nhanh:
- File cài đặt chuẩn (.exe): [TramCanQR-Setup.exe](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/latest/download/TramCanQR-Setup.exe)
- File cập nhật 1-click cho máy trạm: [CAP-NHAT-BAN-MOI.cmd](https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/latest/download/CAP-NHAT-BAN-MOI.cmd)
"@

$handoffDir = Join-Path $projectRoot "dist\handoff-$version"
$shaFile = Join-Path $handoffDir "SHA256SUMS.txt"
$updateScript = Join-Path $projectRoot "packaging\CAP-NHAT-BAN-MOI.cmd"
$assets = @($versionedInstaller, $genericInstaller)
if (Test-Path -LiteralPath $shaFile) {
    $assets += $shaFile
}
if (Test-Path -LiteralPath $updateScript) {
    $assets += $updateScript
}

$releaseExists = $false
$prevPref = $ErrorActionPreference
try {
    $ErrorActionPreference = "SilentlyContinue"
    $null = & gh release view $tag --json tagName 2>&1
    if ($LASTEXITCODE -eq 0) {
        $releaseExists = $true
    }
} catch {
    $releaseExists = $false
} finally {
    $ErrorActionPreference = $prevPref
}

if ($releaseExists) {
    Write-Host ">>> Release $tag da ton tai, dang cap nhat file dinh kem..." -ForegroundColor Yellow
    & gh release upload $tag $assets --clobber
} else {
    Write-Host ">>> Dang tao moi Release $tag..." -ForegroundColor Green
    & gh release create $tag $assets --title "Bản phát hành $tag" --notes $releaseNotes --latest
}

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "PHAT HANH THANH CONG LEN GITHUB!" -ForegroundColor Green
    Write-Host "Duong link tai truc tiep ban moi nhat (khong doi):" -ForegroundColor White
    Write-Host "https://github.com/huybitvvt/tram-can-qr-render-pilot/releases/latest/download/TramCanQR-Setup.exe" -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Green
} else {
    Write-Host "Loi khi phat hanh release bang gh CLI" -ForegroundColor Red
}
