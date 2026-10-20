# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

project_root = Path(SPECPATH).parent
cv_src = project_root / "new_system" / "Digit_QRCode_Detection" / "backend" / "src"
datas = [
    (str(project_root / "data" / "warehouse_scale_demo.png"), "assets/data"),
    (str(project_root / "data" / "viet_nhat_ipt_logo.jpg"), "assets/data"),
    (str(project_root / "frontend" / "index.html"), "assets/frontend"),
    (str(project_root / "frontend" / "fonts"), "assets/frontend/fonts"),
    (str(project_root / "model" / "best.pt"), "assets/model"),
]
binaries = []
hiddenimports = ["backend.cv.digit_detector", "backend.cv.qr_decoder", "backend.cv.types",
                 "backend.cv.display_locator", "backend.camera.source", "backend.config",
                 "backend.recognition.processor", "backend.recognition.stabilizer"]
for package in ("ultralytics", "zxingcpp", "google.genai"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(
    [str(project_root / "backend" / "src" / "roll_qr_scale" / "windows_app.py")],
    pathex=[str(project_root / "backend" / "src"), str(cv_src)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={"matplotlib": {"backends": ["Agg"]}}, runtime_hooks=[],
    excludes=["easyocr", "paddle", "paddleocr", "paddlex", "fastapi", "uvicorn",
              "tensorflow", "IPython", "jupyter", "pytest", "matplotlib.tests", "numpy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TramCanQR",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          version=str(project_root / "packaging" / "TramCanQR.version"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TramCanQR")
