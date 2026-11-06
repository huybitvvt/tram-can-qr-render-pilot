"""Tests for OpenCV-only QR localization, crop decoding, and annotation."""

from __future__ import annotations

import unittest
from pathlib import Path

import cv2
import numpy as np

from src.modules.qr_reg import QrScanner, draw_qr_box


class QrPipelineTests(unittest.TestCase):
    def test_cropped_qr_maps_box_to_original_image(self):
        code = cv2.QRCodeEncoder_create().encode("DEVICE-001")
        code = cv2.copyMakeBorder(
            cv2.resize(code, (120, 120), interpolation=cv2.INTER_NEAREST),
            15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255,
        )
        image = np.full((720, 1280, 3), 255, dtype=np.uint8)
        image[200:350, 500:650] = cv2.cvtColor(code, cv2.COLOR_GRAY2BGR)
        result = QrScanner().scan(image)
        self.assertEqual(result.data, "DEVICE-001")
        self.assertIsNotNone(result.bbox)
        self.assertGreater(result.bbox[0], 500)
        self.assertGreater(result.bbox[1], 200)
        self.assertTrue(np.any(draw_qr_box(image, result) != image))

    def test_requested_image_decodes_from_crop(self):
        path = Path(__file__).resolve().parents[1] / "ssd" / "test_2" / "0d46b13160adc60a01ecbb8bbe467b1e.jpg"
        image = cv2.imread(str(path))
        self.assertIsNotNone(image)
        result = QrScanner().scan(image)
        self.assertEqual(result.data, "MN-BB414_DYY6WM97H6K")
        self.assertIsNotNone(result.crop)
        self.assertEqual(result.localization, "original")
        self.assertTrue(740 < result.bbox[0] < 790)

    def test_blank_image_has_no_qr_box(self):
        image = np.full((300, 400, 3), 255, dtype=np.uint8)
        result = QrScanner().scan(image)
        self.assertIsNone(result.data)
        self.assertIsNone(result.bbox)
        self.assertTrue(np.array_equal(draw_qr_box(image, result), image))


if __name__ == "__main__":
    unittest.main()
