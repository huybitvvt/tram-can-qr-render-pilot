"""Exercise rc74 and new update scripts without touching installed apps/registry."""
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


HARNESS = r'''
param([string]$Root, [string]$Updater, [switch]$BadHash)
$ErrorActionPreference = 'Stop'
$env:LOCALAPPDATA = $Root
$env:TEMP = $Root
$env:TMP = $Root
$env:TRAMCANQR_UPDATER_NONINTERACTIVE = '1'
$env:TRAMCANQR_UPDATER_FILE = Join-Path $Root 'CAP-NHAT-BAN-MOI.cmd'
$script:exe = Join-Path $Root 'TramCanQR.exe'
$script:didStop = $false
$script:didInstall = $false
$script:didOpen = $false
function Get-ItemProperty { param($Path, $ErrorAction) return @{DisplayName='Tram Can QR';InstallLocation=$Root} }
function Get-Item { param($LiteralPath) return @{VersionInfo=@{ProductVersion='0.2.0-rc74'}} }
function Get-Process {
    param($Name, $ErrorAction)
    if (-not $script:didStop) { return @{Name='TramCanQR'} }
}
function Stop-Process {
    param([Parameter(ValueFromPipeline=$true)]$InputObject, [switch]$Force)
    process { $script:didStop = $true }
}
function Invoke-RestMethod {
    param($Uri, $Headers, $TimeoutSec)
    return @{tag_name='v0.2.0-rc75';assets=@(
        @{name='TramCanQR-Setup-0.2.0-rc75.exe';browser_download_url='https://test.invalid/installer'},
        @{name='SHA256SUMS.txt';browser_download_url='https://test.invalid/checksum'})}
}
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing, $TimeoutSec)
    if ($Uri.EndsWith('/installer')) { Copy-Item -LiteralPath (Join-Path $Root 'payload.exe') -Destination $OutFile }
    else {
        $hash = (Get-FileHash -LiteralPath (Join-Path $Root 'payload.exe') -Algorithm SHA256).Hash
        if ($BadHash) { $hash = '0' * 64 }
        [IO.File]::WriteAllText($OutFile, $hash + '  TramCanQR-Setup-0.2.0-rc75.exe' + "`n")
    }
}
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru, $WindowStyle)
    if ($FilePath -eq $script:exe) { $script:didOpen = $true; return }
    if (-not $script:didStop) { throw 'Installer started before app stopped' }
    if ((Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath (Join-Path $Root 'payload.exe') -Algorithm SHA256).Hash) { throw 'Wrong installer' }
    if ('/VERYSILENT' -notin $ArgumentList) { throw 'Missing silent installation flag' }
    $script:didInstall = $true
    return @{ExitCode=0}
}
try {
    $raw = Get-Content -LiteralPath $Updater -Raw -Encoding UTF8
    $parts = $raw -split '(?m)^# POWERSHELL\r?\n', 2
    & ([ScriptBlock]::Create($parts[1]))
} finally {
    @{stopped=$script:didStop;installed=$script:didInstall;opened=$script:didOpen} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Root 'result.json') -Encoding UTF8
}
'''


def main():
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="updater-rc75-", dir=project / ".test-tmp") as temp:
        base = Path(temp)
        legacy = base / "rc74.cmd"
        legacy.write_bytes(subprocess.check_output([
            "git", "show", "0f7400468df72213d78923d7d62b8a6dc71de2fc:packaging/CAP-NHAT-BAN-MOI.cmd"], cwd=project))
        harness = base / "harness.ps1"
        harness.write_text(HARNESS, encoding="utf-8-sig")
        for label, updater in (("rc74", legacy), ("rc75", project / "packaging/CAP-NHAT-BAN-MOI.cmd")):
            for bad_hash in (False, True):
                root = base / f"{label}-{bad_hash}"
                root.mkdir()
                for name, data in (("TramCanQR.exe", b"old exe"), ("payload.exe", b"new verified installer"),
                                   ("config.env", b"old private config"), ("measurements.db", b"old customer DB"), ("old.jpg", b"old photo")):
                    (root / name).write_bytes(data)
                protected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ("config.env", "measurements.db", "old.jpg")}
                command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness), "-Root", str(root), "-Updater", str(updater)]
                if bad_hash: command.append("-BadHash")
                result = subprocess.run(command, capture_output=True, timeout=30)
                state = json.loads((root / "result.json").read_text(encoding="utf-8-sig"))
                assert result.returncode == int(bad_hash), (label, bad_hash, result.stdout, result.stderr)
                assert state == {"stopped": not bad_hash, "installed": not bad_hash, "opened": not bad_hash}, state
                assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest for name, digest in protected.items())
                print(f"PASS {label}: {'reject tampered download before stopping app' if bad_hash else 'select rc75, verify hash, stop/install/reopen'}; DB/config/photo unchanged")


if __name__ == "__main__":
    main()
