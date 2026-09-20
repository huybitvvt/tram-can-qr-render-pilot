$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$version = "source-editable-gemini-pilot-0.2.0-rc9"
$dest = Join-Path $root "dist\$version"
$zip = Join-Path $root "dist\$version.zip"
$hashFile = Join-Path $root "dist\$version.SHA256.txt"

foreach ($target in @($dest, $zip, $hashFile)) {
    if (Test-Path -LiteralPath $target) {
        throw "Dich da ton tai, khong ghi de: $target"
    }
}

New-Item -ItemType Directory -Path $dest -Force | Out-Null

function Copy-Tree([string]$relative) {
    $sourceRoot = Join-Path $root $relative
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Force |
        Where-Object {
            $_.FullName -notmatch '\\(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.temp)(\\|$)' -and
            $_.FullName -notmatch '\\[^\\]+\.egg-info(\\|$)' -and
            $_.Name -notin @(".env", "config.env") -and
            $_.Extension -notin @(".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".pem", ".key", ".p12", ".pfx")
        } |
        ForEach-Object {
            $subpath = $_.FullName.Substring($root.Length + 1)
            $target = Join-Path $dest $subpath
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
}

foreach ($directory in @("frontend", "backend", "tests", "tools", "packaging", "docs", "config")) {
    Copy-Tree $directory
}

foreach ($file in @(
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    ".env.example",
    "YOLOv8_QR_Can_Colab.ipynb"
)) {
    Copy-Item -LiteralPath (Join-Path $root $file) -Destination (Join-Path $dest $file) -Force
}

foreach ($file in @(
    "data\test_frame.png",
    "data\warehouse_scale_demo.png",
    "data\warehouse_scale_demo_base.png",
    "data\viet_nhat_ipt_logo.jpg",
    "data\factory_scale_7_02_full_reference.jpg",
    "data\factory_scale_7_02_full_reference.json",
    "data\factory_scale_9_34_reference.jpg",
    "data\factory_scale_13_04_reference.jpg",
    "data\factory_scale_13_04_reference.json",
    "models\qr_demo_synthetic.pt",
    "yolov8n.pt"
)) {
    $source = Join-Path $root $file
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Thieu file source can ban giao: $file"
    }
    $target = Join-Path $dest $file
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $target -Force
}

# One-click pilot files are placed at ZIP root. The source remains editable
# because setup installs the project with `pip install -e`.
Copy-Item -LiteralPath (Join-Path $root "packaging\requirements-gemini-pilot.txt") -Destination (Join-Path $dest "requirements-gemini-pilot.txt") -Force
Copy-Item -LiteralPath (Join-Path $root "packaging\gemini-pilot-config.env.example") -Destination (Join-Path $dest "config.env.example") -Force
Copy-Item -LiteralPath (Join-Path $root "packaging\CAI-DAT-LAN-DAU.cmd") -Destination $dest -Force
Copy-Item -LiteralPath (Join-Path $root "packaging\CHAY-TRAM-CAN.cmd") -Destination $dest -Force
Copy-Item -LiteralPath (Join-Path $root "packaging\BUILD-BAN-MOI.cmd") -Destination $dest -Force
Copy-Item -LiteralPath (Join-Path $root "packaging\HUONG-DAN-PILOT-GEMINI.txt") -Destination $dest -Force
Copy-Item -LiteralPath (Join-Path $root "packaging\HUONG-DAN-DEVELOPER.md") -Destination (Join-Path $dest "HUONG-DAN-SUA-VA-BUILD.md") -Force

$databaseFiles = Get-ChildItem -LiteralPath $dest -Recurse -File -Force |
    Where-Object { $_.Name -match '\.(db|db-wal|db-shm)$' }
$realConfigs = Get-ChildItem -LiteralPath $dest -Recurse -File -Force |
    Where-Object { $_.Name -in @(".env", "config.env") }
$privateKeys = Get-ChildItem -LiteralPath $dest -Recurse -File -Force |
    Where-Object { $_.Extension -in @(".pem", ".key", ".p12", ".pfx") }
if ($databaseFiles -or $realConfigs -or $privateKeys) {
    throw "Goi source co database, config that hoac private key; huy ban giao"
}

$textExtensions = @(".py", ".ps1", ".cmd", ".txt", ".md", ".toml", ".json", ".yaml", ".yml", ".env", ".example", ".sql", ".ipynb")
$textFiles = Get-ChildItem -LiteralPath $dest -Recurse -File -Force |
    Where-Object { $_.Extension -in $textExtensions }
$secretPatterns = @(
    'AIza[0-9A-Za-z_-]{20,}',
    'AQ\.[0-9A-Za-z_-]{20,}',
    'sk-[0-9A-Za-z_-]{20,}',
    'eyJ[0-9A-Za-z_-]{20,}\.[0-9A-Za-z_-]{20,}\.'
)
$secretHits = $textFiles | Select-String -Pattern $secretPatterns
$apiKeyAssignments = $textFiles | Select-String -Pattern 'ROLL_SCALE_GEMINI_API_KEY\s*='
$unsafeApiKeyAssignments = $apiKeyAssignments | Where-Object {
    $value = ($_.Line -split '=', 2)[1].Trim().Trim('"', "'")
    $value -and $value -notmatch '^(replace-|YOUR_|<)'
}
if ($secretHits -or $unsafeApiKeyAssignments) {
    $paths = @($secretHits) + @($unsafeApiKeyAssignments) |
        Select-Object -ExpandProperty Path -Unique
    throw "Phat hien chuoi co the la secret trong goi source: $($paths -join ', ')"
}

$entries = Get-ChildItem -LiteralPath $dest -Force | Select-Object -ExpandProperty FullName
Compress-Archive -Path $entries -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
$hash | Set-Content -LiteralPath $hashFile -Encoding ascii

[pscustomobject]@{
    Folder = $dest
    Zip = $zip
    ZipBytes = (Get-Item -LiteralPath $zip).Length
    Sha256 = $hash
    FileCount = (Get-ChildItem -LiteralPath $dest -Recurse -File -Force | Measure-Object).Count
    HasSource = Test-Path -LiteralPath (Join-Path $dest "backend\src\roll_qr_scale\test_ui.py")
    HasTests = Test-Path -LiteralPath (Join-Path $dest "tests\test_ui.py")
    HasRealConfig = [bool]$realConfigs
    HasDatabase = [bool]$databaseFiles
    SecretHitCount = @($secretHits).Count + @($unsafeApiKeyAssignments).Count
} | Format-List
