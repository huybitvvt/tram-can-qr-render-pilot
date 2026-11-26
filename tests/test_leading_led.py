from decimal import Decimal
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from tramcan_rapidocr.decision import Observation, decide
from tramcan_rapidocr.leading_led import (
    LeadingLEDVerifier, extract_leading_glyph, extract_led_glyphs, normalize_glyph,
)


def panel_text(digits='710', *, height_scale=1, dot_after: int | None = None, tight_pad: bool = False):
    patterns = {'0': 'abcdef', '1': 'bc', '2': 'abdeg', '3': 'abcdg',
                '4': 'bcfg', '5': 'acdfg', '6': 'acdefg', '7': 'abc',
                '8': 'abcdefg', '9': 'abcdfg'}
    pad_x = 4 if tight_pad else 12
    pad_y = 2 if tight_pad else 14
    top_y = pad_y
    bot_y = top_y + 50
    mid_y = (top_y + bot_y) // 2
    img_h = bot_y + pad_y + 2
    img_w = pad_x * 2 + len(digits) * 35
    image = np.full((img_h, img_w, 3), (12, 12, 18), dtype=np.uint8)
    for index, char in enumerate(digits):
        width = 22 if (index == 0 and len(digits) == 3) else 28
        x = pad_x + index * 35
        left, right = x + 3, x + width - 3
        segments = {'a': ((left + 2, top_y), (right - 2, top_y)),
                    'b': ((right, top_y + 3), (right, mid_y - 3)),
                    'c': ((right, mid_y + 3), (right, bot_y - 3)),
                    'd': ((left + 2, bot_y), (right - 2, bot_y)),
                    'e': ((left, mid_y + 3), (left, bot_y - 3)),
                    'f': ((left, top_y + 3), (left, mid_y - 3)),
                    'g': ((left + 2, mid_y), (right - 2, mid_y))}
        for segment in patterns[char]:
            cv2.line(image, *segments[segment], (40, 130, 250), 4, cv2.LINE_AA)
        if dot_after is not None and index == dot_after:
            # Decimal point fused tightly at the bottom-right foot of the digit.
            cv2.circle(image, (right + 3, bot_y), 3, (40, 130, 250), -1, cv2.LINE_AA)
    return cv2.resize(image, None, fx=height_scale, fy=height_scale,
                      interpolation=cv2.INTER_AREA)


def panel(first='7', *, height_scale=1, dot: bool = False):
    return panel_text(first + '10', height_scale=height_scale, dot_after=0 if dot else None)


def reading(*texts):
    observations = [Observation(text, .97, name) for name, text in
                    zip(('red-row', 'gray'), texts, strict=False)]
    return decide(observations, fixed_digits=True)


@pytest.fixture(scope='module')
def verifier():
    return LeadingLEDVerifier()


def verify(verifier, image, *texts):
    return verifier.verify(image, reading(*texts), min_confidence=.85, fixed_digits=True)


