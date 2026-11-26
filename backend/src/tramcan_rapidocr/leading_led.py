"""Verify LED seven digits from image strokes and a small offline classifier.

The verifier never chooses a weight from history. It only resolves known 1/7
and 2/7 confusions (at the leading digit or the ones digit immediately before
the decimal point) when the remaining digits agree in two distinct OCR views
and the current image supplies a complete seven-segment 7 glyph.
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

PRIMARY_SCALES = (1.0, 1.1, 1.2)
BLOOM_GRAY_SCALES = (1.3, 1.4)
BLOOM_GREEN_SCALES = (1.1, 1.2, 1.3)


@dataclass(frozen=True)
class LeadingGlyph:
    pixels: np.ndarray
    count: int
    height: int
    top_run: int
    stem_width: float
    lower_left_ink: float = 0.0
    mid_left_ink: float = 0.0
    lower_right_ink: float = 1.0

    @property
    def has_top_bar(self) -> bool:
        return (self.height >= 12 and self.top_run >= self.height * .24
                and self.top_run >= max(2, self.stem_width) * 1.5)

    @property
    def has_seven_geometry(self) -> bool:
        """Seven-segment 7 has a lit top bar and right stem, without 2's e/g strokes."""
        return (self.has_top_bar
                and self.lower_left_ink < .20
                and self.mid_left_ink < .28
                and self.lower_right_ink >= .20)


def _measure_glyph(glyph: np.ndarray, count: int) -> LeadingGlyph:
    h, w = glyph.shape
    top_run = 0
    for line in glyph[:max(1, round(h * .22))]:
        run = 0
        for pixel in line:
            run = run + 1 if pixel else 0
            top_run = max(top_run, run)
    stem = float(np.median(glyph[round(h * .3):round(h * .8)].sum(axis=1)))
    ll_slice = glyph[round(h * .55):round(h * .86), :max(1, round(w * .35))]
    ml_slice = glyph[round(h * .40):round(h * .60), :max(1, round(w * .38))]
    lr_slice = glyph[round(h * .55):round(h * .86), round(w * .42):]
    lower_left = float(ll_slice.mean()) if ll_slice.size else 0.0
    mid_left = float(ml_slice.mean()) if ml_slice.size else 0.0
    lower_right = float(lr_slice.mean()) if lr_slice.size else 0.0
    return LeadingGlyph(glyph, count, h, top_run, stem, lower_left, mid_left, lower_right)


