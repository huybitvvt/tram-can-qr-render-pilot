# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from pathlib import Path


project_root = Path(SPECPATH).parent
datas = [
    (str(project_root / "data" / "warehouse_scale_demo.png"), "assets/data"),
    (str(project_root / "data" / "viet_nhat_ipt_logo.jpg"), "assets/data"),
    (str(project_root / "frontend" / "index.html"), "assets/frontend"),
    (str(project_root / "frontend" / "fonts"), "assets/frontend/fonts"),
]
binaries = []
hiddenimports = ["zxingcpp", "google.genai", "google.genai.types"]
for package in ("google.genai", "zxingcpp"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    [str(project_root / "backend" / "src" / "roll_qr_scale" / "windows_app.py")],
    pathex=[str(project_root / "backend" / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "easyocr",
        "paddle",
        "paddleocr",
        "paddlex",
        "torch",
        "torchvision",
        "ultralytics",
        "matplotlib.tests",
        "numpy.tests",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TramCanQR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=str(project_root / "packaging" / "TramCanQR.version"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TramCanQR",
)