def test_classifier_model_is_pinned_and_shipped():
    root = Path(__file__).resolve().parents[1] / 'backend/src/tramcan_rapidocr'
    manifest = json.loads((root / 'led_glyph.json').read_text())
    raw = (root / manifest['file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest['sha256']
    assert len(raw) == manifest['bytes'] < 1_000_000


def test_top_bar_and_seven_geometry_distinguish_seven_from_one_and_two():
    seven, one, two = panel('7'), panel('1'), panel('2')
    seven_dot, two_dot = panel('7', dot=True), panel('2', dot=True)
    before = seven.copy()
    g7 = extract_leading_glyph(seven)
    g7_dot = extract_leading_glyph(seven_dot)
    g1 = extract_leading_glyph(one)
    g2 = extract_leading_glyph(two)
    g2_dot = extract_leading_glyph(two_dot)

    assert g7 is not None and g7.count == 3 and g7.has_top_bar and g7.has_seven_geometry
    assert g7_dot is not None and g7_dot.count == 3 and g7_dot.has_seven_geometry
    assert g1 is not None and not g1.has_top_bar and not g1.has_seven_geometry
    assert g2 is not None and g2.has_top_bar and not g2.has_seven_geometry
    assert g2_dot is not None and not g2_dot.has_seven_geometry
    assert np.array_equal(before, seven)
    normalized = normalize_glyph(g7.pixels)
    assert normalized.shape == (48, 32) and normalized.dtype == np.float32
    assert 0 <= normalized.min() <= normalized.max() <= 1


@pytest.mark.parametrize('texts', [('110', '110'), ('110', '710'), ('710', '110')])
def test_visible_seven_resolves_only_the_leading_1_7_conflict(verifier, texts):
    result = verify(verifier, panel(), *texts)
    assert result.value == Decimal('7.10')
    assert result.reason == 'verified-leading-led'
    assert [o.text for o in result.observations[:2]] == list(texts)
    assert result.observations[-1].variant == verifier.version


@pytest.mark.parametrize('dot', [False, True])
@pytest.mark.parametrize('texts', [('210', '210'), ('210', '710'), ('710', '210'), ('210', '110')])
def test_visible_seven_resolves_leading_2_7_and_1_2_7_confusions(verifier, dot, texts):
    result = verify(verifier, panel('7', dot=dot), *texts)
    assert result.value == Decimal('7.10')
    assert result.reason == 'verified-leading-led'
    assert [o.text for o in result.observations[:2]] == list(texts)
    assert result.observations[-1].variant == verifier.version


@pytest.mark.parametrize('dot', [False, True])
def test_a_real_two_keeps_its_existing_correct_reading(verifier, dot):
    result = verify(verifier, panel('2', dot=dot), '210', '210')
    assert result.value == Decimal('2.10')
    assert result.reason == 'complete-reading'


@pytest.mark.parametrize('dot', [False, True])
def test_real_two_with_seven_conflict_never_turns_into_seven(verifier, dot):
    result = verify(verifier, panel('2', dot=dot), '210', '710')
    assert result.value is None


@pytest.mark.parametrize('first', list('012345689'))
@pytest.mark.parametrize('ocr_pair', [('110', '110'), ('210', '210')])
def test_other_digits_are_never_turned_into_seven(verifier, first, ocr_pair):
    result = verify(verifier, panel(first), *ocr_pair)
    assert result.value != Decimal('7.10')


def test_a_real_one_keeps_its_existing_correct_reading(verifier):
    assert verify(verifier, panel('1'), '110', '110').value == Decimal('1.10')


@pytest.mark.parametrize('texts', [('1208', '1208'), ('1208', '1708'), ('1708', '1208')])
def test_decimal_adjacent_seven_in_tens_weight_resolves_from_two(verifier, texts):
    result = verify(verifier, panel_text('1708', dot_after=1), *texts)
    assert result.value == Decimal('17.08')
    assert result.reason == 'verified-leading-led'


@pytest.mark.parametrize('digits', ['1208', '1294', '2208'])
def test_real_decimal_adjacent_two_in_tens_weight_is_preserved(verifier, digits):
    result = verify(verifier, panel_text(digits, dot_after=1), digits, digits)
    assert result.value == Decimal(digits).scaleb(-2)
    assert result.reason == 'complete-reading'


def test_tight_roi_red_led_is_preserved_while_white_screen_border_is_removed():
    tight = panel_text('708', dot_after=0, tight_pad=True)
    glyphs = extract_led_glyphs(tight)
    assert len(glyphs) == 3 and glyphs[0].has_seven_geometry

    with_border = panel_text('710', dot_after=0)
    # Simulate a bright full-height white UI border along the right edge.
    with_border[:, -5:] = (240, 240, 240)
    glyphs_border = extract_led_glyphs(with_border)
    assert len(glyphs_border) == 3 and glyphs_border[0].has_seven_geometry


@pytest.mark.parametrize('texts', [('110', '718'), ('210', '718'), ('110', '-710'), ('210', '-710')])
def test_other_digits_or_sign_conflicts_remain_rejected(verifier, texts):
    assert verify(verifier, panel(), *texts).value is None


@pytest.mark.parametrize('single_text', ['110', '210'])
def test_one_ocr_view_cannot_establish_the_rest_of_the_weight(verifier, single_text):
    result = verify(verifier, panel(), single_text)
    assert result.value is None and result.reason == 'ambiguous-leading-led'


@pytest.mark.parametrize('ocr_pair', [('110', '110'), ('210', '210')])
def test_uncertain_classifier_does_not_fall_back_to_wrong_one_or_two(verifier, monkeypatch, ocr_pair):
    monkeypatch.setattr(verifier, 'classify', lambda glyph: (7, .98))
    result = verify(verifier, panel(), *ocr_pair)
    assert result.value is None and result.reason == 'ambiguous-leading-led'


@pytest.mark.parametrize('ocr_pair', [('110', '110'), ('210', '210')])
def test_one_threshold_vote_is_not_enough(verifier, monkeypatch, ocr_pair):
    results = iter([(7, .999), (7, .98), (10, .999)])
    monkeypatch.setattr(verifier, 'classify', lambda glyph: next(results))
    result = verify(verifier, panel(), *ocr_pair)
    assert result.value is None and result.reason == 'ambiguous-leading-led'


@pytest.mark.parametrize('ocr_pair', [('110', '110'), ('210', '210')])
def test_confident_contradiction_vetoes_two_seven_votes(verifier, monkeypatch, ocr_pair):
    results = iter([(7, .999), (7, .999), (3, .999)])
    monkeypatch.setattr(verifier, 'classify', lambda glyph: next(results))
    assert verify(verifier, panel(), *ocr_pair).value is None


@pytest.mark.parametrize('ocr_pair', [('110', '110'), ('210', '210')])
def test_guard_respects_a_higher_configured_confidence(verifier, monkeypatch, ocr_pair):
    monkeypatch.setattr(verifier, 'classify', lambda glyph: (7, .992))
    original = decide([Observation(text, .999, variant) for variant, text in zip(('red-row', 'gray'), ocr_pair)],
                      min_confidence=.995, fixed_digits=True)
    result = verifier.verify(panel(), original, min_confidence=.995, fixed_digits=True)
    assert result.value is None


def test_white_printed_glyph_is_not_reinterpreted_as_red_led(verifier):
    image = cv2.cvtColor(cv2.cvtColor(panel(), cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    assert verify(verifier, image, '110', '110').value == Decimal('1.10')
    assert verify(verifier, image, '210', '210').value == Decimal('2.10')


def test_digit_count_mismatch_does_not_invent_a_weight(verifier):
    assert verify(verifier, panel(), '1110', '1110').value == Decimal('11.10')
    assert verify(verifier, panel(), '2110', '2110').value == Decimal('21.10')


def test_empty_and_blank_images_supply_no_digit_evidence():
    assert extract_leading_glyph(np.empty((0, 0, 3), dtype=np.uint8)) is None
    assert extract_leading_glyph(np.zeros((80, 120, 3), dtype=np.uint8)) is None


def test_pinned_scale_reader_fixes_real_factory_784_and_keeps_2015():
    from tramcan_rapidocr.engine import ScaleReader

    root = Path(__file__).resolve().parents[1]
    models = root / 'models' / 'rapidocr'
    if not (models / 'manifest-small.json').is_file():
        pytest.skip('Requires the pinned offline PP-OCRv6 Small models')
    pytest.importorskip('rapidocr')
    reader = ScaleReader(models, decimal_policy='fixed-2')

    f784 = cv2.imread(str(root / 'data' / 'factory_scale_diagnostic_station-01.jpg'))
    r784 = reader.read(f784)
    assert r784.value == Decimal('7.84')
    assert r784.reason == 'verified-leading-led'

    f2015 = cv2.imread(str(root / 'data' / 'factory_scale_diagnostic.jpg'))
    r2015 = reader.read(f2015)
    assert r2015.value == Decimal('20.15')
