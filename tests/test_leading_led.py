from decimal import Decimal
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from tramcan_rapidocr.decision import Observation, decide
from tramcan_rapidocr.leading_led import (
    LeadingLEDVerifier, extract_leading_glyph, normalize_glyph,
)


def panel(first='7', *, height_scale=1):
    patterns = {'0': 'abcdef', '1': 'bc', '2': 'abdeg', '3': 'abcdg',
                '4': 'bcfg', '5': 'acdfg', '6': 'acdefg', '7': 'abc',
                '8': 'abcdefg', '9': 'abcdfg'}
    image = np.full((80, 120, 3), (12, 12, 18), dtype=np.uint8)
    for index, char in enumerate(first+'10'):
        width = 22 if index == 0 else 32
        x = 12+index*35
        left, right = x+3, x+width-3
        segments = {'a': ((left+2, 14), (right-2, 14)),
                    'b': ((right, 17), (right, 36)),
                    'c': ((right, 42), (right, 61)),
                    'd': ((left+2, 64), (right-2, 64)),
                    'e': ((left, 42), (left, 61)),
                    'f': ((left, 17), (left, 36)),
                    'g': ((left+2, 39), (right-2, 39))}
        for segment in patterns[char]:
            cv2.line(image, *segments[segment], (40, 130, 250), 4, cv2.LINE_AA)
    return cv2.resize(image, None, fx=height_scale, fy=height_scale,
                      interpolation=cv2.INTER_AREA)


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
    root = Path(__file__).resolve().parents[1]/'backend/src/tramcan_rapidocr'
    manifest = json.loads((root/'led_glyph.json').read_text())
    raw = (root/manifest['file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest['sha256']
    assert len(raw) == manifest['bytes'] < 1_000_000


def test_top_bar_distinguishes_a_narrow_seven_from_one_without_changing_pixels():
    seven, one = panel('7'), panel('1')
    before = seven.copy()
    glyph = extract_leading_glyph(seven)
    assert glyph is not None and glyph.count == 3 and glyph.has_top_bar
    assert extract_leading_glyph(one) is not None
    assert not extract_leading_glyph(one).has_top_bar
    assert np.array_equal(before, seven)
    normalized = normalize_glyph(glyph.pixels)
    assert normalized.shape == (48, 32) and normalized.dtype == np.float32
    assert 0 <= normalized.min() <= normalized.max() <= 1


@pytest.mark.parametrize('texts', [('110', '110'), ('110', '710'), ('710', '110')])
def test_visible_seven_resolves_only_the_leading_1_7_conflict(verifier, texts):
    result = verify(verifier, panel(), *texts)
    assert result.value == Decimal('7.10')
    assert result.reason == 'verified-leading-led'
    assert [o.text for o in result.observations[:2]] == list(texts)
    assert result.observations[-1].variant == 'led-glyph-v1'


@pytest.mark.parametrize('first', list('012345689'))
def test_other_digits_are_never_turned_into_seven(verifier, first):
    result = verify(verifier, panel(first), '110', '110')
    assert result.value != Decimal('7.10')


def test_a_real_one_keeps_its_existing_correct_reading(verifier):
    assert verify(verifier, panel('1'), '110', '110').value == Decimal('1.10')


@pytest.mark.parametrize('texts', [('110', '718'), ('110', '210'), ('110', '-710')])
def test_other_digits_or_sign_conflicts_remain_rejected(verifier, texts):
    assert verify(verifier, panel(), *texts).value is None


def test_one_ocr_view_cannot_establish_the_rest_of_the_weight(verifier):
    result = verify(verifier, panel(), '110')
    assert result.value is None and result.reason == 'ambiguous-leading-led'


def test_uncertain_classifier_does_not_fall_back_to_the_wrong_one(verifier, monkeypatch):
    monkeypatch.setattr(verifier, 'classify', lambda glyph: (7, .98))
    result = verify(verifier, panel(), '110', '110')
    assert result.value is None and result.reason == 'ambiguous-leading-led'


def test_one_threshold_vote_is_not_enough(verifier, monkeypatch):
    results = iter([(7, .999), (7, .98), (10, .999)])
    monkeypatch.setattr(verifier, 'classify', lambda glyph: next(results))
    result = verify(verifier, panel(), '110', '110')
    assert result.value is None and result.reason == 'ambiguous-leading-led'


def test_confident_contradiction_vetoes_two_seven_votes(verifier, monkeypatch):
    results = iter([(7, .999), (7, .999), (3, .999)])
    monkeypatch.setattr(verifier, 'classify', lambda glyph: next(results))
    assert verify(verifier, panel(), '110', '110').value is None


def test_guard_respects_a_higher_configured_confidence(verifier, monkeypatch):
    monkeypatch.setattr(verifier, 'classify', lambda glyph: (7, .992))
    original = decide([Observation('110', .999, variant) for variant in ('red-row', 'gray')],
                      min_confidence=.995, fixed_digits=True)
    result = verifier.verify(panel(), original, min_confidence=.995, fixed_digits=True)
    assert result.value is None


def test_white_printed_glyph_is_not_reinterpreted_as_red_led(verifier):
    image = cv2.cvtColor(cv2.cvtColor(panel(), cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    assert verify(verifier, image, '110', '110').value == Decimal('1.10')


def test_digit_count_mismatch_does_not_invent_a_weight(verifier):
    assert verify(verifier, panel(), '1110', '1110').value == Decimal('11.10')


def test_empty_and_blank_images_supply_no_digit_evidence():
    assert extract_leading_glyph(np.empty((0, 0, 3), dtype=np.uint8)) is None
    assert extract_leading_glyph(np.zeros((80, 120, 3), dtype=np.uint8)) is None
