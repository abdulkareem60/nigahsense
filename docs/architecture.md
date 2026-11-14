# NigahSense architecture

How the parts fit together **as built today**, and where planned parts will connect. Anything not yet in the code is marked **Proposed**. Feature status is in [requirements.md](requirements.md); setup and commands are in the [root README](../README.md) and [worker/README.md](../worker/README.md).

## Data flow

```text
 Camera / video file                                                        (Proposed)
 file · webcam · RTSP                                                   Next.js frontend
        │ frames                                                        Minal · Musaykah
        ▼                                                                      ▲
 ┌──────────────── Vision worker (Python) ───────────────┐                     │ HTTPS + Firebase ID token
 │ sources.py ─► detection.py ─► rules.py ─► publisher.py │                     │
 │  frames       people+IDs      zone entry   POST event  │                     │
 └──────────────────────────────────────────┬─────────────┘                     │
                         X-Worker-Key header│ vision event v1 (JSON)            │
                                            ▼                                  │
                         ┌──────────── FastAPI backend ──────────────┐         │
                         │ validate · deduplicate · store · authorise │◄────────┘
                         └───────────┬────────────────────────────────┘
                                     │ Firebase Admin SDK (server credentials)
                                     ▼
              Cloud Firestore: incident records          Firebase Auth: operator accounts, role claims
              Media storage: snapshots/clips (Proposed, provider to confirm)
```

Video never passes through the API or Firestore. Only small JSON events and incident records do.

## Components

| Component | Code | Responsibility | Owner |
|---|---|---|---|
| Video source | [`worker/nigah_worker/sources.py`](../worker/nigah_worker/sources.py) | Read frames from a file, webcam or RTSP; give each frame a UTC timestamp; reconnect on failure | Abdul Kareem |
| Person tracker | [`worker/nigah_worker/detection.py`](../worker/nigah_worker/detection.py) | The `PersonTracker` interface. Baseline: Ultralytics YOLO26s + ByteTrack ([tracker config](../worker/config/trackers/bytetrack-nigah.yaml)) | Hania |
| Zone rule | [`rules.py`](../worker/nigah_worker/rules.py), [`zones.py`](../worker/nigah_worker/zones.py) | Polygon test on the person's feet; confirm entry; one event per visit | Hania |
| Event publisher | [`events.py`](../worker/nigah_worker/events.py), [`publisher.py`](../worker/nigah_worker/publisher.py) | Build contract payloads; send in the background with retries and an outbox | Abdul Kareem |
| Worker wiring | [`pipeline.py`](../worker/nigah_worker/pipeline.py), [`__main__.py`](../worker/nigah_worker/__main__.py) | Connect the parts; CLI; clean shutdown | Abdul Kareem |
| Accuracy evaluation | [`evaluation.py`](../worker/nigah_worker/evaluation.py) | Offline replay and scoring against ground truth | Hania |
| API | [`backend/app/`](../backend/app/) | Routes → services → repositories; auth; one error shape | Abdul Kareem |
| Database | Cloud Firestore (emulator locally) | Incident metadata and deduplication records | Abdul Kareem |
| Identity | Firebase Auth | Operator sign-in; `role` custom claim | Abdul Kareem |
| Frontend | Not in the repository yet (**Proposed:** Next.js) | Monitoring, zones, incidents, evidence, reports | Minal, Musaykah |

The worker's parts talk only through small data types (`Frame`, `TrackedPerson`, `ZoneEntry` and the event dict), so the model can change without touching video input or the API client. Worker configuration lives in a TOML file (camera, source, detector, zones, rule) plus environment variables for secrets.

## Event contract

The worker and the API share **vision event v1**: [`contracts/vision-event.v1.schema.json`](../contracts/vision-event.v1.schema.json). The fields, rules and examples are explained in [`contracts/README.md`](../contracts/README.md). Key points:
- The only event type is `restricted_zone_entry`. New features need a new type in a reviewed contract PR.
- `event_id` is unique per message and **reused on every retry**. `idempotency_key` is stable for one real-world occurrence: `<camera>:<zone>:<session>:<track>:restricted_zone_entry`, with `.v2`, `.v3` … for re-entries after the cooldown.
- The API's request model and both the backend and worker tests check payloads against this schema, so code and contract cannot drift silently.

The API's incident response shape is shown in [`contracts/examples/incident.v1.json`](../contracts/examples/incident.v1.json).

## Storage

**Firestore (implemented)**

| Path | Contents |
|---|---|
| `incidents/{incident_id}` | One document per occurrence: type, camera, zone, track, status, review outcome, highest score, first and last time, event count, evidence references, acknowledgement |
| `incidents/{incident_id}/events/{event_id}` | One small record per accepted worker event, used to detect duplicates |

