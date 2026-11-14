# Vision worker

Reads video, finds and tracks people, and sends one `restricted_zone_entry` event to the API when a person enters a configured zone.

```text
video source ─► person tracker ─► restricted-zone rule ─► event publisher ─► POST /v1/events
(sources.py)    (detection.py)     (rules.py, zones.py)    (events.py, publisher.py)
```

`pipeline.py` connects these parts and `__main__.py` is the command line. Each part only talks to its neighbour through a small data type (`Frame`, `TrackedPerson`, `ZoneEntry`, event dict), so one part can change without rewriting the others.

## Setup (Windows, from `worker/`)

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0
.venv\Scripts\python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

On macOS/Linux, use `python3.14` and `.venv/bin/python`. With an NVIDIA GPU, install the CUDA build of `torch==2.15.0` instead of the CPU one, and set `device = "0"` in the config.

Edit `worker/.env` and set `NIGAHSENSE_WORKER_KEY` to the **same** value as `WORKER_API_KEYS` in `backend/.env`.

**Test video.** Videos are never committed. The milestone uses OpenCV's sample pedestrian clip (Apache-2.0, 8 MB):

```powershell
New-Item -ItemType Directory -Force samples
curl.exe -L -o samples/vtest.avi https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi
```

**Model weights** (`models/yolo26s.pt`, 20 MB) download automatically on the first run. They are never committed.

## Run the full flow locally

You need three terminals. Each command block below says which folder to run it from.

1. **Emulators**, from the repo root (needs Java 21+):
   ```powershell
   npx firebase-tools@15 emulators:start --only firestore,auth --project demo-nigahsense
   ```
2. **API**, from `backend/` (see the root README for `backend/.env`):
   ```powershell
   .venv\Scripts\python -m uvicorn app.main:app --port 8000
   ```
3. **Worker**, from `worker/`:
   ```powershell
   .venv\Scripts\python -m nigah_worker --config config/worker.example.toml --annotated runtime/annotated.mp4
   ```

On the sample video this sends 2 events, one per person, at about 53 s into the clip. Each one prints `API 201 ... "outcome": "created"`. Open the emulator UI at http://127.0.0.1:4000/firestore to see the `incidents` documents.

### Useful options

| Option | Effect |
|---|---|
| `--show` | Live window with zones, boxes and track IDs (press `q` to stop) |
| `--annotated runtime/x.mp4` | Save a review video with the same drawings |
| `--dry-run` | Detect and log events, but send nothing (no API needed) |
| `--no-realtime` | Process a file as fast as the CPU allows instead of at video speed |
| `--video path.mp4` | Use another file |
| `--webcam-index 0` | Use a local webcam |
| `--source rtsp` | Use the RTSP URL in `NIGAHSENSE_RTSP_URL` |
| `--max-frames N` | Stop after N frames |

**What you can see:** the console logs each entry and each API reply. `runtime/events.jsonl` records every event and API result. `runtime/outbox.jsonl` holds events that could not be delivered yet.

### Behaviour on problems

| Situation | What happens |
|---|---|
| Video path wrong or file unreadable | Clear error message, exit code 2 |
| End of video | Stops normally (or loops with `loop = true`) |
| API down or slow (connection error, timeout, 429, 5xx) | Retries with backoff using the **same** `event_id`. After `NIGAHSENSE_MAX_SEND_ATTEMPTS`, or at shutdown, the event is saved to the outbox and re-sent on the next start |
| API rejects an event (401, 409, 422) | Not retried. Logged and kept in the outbox, marked `retryable: false`, for someone to inspect |
| Webcam/RTSP drops | Reconnects with exponential backoff (1 s doubling to 30 s), forever unless `max_reconnect_attempts` is set |
| Ctrl+C | Finishes the frame, gives queued events up to 15 s to send, and saves the rest to the outbox. A second Ctrl+C exits immediately |

## Zones

```toml
[[zones]]
id = "zone-south-lawn"          # lowercase, matches the API's zone_id rule
name = "Restricted: south lawn"
points = [[0.00, 0.50], [0.42, 0.63], [0.56, 1.00], [0.00, 1.00]]
```

