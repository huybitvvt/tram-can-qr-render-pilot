"""Verify a leading seven from image strokes and a small offline classifier.

The verifier never chooses a weight from history. It only resolves the known
1/7 disagreement when the remaining digits agree in both OCR views and the
current image supplies a complete leading glyph with a lit top stroke.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .decision import Observation, Reading
from .parsing import parse_weight
from .regions import recognition_variants


@dataclass(frozen=True)
class LeadingGlyph:
    pixels: np.ndarray
    count: int
    height: int
    top_run: int
    stem_width: float

    @property
    def has_top_bar(self) -> bool:
        return (self.height >= 12 and self.top_run >= self.height * .24
                and self.top_run >= max(2, self.stem_width) * 1.5)


def extract_leading_glyph(crop: np.ndarray, *, threshold_scale: float = 1.) -> LeadingGlyph | None:
    if crop.size == 0:
        return None
    scale = min(1., 160 / crop.shape[0], 1024 / crop.shape[1])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    row = recognition_variants(crop)[0][1]
    gray = cv2.cvtColor(row, cv2.COLOR_BGR2GRAY)
    threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    _, mask = cv2.threshold(gray, min(254, threshold*threshold_scale), 255, cv2.THRESH_BINARY)
    height, width = mask.shape
    # Hot red LEDs have white/yellow centers. A per-pixel chroma test would
    # hollow out their strokes. Remove light screen borders by connectivity.
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for label, (x, y, w, h, _) in enumerate(stats[1:], 1):
        if x == 0 or y == 0 or x+w == width or y+h == height:
            mask[labels == label] = 0
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    anchors = [s for s in stats[1:] if s[4] >= 20 and 2 <= s[2] < width*.55
               and s[3] >= height*.22 and s[3]/s[2] >= 1.2]
    if not anchors:
        return None
    _, ay, _, ah, _ = map(int, max(anchors, key=lambda s: s[4]))
    band = mask[max(0, ay-1):min(height, ay+ah+1)].copy()
    band_height = band.shape[0]
    _, labels, stats, _ = cv2.connectedComponentsWithStats(band, 8)
    for label, (x, _, w, _, area) in enumerate(stats[1:], 1):
        if area < 3 or ((x == 0 or x+w == width) and w < band_height*.22):
            band[labels == label] = 0
    # Deskew without any numeric hypothesis: aligned vertical strokes have
    # the most concentrated column projection. Only the verifier sees this
    # mask; the evidence image and RapidOCR inputs remain intact.
    best_score, straight = -1., None
    for slope in np.linspace(-.5, .5, 21):
        offset = round(abs(slope)*band_height)+2
        transform = np.float32([[1, slope, offset], [0, 1, 0]])
        candidate = cv2.warpAffine(band, transform, (width+offset*2, band_height),
                                   flags=cv2.INTER_NEAREST)
        projection = (candidate > 0).sum(axis=0).astype(float)
        score = float(np.sum(projection**2))
        if score > best_score:
            best_score, straight = score, candidate
    ink = straight > 0
    bounds = np.flatnonzero(np.diff(np.r_[False, ink.any(axis=0), False].astype(np.int8)))
    glyphs = []
    for left, right in zip(bounds[::2], bounds[1::2], strict=True):
        ys, xs = np.nonzero(ink[:, left:right])
        if len(xs) and ys.max()-ys.min()+1 >= ah*.65 and len(xs) >= ah*.7:
            glyphs.append(ink[ys.min():ys.max()+1, left:right])
    if not glyphs:
        return None
    glyph = glyphs[0]
    h = glyph.shape[0]
    top_run = 0
    for line in glyph[:max(1, round(h*.22))]:
        run = 0
        for pixel in line:
            run = run+1 if pixel else 0
            top_run = max(top_run, run)
    stem = float(np.median(glyph[round(h*.3):round(h*.8)].sum(axis=1)))
    return LeadingGlyph(glyph, len(glyphs), h, top_run, stem)


def normalize_glyph(mask: np.ndarray) -> np.ndarray:
    canvas = np.zeros((48, 32), dtype=np.float32)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return canvas
    ink = mask[ys.min():ys.max()+1, xs.min():xs.max()+1].astype(np.float32)
    scale = min(28/ink.shape[1], 44/ink.shape[0])
    width, height = max(1, round(ink.shape[1]*scale)), max(1, round(ink.shape[0]*scale))
    ink = cv2.resize(ink, (width, height), interpolation=cv2.INTER_AREA)
    left, top = (32-width)//2, (48-height)//2
    canvas[top:top+height, left:left+width] = ink
    return canvas


class LeadingLEDVerifier:
    def __init__(self, *, threads: int = 2):
        import onnxruntime

        root = Path(__file__).parent
        manifest = json.loads((root/'led_glyph.json').read_text(encoding='utf-8'))
        path = root/'led_glyph.onnx'
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if manifest['file'] != path.name or digest != manifest['sha256']:
            raise ValueError('LED glyph model checksum mismatch')
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
        self.session = onnxruntime.InferenceSession(str(path), sess_options=options,
                                                    providers=['CPUExecutionProvider'])

    def classify(self, glyph: LeadingGlyph) -> tuple[int, float]:
        image = normalize_glyph(glyph.pixels)[None, None]
        logits = self.session.run(None, {'glyph': image})[0][0]
        probabilities = np.exp(logits-logits.max())
        probabilities /= probabilities.sum()
        label = int(probabilities.argmax())
        return label, float(probabilities[label])

    def verify(self, crop: np.ndarray, reading: Reading, *, min_confidence: float,
               fixed_digits: bool, region: tuple | None = None) -> Reading:
        observations = reading.observations
        plausible = []
        for item in observations:
            value = parse_weight(item.text, fixed_digits=fixed_digits)
            if item.confidence >= min(.70, min_confidence) and value is not None:
                plausible.append((item, format(value, '.2f')))
        if not plausible:
            return reading
        numbers = {text for _, text in plausible}
        first = next(iter(numbers))
        unsigned = first.lstrip('-')
        if unsigned[0] not in '17':
            return reading
        suffix = unsigned[1:]
        negative = first.startswith('-')
        # The verifier owns only the first 1/7 glyph. Other disagreements,
        # signs, decimal locations and all remaining digits remain vetoes.
        if any(text.startswith('-') != negative or text.lstrip('-')[0] not in '17'
               or text.lstrip('-')[1:] != suffix for text in numbers):
            return reading
        if all(text.lstrip('-')[0] == '7' for text in numbers):
            return reading
        blue, green, red = cv2.split(crop)
        red_ink = ((red > 80) & (red.astype(np.int16)-green > 10)
                   & (red.astype(np.int16)-blue > 15))
        if np.mean(red_ink) < .03:
            return reading
        digits = sum(char.isdigit() for char in unsigned)
        votes = []
        contradictions = False
        traces = []
        # Requiring agreement across threshold levels avoids depending on one
        # fragile segmentation of a glowing or compressed stroke. These are
        # views of one frame, not independent model accuracy measurements.
        for threshold_scale in (1., 1.1, 1.2):
            glyph = extract_leading_glyph(crop, threshold_scale=threshold_scale)
            if glyph is None or glyph.count != digits or not glyph.has_top_bar:
                continue
            label, confidence = self.classify(glyph)
            traces.append(Observation(f'leading={label if label < 10 else "invalid"}', confidence,
                                      f'led-glyph-v1:t{threshold_scale:.1f}', region))
            if confidence >= max(.99, min_confidence):
                if label == 7:
                    votes.append(confidence)
                elif label != 10:
                    contradictions = True
        if not traces:
            return reading
        observations = [*observations, *traces]
        if len(votes) < 2 or contradictions:
            return Reading(None, 'ambiguous-leading-led', observations)
        # A glyph alone cannot establish the rest of the weight. Require two
        # complete, distinct OCR views with the same tail and a confident read.
        if (len({item.variant for item, _ in plausible}) < 2
                or not any(item.confidence >= min_confidence for item, _ in plausible)):
            return Reading(None, 'ambiguous-leading-led', observations)
        decoded = ('-' if negative else '')+'7'+suffix
        value = parse_weight(decoded, fixed_digits=fixed_digits)
        proof = Observation(decoded, min(votes), 'led-glyph-v1', region)
        return Reading(value, 'verified-leading-led', [*observations, proof])
