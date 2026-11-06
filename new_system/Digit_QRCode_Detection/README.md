# Local Scale Detection System

This application reads a digital scale from a USB or wireless camera. The backend detects the scale digits and QR code, while the React frontend displays the live camera stream and detection boxes.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) for Python dependencies
- Node.js 20 or newer and npm
- A USB camera, or a phone/IP camera that provides an HTTP or RTSP video URL
- The trained model at `backend/model/best.pt`

## 1. Install dependencies

Run these commands from the project root:

```sh
cd backend
uv sync

cd ../frontend
npm install
```

## 2. Configure the backend

The backend reads `backend/.env`. If it does not exist, create it from the example:

```sh
cp backend/.env.example backend/.env
```

Do not overwrite an existing `.env`, because it may already contain your camera settings. The minimum important settings are:

```env
MODEL_PATH=backend/model/best.pt

# Use one camera source only.
CAMERA_SOURCE=0
# CAMERA_SOURCE=rtsp://user:password@192.168.1.50:554/stream1

HOST=127.0.0.1
PORT=8000
CORS_ORIGINS=http://localhost:5173
STORAGE_ENABLE=false
```

`CAMERA_SOURCE=0` uses the first USB or built-in camera. Try `1` or `2` if the wrong camera opens. For an iPhone or other phone camera, replace it with the complete video-stream URL supplied by the camera app, for example an RTSP URL or an HTTP MJPEG URL. The phone and computer must normally be on the same network.

The checkpoint must have these 12 class names:

```text
['-', '.', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
```

The system ignores the detected dot and applies `DECIMAL_PLACES=2`, so `040` becomes `0.40`, `643` becomes `6.43`, and `1300` becomes `13.00`.

## 3. Start the backend

Open a terminal and run:

```sh
cd backend
PYTHONPATH=src .venv/bin/python -m backend
```

Keep this terminal open. The backend runs at `http://localhost:8000` and must use one worker so that only one process opens the camera.

Check its status in a browser:

```text
http://localhost:8000/health
```

The response reports whether the camera, model, and optional storage are ready.

## 4. Start the frontend

Open a second terminal and run:

```sh
cd frontend
npm run dev
```

Then open the URL printed by Vite, normally:

```text
http://localhost:5173
```

The page connects to:

- `http://localhost:8000/stream` for live MJPEG video
- `ws://localhost:8000/ws/detections` for QR and digit detection results

## Optional: enable local storage

To save measurements directly to CSV, use these settings in `backend/.env`:

```env
STORAGE_ENABLE=true
STORAGE_TYPE=csv
CSV_PATH=backend/data/measurements.csv
```

The Save button then writes the QR value, detected digits, numeric value, confidence, and timestamps to `backend/data/measurements.csv`.

SQLite is also available without a separate database server:

```env
STORAGE_ENABLE=true
STORAGE_TYPE=sqlite
DATABASE_PATH=backend/data/measurements.db
```

Restart the backend. It creates the database automatically. To export saved measurements later:

```sh
cd backend
PYTHONPATH=src .venv/bin/python -m backend export-csv data/measurements.csv
```

## Optional: test one image without the frontend

The model-testing application can process a particular image and show both digit and QR boxes:

```sh
cd model_training
uv sync
.venv/bin/python src/main.py ssd/test_2/0d46b13160adc60a01ecbb8bbe467b1e.jpg
```

Choose a random image from `ssd/test_2` by omitting the path:

```sh
.venv/bin/python src/main.py
```

## Troubleshooting

- **Camera does not open:** close other programs using the camera, confirm the operating system granted camera permission to the terminal, and try camera indexes `0`, `1`, or `2`.
- **Phone camera does not connect:** verify its stream URL in VLC first, confirm both devices are on the same network, and allow the camera app to keep running.
- **Model is unavailable or rejected:** confirm `backend/model/best.pt` exists and contains the 12 classes listed above.
- **No detection appears:** aim the camera directly at the illuminated display, reduce glare, move closer, and set `DETECTION_DEBUG=true` in `backend/.env` for detailed logs.
- **WebSocket does not connect:** run `uv sync` again in `backend`; the project includes the required `websockets` package.
- **Frontend cannot reach a backend on another device:** set backend `HOST=0.0.0.0`, add the frontend origin to `CORS_ORIGINS`, and set the frontend variables `VITE_API_BASE_URL`, `VITE_VIDEO_STREAM_URL`, and `VITE_DETECTION_WS_URL` to the backend computer's LAN address.

More details are available in [backend/README.md](backend/README.md), [model_training/README.md](model_training/README.md), and the API contract in [docs/ENDPOINT.md](docs/ENDPOINT.md).

## Build a portable one-click folder

To give the application to someone who does not have Python, Node.js, or `uv`, build a platform-specific standalone folder with PyInstaller:

```cmd
scripts\build_windows.bat
```

or on macOS:

```sh
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

See [docs/PORTABLE_BUILD.md](docs/PORTABLE_BUILD.md) for the complete build, distribution, configuration, and launcher instructions.