def extract_led_glyphs(
    crop: np.ndarray,
    *,
    threshold_scale: float = 1.,
    channel: str = 'gray',
) -> list[LeadingGlyph]:
    if crop.size == 0:
        return []
    scale = min(1., 160 / crop.shape[0], 1024 / crop.shape[1])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    variants = recognition_variants(crop)
    if not variants:
        return []
    row = variants[0][1]
    blue, green, red = cv2.split(row)
    if channel == 'green':
        if int(green.max()) < 140:
            return []
        signal = green
    else:
        signal = cv2.cvtColor(row, cv2.COLOR_BGR2GRAY)
    threshold, _ = cv2.threshold(signal, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    _, mask = cv2.threshold(signal, min(254, threshold * threshold_scale), 255, cv2.THRESH_BINARY)
    height, width = mask.shape
    # Hot red LEDs have white/yellow centers surrounded by a red halo. Remove
    # any full-span border or non-red light screen border touching the edge;
    # keep red LED digits that touch a tightly cropped ROI boundary.
    red_halo = ((red > 70)
                & (red.astype(np.int16) - green > 10)
                & (red.astype(np.int16) - blue > 15))
    dilated_red = cv2.dilate(red_halo.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for label, (x, y, w, h, _) in enumerate(stats[1:], 1):
        if x == 0 or y == 0 or x + w == width or y + h == height:
            comp = labels == label
            if w == width or h == height or float(np.mean(dilated_red[comp])) < .25:
                mask[comp] = 0
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    anchors = [s for s in stats[1:] if s[4] >= 20 and 2 <= s[2] < width * .55
               and s[3] >= height * .22 and s[3] / s[2] >= 1.2]
    if not anchors:
        return []
    _, ay, _, ah, _ = map(int, max(anchors, key=lambda s: s[4]))
    # Only close tiny vertical gaps (width=1) when crisp seven-segment digits
    # split into separate upper/lower components (<70% of the anchor band span).
    ys_all = np.flatnonzero(mask.any(axis=1))
    if len(ys_all) and ah < (int(ys_all[-1]) - int(ys_all[0]) + 1) * .70:
        v_close = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, round(height * .12))))
        band_probe = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, v_close)
        _, _, v_stats, _ = cv2.connectedComponentsWithStats(band_probe, 8)
        v_anchors = [s for s in v_stats[1:] if s[4] >= 20 and 2 <= s[2] < width * .55
                     and s[3] >= height * .22 and s[3] / s[2] >= 1.2]
        if v_anchors:
            _, ay, _, ah, _ = map(int, max(v_anchors, key=lambda s: s[4]))
    band = mask[max(0, ay - 1):min(height, ay + ah + 1)].copy()
    band_height = band.shape[0]
    _, labels, stats, _ = cv2.connectedComponentsWithStats(band, 8)
    for label, (x, _, w, _, area) in enumerate(stats[1:], 1):
        if area < 3 or ((x == 0 or x + w == width) and w < band_height * .22):
            band[labels == label] = 0
    # Deskew without any numeric hypothesis: aligned vertical strokes have
    # the most concentrated column projection. Only the verifier sees this
    # mask; the evidence image and RapidOCR inputs remain intact.
    best_score, straight = -1., None
    for slope in np.linspace(-.5, .5, 21):
        offset = round(abs(slope) * band_height) + 2
        transform = np.float32([[1, slope, offset], [0, 1, 0]])
        candidate = cv2.warpAffine(band, transform, (width + offset * 2, band_height),
                                   flags=cv2.INTER_NEAREST)
        projection = (candidate > 0).sum(axis=0).astype(float)
        score = float(np.sum(projection ** 2))
        if score > best_score:
            best_score, straight = score, candidate
    ink = straight > 0
    bounds = np.flatnonzero(np.diff(np.r_[False, ink.any(axis=0), False].astype(np.int8)))
    raw_glyphs = []
    for left, right in zip(bounds[::2], bounds[1::2], strict=True):
        ys, xs = np.nonzero(ink[:, left:right])
        if len(xs) and ys.max() - ys.min() + 1 >= ah * .65 and len(xs) >= ah * .7:
            raw_glyphs.append(ink[ys.min():ys.max() + 1, left:right])
    if not raw_glyphs:
        return []
    count = len(raw_glyphs)
    return [_measure_glyph(g, count) for g in raw_glyphs]


def extract_leading_glyph(
    crop: np.ndarray,
    *,
    threshold_scale: float = 1.,
    channel: str = 'gray',
) -> LeadingGlyph | None:
    glyphs = extract_led_glyphs(crop, threshold_scale=threshold_scale, channel=channel)
    return glyphs[0] if glyphs else None


def normalize_glyph(mask: np.ndarray) -> np.ndarray:
    canvas = np.zeros((48, 32), dtype=np.float32)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return canvas
    ink = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    scale = min(28 / ink.shape[1], 44 / ink.shape[0])
    width, height = max(1, round(ink.shape[1] * scale)), max(1, round(ink.shape[0] * scale))
    ink = cv2.resize(ink, (width, height), interpolation=cv2.INTER_AREA)
    left, top = (32 - width) // 2, (48 - height) // 2
    canvas[top:top + height, left:left + width] = ink
    return canvas


