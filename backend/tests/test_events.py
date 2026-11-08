"""Worker ingestion: authentication, validation and duplicate handling."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from .conftest import OPERATOR, WORKER, make_event


def _incident(client, incident_id):
    return client.get(f"/v1/incidents/{incident_id}", headers=OPERATOR).json()


# --- authentication ---------------------------------------------------------

@pytest.mark.parametrize("headers", [{}, {"X-Worker-Key": "wrong"}, OPERATOR])
def test_ingest_rejects_requests_without_valid_worker_key(client, repo, headers) -> None:
    r = client.post("/v1/events", json=make_event(), headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_worker_key"
    assert repo._incidents == {}


def test_ingest_disabled_when_no_worker_key_configured(client, settings) -> None:
    settings.worker_api_keys = SecretStr("")
    r = client.post("/v1/events", json=make_event(), headers=WORKER)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "ingestion_disabled"


# --- validation -------------------------------------------------------------

@pytest.mark.parametrize(
    "change",
    [
        {"detection_score": 1.4},
        {"camera_id": "Camera 1"},
        {"event_type": "loitering"},
        {"schema_version": "2.0"},
        {"track_id": "12"},
        {"occurred_at": "2026-11-07T09:31:40"},
        {"evidence": {"kind": "snapshot", "uri": "data:image/jpeg;base64,/9j/4AAQ"}},
        {"evidence": {"kind": "snapshot", "uri": "evidence/../secrets.txt"}},
        {"unexpected_field": True},
    ],
)
def test_ingest_rejects_invalid_events(client, change) -> None:
    r = client.post("/v1/events", json=make_event(**change), headers=WORKER)
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"] and "input" not in body["details"][0]


def test_ingest_rejects_missing_required_field(client) -> None:
    event = make_event()
    del event["zone_id"]
    r = client.post("/v1/events", json=event, headers=WORKER)
    assert r.status_code == 422
    assert any(d["loc"][-1] == "zone_id" for d in r.json()["error"]["details"])


def test_ingest_rejects_events_far_in_the_future(client) -> None:
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = client.post("/v1/events", json=make_event(occurred_at=future), headers=WORKER)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "event_in_future"


# --- creation and duplicates ------------------------------------------------

def test_first_event_creates_incident_with_evidence_reference(client) -> None:
    event = make_event()
    r = client.post("/v1/events", json=event, headers=WORKER)
    assert r.status_code == 201
    assert r.json()["outcome"] == "created"
    inc = _incident(client, r.json()["incident_id"])
    assert inc["status"] == "new" and inc["review_outcome"] == "unreviewed"
    assert inc["event_count"] == 1
    assert inc["occurred_at"].endswith("Z") and inc["occurred_at"].startswith("2026-11-07T09:31:40")  # stored in UTC
    assert inc["evidence"] == [{"kind": "snapshot", "uri": event["evidence"]["uri"], "captured_at": "2026-11-07T09:31:40.120000Z"}]


def test_retry_with_same_event_id_is_a_duplicate_and_changes_nothing(client) -> None:
    event = make_event()
    first = client.post("/v1/events", json=event, headers=WORKER).json()
    before = _incident(client, first["incident_id"])
    for _ in range(3):
        r = client.post("/v1/events", json=event, headers=WORKER)
        assert r.status_code == 200
        assert r.json() == {**r.json(), "incident_id": first["incident_id"], "outcome": "duplicate"}
    assert _incident(client, first["incident_id"]) == before


def test_new_frames_for_same_occurrence_merge_into_one_incident(client) -> None:
    first = make_event(detection_score=0.71)
    later = make_event(detection_score=0.93, occurred_at="2026-11-07T14:31:46.480+05:00",
                       evidence={"kind": "clip", "uri": "evidence/cam-stockroom-01/2026-11-07/clip-12.mp4"})
    r1 = client.post("/v1/events", json=first, headers=WORKER).json()
    r2 = client.post("/v1/events", json=later, headers=WORKER)
    assert r2.status_code == 200 and r2.json()["outcome"] == "merged"
    assert r2.json()["incident_id"] == r1["incident_id"]
    inc = _incident(client, r1["incident_id"])
    assert inc["event_count"] == 2
    assert inc["detection_score"] == 0.93
    assert inc["last_event_at"].startswith("2026-11-07T09:31:46.48")
    assert [e["kind"] for e in inc["evidence"]] == ["snapshot", "clip"]
    listing = client.get("/v1/incidents", headers=OPERATOR).json()
    assert len(listing["items"]) == 1


def test_different_occurrences_create_separate_incidents(client) -> None:
    a = client.post("/v1/events", json=make_event(), headers=WORKER).json()
    b = client.post("/v1/events", json=make_event(idempotency_key="cam-stockroom-01:zone-high-bay:s20261107a:13:restricted_zone_entry", track_id=13), headers=WORKER).json()
    assert a["incident_id"] != b["incident_id"]


def test_idempotency_key_reused_for_different_track_is_rejected(client) -> None:
    client.post("/v1/events", json=make_event(), headers=WORKER)
    r = client.post("/v1/events", json=make_event(track_id=99), headers=WORKER)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "idempotency_key_conflict"