- `points` are polygon corners as `[x, y]`, **normalised** to the frame. `x` runs from 0 (left edge) to 1 (right edge), and `y` from 0 (top edge) to 1 (bottom edge). The same zone works at any resolution.
- Give at least 3 points, in order around the shape (either direction). Concave shapes work.
- A person is inside when the **bottom centre of their box** (their feet) is inside the polygon. Use `anchor = "center"` for top-down cameras.
- To find coordinates: take a pixel position from a frame and divide by the frame width and height. For example, (336, 363) on a 768×576 frame → [0.44, 0.63].

## Alert rule (`[rule]`)

| Setting | Default | Meaning |
|---|---|---|
| `confirm_frames` | 3 | Feet inside for this many processed frames before it counts as an entry |
| `min_score` | 0.40 | Frames with lower detector confidence do not count |
| `exit_frames` | 5 | Frames outside before the person counts as having left |
| `track_gap_seconds` | 5 | Track forgotten after being unseen this long. Shorter gaps do not re-alert |
| `reentry_cooldown_seconds` | 30 | The same track re-entering sooner than this does not alert again |

A person standing in the zone produces **one** event, not one per frame.

**Known limit:** the rule cannot tell that a *new* track ID is the same person. If the tracker loses someone and gives them a new ID, a second event follows. That is what caused a duplicate alert on the sample video before the detector/tracker change below. Tracking quality, not the rule, is where this is fixed.

## Evaluate accuracy (no API or Firestore needed)

`nigah_worker/evaluation.py` runs detection once, caches every person box, then replays the cache through any tracker setting plus the real zone rule and scores the result against a hand-checked ground-truth file. Run it from `worker/`:

```powershell
# 1. Detector pass, once per video/model/size (a few minutes on CPU). Cache goes to runtime/eval/
.venv\Scripts\python -m nigah_worker.evaluation detect --video samples/vtest.avi --model models/yolo26s.pt

# 2. Tracker + zone rule + score (seconds). Add --dump file.jsonl for per-frame tracks, feet, zone decisions and alerts
.venv\Scripts\python -m nigah_worker.evaluation run --video samples/vtest.avi --model models/yolo26s.pt `
    --tracker config/trackers/bytetrack-nigah.yaml --truth eval/ground_truth/vtest.json
