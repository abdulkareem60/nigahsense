# Shared contracts

These files are the agreed interface between the vision worker, the backend API and the frontend. Change them only through a reviewed pull request approved by the backend lead (Abdul Kareem) and the affected owner. A breaking change gets a new versioned file (`v2`); `v1` is never edited in a breaking way.

| File | Used by | Purpose |
|---|---|---|
| [`vision-event.v1.schema.json`](vision-event.v1.schema.json) | Vision worker → API | JSON Schema for one event sent to `POST /v1/events` |
| [`examples/vision-event.v1.restricted-zone-entry.json`](examples/vision-event.v1.restricted-zone-entry.json) | Worker, tests | Realistic valid event |
| [`examples/incident.v1.json`](examples/incident.v1.json) | Frontend | Shape of one incident returned by the incident endpoints |

The backend tests validate both examples against the API's models, so the examples cannot silently drift from the code.

## Vision event v1

Only `restricted_zone_entry` exists in v1. All fields except `evidence` are required. Unknown fields are rejected, to catch typos early.

| Field | Type | Rule |
|---|---|---|
| `schema_version` | string | Always `"1.0"` |
| `event_id` | UUID string | New for each message; **reuse it when retrying** the same message |
| `idempotency_key` | string, 8–200 chars, `[A-Za-z0-9:._-]` | Same value for every event about the same occurrence. Recommended: `<camera_id>:<zone_id>:<session_id>:<track_id>:<event_type>` |
| `event_type` | enum | `restricted_zone_entry` |
| `camera_id`, `zone_id` | lowercase id, max 64 chars | Configured identifiers |
| `track_id` | integer ≥ 0 | Tracker ID, valid only within one camera and worker session |
| `occurred_at` | RFC 3339 with offset | Time of the triggering frame. More than 5 minutes in the future is rejected |
| `detection_score` | number 0–1 | Detector confidence, not system accuracy |
| `evidence` | object or null, optional | `{ "kind": "snapshot" \| "clip", "uri": "...", "captured_at"?: "..." }` |

**Evidence is a reference, never bytes.** Upload the snapshot or clip to media storage first, then send its location (`gs://`, `s3://`, `https://` or a relative `evidence/...` path). `data:` URIs are rejected.

### How duplicates are handled

| Situation | API result | Effect |
|---|---|---|
| First event for an `idempotency_key` | `201`, `"outcome": "created"` | New incident |
| Same `event_id` sent again (network retry) | `200`, `"outcome": "duplicate"` | Nothing changes |
| New `event_id`, same `idempotency_key` (later frame of the same occurrence) | `200`, `"outcome": "merged"` | Same incident: `event_count` +1, `last_event_at`, highest score and new evidence updated |

The worker should send one event when a track **enters** the zone. Sending more frames is safe but adds load, so throttle repeats (for example, at most one per track per few seconds).

## Incident (API response)

See [`examples/incident.v1.json`](examples/incident.v1.json). Key points for the frontend:

- `status` is the lifecycle: `new` → `acknowledged` (resolution comes in a later increment).
- `review_outcome` is separate from status and is `unreviewed` until review endpoints exist. Show detections as *possible* events until an operator confirms them.
- All timestamps are UTC (`Z`). Display them in Asia/Karachi (PKT).
- `evidence[].uri` is a storage reference. The frontend must get a viewable URL from a later evidence endpoint, not read storage directly.

Errors from every endpoint use one shape:

```json
{ "error": { "code": "validation_error", "message": "Request validation failed.", "details": [] } }
```
