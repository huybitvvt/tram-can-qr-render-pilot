$ErrorActionPreference = 'Stop'

try {
    Write-Host 'Đang cài Antigravity CLI từ antigravity.google...' -ForegroundColor Cyan
    $installScript = Invoke-RestMethod -Uri 'https://antigravity.google/cli/install.ps1'
    if (-not ($installScript -is [string]) -or -not $installScript.Trim()) {
        throw 'Không tải được trình cài Antigravity CLI.'
    }
    Invoke-Expression $installScript
    $agyExe = Join-Path $env:LOCALAPPDATA 'agy\bin\agy.exe'
    if (-not (Test-Path -LiteralPath $agyExe)) {
        throw 'Chưa tìm thấy agy.exe sau khi cài.'
    }
    & $agyExe --version
    if ($LASTEXITCODE -ne 0) {
        throw 'Antigravity CLI không chạy được sau khi cài.'
    }
    Write-Host 'Đã cài Antigravity CLI. Mở Trạm Cân QR, chọn Antigravity rồi bấm Đăng nhập.' -ForegroundColor Green
} catch {
    Write-Host ('Cài Antigravity CLI thất bại: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
