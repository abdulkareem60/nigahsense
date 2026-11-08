"""Same core flows against the Firestore emulator. Skipped unless FIRESTORE_EMULATOR_HOST is set.

Run: firebase emulators:exec --only firestore "python -m pytest -m emulator" (from the repo root, see README).
"""

import os
import uuid

import pytest

from app.schemas.events import VisionEventV1
from app.schemas.incidents import IncidentFilters
from app.services.incidents import IncidentService

from .conftest import make_event

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="Firestore emulator not running"),
]


@pytest.fixture
def service() -> IncidentService:
    from app.repositories.firestore import FirestoreIncidentRepository, make_client

    # A unique project ID isolates each run's data inside the emulator.
    client = make_client(f"demo-nigahsense-test-{uuid.uuid4().hex[:8]}")
    return IncidentService(FirestoreIncidentRepository(client))


def _event(**kw) -> VisionEventV1:
    return VisionEventV1.model_validate(make_event(**kw))


def test_firestore_create_duplicate_merge(service: IncidentService) -> None:
    ev = _event()
    assert service.ingest(ev).outcome == "created"
    assert service.ingest(ev).outcome == "duplicate"
    merged = service.ingest(_event(detection_score=0.95))
    assert merged.outcome == "merged"
    inc = service.get(merged.incident_id)
    assert inc.event_count == 2 and inc.detection_score == 0.95
    assert inc.evidence[0].uri.startswith("evidence/")


def test_firestore_list_filter_paginate_and_acknowledge(service: IncidentService) -> None:
    ids = []
    for i in range(3):
        ids.append(service.ingest(_event(track_id=i, idempotency_key=f"cam-stockroom-01:zone-high-bay:s9:{i}:restricted_zone_entry",
                                         occurred_at=f"2026-11-07T14:20:0{i}+05:00")).incident_id)
    page1 = service.list(IncidentFilters(), 2, None)
    page2 = service.list(IncidentFilters(), 2, page1.next_cursor)
    assert [i.id for i in page1.items + page2.items] == list(reversed(ids))
    assert page2.next_cursor is None

    acked = service.acknowledge(ids[0], "op-1", "on it")
    assert acked.status == "acknowledged" and acked.acknowledged_by == "op-1"
    assert service.acknowledge(ids[0], "op-2", "again").acknowledged_by == "op-1"
    assert [i.id for i in service.list(IncidentFilters(status="acknowledged"), 10, None).items] == [ids[0]]
    assert len(service.list(IncidentFilters(status="new", camera_id="cam-stockroom-01"), 10, None).items) == 2
