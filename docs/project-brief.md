# NigahSense — Project Brief

**Intelligent Surveillance & Safety** · Initial brief for the implementation team · Times in Asia/Karachi (PKT)

NigahSense is a web application that analyses camera and video feeds, detects safety-relevant events and lets an operator review each incident with its video evidence. Our two priorities are **accurate detection** and a **polished, readable, responsive interface** (light and dark modes) that is honest about uncertain detections.

> **Status labels used below:** **Agreed** = decided by the team · **Proposed** = recommended, needs team sign-off · **To confirm** = open question.

---

## 1. Purpose and users

| User | Need |
|---|---|
| Operator | Watch cameras, receive alerts, review evidence, record what happened |
| Supervisor / admin | Configure cameras, zones and rules; manage registered people; export reports |

Manual monitoring misses events and leaves no searchable record. NigahSense flags *possible* events for a human to confirm; it does not replace the operator's judgement.

The earlier **Claude Design preview** is a preserved visual reference only; its interactions, detections and sample photos are mock-ups, not working features.

## 2. Scope — the 12 agreed features

| Area | Features (Agreed) |
|---|---|
| Live detection | 1. Live person detection and tracking · 12. Possible fall detection |
| Zones and rules | 2. Restricted area detection · 3. Loitering detection · 4. Directional line crossing · 10. Unattended object alerts |
| Counting | 5. People counting and occupancy |
| Incidents | 6. Alerts with video evidence · 7. Searchable incident history |
| Operations | 8. Camera health monitoring · 9. Registered-person recognition |
| Reporting | 11. PDF and XLSX report generation |

Delivery is incremental: each feature ships only when it works end to end, starting with the milestone in section 6.

## 3. Technical approach

```text
Camera / test video
   → Vision worker (Python: OpenCV/FFmpeg frames → YOLO detection → tracking → rule checks)
   → Event/incident API (FastAPI: validates events, applies workflows, controls access)
   → Firestore (incident records, rules, cameras, users)  +  media storage (snapshots, clips)
   → Next.js interface (live view, incidents, evidence review, reports)
```

- **Firestore stores records, not video.** Frames and clips go to separate media storage; Firestore keeps metadata and a reference to the evidence.
- **YOLO is not face recognition.** YOLO finds people and objects; recognising a *registered person* needs a separate face model and enrolment.
- **OpenCV handles frames, not accuracy.** Detection quality depends on the models, the footage and our evaluation.
- *Tracking* keeps a temporary ID on the same person across frames (needed for loitering, counting and line crossing).

## 4. Technology and verified versions

**Versions verified: 8 November 2026 (PKT).** After setup, exact dependency versions will be locked in `uv.lock` / `requirements.txt` (backend) and `package-lock.json` (frontend).

