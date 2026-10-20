"""Check QR localization and crop decoding across a directory of images."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from statistics import median

import cv2

try:
    from src.modules.qr_reg import QrScanner
except ModuleNotFoundError:
    from modules.qr_reg import QrScanner


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-test OpenCV QR cropping and scanning")
    parser.add_argument("directory", nargs="?", type=Path, default=Path(__file__).resolve().parents[1] / "ssd" / "test_2")
    parser.add_argument("--show-each", action="store_true", help="Print the result of every image")
    parser.add_argument("--show-failures", action="store_true", help="List images with a QR candidate that could not be decoded")
    args = parser.parse_args()
    paths = sorted(path for path in args.directory.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"})
    if not paths:
        parser.error(f"No images found in {args.directory}")

    scanner = QrScanner()
    stages: Counter[str] = Counter()
    decoded = 0
    localized_only = 0
    localized_unreadable_files: list[str] = []
    unreadable_files: list[str] = []
    timings: list[float] = []
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            unreadable_files.append(path.name)
            continue
        result = scanner.scan(image)
        timings.append(result.elapsed_ms)
        if result.data:
            decoded += 1
            stages[result.localization or "unknown"] += 1
        elif result.bbox:
            localized_only += 1
            localized_unreadable_files.append(path.name)
        if args.show_each:
            print(f"{path.name}: qr={result.data!r}, bbox={result.bbox}, stage={result.localization}, attempts={result.decode_attempts}, ms={result.elapsed_ms:.1f}")

    print(f"Images: {len(paths)}")
    print(f"Decoded: {decoded}")
    print(f"Localized but unreadable: {localized_only}")
    print(f"No QR localized: {len(paths) - decoded - localized_only - len(unreadable_files)}")
    print(f"Unreadable image files: {len(unreadable_files)}")
    print(f"Decoded by stage: {dict(stages)}")
    print(f"Median QR scan time: {median(timings):.1f} ms" if timings else "Median QR scan time: n/a")
    if args.show_failures:
        print(f"Localized but unreadable images: {localized_unreadable_files}")
    print("Note: No QR localized does not imply failure; some images have no visible QR code.")


if __name__ == "__main__":
    main()
