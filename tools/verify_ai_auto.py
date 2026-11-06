"""Reject stale source/assets, missing model or private data in the frozen app."""
import hashlib
import json
import marshal
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def normalized(code):
    return code.replace(co_filename="", co_consts=tuple(
        normalized(value) if isinstance(value, types.CodeType) else value for value in code.co_consts
    ))


def main():
    root = Path(__file__).resolve().parents[1]
    package = root / "dist/TramCanQRAuto"
    executable = CArchiveReader(str(package / "TramCanQRAuto.exe"))
    archive = executable.open_embedded_archive("PYZ.pyz")
    sources = {
        "roll_qr_scale.test_ui": root / "backend/src/roll_qr_scale/test_ui.py",
        "roll_qr_scale.live_camera": root / "backend/src/roll_qr_scale/live_camera.py",
        "roll_qr_scale.station_session": root / "backend/src/roll_qr_scale/station_session.py",
        "roll_qr_scale.sync": root / "backend/src/roll_qr_scale/sync.py",
        "backend.cv.digit_detector": root / "new_system/Digit_QRCode_Detection/backend/src/backend/cv/digit_detector.py",
        "backend.cv.qr_decoder": root / "new_system/Digit_QRCode_Detection/backend/src/backend/cv/qr_decoder.py",
    }
    for module, source in sources.items():
        expected = compile(source.read_bytes(), str(source), "exec", dont_inherit=True)
        assert normalized(archive.extract(module)) == normalized(expected), f"Stale frozen module: {module}"
        print("Source matches:", module)
    entry = root / "backend/src/roll_qr_scale/windows_auto_app.py"
    assert normalized(marshal.loads(executable.extract("windows_auto_app"))) == normalized(compile(entry.read_bytes(), str(entry), "exec", dont_inherit=True))
    print("Source matches: Windows AI Auto entry point")
    assets = package / "_internal/assets"
    assert (assets / "frontend/index.html").read_bytes() == (root / "frontend/index.html").read_bytes()
    model = assets / "model/best.pt"
    info = json.loads((root / "model/MODEL-INFO.json").read_text())
    assert hashlib.sha256(model.read_bytes()).hexdigest() == info["sha256"]
    assert model.stat().st_size == info["bytes"]
    forbidden = {".env", "config.env", "measurements.db", ".active-bindings.json"}
    assert not [path for path in package.rglob("*") if path.name in forbidden]
    handoff = root / "dist/handoff-ai-auto-beta1"
    hashes = (handoff / "SHA256SUMS.txt").read_text().splitlines()
    for line in hashes:
        expected, name = line.split("  ", 1)
        assert hashlib.sha256((handoff / name).read_bytes()).hexdigest().lower() == expected.lower()
    assert (handoff / "TramCanQRAuto-Setup.exe").read_bytes() == (handoff / "TramCanQRAuto-Setup-0.2.0-ai-auto-beta1.exe").read_bytes()
    print("PASS: frozen code, frontend, model, installer hashes; no runtime config or existing DB in package")


if __name__ == "__main__":
    main()
