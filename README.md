# NigahSense

**Intelligent Surveillance & Safety** — an AI-assisted surveillance and safety monitoring web application. See [docs/project-brief.md](docs/project-brief.md) for scope and team ownership, and [docs/branch-workflow.md](docs/branch-workflow.md) for the branch and PR process.

| Path | Contents |
|---|---|
| [`contracts/`](contracts/) | Shared event and incident contracts (worker ↔ API ↔ frontend) |
| [`backend/`](backend/) | FastAPI incident API (Python 3.14) |
| `firebase.json`, `firestore.rules`, `firestore.indexes.json` | Firebase Emulator Suite and Firestore configuration |

## Backend: first milestone API

The API receives restricted-zone events from the vision worker, stores one incident per occurrence in Firestore (metadata and evidence **references** only, never video bytes), and lets signed-in operators list, inspect and acknowledge incidents.

### Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.14.x | Backend runtime |
| Node.js | 24 LTS | Runs the Firebase CLI |
| Java | 21 or newer | Required by the Firestore emulator |
| Firebase CLI | 15.x (`npx firebase-tools@15`) | Local emulators |

No Firebase account or credentials are needed for local work: the project ID `demo-nigahsense` runs fully on the emulators.

### Setup

Windows (PowerShell), from the repository root:

```powershell
cd backend
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cd backend
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Then edit `backend/.env` and set `WORKER_API_KEYS` to a generated secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Run locally

Terminal 1, from the repository root: start the Firestore and Auth emulators (emulator UI at http://127.0.0.1:4000).

```bash
npx firebase-tools@15 emulators:start --only firestore,auth --project demo-nigahsense
```

Terminal 2, from `backend/`: start the API (interactive docs at http://127.0.0.1:8000/docs).

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

On macOS/Linux use `.venv/bin/python` instead of `.venv/Scripts/python`.

### Test

From `backend/`, unit and API tests (no emulator needed; they use in-memory storage and a fake token verifier):

```bash
.venv/Scripts/python -m pytest
```

From the repository root, the same core flows against the real Firestore emulator. On Windows `cmd` runs the script, so keep the backslashes:

```bash
npx firebase-tools@15 emulators:exec --only firestore --project demo-nigahsense "cd backend && .venv\Scripts\python -m pytest -m emulator"
```

### Environment variables

Set in `backend/.env` (see [`backend/.env.example`](backend/.env.example)). Never commit `.env` or service-account keys.

| Variable | Required | Purpose |
|---|---|---|
| `APP_ENV` | No (`development`) | `development`, `test` or `production`. `/docs` is disabled in production |
| `FIREBASE_PROJECT_ID` | Yes | `demo-nigahsense` locally; the real project ID in production |
| `STORAGE_BACKEND` | No (`firestore`) | `firestore`, or `memory` for throwaway experiments |
| `WORKER_API_KEYS` | Yes, for ingestion | Comma-separated worker secrets. If empty, `POST /v1/events` returns 503 |
| `OPERATOR_ROLES` | No | Custom-claim roles allowed on operator endpoints (default `operator,supervisor,admin`) |
| `CORS_ORIGINS` | No | Allowed frontend origins (default `http://localhost:3000`) |
| `FIRESTORE_EMULATOR_HOST`, `FIREBASE_AUTH_EMULATOR_HOST` | Local only | Emulator addresses. The app refuses to start with these in production |
| `GOOGLE_APPLICATION_CREDENTIALS` | Production only | Path to a service-account key kept outside the repo, or omit to use the host identity |

### Endpoints

All errors use `{"error": {"code", "message", "details?"}}`. Timestamps are UTC; display them in Asia/Karachi (PKT).

| Method and path | Caller | Purpose |
|---|---|---|
| `GET /health` | Anyone | Liveness plus a storage check (`503` if Firestore is unreachable) |
| `POST /v1/events` | Vision worker (`X-Worker-Key`) | Ingest one vision event v1. `201 created`, or `200` with `duplicate` / `merged` |
| `GET /v1/incidents` | Operator | List newest first. Filters: `status`, `camera_id`, `event_type`, `occurred_from`, `occurred_to`; paging with `limit` (1–100) and `cursor` → `next_cursor` |
| `GET /v1/incidents/{id}` | Operator | One incident |
| `POST /v1/incidents/{id}/acknowledge` | Operator | Body `{"note"?: string ≤ 500}`. Repeating it keeps the first acknowledgement |

**Operator** means a Firebase ID token (`Authorization: Bearer <token>`) whose custom claim `role` is in `OPERATOR_ROLES`. Without a token the API returns 401; with the wrong role, 403.

### Using the contract

- **Vision worker (Hania):** send JSON matching [`contracts/vision-event.v1.schema.json`](contracts/vision-event.v1.schema.json) to `POST /v1/events` with the `X-Worker-Key` header. Reuse `event_id` on retries, and keep `idempotency_key` stable per occurrence. Upload media first and send only its reference. To try the API without the worker:
  ```bash
  .venv/Scripts/python scripts/send_sample_event.py --key <your WORKER_API_KEYS value> --repeat 2
  ```
- **Frontend (Minal, Musaykah):** build types from [`contracts/examples/incident.v1.json`](contracts/examples/incident.v1.json) and keep mock data in exactly that shape. With the emulators running, get a local operator token from `backend/` and send it as `Authorization: Bearer <token>`:
  ```bash
  .venv/Scripts/python scripts/dev_operator_token.py --role operator
  ```
  In the real app the token comes from the Firebase JS SDK (`getIdToken()`); roles are set server-side as custom claims.
- Contract changes go through a reviewed PR approved by Abdul Kareem (see [`contracts/README.md`](contracts/README.md)).

### Not in this increment

Incident resolution and review outcomes, cameras and zones configuration, evidence upload and signed viewing URLs, and the other milestone features. Composite indexes for production queries are declared in `firestore.indexes.json`; the emulator does not enforce them.