```

Options: `--set key=value` overrides one tracker setting, `--det-conf` sets the detector threshold passed to the tracker, `--stride N` processes every Nth frame, `--imgsz` sets the detector input size, and `--live` runs the model per frame (needed for ReID trackers).

**Output.**
- `correct`, `missed`: entries found and not found.
- `duplicates`: extra alerts for a person already alerted.
- `false_alerts`: alerts for nobody, or for someone who never entered.
- `id_switches`: track ID changes along each person's path.
- `ignored_ambiguous`: alerts for people marked ambiguous, which are not scored.

**Ground truth** (`eval/ground_truth/*.json`): one entry per person, with `enters_zone` (`true`, `false` or `"ambiguous"`), `enter_frame`, and `keyframes` as `[frame, feet_x, feet_y]` in pixels. A person counts as entered when their feet are at least 12 px inside the polygon for at least 3 frames; shallower is ambiguous. Positions come from detector boxes that were checked by eye, and frames where identity is unclear (people overlapping, half out of frame) are left out. Both files say how they were made.

**Second test clip** (dense crowd, same camera; CC BY-NC-SA 3.0, non-commercial research use):
```powershell
curl.exe -L -o samples/PETS09-S2L2-raw.webm https://motchallenge.net/sequenceVideos/PETS09-S2L2-raw.webm
```

### Measured results (2026-11-14, south-lawn zone, CPU)

| Setup | vtest.avi (2 true entries) | PETS09-S2L2 (4 true + 1 ambiguous) | Worker speed |
|---|---|---|---|
| Before: `yolo26n` + stock ByteTrack | 2 correct, **1 duplicate**, 2 ID switches | 4 correct, 0 extra, 0 switches | 7.9 fps |
| **Now: `yolo26s` + `bytetrack-nigah.yaml`** | **2 correct, 0 duplicates, 0 ID switches** | 4 correct, 0 extra, 0 switches | 2.9–3.3 fps |

What was tried and did **not** remove the duplicate:
- `yolo26n` with ByteTrack at detector confidence 0.10–0.35, `track_buffer` 60 or 90, `match_thresh` 0.9, or `fuse_score` off;
- BoT-SORT (with and without ReID), OC-SORT, FastTracker and TrackTrack;
- `yolo26n` at 960 px.

`yolo26s` with stock ByteTrack fixed 640 px and 480 px but **not 512 px**. Adding `fuse_score: False` fixed all three sizes. Processing every second frame (`frame_stride = 2`) brought duplicates back with both models.

**Limits of this evidence.** It rests on 2 short clips from one camera and one occlusion that caused the failure, with 6 people scored in total. It shows that this failure is fixed and nothing broke on the second clip. It does **not** prove general accuracy.

**Speed.** On this laptop's CPU, `yolo26s` runs at about 3 fps, slower than a 7–10 fps camera. With a live camera the worker would fall behind and effectively skip frames, which the evaluation shows causes ID switches. For live use, run on a GPU or a faster CPU, or test `--imgsz 480` (about 5.5 fps, still correct on both clips) before relying on it.

## Event fields

| Field | Source |
|---|---|
| `event_id` | New UUID per event; reused on every retry |
| `idempotency_key` | `<camera_id>:<zone_id>:<session_id>:<track_id>:restricted_zone_entry`. A re-entry after the cooldown adds `.v2`, `.v3` … |
| `session_id` (inside the key) | Set per worker run, because track IDs restart at every run |
| `occurred_at` | UTC time of the confirming frame. For files, the run start time plus the position in the video, never in the future. For live sources, the wall clock |
| `detection_score` | Highest detector confidence during the confirmation frames |
| `evidence` | **Omitted**, because media upload is not built yet. The worker never invents a URL |

## Tests

```powershell
.venv\Scripts\python -m pytest
```

The tests cover:
- polygon geometry;
- the alert rule (no repeat alerts, gaps, cooldown);
- payloads, checked against both the contract schema and the API's own model;
- publisher retries and the outbox;
- video file errors;
- a full pipeline run with a scripted tracker;
- the evaluation scoring.

`tests/test_tracking_regression.py` replays the **real detector output** around the sample-video occlusion (`tests/fixtures/vtest_occlusion_detections.json`, numbers only, no video) through the real tracker and zone rule. It checks three things: the fixed setup sends one alert per person, the old setup still reproduces the duplicate (so the fixture keeps proving something), and neither change works alone. These tests need Ultralytics and PyTorch; they are skipped with the light `requirements-test.txt` install. CI runs both installs.

## Ownership: what Hania can take over next

The detector/tracker boundary is `PersonTracker` in [`nigah_worker/detection.py`](nigah_worker/detection.py):

```python
class PersonTracker(Protocol):
    def update(self, frame: np.ndarray) -> list[TrackedPerson]: ...  # once per frame, in order
    def reset(self) -> None: ...                                       # video restarted / camera reconnected

@dataclass(frozen=True)
class TrackedPerson:
    track_id: int                                   # stable for the same person across frames
    box: tuple[float, float, float, float]          # x1, y1, x2, y2 in pixels of that frame
    score: float                                    # detector confidence 0..1
```

| Hania owns | Change through Abdul Kareem |
|---|---|
| `nigah_worker/detection.py`: model, thresholds, tracker, a better `PersonTracker` | `nigah_worker/sources.py`, `publisher.py`, `events.py`, `pipeline.py`, `__main__.py` |
| `nigah_worker/rules.py` and `zones.py`: rule tuning and new rule logic | `contracts/` (event fields) and the API |
| `[detector]` and `[rule]` defaults in `config/worker.example.toml`, and `config/trackers/` | `[camera]`, `[source]`, `[output]` |
| `nigah_worker/evaluation.py`, `eval/ground_truth/`, `tests/test_tracking_regression.py`, `tests/test_rules.py` | |

Suggested next steps for Hania:
1. **Review the detector and tracker change** (`yolo26s` + `config/trackers/bytetrack-nigah.yaml`) and the ground-truth files. Re-run the two evaluation commands above and check that you get the same numbers.
2. **Grow the evaluation set.** This matters most. Add clips with more occlusions, other cameras and other zones (for example the dense east walkway in vtest), using the same JSON format. Until then, accuracy beyond these two clips is unproven.
3. **Fix the speed for live cameras without losing accuracy.** Measure `yolo26s` at 480 px on more clips, try an OpenVINO or ONNX export for CPU, or use a GPU. Keep `frame_stride = 1` unless the evaluation shows otherwise.
4. Tune `confirm_frames`, `min_score` and the tracker using the evaluation, not by eye. Change one thing at a time and keep the regression tests passing.
