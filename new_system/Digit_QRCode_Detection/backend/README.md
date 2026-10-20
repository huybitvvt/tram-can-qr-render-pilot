# Local capture backend

FastAPI service for one USB or wireless camera, QR decoding, digit inference, MJPEG video, recognition events, and optional SQLite storage. The API contract is in `../docs/ENDPOINT.md`.

## Setup

From this directory:

```sh
uv sync
```

An existing `.env` is already present. Keep it and use `.env.example` to review optional settings; do not overwrite your camera configuration.

Place trained checkpoint weights at `backend/model/best.pt` (the default `MODEL_PATH`), or set `MODEL_PATH` in `.env` to another path. The backend accepts both `model_1` (class IDs `0`–`9` are digits, optional class `10` is `none`) and `model_2` (class `0` is `-`, class `1` is `.`, classes `2`–`11` are digits `0`–`9`). The mapping is selected from the checkpoint's class names. Both models use `DECIMAL_PLACES` as an implied decimal separator: `040` → `0.40`, `643` → `6.43`, `1300` → `13.00` when set to `2`. The `model_2` dot class is ignored; a leading minus sign is kept for negative readings. Invalid sign placement never becomes save-ready. The base `yolo26n.pt` checkpoint is trained for COCO objects and will be rejected. Set only one `CAMERA_SOURCE`: a USB index such as `0`, or an RTSP/HTTP URL. For wireless cameras, keep credentials only in `.env` and do not commit it.

On Windows, OBS Virtual Camera commonly works best through DirectShow:

```env
CAMERA_SOURCE=0
CAMERA_BACKEND=DSHOW
```

Use `CAMERA_BACKEND=MSMF` to force Microsoft Media Foundation, or leave it blank/use `AUTO` to let OpenCV choose automatically. Restart the backend after changing this value.

Run one server worker so only one process opens the camera:

```sh
PYTHONPATH=src .venv/bin/python -m backend
```

The frontend defaults to `http://localhost:8000` and `ws://localhost:8000/ws/detections`.

The backend locates a colored LED display in each camera frame, tests several tighter crops, and runs the digit model on those crops. The MJPEG stream stays unmodified; WebSocket `detections` include the selected `display` ROI and each `digit` box in full-frame coordinates, which the frontend overlays on the stream. The locator defaults to red LEDs. Set `DISPLAY_COLORS=red,green,blue` if your display uses another color. `DISPLAY_MAX_CANDIDATES` and `DISPLAY_IMAGE_SIZE` control search breadth and model input size.

QR scanning uses OpenCV only, with no extra model. After finding a QR code, it decodes a padded crop around the last QR position on subsequent frames. For a new or moved QR, it locates candidates in the original frame, CLAHE-enhanced grayscale, and a half-size grayscale preview, then tries the tested crop sizes and preprocessing variants from `model_training`. A tiled, upscaled search recovers small QRs that full-frame localization misses. A full-frame decode is the final fallback when a candidate or a previous QR position exists. Decoded boxes are mapped back to full-frame coordinates; stale QR data is never reused. Detection logs include `qr_stage` (`cached_crop`, `localized_crop`, `tiled_crop`, `full_frame`, or `none`).

At the normal log level, the terminal shows digit or QR detections and their timing, plus connection and error messages. Frames with no digit or QR detection are silent. Set `DETECTION_DEBUG=true` to also print every locator candidate, crop, raw prediction, and score, including empty frames. Crop search may take longer than `1 / INFERENCE_FPS`; in that case the backend drops older frames and processes the newest available frame rather than queuing them. The server requires the `websockets` dependency in this project; run `uv sync` after updating dependencies so `/ws/detections` can connect.

## Storage

`STORAGE_ENABLE=false` skips local storage initialization. `GET /measurements` returns `[]`, and `POST /measurements` returns `503 STORAGE_DISABLED`. Recognition and camera streaming still run.

For a directly readable CSV file, use:

```env
STORAGE_ENABLE=true
STORAGE_TYPE=csv
CSV_PATH=backend/data/measurements.csv
```

The frontend's **Save measurement** button writes the validated QR data, raw digits, numeric value, confidence, capture time, and save time to that file. The backend creates the folder and CSV header automatically. Writes are locked and atomically replace the file so camera processing cannot leave a partially written CSV.

SQLite remains available by setting `STORAGE_TYPE=sqlite` and `DATABASE_PATH=backend/data/measurements.db`; no separate database server or manual schema setup is needed.

When storage is enabled, export or copy the saved records to another spreadsheet-compatible file with:

```sh
PYTHONPATH=src .venv/bin/python -m backend export-csv data/measurements.csv
```

## Configuration

See `.env.example` for all supported options. The parser also tolerates a trailing semicolon in boolean values such as `false;`, although plain `false` is recommended. Relative model and database paths resolve from the repository root. Host environment variables override `.env` values.

## API

| Route | Purpose |
| --- | --- |
| `GET /health` | Camera, model, and database readiness. |
| `GET /stream` | Shared camera as MJPEG. |
| `WS /ws/detections` | Recognition JSON events. |
| `GET /measurements` | Recent saved records. |
| `POST /measurements` | Save the current ready recognition. |

The backend can start without model weights or an available camera so the health endpoint reports the problem. Digit recognition requires valid trained weights; QR decoding can still run when the camera is available.
