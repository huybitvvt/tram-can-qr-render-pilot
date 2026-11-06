$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$installerDir = Join-Path $projectRoot "dist\installer"
$versionMatch = Select-String -LiteralPath packaging\TramCanQR.iss -Pattern '^#define MyAppVersion "([^"]+)"'
$version = $versionMatch.Matches[0].Groups[1].Value
if (-not $version) { throw "Khong doc duoc phien ban bo cai" }
$pythonCandidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    (Join-Path $projectRoot ".venv-pilot\Scripts\python.exe")
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    throw "Chưa có môi trường Python. Hãy chạy CAI-DAT-LAN-DAU.cmd trước."
}
& $python -c "import PyInstaller; assert PyInstaller.__version__ == '6.21.0'"
if ($LASTEXITCODE -ne 0) { throw "Can PyInstaller 6.21.0 trong moi truong build" }
$buildTemp = Join-Path $projectRoot ".test-tmp\rapidocr-build-temp"
New-Item -ItemType Directory -Path $buildTemp -Force | Out-Null
$previousTemp, $previousTmp, $previousCache = $env:TEMP, $env:TMP, $env:PYINSTALLER_CONFIG_DIR
$previousErrorActionPreference = $ErrorActionPreference
try {
    $env:TEMP = $buildTemp
    $env:TMP = $buildTemp
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot ".test-tmp\pyinstaller-rapidocr-cache"
    $ErrorActionPreference = "Continue"
    & $python -m PyInstaller --noconfirm --clean --workpath build\rapidocr packaging\TramCanQR.spec 2>&1 | ForEach-Object { Write-Output $_.ToString() }
    $pyInstallerExitCode = $LASTEXITCODE
} finally {
    $env:TEMP, $env:TMP, $env:PYINSTALLER_CONFIG_DIR = $previousTemp, $previousTmp, $previousCache
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($pyInstallerExitCode -ne 0) { throw "PyInstaller build failed (exit code $pyInstallerExitCode)" }

$portableDir = Join-Path $projectRoot "dist\TramCanQR"
$portableExe = Join-Path $portableDir "TramCanQR.exe"
if (-not (Test-Path -LiteralPath $portableExe)) {
    throw "Không tìm thấy bản portable sau khi build: $portableExe"
}
# These two files are intentionally beside the EXE for portable handoff. The
# Inno installer also adds them explicitly to the installed program directory.
Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\customer-config.env.example") -Destination $portableDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\HUONG-DAN-KHACH-HANG.md") -Destination $portableDir -Force

$innoCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $innoCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$installerPath = Join-Path $installerDir "TramCanQR-Setup-$version.exe"
if ($iscc) {
    & $iscc packaging\TramCanQR.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup build thất bại" }
    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw "Không tìm thấy installer sau khi build: $installerPath"
    }
} else {
    Write-Warning "Inno Setup chưa cài; đã tạo bản portable tại dist\TramCanQR\TramCanQR.exe"
}

$handoffDir = Join-Path $projectRoot "dist\handoff-$version"
New-Item -ItemType Directory -Path $handoffDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\customer-config.env.example") -Destination $handoffDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\HUONG-DAN-KHACH-HANG.md") -Destination $handoffDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\CAP-NHAT-BAN-MOI.cmd") -Destination $handoffDir -Force
if (Test-Path -LiteralPath $installerPath) {
    Copy-Item -LiteralPath $installerPath -Destination $handoffDir -Force
    $genericInstaller = Join-Path $installerDir "TramCanQR-Setup.exe"
    Copy-Item -LiteralPath $installerPath -Destination $genericInstaller -Force
    Copy-Item -LiteralPath $installerPath -Destination (Join-Path $handoffDir "TramCanQR-Setup.exe") -Force
    $hashes = @(
        ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLower() + "  " + (Split-Path $installerPath -Leaf)),
        ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLower() + "  TramCanQR-Setup.exe")
    )
} else {
    $portableArchive = Join-Path $handoffDir "TramCanQR-portable-$version.zip"
    Compress-Archive -Path $portableDir -DestinationPath $portableArchive -CompressionLevel Optimal -Force
    $hashes = @(
        ((Get-FileHash -LiteralPath $portableArchive -Algorithm SHA256).Hash + "  " + (Split-Path $portableArchive -Leaf))
    )
}
$hashes | Set-Content -LiteralPath (Join-Path $handoffDir "SHA256SUMS.txt") -Encoding ascii
Write-Output "Handoff files: $handoffDir"
