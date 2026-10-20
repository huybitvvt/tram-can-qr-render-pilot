# Seven-segment model testing

Run the detector on a random image from `ssd/test_2`:

```bash
.venv/bin/python src/main.py
```

Run a particular image or choose a random image from a directory:

```bash
.venv/bin/python src/main.py ssd/test_2/example.jpg
.venv/bin/python src/main.py ssd/test_2
```

`src/main.py` also scans QR codes with OpenCV and draws a separate QR box
alongside the unchanged digit annotations. On the included example:

```bash
.venv/bin/python src/main.py ssd/test_2/0d46b13160adc60a01ecbb8bbe467b1e.jpg
```

The QR payload is `MN-BB414_DYY6WM97H6K`. Add `--no-window` to print results
without opening the annotated image. To check every image in `ssd/test_2`:

```bash
.venv/bin/python src/qr_benchmark.py ssd/test_2 --show-failures
```

The QR pipeline first locates QR-like corners, decodes several padded crops,
then tries contrast-enhanced and half-size localization before a full-frame
fallback. This is OpenCV-only; it uses no extra trained model. A failed scan
does not necessarily mean the algorithm missed a QR, since some frames have
no visible QR code.

The test pipeline uses OpenCV HSV masks to locate the illuminated display,
runs YOLO on four crop widths for up to five display candidates, and tries
mild sharpening at one crop width. It chooses the most coherent row of symbols,
maps their boxes back onto the full image, and prints a reading. Red is the
default display color. Select another known color
or a small set of colors when needed:

```bash
.venv/bin/python src/main.py ssd/test_2 --display-colors green
.venv/bin/python src/main.py ssd/test_2 --display-colors red,green,blue
```

Use `--grayscale` only for comparison. The model version is detected from the
checkpoint class names:

- `model_1` (`best_0.pt`, `best_1.pt`, `best_2.pt`): class IDs `0`–`9` are digits; optional class `10` is `none`. The reading has an implied two-place decimal.
- `model_2` (current `best.pt`): class `0` is `-`, class `1` is `.`, and classes `2`–`11` are digits `0`–`9`. The reading uses the predicted decimal point and sign.

To test an older checkpoint without editing source code:

```bash
.venv/bin/python src/main.py ssd/test_2/0a23f511a1e0d253877ef85b7609b11f.jpg --model model/best_1.pt
```

With the current `best.pt`, these production-style examples produce complete
readings at the default confidence and image size:

```bash
.venv/bin/python src/main.py ssd/test_2/0a23f511a1e0d253877ef85b7609b11f.jpg
.venv/bin/python src/main.py ssd/test_2/0ad3a04f45f5bec271d3374b1a55c30a.jpg
```

With the current `best.pt`, the first example prints `0.44` from class IDs
`2, 1, 6, 6`. Other images can still be misclassified after a correct crop,
so inspect the returned boxes and confidences before using a reading.
