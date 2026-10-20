"""Train the seven-segment digit detector locally.

Run from the repository root with: ``python -m src.train``.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_CONFIG = PROJECT_ROOT / "ssd" / "data.yaml"
BASE_WEIGHTS = PROJECT_ROOT / "model" / "yolo26n.pt"


def validate_labels(data_config: Path) -> None:
    """Fail early when a label class id is absent from ``data.yaml``."""
    with data_config.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    class_count = int(data["nc"])
    label_files = list((data_config.parent / "train" / "labels").glob("*.txt"))
    label_files += list((data_config.parent / "valid" / "labels").glob("*.txt"))
    invalid_ids: set[int] = set()

    for label_file in label_files:
        for line in label_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                class_id = int(line.split(maxsplit=1)[0])
                if not 0 <= class_id < class_count:
                    invalid_ids.add(class_id)

    if invalid_ids:
        raise ValueError(
            f"data.yaml declares nc={class_count} (valid ids: 0-{class_count - 1}), "
            f"but the labels use {sorted(invalid_ids)}. Fix data.yaml and/or the labels "
            "before training."
        )


def train() -> None:
    """Train from COCO weights and store output in ``runs/detect/digits``."""
    if not DATA_CONFIG.is_file():
        raise FileNotFoundError(f"Dataset configuration not found: {DATA_CONFIG}")
    if not BASE_WEIGHTS.is_file():
        raise FileNotFoundError(f"Base weights not found: {BASE_WEIGHTS}")

    validate_labels(DATA_CONFIG)
    model = YOLO(str(BASE_WEIGHTS))
    model.train(
        data=str(DATA_CONFIG),
        epochs=100,
        imgsz=640,
        batch=8,
        project=str(PROJECT_ROOT / "runs" / "detect"),
        name="digits",
        exist_ok=True,
    )


if __name__ == "__main__":
    train()
