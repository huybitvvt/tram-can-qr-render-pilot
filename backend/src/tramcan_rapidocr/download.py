"""Explicit, resumable model downloads verified against the upstream tag."""

import hashlib
import json
from pathlib import Path
import subprocess


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def download(root: Path, key: str) -> Path:
    spec = json.loads(Path(__file__).with_name('model_sources.json').read_text())['models'][key]
    root.mkdir(parents=True,exist_ok=True)
    target = root/spec['file']
    if target.exists():
        if digest(target)!=spec['sha256']:
            raise ValueError(f'Existing model differs from upstream; refusing to overwrite {target}')
        return target
    partial = target.with_suffix('.onnx.part')
    if not partial.exists() or digest(partial)!=spec['sha256']:
        print(f'Downloading {spec["file"]} (resumable)',flush=True)
        subprocess.run(['curl.exe' if __import__('os').name=='nt' else 'curl',
            '--location','--fail','--silent','--show-error','--continue-at','-',
            '--connect-timeout','15','--max-time','600','--retry','2',
            spec['url'],'-o',str(partial)],check=True)
    if digest(partial)!=spec['sha256']:
        raise ValueError(f'Download checksum mismatch for {partial}')
    partial.rename(target)
    print(f'Verified {spec["file"]}',flush=True)
    return target
