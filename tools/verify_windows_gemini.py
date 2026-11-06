"""Verify the rc74 runtime and packaged rc80 Gemini recovery artifacts."""
import hashlib
import marshal
import subprocess
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

from roll_qr_scale.windows_app import APP_VERSION
from verify_ai_auto import normalized


def main():
    root = Path(__file__).resolve().parents[1]
    restored = ["frontend/index.html", *[
        f"backend/src/roll_qr_scale/{name}.py"
        for name in ("test_ui", "app", "storage", "station_session", "sync", "gemini_weight", "gemini_key_manager")
    ]]
    for path in restored:
        original = subprocess.check_output(["git", "show", f"v0.2.0-rc74:{path}"], cwd=root)
        assert (root / path).read_bytes().replace(b"\r\n", b"\n") == original.replace(b"\r\n", b"\n"), path
    package = root / "dist/TramCanQR"
    executable = CArchiveReader(str(package / "TramCanQR.exe"))
    archive = executable.open_embedded_archive("PYZ.pyz")
    for name in ("test_ui", "storage", "station_session", "sync", "gemini_weight", "gemini_key_manager", "codex_oauth"):
        source = root / f"backend/src/roll_qr_scale/{name}.py"
        assert normalized(archive.extract(f"roll_qr_scale.{name}")) == normalized(compile(source.read_bytes(), str(source), "exec", dont_inherit=True)), name
    entry = root / "backend/src/roll_qr_scale/windows_app.py"
    assert normalized(marshal.loads(executable.extract("windows_app"))) == normalized(compile(entry.read_bytes(), str(entry), "exec", dont_inherit=True))
    assert (package / "_internal/assets/frontend/index.html").read_bytes() == (root / "frontend/index.html").read_bytes()
    forbidden = {".env", "config.env", "measurements.db", ".active-bindings.json", "telegram-token.txt"}
    assert not [path for path in package.rglob("*") if path.name in forbidden]
    for name in ("torch", "ultralytics", "paddle", "paddleocr"):
        assert not (package / "_internal" / name).exists(), name
    handoff = root / f"dist/handoff-{APP_VERSION}"
    for line in (handoff / "SHA256SUMS.txt").read_text().splitlines():
        expected, name = line.split("  ", 1)
        assert hashlib.sha256((handoff / name).read_bytes()).hexdigest() == expected.lower(), name
    assert (handoff / "TramCanQR-Setup.exe").read_bytes() == (handoff / f"TramCanQR-Setup-{APP_VERSION}.exe").read_bytes()
    assert (handoff / "CAP-NHAT-BAN-MOI.cmd").read_bytes() == (root / "packaging/CAP-NHAT-BAN-MOI.cmd").read_bytes()
    print(f"PASS {APP_VERSION}: rc74 runtime parity; frozen backend/frontend match; no private config/DB; Gemini-only package; installer hashes match")


if __name__ == "__main__":
    main()