def _candidate_positions(numbers: set[str]) -> tuple[bool, str, list[tuple[int, set[str]]]] | None:
    """Return (negative, template_unsigned, [(str_pos, ocr_chars), ...]) when eligible."""
    first = next(iter(numbers))
    negative = first.startswith('-')
    unsigned_set = {text.lstrip('-') for text in numbers}
    if any(text.startswith('-') != negative for text in numbers):
        return None
    template = next(iter(unsigned_set))
    dot_pos = template.find('.')
    if any(len(u) != len(template) or u.find('.') != dot_pos for u in unsigned_set):
        return None
    ones_pos = dot_pos - 1 if dot_pos > 0 else len(template) - 1
    eligible_positions = {0}
    if ones_pos > 0:
        eligible_positions.add(ones_pos)

    # Multiple OCR values: allow verification only when they disagree at a
    # single eligible position and every conflicting character is in 1/2/7.
    if len(unsigned_set) > 1:
        diff_positions = [
            i for i in range(len(template))
            if len({u[i] for u in unsigned_set}) > 1
        ]
        if len(diff_positions) != 1:
            return None
        pos = diff_positions[0]
        if pos not in eligible_positions:
            return None
        chars = {u[pos] for u in unsigned_set}
        if not chars <= {'1', '2', '7'} or chars == {'7'}:
            return None
        return negative, template, [(pos, chars)]

    # Unanimous OCR value: verify leading 1/2, or a decimal-adjacent ones digit '2'.
    checks: list[tuple[int, set[str]]] = []
    if template[0] in ('1', '2'):
        checks.append((0, {template[0]}))
    if ones_pos > 0 and template[ones_pos] == '2':
        checks.append((ones_pos, {'2'}))
    if not checks:
        return None
    return negative, template, checks


