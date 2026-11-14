# Accuracy evaluation plan

Accuracy is NigahSense's highest priority. This plan says how we label video, what we measure, how we record results, and how later features will be evaluated. The tool itself, `nigah_worker.evaluation` (commands and ground-truth format), is described in [worker/README.md → Evaluate accuracy](../worker/README.md#evaluate-accuracy-no-api-or-firestore-needed). Feature definitions are in [requirements.md](requirements.md).

## Tests are not accuracy

| | Unit and regression tests (CI) | Accuracy evaluation |
|---|---|---|
| Question answered | Does the code do what it was written to do? | How often is the system right on real video? |
| Input | Scripted tracks, synthetic frames, one recorded detector output ([fixture](../worker/tests/fixtures/vtest_occlusion_detections.json)) | Labelled clips, run through the real detector, tracker and rule |
| Result | Pass/fail | Counts and rates per clip, compared over time |

A green CI run says nothing about how many people the model misses on a new camera. Accuracy claims (in PRs, reports or the UI) must quote an evaluation result with its clip set and date, never test results.

## What we measure

Measured per clip and per configuration (model, input size, tracker settings, rule settings, `frame_stride`).

| Metric | Definition | Tool support |
|---|---|---|
| Restricted-area alerts: **correct** | True entries that received an alert | Yes (`correct`) |
| **Missed** events | True entries with no alert | Yes (`missed`, `missed_people`) |
| **Duplicate** alerts | Extra alerts for a person already alerted | Yes (`duplicates`) |
| **False alerts** | Alerts for nobody, or for someone who did not enter | Yes (`false_alerts`) |
| Tracking **ID switches** | Changes of track ID along a labelled person's path | Yes (`id_switches`, `id_chains`) |
| Person **detection** (per frame) | Missed people and false boxes on sampled frames, by box overlap with labelled boxes | **Not yet**: needs labelled boxes and a scoring command |
| **Processing speed** | Frames per second for the full worker on named hardware, with `frame_stride = 1`, compared with the camera's own frame rate | Partly: the worker prints frames and seconds when it finishes (`Done: …`); `detect` prints fps |
| **Live lag** | Delay between capture and event on a live camera | **Not yet** |

People marked `ambiguous` in the ground truth (feet only at the zone edge) are excluded from all counts and reported separately (`ignored_ambiguous`).

## Building the clip set

### Coverage

We need clips for each condition. ✓ marks one we already have; everything else is still needed.

| Condition | Why it matters | Have now |
|---|---|---|
| People overlapping or walking together | Caused the duplicate alert we fixed | ✓ vtest (one event) |
| Dense crowd near a zone edge | Edge walkers, many tracks | ✓ PETS09-S2L2 |
| Different camera angles and heights (high, eye level, top-down) | Feet position and box shape change | Needed |
| Lighting: indoor, night or low light, backlight, strong shadows | Detector confidence drops | Needed (both clips are daylight) |
| Occlusion by objects (pillars, shelves, vehicles) | Lost tracks | Needed |
| Our own camera over RTSP, and a webcam | Compression, frame drops, real frame rate | Needed: no real RTSP camera yet; the webcam was only used for a short dry run |
| Empty scenes and non-people motion (trees, vehicles, animals) | False alerts | Needed |
| Long recordings (≥ 1 hour) | False alerts per hour, stability | Needed |

Current clips (videos are never committed; sources and licences are in each ground-truth file):

| Clip | Source | Frames | Ground truth |
|---|---|---|---|
| `vtest.avi` | OpenCV sample (PETS 2009 S2.L1), Apache-2.0 | 795 @ 10 fps | [`vtest.json`](../worker/eval/ground_truth/vtest.json) |
| `PETS09-S2L2-raw.webm` | PETS 2009 via MOTChallenge, CC BY-NC-SA 3.0 (non-commercial research use) | 436 @ 7 fps | [`pets09-s2l2.json`](../worker/eval/ground_truth/pets09-s2l2.json) |

### Recording our own footage

Footage of real people needs their consent (or must come from a location where recording is permitted and signed), must stay out of Git, and should be stored where only the team can access it. Record live sources to a file first (RTSP or webcam → `.mp4`), then evaluate the file, so results can be repeated.

### Labelling procedure

1. Choose the zone (or line) and save the worker config used, so labels and config match.
2. Watch the clip and list every person who comes near the zone, with a short description (clothing) so others can recognise them.
3. For each person, record `enters_zone`:
   - `true`: feet at least 12 px inside the polygon for at least 3 frames in a row;
   - `"ambiguous"`: only shallower or shorter;
   - `false`: never inside.
   Also record `enter_frame` and `keyframes` (`[frame, feet_x, feet_y]`, every few frames).
