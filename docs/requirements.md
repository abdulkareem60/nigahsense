# NigahSense requirements

What each of the 12 agreed features must do, how we will know it works, and where it stands **in the code today**. Scope and team roles come from the [project brief](project-brief.md); system design is in [architecture.md](architecture.md); how accuracy is measured is in [accuracy-evaluation.md](accuracy-evaluation.md).

This is a living document. Change it through a reviewed PR when a decision or a status changes, so the history stays in Git.

## Status labels

| Label | Meaning |
|---|---|
| **Implemented** | In the code on `feature/api-incidents` (PR #3, or already merged to `main`), with automated tests |
| **Partial** | Some parts exist; the missing parts are listed |
| **Planned** | Agreed feature, no code yet |
| **Needs validation** | Feasibility, accuracy, privacy or hardware still has to be proven before we commit to a design |

Accuracy targets are **to be agreed after the baseline** measurements in [accuracy-evaluation.md](accuracy-evaluation.md). None are set yet. Acceptance criteria that depend on accuracy refer to those agreed targets.

## Summary

| # | Feature | Status | Lead |
|---|---|---|---|
| 1 | Person detection and tracking | Implemented (baseline); needs validation | Hania |
| 2 | Restricted areas | Implemented in worker and API; UI planned | Abdul Kareem, Hania |
| 3 | Loitering | Planned | Hania |
| 4 | Directional line crossing | Planned | Hania |
| 5 | Counting and occupancy | Planned | Hania |
| 6 | Alerts with video evidence | Partial | Abdul Kareem, Musaykah |
| 7 | Incident search | Partial | Abdul Kareem, Musaykah |
| 8 | Camera health | Planned | Abdul Kareem, Musaykah |
| 9 | Registered-person recognition | Planned; needs validation | Hania, Abdul Kareem |
| 10 | Unattended objects | Planned; needs validation | Hania |
| 11 | PDF and XLSX reports | Planned | Musaykah, Abdul Kareem |
| 12 | Possible fall detection | Planned; needs validation | Hania |

The Next.js frontend (Minal: monitoring, cameras, zone editing; Musaykah: incidents, evidence, reports) has **no code in the repository yet**. Every user-facing criterion below is therefore planned, even where the backend part exists.

## Cross-cutting requirements

These apply to every feature.

- **Possible versus confirmed.** A detection is a *possible* event until an operator reviews it. Incidents carry `review_outcome` (`unreviewed`, `confirmed`, `false_alert`, `uncertain`), separate from `status` (`new`, `acknowledged`). Today only acknowledgement has an endpoint; setting the review outcome is planned. The UI must show detector scores as detector confidence, never as system accuracy.
- **No video in Firestore.** Incident records hold metadata and evidence *references* only.
- **Access control.** Operator data needs a Firebase ID token with an allowed `role` claim, and events need the worker key (see [architecture.md](architecture.md#authentication-boundaries)). Footage and registered-person data must stay limited to authorised roles.
- **Time.** APIs use UTC; the UI shows Asia/Karachi (PKT).
- **Shared contracts.** Worker, API and frontend agree on payloads in [`contracts/`](../contracts/README.md). A change needs a reviewed PR.

---

## 1. Person detection and tracking

**Description.** Find people in each video frame and give each person a track ID that stays the same while they remain in view.

**Key behaviour**
- Input from a recorded file, a local webcam or an RTSP camera, with reconnect on failure.
- The person detector and tracker are configurable. The current default is YOLO26s with ByteTrack (`fuse_score` off); the reason is in [`worker/config/trackers/bytetrack-nigah.yaml`](../worker/config/trackers/bytetrack-nigah.yaml).
- Every frame is processed (`frame_stride = 1`). Skipping frames caused ID switches in evaluation.

**Status: Implemented (baseline); needs validation.**
- Measured only on 2 clips from one camera (see [accuracy-evaluation.md](accuracy-evaluation.md#current-results)).
- RTSP reconnect was tested only against an address with no camera, never a real camera.
- The webcam input was tested only with a short dry run.
- About 3 fps on the development laptop's CPU, slower than a live 7–10 fps camera.
- Showing live video in the browser is not built.

**Acceptance criteria**
- [x] A recorded file, a webcam index or an RTSP URL from the environment can be selected in config; a bad path or URL gives a clear error, not a crash. *(tests: `worker/tests/test_sources_pipeline.py`)*
- [x] A lost webcam or RTSP connection is retried with backoff, and passwords in RTSP URLs never appear in logs.
- [ ] On every clip in the evaluation set, person-detection and ID-switch results are recorded, and they meet the targets agreed after the baseline.
- [ ] The worker keeps up with the agreed camera frame rate on the agreed deployment hardware, with every frame processed.
- [ ] RTSP has been run against a real camera for an agreed duration, including a disconnect and reconnect.

## 2. Restricted areas

**Description.** Raise one alert when a person enters a polygon zone that is restricted on that camera.

**Key behaviour**
- Zones are normalised polygons per camera, written in the worker's TOML config.
- A person is inside when the bottom centre of their box (their feet) is inside the polygon.
- The rule does the following:
  - confirms entry over `confirm_frames` frames;
  - ignores brief exits (`exit_frames`);
  - remembers a track through short gaps;
  - applies a re-entry cooldown.
- Each confirmed entry sends one `restricted_zone_entry` event. The API turns it into one incident, and retries and repeat frames never create a second incident.

**Status: Implemented** in the worker and API (on PR #3; the API is on `main`).
- Zones can only be edited in the TOML file. Zone editing through the API or UI (Minal) is **planned**.
- Schedules (for example "restricted after 18:00") are **planned**.

**Acceptance criteria**
- [x] Point-in-polygon is correct for convex and concave zones, including edges. *(`test_zones.py`)*
- [x] A person standing in a zone produces one event, not one per frame; short flicker or gaps do not re-alert. *(`test_rules.py`)*
- [x] A repeated `event_id` returns `duplicate`, and the same `idempotency_key` returns `merged`; neither creates a new incident. *(`backend/tests/test_events.py`, emulator tests)*
- [x] Recorded video → event → Firestore incident → list, get and acknowledge works end to end with the emulators (manual run, 2026-11-11).
- [ ] On the evaluation set: every true entry is alerted once, with no duplicates or false alerts beyond the agreed targets.
- [ ] An operator can draw, edit and save a zone in the UI, and the worker uses it without a code change.

## 3. Loitering

**Description.** Alert when a person stays inside a zone longer than a configured dwell time.

**Key behaviour.** Dwell time is measured per track from confirmed entry. It must survive short occlusions without restarting, and it alerts once per stay. It is a new event type, so it needs a contract update.

**Status: Planned.**

**Acceptance criteria**
- [ ] The contract gains a loitering event type (reviewed contract PR), and the API stores it as an incident.
- [ ] A person inside longer than the dwell time gives exactly one alert; a person leaving earlier gives none.
- [ ] An occlusion shorter than the configured gap does not reset the dwell timer.
- [ ] Alert-time error and missed or false alerts are measured on labelled clips (see [accuracy-evaluation.md](accuracy-evaluation.md#later-features)).

## 4. Directional line crossing

**Description.** Alert when a person crosses a configured line in a chosen direction (for example "into the stockroom").

**Key behaviour.** A line has a direction. Crossing is decided from the track's foot position before and after the line, and wobbling on the line must not count twice. It is a new event type, so it needs a contract update.

**Status: Planned.**

**Acceptance criteria**
- [ ] A crossing in the configured direction gives one event; the opposite direction gives none (unless configured).
- [ ] Standing on the line or stepping back and forth across it does not create repeated events.
- [ ] Direction errors and missed or extra crossings are measured on labelled clips.

## 5. Counting and occupancy

**Description.** Count people entering or leaving an area, and show current occupancy against a configured capacity.

**Key behaviour.** Counts come from line crossings or zone presence. Occupancy can alert above capacity. Counts must not drift when tracks are lost and found again.

**Status: Planned.** Depends on features 1 and 4.

**Acceptance criteria**
- [ ] Occupancy and counts are available per camera and area, through the API and UI.
- [ ] An alert fires once when occupancy goes above capacity, and again only after it has dropped back below.
- [ ] Count error against manual counts is measured on labelled clips.

## 6. Alerts with video evidence

**Description.** Each alert reaches operators with a snapshot or short clip they can review.

**Key behaviour.**
- The worker uploads media to storage, then sends only a reference in the event; it never sends bytes or invents a URL.
- The API stores references, and the frontend gets viewable links from the API.
- Operators can acknowledge the alert.

**Status: Partial.**

| Part | Status |
|---|---|
| Event → incident, list, detail, acknowledge (`POST /v1/incidents/{id}/acknowledge`) | Implemented |
| `evidence` reference field in the contract, validated and stored by the API | Implemented |
| Worker capturing and uploading snapshots or clips | Planned (the worker omits `evidence`) |
| Media storage provider and retention | To confirm ([project brief §9](project-brief.md#9-open-decisions)) |
| Endpoint returning a short-lived viewable URL | Planned |
| Alert channel beyond the app (email or messaging) | To confirm |
| Operator UI for alerts and evidence review | Planned (Musaykah) |

**Acceptance criteria**
- [x] The API rejects evidence that is not a storage reference (`data:` URIs, `..` paths). *(`backend/tests/test_events.py`)*
- [ ] Each new incident has a snapshot reference that the operator can open from the UI, through a link that expires.
- [ ] Evidence is visible only to authorised roles, and kept for the agreed retention period.
- [ ] A new incident appears in the operator UI without a manual page refresh.

## 7. Incident search

**Description.** Operators find past incidents by time, camera, type, status and review outcome.

**Key behaviour.** Filtered, paginated, newest first. Results show the possible or confirmed state.

**Status: Partial.**
- **Implemented:** `GET /v1/incidents` with `status`, `camera_id`, `event_type`, `occurred_from`, `occurred_to` and cursor pagination, plus `GET /v1/incidents/{id}`.
- **Planned:** a filter on review outcome, an endpoint to set the review outcome, text search over notes, and the search UI (Musaykah).

**Acceptance criteria**
- [x] Filters and cursor pagination return the correct incidents newest first; invalid filters return `400` or `422` in the standard error shape. *(`backend/tests/test_incidents.py`)*
- [ ] An operator can mark an incident `confirmed`, `false_alert` or `uncertain`, and filter by it.
- [ ] Search results in the UI match the API for the same filters, with times shown in PKT.

## 8. Camera health

**Description.** Show whether each camera is delivering video, and alert when one goes offline.

**Key behaviour.** The worker already logs open failures, read failures and reconnect attempts. Planned: the worker reports a heartbeat and state to the API, and the UI shows online, degraded or offline with the time the state last changed.

**Status: Planned.** Only local logging exists today.

**Acceptance criteria**
- [ ] Unplugging a camera (or stopping an RTSP stream) shows it as offline within an agreed time, and reconnecting clears it.
- [ ] A camera-offline incident is raised once per outage, not once per retry.

## 9. Registered-person recognition

**Description.** Recognise enrolled people (for example staff) from a separate face-recognition model.

**Key behaviour.** Enrolment only with recorded consent. Results are shown as a *possible* match with a score, never as certain identity. YOLO person detection does not identify anyone.

**Status: Planned; needs validation.** Open points:
- choice of model;
- consent and retention policy;
- how well it works at our camera distances and resolution (in the sample footage, people are about 130–160 px tall, so faces are only about 15–20 px).

**Acceptance criteria**
- [ ] A feasibility test on our own consented footage reports match and false-match rates before a design is committed.
- [ ] Enrolment, deletion and access to face data are limited to authorised roles, and logged.
- [ ] Unknown people are never labelled as a registered person above the agreed false-match rate.

## 10. Unattended objects

**Description.** Alert when an object (bag, box) stays in a watched area without its owner for longer than a set time.

**Key behaviour.** Detect object classes, link each object to a nearby person if possible, and alert after a stationary time without that person. The current worker detects **people only**.

**Status: Planned; needs validation.** Detection of small or partly hidden objects at our camera distances is not yet known.

**Acceptance criteria**
- [ ] An object left in a watched area longer than the set time gives one alert; an object picked up earlier gives none.
- [ ] Missed and false object alerts are measured on staged, labelled clips.

## 11. PDF and XLSX reports

**Description.** Export incident data for a period, camera or type as PDF (readable) and XLSX (data).

**Key behaviour.** Generated from stored incidents with the same filters as search. Times in PKT. The report states that detections are possible events unless reviewed.

**Status: Planned.** No report code exists.

**Acceptance criteria**
- [ ] For a given filter, the PDF and XLSX contain the same incidents as the API returns.
- [ ] XLSX opens in Excel with one row per incident and correct types (dates as dates).
- [ ] Reports are available only to authorised roles.

## 12. Possible fall detection

**Description.** Flag a person who appears to have fallen, as a possible event for review.

**Key behaviour.** Needs a pose model with a short temporal check, separate from the person detector. Results are always shown as "possible fall".

**Status: Planned; needs validation.** Model choice and accuracy on our camera angles are unknown, and test data must be staged with consent.

**Acceptance criteria**
- [ ] A feasibility test on staged, consented falls and non-fall movements (sitting, bending) reports detection and false-alarm rates before a design is committed.
- [ ] Each detected fall produces one incident, marked as a possible fall.
