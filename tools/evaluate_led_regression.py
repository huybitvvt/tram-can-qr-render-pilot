"""Evaluate labeled local images with the real OCR; never saves a scale ticket.

Manifest: JSON array of {"path": "image.png", "expected": "7.10"} records.
Relative image paths are resolved from the current working directory.
"""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import statistics

import cv2
import numpy as np
from tramcan_rapidocr.engine import ScaleReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', type=Path, default=Path('models/rapidocr'))
    parser.add_argument('--baseline', action='store_true', help='Also run the unguarded rc92 recognition path')
    parser.add_argument('--auto-roi', action='store_true', help='Locate the red display in full images')
    args = parser.parse_args()
    samples = json.loads(args.samples.read_text(encoding='utf-8'))
    readers = {'current': ScaleReader(args.models, decimal_policy='fixed-2')}
    if args.baseline:
        readers['baseline'] = ScaleReader(args.models, decimal_policy='fixed-2', leading_guard=False)
    rows = []
    for sample in samples:
        if sample.get('expected') is None:
            continue
        path = Path(sample['path'])
        frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f'Cannot decode image: {path}')
        results = {name: (reader.read(frame) if args.auto_roi else reader.read_crop(frame)).as_dict()
                   for name, reader in readers.items()}
        rows.append({**sample, 'results': results})
    if not rows:
        raise ValueError('No labeled images in manifest')
    summary = {}
    for name in readers:
        counts = Counter()
        for row in rows:
            value = row['results'][name]['weight']
            counts['rejected' if value is None else 'correct' if Decimal(value) == Decimal(row['expected']) else 'wrong'] += 1
        times = sorted(row['results'][name]['elapsed_ms'] for row in rows)
        summary[name] = dict(counts=counts, samples=len(rows), median_ms=statistics.median(times),
                             p95_ms=times[min(len(times)-1, int(len(times)*.95))])
    report = dict(summary=summary, rows=rows,
                  note='Image regressions only; correlated video crops are not a factory accuracy benchmark.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