- `incident_id` is `inc_` plus a hash of the `idempotency_key`, so repeated events land on the same document.
- Writes run in a Firestore transaction.
- Composite indexes are declared in [`firestore.indexes.json`](../firestore.indexes.json). The emulator does not enforce them, so check them on the first real deployment.

**Evidence (partly implemented)**
- The contract and API accept an optional `evidence` reference (`gs://`, `s3://`, `https://` or a relative `evidence/…` path) and reject raw data.
- The worker **does not upload media yet**, so it omits `evidence`.
- **Proposed:**
  - the worker saves a snapshot or clip to object storage, then sends its reference;
  - the API issues short-lived viewing links to authorised operators;
  - retention follows an agreed policy.
- The storage provider and retention period are open decisions ([project brief §9](project-brief.md#9-open-decisions)).

## Authentication boundaries

| Caller | Proof | Allowed |
|---|---|---|
| Vision worker | `X-Worker-Key` header matching one of `WORKER_API_KEYS` (comma-separated, so keys can be rotated) | `POST /v1/events` only. If no key is configured, ingestion is off (`503`) |
| Operator (browser) | Firebase ID token in `Authorization: Bearer …`, with custom claim `role` in `OPERATOR_ROLES` (default `operator,supervisor,admin`) | `GET /v1/incidents`, `GET /v1/incidents/{id}`, `POST /v1/incidents/{id}/acknowledge`. A missing or invalid token gives `401`; a wrong role gives `403` |
| Anyone | none | `GET /health` |
| Browser → Firestore directly | — | Denied: [`firestore.rules`](../firestore.rules) blocks all client reads and writes. Only the backend's server credentials reach Firestore |

Supporting details:
- Roles are set server-side as custom claims. Locally, `backend/scripts/dev_operator_token.py` creates an operator in the Auth emulator.
- Secrets come only from environment variables ([`backend/.env.example`](../backend/.env.example), [`worker/.env.example`](../worker/.env.example)). The API refuses emulator settings when `APP_ENV=production` and turns off `/docs` there.
- **Proposed:** role-specific permissions (for example, only supervisors manage zones or registered people) once those endpoints exist.

## Failures and retries

| Situation | Behaviour |
|---|---|
| Video file missing or unreadable | The worker exits with a clear error (code 2) |
| Webcam/RTSP fails to open or stops sending frames | Reconnect with backoff: 1 s, doubling up to 30 s. Unlimited unless `max_reconnect_attempts` is set |
| API unreachable, timeout, `429` or `5xx` | Publisher retries in the background with exponential backoff and jitter, reusing the **same** `event_id` (up to `NIGAHSENSE_MAX_SEND_ATTEMPTS`, default 8). Then the event is saved to `runtime/outbox.jsonl` and re-sent on the next start |
| API rejects an event (`401`, `409`, `422`) | Not retried; logged and kept in the outbox, marked `retryable: false` |
| Worker stopped (Ctrl+C) | Finishes the current frame, gives queued events up to 15 s to send, and saves the rest to the outbox |
| Same event received twice | API answers `200 duplicate` and changes nothing |
| Later event for the same occurrence | API answers `200 merged`: event count +1, latest time, highest score |
| Firestore unreachable | `GET /health` returns `503`; other endpoints return the standard error shape |

All API errors use `{"error": {"code", "message", "details?"}}`.

## Where each person's work connects

| Person | Builds | Connects through |
|---|---|---|
| Hania | Detector, tracker, rules, accuracy evaluation | `PersonTracker` / `TrackedPerson` in `detection.py`; `ZoneEntry` from `rules.py`; new event types via a contract PR |
| Abdul Kareem | API, Firestore, auth, contracts, video sources, publisher | The vision event contract (worker side); REST endpoints and the incident shape (frontend side) |
| Minal | Frontend structure, design system, monitoring and camera screens, zone editor | Firebase Auth sign-in in the browser; API endpoints for cameras and zones (**proposed**, not built) |
| Musaykah | Incidents, evidence review, search, reports, camera-health views | `GET/POST /v1/incidents…` and the [incident example](../contracts/examples/incident.v1.json); evidence links and reports (**proposed**) |

Frontend mock data must match the contract examples exactly, so switching to the real API needs no UI changes.

## Proposed, not yet built

- **Next.js frontend:** sign-in, plus calling the API with the user's ID token.
- **Media upload and evidence links**, with a storage provider to confirm.
- **Configuration through the API instead of TOML:** cameras, zones and schedules, stored in Firestore, read by the worker.
- **Camera health:** a worker heartbeat to the API, and an offline incident.
- **More event types and their services:** loitering, line crossing, occupancy, unattended objects, possible fall; plus recognition and reports.
- **Deployment and hosting:** to confirm ([project brief §9](project-brief.md#9-open-decisions)).
