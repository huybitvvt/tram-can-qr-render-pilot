"""Download the pinned public ONNX export for builds; never run on client startup."""
import hashlib
import json
from pathlib import Path
import urllib.request


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root/'backend/src/roll_qr_scale/counter_model.json').read_text(encoding='utf-8'))
    folder = root/'models/roll-counter'
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder/manifest['file']
    if not destination.is_file():
        temporary = destination.with_suffix('.download')
        urllib.request.urlretrieve(manifest['source'], temporary)
        with temporary.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != manifest['sha256']:
                raise ValueError('Counter model SHA-256 mismatch')
        temporary.replace(destination)
    with destination.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == manifest['sha256']
    assert destination.stat().st_size == manifest['bytes']
    print(f"PASS {destination.name}: {manifest['bytes']} bytes, SHA-256 verified")


if __name__ == '__main__':
    main()
