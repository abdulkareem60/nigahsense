"""Operator endpoints: authorization, listing, retrieval and acknowledgement."""

import pytest

from .conftest import OPERATOR, WORKER, make_event


def _create(client, n: int = 1, camera: str = "cam-stockroom-01", minute: int = 10) -> list[str]:
    ids = []
    for i in range(n):
        ev = make_event(camera_id=camera, track_id=i, idempotency_key=f"{camera}:zone-high-bay:s1:{i}:restricted_zone_entry",
                        occurred_at=f"2026-11-07T14:{minute:02d}:{i:02d}+05:00")
        ids.append(client.post("/v1/events", json=ev, headers=WORKER).json()["incident_id"])
    return ids


# --- authorization ----------------------------------------------------------

@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [
        ({}, 401, "unauthenticated"),
        ({"Authorization": "Bearer not-a-real-token"}, 401, "invalid_token"),
        ({"Authorization": "Bearer viewer-token"}, 403, "forbidden"),
        ({"Authorization": "Bearer norole-token"}, 403, "forbidden"),
        ({"X-Worker-Key": "test-worker-key-1234567890"}, 401, "unauthenticated"),
    ],
)
def test_operator_endpoints_require_operator_role(client, headers, status, code) -> None:
    [incident_id] = _create(client)
    for method, url in [("get", "/v1/incidents"), ("get", f"/v1/incidents/{incident_id}"), ("post", f"/v1/incidents/{incident_id}/acknowledge")]:
        r = getattr(client, method)(url, headers=headers)
        assert r.status_code == status, url
        assert r.json()["error"]["code"] == code


# --- list and get -----------------------------------------------------------

def test_list_is_newest_first_and_paginates(client) -> None:
    ids = _create(client, 5)
    page1 = client.get("/v1/incidents?limit=2", headers=OPERATOR).json()
    page2 = client.get(f"/v1/incidents?limit=2&cursor={page1['next_cursor']}", headers=OPERATOR).json()
    page3 = client.get(f"/v1/incidents?limit=2&cursor={page2['next_cursor']}", headers=OPERATOR).json()
    seen = [i["id"] for p in (page1, page2, page3) for i in p["items"]]
    assert seen == list(reversed(ids))
    assert page3["next_cursor"] is None


def test_list_filters_by_camera_status_and_time(client) -> None:
    _create(client, 2, camera="cam-stockroom-01", minute=10)
    [dock] = _create(client, 1, camera="cam-loading-bay", minute=20)
    assert [i["id"] for i in client.get("/v1/incidents?camera_id=cam-loading-bay", headers=OPERATOR).json()["items"]] == [dock]
    client.post(f"/v1/incidents/{dock}/acknowledge", headers=OPERATOR)
    assert len(client.get("/v1/incidents?status=new", headers=OPERATOR).json()["items"]) == 2
    assert len(client.get("/v1/incidents?status=acknowledged", headers=OPERATOR).json()["items"]) == 1
    late = client.get("/v1/incidents", params={"occurred_from": "2026-11-07T14:15:00+05:00"}, headers=OPERATOR).json()
    assert [i["id"] for i in late["items"]] == [dock]


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("cursor=bm90LWFuLWlk", "invalid_cursor"),
        ("cursor=%%%", "invalid_cursor"),
        ("limit=0", "validation_error"),
        ("limit=500", "validation_error"),
        ("status=closed", "validation_error"),
        ("occurred_from=2026-11-07T10:00:00", "validation_error"),
        ("occurred_from=2026-11-08T00:00:00Z&occurred_to=2026-11-07T00:00:00Z", "invalid_range"),
    ],
)
def test_list_rejects_bad_query_parameters(client, query, code) -> None:
    r = client.get(f"/v1/incidents?{query}", headers=OPERATOR)
    assert r.status_code in (400, 422)
    assert r.json()["error"]["code"] == code


def test_get_unknown_incident_returns_404(client) -> None:
    for incident_id in ["inc_000000000000000000000000", "not-an-id"]:
        r = client.get(f"/v1/incidents/{incident_id}", headers=OPERATOR)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "incident_not_found"


# --- acknowledge ------------------------------------------------------------

def test_acknowledge_records_who_and_when(client) -> None:
    [incident_id] = _create(client)
    r = client.post(f"/v1/incidents/{incident_id}/acknowledge", json={"note": "  Checking with stockroom.  "}, headers=OPERATOR)
    assert r.status_code == 200
    inc = r.json()
    assert inc["status"] == "acknowledged"
    assert inc["acknowledged_by"] == "op-1"
    assert inc["acknowledged_at"] is not None
    assert inc["acknowledgement_note"] == "Checking with stockroom."
    assert inc["review_outcome"] == "unreviewed"  # acknowledging is not confirming the event
    assert client.get(f"/v1/incidents/{incident_id}", headers=OPERATOR).json() == inc


def test_acknowledge_twice_keeps_the_first_acknowledgement(client) -> None:
    [incident_id] = _create(client)
    first = client.post(f"/v1/incidents/{incident_id}/acknowledge", json={"note": "first"}, headers=OPERATOR).json()
    second = client.post(f"/v1/incidents/{incident_id}/acknowledge", json={"note": "second"}, headers=OPERATOR)
    assert second.status_code == 200
    assert second.json() == first


def test_acknowledge_without_body_is_allowed(client) -> None:
    [incident_id] = _create(client)
    r = client.post(f"/v1/incidents/{incident_id}/acknowledge", headers=OPERATOR)
    assert r.status_code == 200 and r.json()["acknowledgement_note"] is None


def test_acknowledge_validation_and_missing_incident(client) -> None:
    [incident_id] = _create(client)
    too_long = client.post(f"/v1/incidents/{incident_id}/acknowledge", json={"note": "x" * 501}, headers=OPERATOR)
    assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "validation_error"
    missing = client.post("/v1/incidents/inc_000000000000000000000000/acknowledge", headers=OPERATOR)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "incident_not_found"


def test_new_event_after_acknowledgement_does_not_reopen_incident(client) -> None:
    [incident_id] = _create(client)
    client.post(f"/v1/incidents/{incident_id}/acknowledge", headers=OPERATOR)
    ev = make_event(track_id=0, idempotency_key="cam-stockroom-01:zone-high-bay:s1:0:restricted_zone_entry", occurred_at="2026-11-07T14:10:05+05:00")
    assert client.post("/v1/events", json=ev, headers=WORKER).json()["outcome"] == "merged"
    inc = client.get(f"/v1/incidents/{incident_id}", headers=OPERATOR).json()
    assert inc["status"] == "acknowledged" and inc["event_count"] == 2


def test_health_and_unknown_routes(client) -> None:
    assert client.get("/health").json() == {"status": "ok", "storage": "ok"}
    r = client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
