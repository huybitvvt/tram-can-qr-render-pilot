"""Exercise the shipped retry button API against an isolated fake Supabase."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import numpy as np
from roll_qr_scale.storage import MeasurementStore
from roll_qr_scale.windows_app import APP_VERSION


def main():
    project = Path(__file__).resolve().parents[1]
    cloud_rows, sent, checked = {}, [], []

    class Cloud(BaseHTTPRequestHandler):
        def reply(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            qr_code = query.get('qr_code', [''])[0]
            assert qr_code.startswith('eq.') and 'event_id' not in query, self.path
            qr_code = qr_code[3:]
            checked.append(qr_code)
            self.reply([cloud_rows[qr_code]] if qr_code in cloud_rows else [])

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            event_id = payload['event_id']
            qr_code = payload['qr_code']
            assert qr_code in checked
            assert payload['skip_cloudinary'] is True
            assert 'image_base64' not in payload
            sent.append(event_id)
            cloud_rows[qr_code] = {'id': 102, 'event_id': event_id, 'qr_code': qr_code}
            self.reply({'ok': True, **cloud_rows[qr_code], 'local_backup_committed': True})

        def log_message(self, *args):
            pass

    remote = ThreadingHTTPServer(('127.0.0.1', 0), Cloud)
    threading.Thread(target=remote.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='retry-rc90-', dir=project / '.test-tmp') as temporary:
            sandbox = Path(temporary)
            station = sandbox / 'TramCanQR'
            store = MeasurementStore(station / 'data/measurements.db', station / 'data/captures')
            frame = np.zeros((80, 100, 3), dtype=np.uint8)
            tags = 'SOURCE_DATE=2026-09-26; SOURCE_SHIFT=12C1; SOURCE_MACHINE=TEST'
            existing = store.save('RETRY-EXISTS', 2, 'kg', frame, 'manual', needs_sync=True, weight_raw=tags)
            missing = store.save('RETRY-MISSING', 3, 'kg', frame, 'manual', needs_sync=True, weight_raw=tags)
            for row in (existing, missing):
                store.mark_synced(row.event_id, 99)
            store.close()
            cloud_rows[existing.qr_code] = {'id': 101, 'event_id': '00000000-0000-0000-0000-000000000001',
                                            'qr_code': existing.qr_code}
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            endpoint = f'http://127.0.0.1:{remote.server_port}'
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(('ROLL_SCALE_', 'SUPABASE_KHO_', 'PYTHON'))}
            env.update(LOCALAPPDATA=str(sandbox), ROLL_SCALE_PORT=str(port),
                       ROLL_SCALE_OPEN_BROWSER='0', ROLL_SCALE_HEADLESS='1', ROLL_SCALE_AUTO_SYNC='0',
                       ROLL_SCALE_API_URL=endpoint + '/ingest', ROLL_SCALE_DEVICE_TOKEN='test-token',
                       ROLL_SCALE_SUPABASE_URL=endpoint, ROLL_SCALE_SUPABASE_PUBLISHABLE_KEY='test-key')
            process = subprocess.Popen([str(project / 'dist/TramCanQR/TramCanQR.exe')], env=env,
                                       cwd=sandbox, creationflags=subprocess.CREATE_NO_WINDOW)

            def request(path, payload=None):
                req = Request(f'http://127.0.0.1:{port}' + path,
                              data=json.dumps(payload).encode() if payload is not None else None,
                              headers={'Content-Type': 'application/json'})
                with urlopen(req, timeout=20) as response:
                    return json.load(response)

            try:
                deadline = time.monotonic() + 90
                while True:
                    assert process.poll() is None, 'Frozen application exited'
                    try:
                        status = request('/api/status')
                        break
                    except OSError:
                        assert time.monotonic() < deadline, 'Frozen application startup timed out'
                        time.sleep(.5)
                assert status['weight_engine'] == 'rapidocr' and status['sync_enabled'], status
                reset = request('/api/manual-sync/reset', {'event_ids': [existing.event_id, missing.event_id]})
                assert reset['updated'] == 2 and reset['sync_status'] == 'pending', reset
                filters = {'scope': 'production', 'date_from': '2026-09-26',
                           'date_to': '2026-09-26', 'force': True, 'skip_cloudinary': True}
                for expected_synced, expected_skipped in ((1, 1), (0, 2)):
                    assert request('/api/manual-sync/preview', filters)['total'] == 2
                    request('/api/manual-sync/start', filters)
                    deadline = time.monotonic() + 30
                    while True:
                        job = request('/api/manual-sync/status')
                        if job['state'] != 'running':
                            break
                        assert time.monotonic() < deadline, job
                        time.sleep(.1)
                    assert job['state'] == 'complete' and job['failed'] == 0, job
                    assert job['synced'] == expected_synced and job['skipped'] == expected_skipped, job
                assert sent == [missing.event_id], sent
                print(f'PASS {APP_VERSION}: frozen app resets selected tickets, checks exact QR, sends only missing QR, '
                      'skips QR with a different event_id, repeated retry sends nothing; no real cloud/customer data used')
            finally:
                process.terminate()
                process.wait(timeout=20)
    finally:
        remote.shutdown()
        remote.server_close()


if __name__ == '__main__':
    main()