4. Leave out keyframes where identity is unclear: people overlapping, a person half out of frame, or someone crossing another person.
5. **Check by a second person.** Render the keyframes on the frames and confirm each label sits on the right person. In the first round this check found two labelling mistakes (one person counted as two, and one position on the wrong person).
6. Write how the file was made (`how_made`) and the clip's source and licence, then commit the JSON under [`worker/eval/ground_truth/`](../worker/eval/ground_truth/).

**Planned:** a small labelling helper that renders keyframes for checking, plus labelled boxes on sampled frames for per-frame detection scoring.

## Running an evaluation

1. Cache detections once per clip, model and input size (`evaluation detect`).
2. Run `evaluation run --truth …` for the baseline configuration, and keep the JSON output (`--json`).
3. Change **one** thing at a time (model, input size, tracker setting, rule setting, stride) and rerun.
4. For any surprising result, use `--dump` and look at the frames before drawing a conclusion.
5. Confirm the chosen configuration with the real worker (`python -m nigah_worker --dry-run --no-realtime`), not only with the replay.
6. Record the results in the table below and in the PR that changes the configuration.

## Targets

**To be agreed after the baseline.** Once the clip set covers the conditions above, the team agrees targets per metric (for example missed entries, duplicates, false alerts per hour, minimum fps on the deployment hardware) and records them here through a PR. Until then, no change may make any metric worse on the existing clips without a written reason in the PR.

## Results

Add a row per evaluated configuration and clip. Keep old rows: history matters.

| Date | Commit | Clip | Model @ size | Tracker | Stride | Correct / true | Missed | Duplicates | False | Ambiguous alerts | ID switches | Worker fps (hardware) | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | | | |

### Current results

The first baseline, measured 2026-11-14 on the development laptop (CPU only), south-lawn zone. Details and everything else that was tried are in [worker/README.md → Measured results](../worker/README.md#measured-results-2026-11-14-south-lawn-zone-cpu) and PR #3.

| Date | Commit | Clip | Model @ size | Tracker | Stride | Correct / true | Missed | Duplicates | False | Ambiguous alerts | ID switches | Worker fps (hardware) | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-14 | `3eeec53` | vtest | yolo26n @640 | ByteTrack default | 1 | 2 / 2 | 0 | 1 | 0 | 0 | 2 | 7.9 (laptop CPU) | Duplicate after occlusion |
| 2026-11-14 | `aeae9f0` | vtest | yolo26s @640 | bytetrack-nigah | 1 | 2 / 2 | 0 | 0 | 0 | 0 | 0 | 2.9–3.3 (laptop CPU) | Current default |
| 2026-11-14 | `3eeec53` | PETS09-S2L2 | yolo26n @640 | ByteTrack default | 1 | 4 / 4 | 0 | 0 | 0 | 1 | 0 | — | |
| 2026-11-14 | `aeae9f0` | PETS09-S2L2 | yolo26s @640 | bytetrack-nigah | 1 | 4 / 4 | 0 | 0 | 0 | 1 | 0 | 2.9 (laptop CPU) | Current default |

**What these results do not show:**
- general accuracy (2 clips from one camera, 6 labelled people, daylight only);
- per-frame detection quality;
- live-camera performance;
- whether the CPU speed is acceptable. At about 3 fps the worker is slower than these 7–10 fps clips. Frame skipping caused ID switches in testing, so live use needs a faster CPU or a GPU.

## Later features

Each feature gets the same treatment: labelled clips, a scoring command, results in the table, and targets agreed after a baseline.

| Feature | Label per clip | Main measures |
|---|---|---|
| Loitering | Each person's true entry and exit time in the zone | Missed and false loitering alerts; difference between alert time and the true dwell threshold |
| Directional line crossing | Each crossing: frame and direction | Missed crossings, extra crossings, wrong direction |
| Counting / occupancy | True count in the area at regular intervals | Count error over time; capacity alerts missed or false |
| Unattended objects | When each object is put down, its owner leaves, and the object is picked up | Missed and false object alerts; alert delay |
| Registered-person recognition | Identity of each enrolled, consented person per appearance; unknown people marked unknown | Correct matches, false matches (unknown person named), missed matches. Tested on our own consented footage at real camera distances before any design is committed |
| Possible fall | Staged falls and look-alike actions (sitting, bending, lying down on purpose), all with consent | Detected falls, missed falls, false alarms per hour of normal footage |
| Camera health | Recorded disconnects and reconnects with times | Time to show offline and back online; false offline states |

Recognition and fall detection also need a privacy and consent review before any real footage is collected.
