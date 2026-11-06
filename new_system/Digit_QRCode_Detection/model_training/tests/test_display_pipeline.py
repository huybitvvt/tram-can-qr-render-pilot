"""Tests for OpenCV display localization and crop-coordinate mapping."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.modules.display_locator import DisplayRegion, locate_display_candidates
from src.modules.image_reg import _consistent_digit_row, _deduplicate_digits, _predict_region, _validate_model
from src.modules.utils import draw_detections


class ArrayResult:
    def __init__(self, values):
        self.values = np.asarray(values)

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class FakeBoxes:
    def __init__(self):
        self.xyxy = ArrayResult([[2, 3, 12, 13], [20, 3, 30, 13]])
        self.cls = ArrayResult([4, 10])
        self.conf = ArrayResult([0.9, 0.99])

    def __len__(self):
        return 2


class FakeModel:
    names = {**{index: str(index) for index in range(10)}, 10: "none"}

    def predict(self, **kwargs):
        return [SimpleNamespace(boxes=FakeBoxes())]


class DisplayPipelineTests(unittest.TestCase):
    def test_model_2_maps_punctuation_and_shifted_digit_ids(self):
        class NewBoxes:
            xyxy = ArrayResult([[2, 3, 12, 13], [14, 3, 18, 13], [20, 3, 30, 13], [32, 3, 42, 13]])
            cls = ArrayResult([0, 1, 2, 11])
            conf = ArrayResult([0.9, 0.8, 0.95, 0.85])

            def __len__(self):
                return 4

        class NewModel:
            names = {0: "-", 1: ".", **{index + 2: str(index) for index in range(10)}}

            def predict(self, **kwargs):
                return [SimpleNamespace(boxes=NewBoxes())]

        model = NewModel()
        self.assertEqual(_validate_model(model), "model_2")
        detections, ignored = _predict_region(
            model,
            np.zeros((100, 100, 3), dtype=np.uint8),
            DisplayRegion(10, 20, 90, 80, "red", 1.0),
            confidence=0.25,
            image_size=640,
        )
        self.assertEqual(ignored, 0)
        self.assertEqual([item["class_name"] for item in detections], ["-", ".", "0", "9"])
        self.assertEqual(detections[-1]["class_id"], 11)
        self.assertEqual(detections[-1]["bbox"], (42.0, 23.0, 52.0, 33.0))
        annotated = draw_detections(
            np.zeros((100, 100, 3), dtype=np.uint8),
            [item["bbox"] for item in detections],
            [item["class_id"] for item in detections],
            labels=[item["class_name"] for item in detections],
        )
        self.assertTrue(np.any(annotated))

    def test_model_2_keeps_small_decimal_point_in_digit_row(self):
        predictions = [
            {"class_id": 3, "class_name": "1", "confidence": 0.9, "bbox": (10, 20, 25, 60)},
            {"class_id": 4, "class_name": "2", "confidence": 0.9, "bbox": (30, 20, 45, 60)},
            {"class_id": 1, "class_name": ".", "confidence": 0.8, "bbox": (47, 52, 51, 59)},
            {"class_id": 7, "class_name": "5", "confidence": 0.9, "bbox": (55, 20, 70, 60)},
        ]
        selected = _consistent_digit_row(predictions)
        self.assertEqual([item["class_name"] for item in selected], ["1", "2", ".", "5"])

    def test_locates_each_supported_display_color(self):
        bgr_colors = {
            "red": (0, 0, 255),
            "green": (0, 255, 0),
            "blue": (255, 0, 0),
        }
        for name, bgr in bgr_colors.items():
            with self.subTest(color=name):
                image = np.zeros((300, 400, 3), dtype=np.uint8)
                cv2.rectangle(image, (130, 120), (270, 175), bgr, cv2.FILLED)
                regions = locate_display_candidates(image, colors=(name,))
                self.assertTrue(regions)
                self.assertEqual(regions[0].color, name)
                self.assertLessEqual(regions[0].x1, 130)
                self.assertGreaterEqual(regions[0].x2, 270)

    def test_candidate_padding_is_clipped_to_image(self):
        image = np.zeros((200, 300, 3), dtype=np.uint8)
        cv2.rectangle(image, (0, 0), (100, 35), (0, 0, 255), cv2.FILLED)
        region = locate_display_candidates(image, colors=("red",))[0]
        self.assertEqual(region.x1, 0)
        self.assertEqual(region.y1, 0)

    def test_maps_crop_boxes_and_filters_none(self):
        region = DisplayRegion(100, 50, 200, 150, "red", 1.0)
        detections, ignored = _predict_region(
            FakeModel(),
            np.zeros((250, 300, 3), dtype=np.uint8),
            region,
            confidence=0.25,
            image_size=640,
        )
        self.assertEqual(ignored, 1)
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0]["class_id"], 4)
        self.assertEqual(detections[0]["bbox"], (102.0, 53.0, 112.0, 63.0))

    def test_filters_cross_class_duplicates_and_off_row_boxes(self):
        def digit(value, score, box):
            return {
                "class_id": value,
                "class_name": str(value),
                "confidence": score,
                "bbox": box,
            }

        predictions = [
            digit(0, 0.8, (10, 20, 30, 60)),
            digit(8, 0.4, (11, 19, 31, 61)),
            digit(4, 0.9, (35, 20, 55, 60)),
            digit(4, 0.7, (60, 20, 80, 60)),
            digit(0, 0.3, (57, 83, 80, 92)),
            digit(2, 0.35, (85, 0, 145, 80)),
        ]
        selected = _consistent_digit_row(_deduplicate_digits(predictions))
        self.assertEqual([item["class_id"] for item in selected], [0, 4, 4])

    def test_all_test_2_images_have_red_display_candidates(self):
        directory = Path(__file__).resolve().parents[1] / "ssd" / "test_2"
        paths = sorted(directory.glob("*.jpg"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(image=path.name):
                image = cv2.imread(str(path))
                self.assertTrue(
                    locate_display_candidates(image, colors=("red",)),
                    f"No red display candidate found in {path.name}",
                )


if __name__ == "__main__":
    unittest.main()
