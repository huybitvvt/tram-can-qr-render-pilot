$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$version = "0.2.0-ai-auto-beta1"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path -LiteralPath $iscc)) {
    $iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path -LiteralPath $python)) { throw "Thieu .venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $iscc)) { throw "Can Inno Setup 6 de tao bo cai Windows" }
if (-not (Test-Path -LiteralPath model\best.pt)) { throw "Thieu model\best.pt" }
& $python -c "import torch, PyInstaller; assert torch.version.cuda is None, 'Use CPU-only PyTorch for customer package'; print('CPU Torch', torch.__version__, 'PyInstaller', PyInstaller.__version__)"
if ($LASTEXITCODE -ne 0) { throw "Moi truong build local YOLO chua dung" }
$buildTemp = Join-Path $projectRoot ".test-tmp\auto-build-temp"
New-Item -ItemType Directory -Path $buildTemp -Force | Out-Null
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$previousCache = $env:PYINSTALLER_CONFIG_DIR
try {
    $env:TEMP = $buildTemp
    $env:TMP = $buildTemp
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot ".test-tmp\pyinstaller-auto-cache"
    & $python -m PyInstaller --noconfirm --clean --workpath build\ai-auto packaging\TramCanQRAuto.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller AI Auto build failed" }
    $portable = Join-Path $projectRoot "dist\TramCanQRAuto"
    Copy-Item -LiteralPath packaging\HUONG-DAN-CAN-AI-TU-DONG.md -Destination $portable -Force
    & $iscc packaging\TramCanQRAuto.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup AI Auto build failed" }
    $handoff = Join-Path $projectRoot "dist\handoff-ai-auto-beta1"
    New-Item -ItemType Directory -Path $handoff -Force | Out-Null
    $installer = Join-Path $projectRoot "dist\installer-auto\TramCanQRAuto-Setup-$version.exe"
    Copy-Item -LiteralPath $installer -Destination $handoff -Force
    Copy-Item -LiteralPath $installer -Destination (Join-Path $handoff "TramCanQRAuto-Setup.exe") -Force
    Copy-Item -LiteralPath packaging\HUONG-DAN-CAN-AI-TU-DONG.md -Destination $handoff -Force
    Copy-Item -LiteralPath model\MODEL-INFO.json -Destination $handoff -Force
    $hashes = Get-ChildItem -LiteralPath $handoff -File -Filter *.exe | ForEach-Object {
        (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower() + "  " + $_.Name
    }
    $hashes | Set-Content -LiteralPath (Join-Path $handoff "SHA256SUMS.txt") -Encoding ascii
    Write-Output "AI Auto handoff: $handoff"
} finally {
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    $env:PYINSTALLER_CONFIG_DIR = $previousCache
}
