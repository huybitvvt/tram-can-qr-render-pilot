@echo off
setlocal DisableDelayedExpansion
set "TRAMCANQR_UPDATER_FILE=%~f0"
start "Cap nhat Tram Can QR" powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$raw = Get-Content -LiteralPath $env:TRAMCANQR_UPDATER_FILE -Raw -Encoding UTF8; $parts = $raw -split '(?m)^# POWERSHELL\r?\n', 2; if ($parts.Count -ne 2) { throw 'Updater payload missing' }; & ([ScriptBlock]::Create($parts[1]))"
if errorlevel 1 (
    echo Khong mo duoc PowerShell de cap nhat.
    pause
    exit /b 1
)
exit /b 0
# POWERSHELL
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Compare-ReleaseVersion([string]$installed, [string]$latest) {
    $pattern = '^(\d+\.\d+\.\d+)(?:-rc(\d+))?$'
    $a = [regex]::Match($installed, $pattern)
    $b = [regex]::Match($latest, $pattern)
    if (-not $a.Success -or -not $b.Success) { return $null }

    $baseComparison = ([version]$a.Groups[1].Value).CompareTo([version]$b.Groups[1].Value)
    if ($baseComparison -ne 0) { return $baseComparison }
    $aRc = if ($a.Groups[2].Success) { [int]$a.Groups[2].Value } else { [int]::MaxValue }
    $bRc = if ($b.Groups[2].Success) { [int]$b.Groups[2].Value } else { [int]::MaxValue }
    return $aRc.CompareTo($bRc)
}

$temporaryDirectory = $null
$installedExe = $null
$stoppedApp = $false
try {
    $updaterDirectory = Split-Path -Parent $env:TRAMCANQR_UPDATER_FILE
    $candidates = @((Join-Path $updaterDirectory 'TramCanQR.exe'))
    foreach ($entry in @(Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue)) {
        if ($entry.DisplayName -eq 'Tram Can QR' -and $entry.InstallLocation) {
            $candidates += Join-Path $entry.InstallLocation 'TramCanQR.exe'
        }
    }
    $candidates += Join-Path $env:LOCALAPPDATA 'Programs\TramCanQR\TramCanQR.exe'
    $installedExe = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $installedExe) {
        throw 'Khong tim thay TramCanQR.exe da cai. Hay cai bo TramCanQR-Setup.exe truoc.'
    }

    Write-Host 'Dang kiem tra ban moi tren GitHub Release...'
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/huybitvvt/tram-can-qr-render-pilot/releases/latest' -Headers @{ 'User-Agent' = 'TramCanQR-Updater' } -TimeoutSec 30
    $tag = [string]$release.tag_name
    if ($tag -notmatch '^v(\d+\.\d+\.\d+(?:-rc\d+)?)$') {
        throw "Phien ban GitHub Release khong hop le: $tag"
    }
    $latestVersion = $Matches[1]
    $installerName = "TramCanQR-Setup-$latestVersion.exe"
    $installerAsset = $release.assets | Where-Object { $_.name -eq $installerName } | Select-Object -First 1
    $checksumAsset = $release.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' } | Select-Object -First 1
    if (-not $installerAsset -or -not $checksumAsset) {
        throw "Release $tag thieu $installerName hoac SHA256SUMS.txt."
    }

    $installedVersion = [string](Get-Item -LiteralPath $installedExe).VersionInfo.ProductVersion
    $comparison = Compare-ReleaseVersion $installedVersion $latestVersion
    if ($null -ne $comparison -and $comparison -ge 0) {
        Write-Host "Da co ban $installedVersion; ban moi nhat tren GitHub la $latestVersion. Khong can cai lai."
        exit 0
    }

    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) ('TramCanQR-update-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
    $installerPath = Join-Path $temporaryDirectory $installerName
    $checksumPath = Join-Path $temporaryDirectory 'SHA256SUMS.txt'

    Write-Host "Dang tai bo cai $latestVersion..."
    Invoke-WebRequest -Uri $installerAsset.browser_download_url -OutFile $installerPath -UseBasicParsing -TimeoutSec 600
    Invoke-WebRequest -Uri $checksumAsset.browser_download_url -OutFile $checksumPath -UseBasicParsing -TimeoutSec 60

    $expectedHash = $null
    foreach ($line in [IO.File]::ReadAllLines($checksumPath)) {
        if ($line -match '^([0-9a-fA-F]{64})\s{2}(.+)$' -and $Matches[2] -eq $installerName) {
            $expectedHash = $Matches[1]
            break
        }
    }
    if (-not $expectedHash) { throw "SHA256SUMS.txt khong co hash cho $installerName." }
    $actualHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) { throw 'SHA-256 cua bo cai khong khop. Da huy cap nhat.' }
    Write-Host 'Da tai va xac minh SHA-256 thanh cong.'

    $runningApp = Get-Process -Name TramCanQR -ErrorAction SilentlyContinue
    if ($runningApp) {
        Write-Host 'Dang dong Tram Can QR cu...'
        $runningApp | Stop-Process -Force
        $stoppedApp = $true
        foreach ($attempt in 1..20) {
            if (-not (Get-Process -Name TramCanQR -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 250
        }
        if (Get-Process -Name TramCanQR -ErrorAction SilentlyContinue) {
            throw 'Khong dong duoc TramCanQR.exe. Hay dong ung dung va thu lai.'
        }
    }

    Write-Host 'Dang cai dat ban moi...'
    $setup = Start-Process -FilePath $installerPath -ArgumentList '/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS' -Wait -PassThru
    if ($setup.ExitCode -ne 0) { throw "Bo cai tra ma loi $($setup.ExitCode)." }

    Write-Host "Da cap nhat len ban $latestVersion. Dang mo Tram Can QR..."
    Start-Process -FilePath $installedExe
    $stoppedApp = $false
} catch {
    Write-Host ('[LOI] ' + $_.Exception.Message) -ForegroundColor Red
    if ($stoppedApp -and $installedExe -and (Test-Path -LiteralPath $installedExe -PathType Leaf)) {
        try { Start-Process -FilePath $installedExe } catch { Write-Host ('Khong mo lai duoc ung dung: ' + $_.Exception.Message) -ForegroundColor Red }
    }
    if (-not $env:TRAMCANQR_UPDATER_NONINTERACTIVE) { [void](Read-Host 'Nhan Enter de dong cua so') }
    exit 1
} finally {
    if ($temporaryDirectory -and (Test-Path -LiteralPath $temporaryDirectory)) {
        Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}
