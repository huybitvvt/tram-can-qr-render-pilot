# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata
from pathlib import Path
from importlib.metadata import distribution
import sys


project_root = Path(SPECPATH).parent
datas = [
    (str(project_root / "data" / "warehouse_scale_demo.png"), "assets/data"),
    (str(project_root / "data" / "viet_nhat_ipt_logo.jpg"), "assets/data"),
    (str(project_root / "frontend" / "index.html"), "assets/frontend"),
    (str(project_root / "frontend" / "local-ocr.js"), "assets/frontend"),
    (str(project_root / "frontend" / "fonts"), "assets/frontend/fonts"),
]
binaries = []
hiddenimports = ["zxingcpp", "onnxruntime", "PIL.ImageTk", "roll_qr_scale.local_camera"]
for package in ("zxingcpp",):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

datas += collect_data_files('rapidocr') + collect_data_files('tramcan_rapidocr')
datas += copy_metadata('rapidocr') + copy_metadata('onnxruntime')
hiddenimports += collect_submodules('rapidocr')
for name in ('PP-OCRv6_det_small.onnx', 'PP-OCRv6_rec_small.onnx', 'manifest-small.json'):
    datas.append((str(project_root/'models'/'rapidocr'/name), 'assets/models/rapidocr'))
datas.append((str(project_root/'licenses'), 'licenses'))
for name in ['rapidocr','onnxruntime','numpy','opencv-python-headless','Pillow','omegaconf',
             'pyclipper','shapely','PyYAML','requests','tqdm','six','colorlog','colorama',
             'certifi','charset-normalizer','idna','urllib3','protobuf','flatbuffers',
             'packaging','cryptography','cffi','pycparser','pyserial','zxing-cpp']:
    dist = distribution(name)
    for entry in dist.files or []:
        path = Path(dist.locate_file(entry))
        if path.is_file() and any(word in path.name.lower() for word in ('license','copying','notice')):
            datas.append((str(path), f'licenses/{name}/{entry.parent}'))
if (Path(sys.base_prefix)/'LICENSE.txt').is_file():
    datas.append((str(Path(sys.base_prefix)/'LICENSE.txt'), 'licenses/Python'))

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
        "google.genai",
        "google.generativeai",
        "google.auth",
        "tensorflow",
        "openvino",
        "tensorrt",
        "pytest",
        "matplotlib",
        "scipy",
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
