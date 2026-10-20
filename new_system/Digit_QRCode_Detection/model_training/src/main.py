# ==========================================================================
# PURPOSE: MAIN ENDPOINT
# ==========================================================================
# IMPORTS & MODULE LOADING
# ==========================================================================

import argparse
import random
from pathlib import Path

import cv2

try:
    from src.modules.image_reg import analyze_image
    from src.modules.qr_reg import QrScanner, draw_qr_box
except ModuleNotFoundError:
    # Support direct execution with: python src/main.py
    from modules.image_reg import analyze_image
    from modules.qr_reg import QrScanner, draw_qr_box

# ==========================================================================
# PARAMETERS
# ==========================================================================


# ==========================================================================
# CORE LOGIC & FUNCTIONS
# ==========================================================================


# ==========================================================================
# MAIN EXECUTION ENTRYPOINT
# ==========================================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run best.pt on an image and display digit bounding boxes."
    )
    parser.add_argument(
        "image",
        nargs="?",
        type=Path,
        help=(
            "Image to test. When omitted, an image is selected from "
            "ssd/test_2, ssd/test/images, or ssd/valid/images."
        ),
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=None,
        help="YOLO weights path (default: model/best.pt).",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.25,
        help="Minimum prediction confidence (default: 0.25).",
    )
    parser.add_argument(
        "--image-size",
        type=int,
        default=640,
        help="YOLO inference image size (default: 640).",
    )
    parser.add_argument(
        "--display-colors",
        default="red",
        help="Comma-separated display colors: red, green, blue.",
    )
    parser.add_argument(
        "--max-roi-candidates",
        type=int,
        default=5,
        help="Maximum display candidates evaluated by YOLO (default: 5).",
    )
    parser.add_argument(
        "--grayscale",
        action="store_true",
        help="Convert each candidate crop to grayscale before inference.",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Print results without opening an image window (useful for tests).",
    )
    return parser.parse_args()


def choose_random_image(directory: Path) -> Path:
    image_paths = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
    ]
    if not image_paths:
        raise FileNotFoundError(f"No test images found in: {directory}")
    return random.choice(image_paths)


def main():
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    if args.image is None:
        candidates = (
            project_root / "ssd" / "test_2",
            project_root / "ssd" / "test" / "images",
            project_root / "ssd" / "valid" / "images",
        )
        image_directory = next(
            (directory for directory in candidates if directory.is_dir()), None
        )
        if image_directory is None:
            raise FileNotFoundError("No test_2, test, or validation image directory found.")
        image_path = choose_random_image(image_directory)
    else:
        requested_path = args.image.expanduser()
        image_path = (
            choose_random_image(requested_path)
            if requested_path.is_dir()
            else requested_path
        )

    display_colors = tuple(
        color.strip().lower()
        for color in args.display_colors.split(",")
        if color.strip()
    )

    options = {
        "confidence": args.confidence,
        "image_size": args.image_size,
        "grayscale": args.grayscale,
        "display_colors": display_colors,
        "max_roi_candidates": args.max_roi_candidates,
    }
    if args.model is not None:
        options["model_path"] = args.model.expanduser()
    original_image = cv2.imread(str(image_path))
    if original_image is None:
        raise ValueError(f"Could not read image: {image_path}")
    qr_result = QrScanner().scan(original_image)
    result = analyze_image(image_path, **options)
    annotated_image = draw_qr_box(result.annotated_image, qr_result)
    detections = result.detections
    print(f"Model: {args.model or project_root / 'model' / 'best.pt'}")
    print(f"Model mapping: {result.model_version}")
    print(f"Image: {image_path}")
    print(f"QR data: {qr_result.data}")
    print(f"QR box: {qr_result.bbox}")
    print(f"QR localization: {qr_result.localization}")
    print(f"QR crop: {qr_result.crop}")
    print(f"QR preprocessing: {qr_result.preprocessing}")
    print(f"QR decode attempts: {qr_result.decode_attempts} ({qr_result.elapsed_ms:.1f} ms)")
    print(f"Confidence threshold: {args.confidence:.2f}")
    print(f"Inference image size: {args.image_size}")
    print(f"Display colors: {', '.join(display_colors)}")
    print(f"Preprocessing: {'grayscale' if args.grayscale else 'color'}")
    print(f"ROI candidates: {result.candidate_count}")
    print(f"Selected ROI: {result.roi}")
    print(f"Selected display color: {result.display_color}")
    print(f"Selected crop scale: {result.crop_scale}")
    print(f"Selected crop preprocessing: {result.crop_preprocessing}")
    if result.model_version == "model_1":
        print(f"Ignored none detections: {result.ignored_none_count}")
    print(f"Failure reason: {result.failure_reason}")
    print(f"Detections: {len(detections)}")
    if not detections:
        print("  No detections found.")
    else:
        for index, detection in enumerate(detections, start=1):
            x1, y1, x2, y2 = detection["bbox"]
            print(
                f"  {index}. class={detection['class_id']} "
                f"({detection['class_name']}), "
                f"confidence={detection['confidence']:.4f}, "
                f"bbox=({x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f})"
            )
    print(f"Raw reading: {result.raw_digits}")
    if result.raw_digits is not None:
        #==================================================
        # model_1: digits have an implied two-place decimal separator.
        # model_2: '-' and '.' are explicitly detected by the model.
        #==================================================
        try:
            reading = (
                int(result.raw_digits) / 100
                if result.model_version == "model_1"
                else float(result.raw_digits)
            )
        except ValueError:
            print("Reading: incomplete or invalid punctuation sequence")
        else:
            print(f"Reading: {reading:.2f}")

    if args.no_window:
        return
    cv2.namedWindow("Digit + QR detection", cv2.WINDOW_NORMAL)
    cv2.imshow("Digit + QR detection", annotated_image)
    print("Press any key in the image window to close it.")
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