class LeadingLEDVerifier:
    def __init__(self, *, threads: int = 2):
        import onnxruntime

        root = Path(__file__).parent
        manifest = json.loads((root / 'led_glyph.json').read_text(encoding='utf-8'))
        path = root / 'led_glyph.onnx'
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if manifest['file'] != path.name or digest != manifest['sha256']:
            raise ValueError('LED glyph model checksum mismatch')
        self.version = str(manifest.get('version') or 'led-glyph-v1')
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
        self.session = onnxruntime.InferenceSession(
            str(path),
            sess_options=options,
            providers=['CPUExecutionProvider'],
        )

    def classify(self, glyph: LeadingGlyph) -> tuple[int, float]:
        image = normalize_glyph(glyph.pixels)[None, None]
        logits = self.session.run(None, {'glyph': image})[0][0]
        probabilities = np.exp(logits - logits.max())
        probabilities /= probabilities.sum()
        label = int(probabilities.argmax())
        return label, float(probabilities[label])

    def _collect_glyphs(self, crop: np.ndarray, digits: int) -> list[tuple[str, list[LeadingGlyph]]]:
        """Extract complete digit sequences across threshold levels.

        Falls back to the green luminance core only if red halation merged
        adjacent digits across every grayscale threshold level.
        """
        found: list[tuple[str, list[LeadingGlyph]]] = []
        merged_seen = False
        for threshold_scale in PRIMARY_SCALES:
            glyphs = extract_led_glyphs(crop, threshold_scale=threshold_scale, channel='gray')
            if len(glyphs) == digits:
                found.append((f't{threshold_scale:.1f}', glyphs))
            elif 0 < len(glyphs) < digits:
                merged_seen = True
        if len(found) < 2 and merged_seen:
            for threshold_scale in BLOOM_GRAY_SCALES:
                glyphs = extract_led_glyphs(crop, threshold_scale=threshold_scale, channel='gray')
                if len(glyphs) == digits:
                    found.append((f't{threshold_scale:.1f}', glyphs))
        if len(found) < 2 and merged_seen:
            for threshold_scale in BLOOM_GREEN_SCALES:
                glyphs = extract_led_glyphs(crop, threshold_scale=threshold_scale, channel='green')
                if len(glyphs) == digits:
                    found.append((f'g{threshold_scale:.1f}', glyphs))
        return found

    def verify(
        self,
        crop: np.ndarray,
        reading: Reading,
        *,
        min_confidence: float,
        fixed_digits: bool,
        region: tuple | None = None,
    ) -> Reading:
        observations = reading.observations
        plausible = []
        for item in observations:
            value = parse_weight(item.text, fixed_digits=fixed_digits)
            if item.confidence >= min(.70, min_confidence) and value is not None:
                plausible.append((item, format(value, '.2f')))
        if not plausible:
            return reading
        numbers = {text for _, text in plausible}
        plan = _candidate_positions(numbers)
        if plan is None:
            return reading
        negative, template, checks = plan
        blue, green, red = cv2.split(crop)
        red_ink = ((red > 80) & (red.astype(np.int16) - green > 10)
                   & (red.astype(np.int16) - blue > 15))
        if np.mean(red_ink) < .03:
            return reading

        digits = sum(char.isdigit() for char in template)
        extracted = self._collect_glyphs(crop, digits)
        if not extracted:
            return reading

        all_traces: list[Observation] = []
        updated = list(template)
        promoted_confidences: list[float] = []
        ambiguous = False

        for pos, ocr_chars in checks:
            glyph_idx = sum(char.isdigit() for char in template[:pos])
            involves_two = '2' in ocr_chars
            unanimous_ocr = len(ocr_chars) == 1 and reading.value is not None
            ocr_label = int(next(iter(ocr_chars))) if unanimous_ocr else None

            votes: list[float] = []
            contradictions = False
            pos_traces: list[tuple[int, float, Observation]] = []

            for tag, glyphs in extracted:
                glyph = glyphs[glyph_idx]
                # A real '2' naturally has a top bar, so 2/7 checks require
                # full seven-segment 7 geometry (no lower-left e or mid-left g).
                geom_ok = glyph.has_seven_geometry if involves_two else glyph.has_top_bar
                if not geom_ok:
                    continue
                label, confidence = self.classify(glyph)
                prefix = 'leading' if glyph_idx == 0 else f'pos{glyph_idx}'
                trace = Observation(
                    f'{prefix}={label if label < 10 else "invalid"}',
                    confidence,
                    f'{self.version}:{tag}',
                    region,
                )
                pos_traces.append((label, confidence, trace))
                if confidence >= max(.99, min_confidence):
                    if label == 7 and glyph.has_seven_geometry:
                        votes.append(confidence)
                    elif label != 10:
                        contradictions = True

            if not pos_traces:
                continue

            # If unanimous OCR (e.g. '12.94') triggered a borderline top-bar
            # check on a real '1' and every classifier trace confirmed that
            # exact OCR digit with zero '7' predictions, keep the reading.
            if (unanimous_ocr
                    and not votes
                    and all(lbl == ocr_label for lbl, _, _ in pos_traces)):
                continue

            all_traces.extend(trace for _, _, trace in pos_traces)
            if len(votes) >= 2 and not contradictions:
                updated[pos] = '7'
                promoted_confidences.append(min(votes))
            else:
                ambiguous = True

        if not all_traces:
            return reading
        observations = [*observations, *all_traces]
        if ambiguous or not promoted_confidences:
            return Reading(None, 'ambiguous-leading-led', observations)

        # A glyph alone cannot establish the rest of the weight. Require two
        # complete, distinct OCR views agreeing on the rest and a confident read.
        if (len({item.variant for item, _ in plausible}) < 2
                or not any(item.confidence >= min_confidence for item, _ in plausible)):
            return Reading(None, 'ambiguous-leading-led', observations)

        decoded = ('-' if negative else '') + ''.join(updated)
        value = parse_weight(decoded, fixed_digits=fixed_digits)
        proof = Observation(decoded, min(promoted_confidences), self.version, region)
        return Reading(value, 'verified-leading-led', [*observations, proof])
