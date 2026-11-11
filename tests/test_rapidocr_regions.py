from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
import pytest

from tramcan_rapidocr.decision import Observation, decide
from tramcan_rapidocr.regions import recognition_variants


@pytest.mark.parametrize('color', [(35, 120, 250), (0, 65, 190)])
def test_led_normalization_keeps_minus_decimal_and_all_digit_pixels(color):
    panel = np.full((80, 180, 3), 12, dtype=np.uint8)
    # Separated minus, digit strokes, and decimal: small components must survive.
    cv2.rectangle(panel, (18, 38), (28, 41), color, -1)
    cv2.rectangle(panel, (38, 20), (60, 24), color, -1)
    cv2.rectangle(panel, (55, 20), (60, 57), color, -1)
    cv2.rectangle(panel, (76, 20), (80, 57), color, -1)
    cv2.circle(panel, (90, 56), 2, color, -1)
    cv2.rectangle(panel, (104, 20), (126, 57), color, 4)
    before = panel.copy()

    variants = recognition_variants(panel)
    row, gray = variants[0][1], variants[1][1]

    assert row.shape[0] < panel.shape[0] and row.shape[1] < panel.shape[1]
    # Cropping must preserve the complete lit display, even tiny punctuation.
    assert np.count_nonzero(np.all(row == color, axis=2)) == np.count_nonzero(np.all(panel == color, axis=2))
    assert np.array_equal(gray, cv2.cvtColor(cv2.cvtColor(row, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR))
    assert np.array_equal(panel, before)


def test_led_at_frame_edges_is_not_trimmed():
    panel = np.zeros((24, 60, 3), dtype=np.uint8)
    panel[0:4, :] = (40, 120, 250)
    panel[:, 0:4] = (40, 120, 250)
    panel[-4:, :] = (40, 120, 250)
    panel[:, -4:] = (40, 120, 250)

    assert np.array_equal(recognition_variants(panel)[0][1], panel)


@pytest.mark.parametrize('dim_red', [(0, 0, 200), (0, 10, 180), (0, 25, 190)])
def test_led_normalization_keeps_red_digits_and_punctuation_with_little_green(dim_red):
    panel = np.full((80, 200, 3), 12, dtype=np.uint8)
    # Camera exposure/white balance can leave a complete red stroke with
    # almost no green. A green-channel threshold must not crop it away.
    cv2.rectangle(panel, (12, 38), (22, 41), dim_red, -1)  # minus
    cv2.rectangle(panel, (34, 20), (39, 57), dim_red, -1)  # leading 1
    cv2.circle(panel, (181, 56), 2, dim_red, -1)  # decimal at the other edge
    cv2.rectangle(panel, (70, 20), (92, 57), (35, 120, 250), 4)
    cv2.rectangle(panel, (120, 20), (142, 57), (35, 120, 250), 4)
    before = panel.copy()

    row = recognition_variants(panel)[0][1]

    assert row.shape[0] < panel.shape[0]
    assert np.count_nonzero(np.all(row == dim_red, axis=2)) == np.count_nonzero(np.all(panel == dim_red, axis=2))
    assert np.array_equal(panel, before)


def test_blue_pixels_cannot_be_mistaken_for_red_due_to_uint8_wraparound():
    panel = np.full((30, 80, 3), 10, dtype=np.uint8)
    panel[10:20, 30:50] = (250, 180, 20)

    assert np.array_equal(recognition_variants(panel)[0][1], panel)


def test_nonred_display_keeps_original_extent():
    panel = np.full((40, 90, 3), 12, dtype=np.uint8)
    panel[12:28, 20:70] = 225

    assert np.array_equal(recognition_variants(panel)[0][1], panel)
    assert recognition_variants(np.empty((0, 0, 3), dtype=np.uint8)) == []


def test_conflicting_leading_digits_are_still_rejected():
    reading = decide([
        Observation('708', .95, 'red-row'),
        Observation('208', .75, 'gray'),
    ], fixed_digits=True)

    assert reading.value is None
    assert reading.reason == 'conflicting-readings'


@pytest.mark.parametrize('text, expected', [('208', '2.08'), ('708', '7.08'), ('-708', '-7.08')])
def test_normalization_never_substitutes_numeric_values(text, expected):
    reading = decide([
        Observation(text, .95, 'red-row'),
        Observation(text, .95, 'gray'),
    ], fixed_digits=True)

    assert reading.value == Decimal(expected)


@pytest.fixture(scope='module')
def scale_reader():
    from tramcan_rapidocr.engine import ScaleReader

    root = Path(__file__).resolve().parents[1] / 'models' / 'rapidocr'
    if not (root / 'manifest-small.json').is_file():
        pytest.skip('Requires the pinned offline PP-OCRv6 Small models')
    pytest.importorskip('rapidocr')
    pytest.importorskip('onnxruntime')
    return ScaleReader(root, decimal_policy='fixed-2')


def _seven_segment_panel(text, scale, blur, padding):
    patterns = {
        '0': 'abcdef', '1': 'bc', '2': 'abdeg', '3': 'abcdg', '4': 'bcfg',
        '5': 'acdfg', '6': 'acdefg', '7': 'abc', '8': 'abcdefg', '9': 'abcdfg',
    }
    segments = {
        'a': ((8, 5), (28, 5)), 'b': ((31, 8), (31, 27)),
        'c': ((31, 34), (31, 54)), 'd': ((8, 57), (28, 57)),
        'e': ((5, 34), (5, 54)), 'f': ((5, 8), (5, 27)),
        'g': ((8, 31), (28, 31)),
    }
    panel = np.full((64 + 2 * padding, len(text) * 39 + 2 * padding, 3),
                    (14, 16, 19), dtype=np.uint8)
    for index, digit in enumerate(text):
        for segment in patterns[digit]:
            (x1, y1), (x2, y2) = segments[segment]
            offset = padding + index * 39
            cv2.line(panel, (x1 + offset, y1 + padding), (x2 + offset, y2 + padding),
                     (38, 126, 250), 5, cv2.LINE_AA)
    panel = cv2.resize(panel, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(panel, (3, 3), blur) if blur else panel


@pytest.mark.parametrize('digits', ['208', '202', '278', '708', '702', '728', '1304', '000'])
@pytest.mark.parametrize('scale, blur, padding', [(1, 0, 12), (.5, .3, 15), (.4, .5, 18)])
def test_pinned_model_reads_both_leading_2_and_7(scale_reader, digits, scale, blur, padding):
    panel = _seven_segment_panel(digits, scale, blur, padding)

    assert scale_reader.read_crop(panel).value == Decimal(digits).scaleb(-2)


def test_pinned_model_keeps_public_factory_gross_weight(scale_reader):
    path = Path(__file__).resolve().parents[1] / 'data' / 'factory_scale_13_04_reference.jpg'

    assert scale_reader.read(cv2.imread(str(path))).value == Decimal('13.04')


@pytest.mark.parametrize('digits', ['106', '108', '208', '708', '1304'])
@pytest.mark.parametrize('dim_red', [(0, 0, 200), (0, 10, 180), (0, 25, 190)])
def test_pinned_model_keeps_a_red_leading_digit_when_other_digits_are_brighter(scale_reader, digits, dim_red):
    panel = _seven_segment_panel(digits, 1, 0, 20)
    leading = panel[:, :, 2] > 100
    leading[:, 59:] = False
    panel[leading] = dim_red

    assert scale_reader.read_crop(panel).value == Decimal(digits).scaleb(-2)


def test_red_exposure_changes_reach_live_stability_with_the_current_frame(scale_reader):
    from roll_qr_scale.local_live import LocalLiveReader

    clock = [0.0]
    live = LocalLiveReader(Path('not-used'), reader=scale_reader, clock=lambda: clock[0])
    for sequence, color in enumerate([(0, 0, 200), (0, 10, 180), (35, 120, 250)], 1):
        panel = _seven_segment_panel('106', 1, 0, 20)
        leading = panel[:, :, 2] > 100
        leading[:, 59:] = False
        panel[leading] = color
        clock[0] = sequence * .4
        result = live.preview(panel, station='test', camera='test', source='test',
                              sequence=sequence, roi='0,0,1,1')
        assert result['weight'] == 1.06
        assert result['stable'] is (sequence == 3)

    assert live.claim(result['live_token'], station='test', camera='test', source='test',
                      event='test', kind='product', round_index=0)['weight'] == 1.06
    assert live.resolve(result['live_token'], panel, station='test', camera='test',
                        event='test', kind='product', round_index=0)['weight'] == 1.06
