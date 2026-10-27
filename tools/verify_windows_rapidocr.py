"""Verify the frozen local app matches reviewed source, trial model and rc80 storage."""
import ast
import hashlib
import json
import marshal
from pathlib import Path
import subprocess

from PyInstaller.archive.readers import CArchiveReader
from verify_ai_auto import normalized
from roll_qr_scale.windows_app import APP_VERSION


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    package = root/'dist'/'TramCanQR'
    executable = CArchiveReader(str(package/'TramCanQR.exe'))
    archive = executable.open_embedded_archive('PYZ.pyz')
    for prefix, names in [('roll_qr_scale', ['test_ui','storage','station_session','sync','api_client',
        'warehouse','local_live','local_camera','local_camera_manager']),
        ('tramcan_rapidocr', ['engine','decision','parsing','regions'])]:
        for name in names:
            source = root/'backend'/'src'/prefix/(name+'.py')
            actual = archive.extract(prefix+'.'+name)
            assert normalized(actual)==normalized(compile(source.read_bytes(), str(source), 'exec', dont_inherit=True)),name
    entry = root/'backend/src/roll_qr_scale/windows_app.py'
    assert normalized(marshal.loads(executable.extract('windows_app')))==normalized(compile(entry.read_bytes(),str(entry),'exec',dont_inherit=True))
    for name in ('index.html','local-ocr.js'):
        assert (package/'_internal/assets/frontend'/name).read_bytes()==(root/'frontend'/name).read_bytes(),name
    for name in ('storage','station_session','sync','api_client'):
        relative = f'backend/src/roll_qr_scale/{name}.py'
        old = subprocess.check_output(['git','show',f'v0.2.0-rc80:{relative}'],cwd=root)
        assert (root/relative).read_bytes().replace(b'\r\n',b'\n')==old.replace(b'\r\n',b'\n'),name
    warehouse_path = 'backend/src/roll_qr_scale/warehouse.py'
    old_warehouse = subprocess.check_output(['git','show',f'v0.2.0-rc80:{warehouse_path}'],cwd=root)
    def warehouse_core(source):
        module = ast.parse(source)
        module.body = [node for node in module.body
            if not (isinstance(node, ast.FunctionDef) and node.name in {'_push_time_text','_summary_csv_text'})
            and not (isinstance(node, ast.ImportFrom) and node.module == 'datetime')]
        return ast.dump(module, include_attributes=False)
    assert warehouse_core(old_warehouse) == warehouse_core((root/warehouse_path).read_bytes())
    info = json.loads((root/'backend/src/tramcan_rapidocr/model_sources.json').read_text())['models']
    for key in ('det-small','rec-small'):
        model = package/'_internal/assets/models/rapidocr'/info[key]['file']
        assert digest(model)==info[key]['sha256'],model
    forbidden = {'.env','.env.local','config.env','measurements.db','.active-bindings.json','telegram-token.txt'}
    assert not [p for p in package.rglob('*') if p.name in forbidden]
    assert not [name for name in archive.toc if name.startswith(('google.genai','google.generativeai','torch','paddleocr','ultralytics'))]
    for name in ('torch','ultralytics','paddle','paddleocr','google/genai'):
        assert not (package/'_internal'/name).exists(),name
    handoff = root/f'dist/handoff-{APP_VERSION}'
    for line in (handoff/'SHA256SUMS.txt').read_text().splitlines():
        expected,name = line.split('  ',1)
        assert digest(handoff/name)==expected,name
    assert digest(handoff/'TramCanQR-Setup.exe')==digest(handoff/f'TramCanQR-Setup-{APP_VERSION}.exe')
    assert (handoff/'CAP-NHAT-BAN-MOI.cmd').read_bytes()==(root/'packaging/CAP-NHAT-BAN-MOI.cmd').read_bytes()
    print(f'PASS {APP_VERSION}: frozen modules/frontend match source; trial model SHA matches; '
          'rc80 storage/sync/schema and warehouse write path unchanged; warehouse export time added; '
          'Gemini SDK absent; no private config/DB; installer hashes match')


if __name__=='__main__':main()