| Tool | Latest stable | Project choice | Status | Reason | Source |
|---|---|---|---|---|---|
| Python | 3.15.2 | **3.14.x** | Agreed (language) | OpenCV wheels list support to 3.14; NumPy, PyTorch and Ultralytics also support it | [python.org](https://www.python.org/downloads/) |
| FastAPI | 0.162.2 | **0.162.x** + Uvicorn 0.54.x | Agreed | Requires Python ≥3.10 | [PyPI](https://pypi.org/project/fastapi/) |
| Firebase Admin SDK (Python) | 7.7.0 | **7.7.x** | Agreed | Server-side Firestore + Auth token checks | [PyPI](https://pypi.org/project/firebase-admin/) |
| Cloud Firestore / Firebase Auth | — | Managed service; no app-side server version to pin | Agreed | Accessed through the SDKs | [Firebase docs](https://firebase.google.com/docs/firestore) |
| Firebase CLI (`firebase-tools`) | 15.35.0 | **15.x** | Agreed | Emulators, rules, deploys; Node ≥20 | [npm](https://www.npmjs.com/package/firebase-tools) |
| Firebase JS SDK | 13.2.0 | **13.x** | Agreed | Frontend sign-in | [npm](https://www.npmjs.com/package/firebase) |
| OpenCV (`opencv-python-headless`) | 5.0.0.93 | **5.0.x** | Agreed | Headless build for servers (no GUI dependencies) | [PyPI](https://pypi.org/project/opencv-python-headless/) |
| Ultralytics package | 8.4.207 | **8.4.x** | Agreed (YOLO) | Detection + built-in ByteTrack/BoT-SORT trackers | [PyPI](https://pypi.org/project/ultralytics/) |
| YOLO model family | YOLO26 | **YOLO26** (fallback YOLO11) | Proposed | Ultralytics recommends YOLO26 for new projects; YOLO11 is the mature fallback. Weights are separate from the package version | [Ultralytics models](https://docs.ultralytics.com/models/) |
| PyTorch | 2.15.0 | **2.15.x** (CPU or CUDA build) | Proposed | Ultralytics runtime; supports Python 3.11–3.15 | [PyPI](https://pypi.org/project/torch/) |
| FFmpeg | 9.0.2 | **9.0.x** | Agreed | Evidence clips and stream handling | [ffmpeg.org](https://ffmpeg.org/download.html) |
| Node.js | 26.13.0 (LTS) | **24.x LTS** | Proposed | 24 has the widest tool support; 26 became LTS only in Oct 2026 — revisit later | [nodejs.org](https://nodejs.org/en/about/previous-releases) |
| Next.js | 16.4.5 | **16.4.x** | Agreed | Requires Node ≥20.9 | [npm](https://www.npmjs.com/package/next) |
| React | 19.3.1 | **19.3.x** | Agreed | Next.js 16 supports React 19 | [react.dev](https://react.dev/versions) |
| TypeScript | 7.0.2 | **6.0.x** | Proposed | 7.0 is a new native compiler; verify during setup that Next.js 16 supports it before upgrading | [npm](https://www.npmjs.com/package/typescript) |
| Tailwind CSS | 4.3.5 | **4.3.x** | Proposed | Design tokens for light/dark themes | [npm](https://www.npmjs.com/package/tailwindcss) |

**Also proposed:** object storage for media, a face-recognition model separate from YOLO, and a pose model plus temporal classifier for possible falls. Ultralytics is AGPL-3.0 licensed; whether that suits the project is *to confirm*.

## 5. Team responsibilities

| Member | Role | Owns |
|---|---|---|
| **Abdul Kareem** | **Backend Lead** | Final technical ownership of backend architecture; FastAPI API design; database schema; Firebase integration; authentication and authorization; incident and rule workflows; API contracts; backend code review; integration coordination — ensures the backend and vision worker fit together |
| **Hania** | Backend and Computer Vision Engineer | Python video-processing worker: OpenCV/FFmpeg ingestion of cameras or test video, YOLO person/object detection, tracking, event detection logic, accuracy evaluation, and sending structured events to the agreed backend interface. Coordinates all event schemas with Abdul Kareem |
| **Minal** | Frontend Lead and UI Systems | Next.js app structure, reusable components, typography, design tokens, light/dark modes, responsive navigation, monitoring screen, camera views, zone/rule editing UX. Coordinates shared UI decisions with Musaykah |
| **Musaykah** | Frontend Engineer and Incident Workflows | Incidents and evidence review, searchable history, registered-people screens, analytics, report screens, camera health presentation, frontend integration with typed API responses. Coordinates shared component changes with Minal |

**Cross-review rule:** frontend members do not redefine API payloads on their own, and backend members do not silently change a shared event contract. Contract changes go through a reviewed pull request approved by Abdul Kareem and the affected owner.

## 6. First working milestone

**Goal:** one camera or recorded test video → person detection and tracking → restricted-zone event → stored incident → evidence review in the frontend.

It is **complete** when the team can show, live and in one run:

1. The worker reads the video and draws person boxes with stable track IDs.
2. A person entering a configured polygon zone creates **one** event (not one per frame).
3. The API validates the event and stores an incident in Firestore, with a snapshot or short clip saved to media storage.
4. A signed-in user sees the incident in the frontend, opens the evidence, and acknowledges it; the status change persists.
5. The demo uses no hard-coded incident data, and setup steps are written in the README.

## 7. Collaboration rules

- One repository; short-lived feature branches; small pull requests with at least one reviewer.
- API and event contracts live in the repo (e.g. `contracts/`) and are changed only by reviewed pull request.
- Frontend mock data must match those contracts exactly, so switching to the real API needs no UI rewrite.
- A weekly integrated demo on the main branch; anything not shown working there is not "done".

## 8. Quality and safety requirements

- **Detection quality:** measure missed detections, false alerts, tracking stability (ID switches) and latency on our own footage before tuning. No accuracy claims without that evaluation.
- **Honest UI:** separate *possible* (detected) events from *confirmed* (operator-reviewed) ones; show model confidence as a detection score, never as system accuracy.
- **Interface:** responsive from phone to wide desktop, light and dark modes, keyboard-accessible, readable contrast.
- **Privacy and security:** limit footage and registered-person data to authorised roles; enrol people only with recorded consent; keep credentials and service-account keys out of Git.

## 9. Open decisions

| Decision | Status |
|---|---|
| Camera hardware and test footage source | To confirm |
| GPU capacity for inference (local vs. cloud) | To confirm |
| Media storage provider and retention period | To confirm |
| Alert channel (in-app only, email, or messaging) | To confirm |
| Deployment method and hosting | To confirm |
| Face-recognition and fall-detection model choice | To confirm after evaluation |
