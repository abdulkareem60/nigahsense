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

**Model weights** (`models/yolo26n.pt`, 5.5 MB) download automatically on the first run. They are never committed.

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

On the sample video this sends 3 events, at about 53 s and 57 s into the clip. Each one prints `API 201 ... "outcome": "created"`. Open the emulator UI at http://127.0.0.1:4000/firestore to see the `incidents` documents.

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

**Known limit:** if the tracker gives the same person a new track ID, a second event is possible. On the sample video, 2 people walking together on the lawn produce 3 events because one person's ID switched while they overlapped (track 49 → 55). Better tracking is the fix (see Hania's next steps).

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

The tests cover polygon geometry, the alert rule (no repeat alerts, gaps, cooldown), payloads checked against both the contract schema and the API's own model, publisher retries and outbox, video file errors, and a full pipeline run with a scripted tracker. They need no model, so CI installs only `requirements-test.txt`.

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
| `[detector]` and `[rule]` defaults in `config/worker.example.toml` | `[camera]`, `[source]`, `[output]` |
| New tests in `tests/test_rules.py`, plus an evaluation script (e.g. `worker/eval/`) | |

Suggested next steps for Hania:
1. **Fix the ID switch on the sample video.** Try `tracker` settings (a custom ByteTrack YAML with a longer `track_buffer` and a lower `match_thresh`), or BoT-SORT with ReID. A quick BoT-SORT test with default settings still switched IDs and was slower.
2. **Build a small evaluation set.** Label a few clips with ground truth ("person X entered zone at frame N"), and write a script that reports missed entries, false alerts and ID switches.
3. **Compare models.** Try `yolo26s.pt` against `yolo26n.pt` for accuracy versus CPU speed. Baseline: about 7 fps for `yolo26n` at 640 px on this development laptop's CPU.
4. Tune `confirm_frames` and `min_score` using that evaluation, not by eye.
