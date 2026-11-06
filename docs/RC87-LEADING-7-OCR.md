# RC87: leading 7 intermittently recognized as 2

Base: `8215fb44daa781c714aa67be1eb1a0a09fda8a6f` (rc87).
Local branch: `fix/rc87-led-flicker`.

## Evidence and scope

The supplied 16.6-second clip is a phone recording of the application screen,
not the original USB camera stream. Its enlarged LED preview visibly reads
7.08 while the application alternates between 7.08, an empty reading and 2.08.

The pinned rc87 model reproduces this error when reading crops of that preview.
This establishes an OCR recognition failure; decimal conversion and display
formatting do not explain raw OCR text `208` instead of `708`.

There are two failure paths: a confident incorrect `208` is accepted, or
plausible `708` and `208` disagree and the decision layer rejects the result.
The rejection correctly resets live stability. Suppressing that reset would
allow a previous weight to appear current.

## Scoped change

`recognition_variants` trims dark panel margins around the bright red row,
retains a 10% border, and reads both the unchanged cropped color pixels and
ordinary grayscale. It replaces green-channel CLAHE, which was another source
of incorrect leading digits. Both crop scale and contrast processing affect
these samples; the original color view can also misread 7 as 2.

There is no digit substitution, previous-value hold, confidence reduction or
change to the live stability/capture rules. The model and number of recognition
passes remain unchanged. Nonred input retains its original extent.

## Local evaluation

Sampling every 15 video frames produced 31 usable preview-panel crops. All
were visually labeled 7.08. These are correlated samples from one scene,
not a factory accuracy benchmark.

| Pipeline | 7.08 | Rejected | Incorrect 2.08 |
| --- | ---: | ---: | ---: |
| RC87 Small | 13 | 14 | 4 |
| RC87 Medium, unchanged preprocessing | 16 | 9 | 6 |
| Small with this preprocessing change | 27 | 4 | 0 |

The four remaining rejections include conflicting 7/2 and 1/2 predictions.
The change therefore improves this clip but does not eliminate unreadable
frames. Switching to Medium alone does not solve the demonstrated issue.

Additional checks:

- 96 generated seven-segment panels: 32 values at three size/blur settings,
  including leading 2 and 7. All 96 were read correctly by both pipelines.
- The existing public 13.04 factory reference still reads 13.04 using auto ROI.
- A separate older operator-verified 7.02 photo crop previously read 2.02.
  This change rejects it (raw `70.2`), rather than producing a correct reading.
  It is not evidence that all leading-7 cases are solved.
- Automated tests cover punctuation retention, image edges, nonred fallback,
  conflict rejection, live capture/stability and damaged-goods handling.
  When offline models are installed, they also run actual Small-model reads
  on 24 generated panels and the public 13.04 reference.

Run from the repository root, with the pinned dependencies installed:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'backend\src'
.\.venv\Scripts\python.exe -m pytest tests\test_rapidocr_regions.py tests\test_local_live.py tests\test_damaged_goods.py -o addopts='' -q
```

Field video, extracted frames and detailed per-frame observations remain in
ignored local diagnostics. No factory images were added to the repository.
This preprocessing change is included in rc88; see its release notes for updating.
Native camera behavior and long-running factory operation remain unverified.
