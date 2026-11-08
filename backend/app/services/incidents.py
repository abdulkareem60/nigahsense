"""Incident business rules: turning vision events into incidents, listing, acknowledging."""

import base64
import binascii
import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ..errors import ApiError
from ..repositories.base import IncidentRepository, InvalidCursor
from ..schemas.events import IngestResult, VisionEventV1
from ..schemas.incidents import Incident, IncidentFilters, IncidentList

MAX_EVIDENCE_PER_INCIDENT = 20
INCIDENT_ID_RE = re.compile(r"^inc_[0-9a-f]{24}$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def incident_id_for(idempotency_key: str) -> str:
    """Same idempotency key -> same incident document, so retries and repeated frames converge."""
    return "inc_" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]


def encode_cursor(incident_id: str | None) -> str | None:
    return base64.urlsafe_b64encode(incident_id.encode()).decode().rstrip("=") if incident_id else None


def decode_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    try:
        value = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ApiError(400, "invalid_cursor", "The pagination cursor is not valid.") from None
    if not INCIDENT_ID_RE.match(value):
        raise ApiError(400, "invalid_cursor", "The pagination cursor is not valid.")
    return value


class IncidentService:
    def __init__(self, repo: IncidentRepository, max_future_skew_seconds: int = 300, clock: Callable[[], datetime] = utcnow) -> None:
        self._repo = repo
        self._skew = timedelta(seconds=max_future_skew_seconds)
        self._clock = clock

    def ingest(self, event: VisionEventV1) -> IngestResult:
        now = self._clock()
        occurred = event.occurred_at.astimezone(UTC)
        if occurred > now + self._skew:
            raise ApiError(422, "event_in_future", "occurred_at is too far in the future; check the worker clock.")
        incident_id = incident_id_for(event.idempotency_key)
        evidence = event.evidence.model_copy(update={"captured_at": event.evidence.captured_at.astimezone(UTC) if event.evidence.captured_at else None}) if event.evidence else None

        def apply(existing: Incident | None) -> Incident:
            if existing is None:
                return Incident(
                    id=incident_id, event_type=event.event_type, camera_id=event.camera_id, zone_id=event.zone_id,
                    track_id=event.track_id, detection_score=event.detection_score, occurred_at=occurred,
                    last_event_at=occurred, event_count=1, first_event_id=str(event.event_id),
                    evidence=[evidence] if evidence else [], created_at=now, updated_at=now,
                )
            if (existing.event_type, existing.camera_id, existing.zone_id, existing.track_id) != (event.event_type, event.camera_id, event.zone_id, event.track_id):
                raise ApiError(409, "idempotency_key_conflict", "This idempotency_key already belongs to a different camera, zone, track or event type.")
            refs = list(existing.evidence)
            if evidence and all(r.uri != evidence.uri for r in refs) and len(refs) < MAX_EVIDENCE_PER_INCIDENT:
                refs.append(evidence)
            return existing.model_copy(update={
                "event_count": existing.event_count + 1,
                "occurred_at": min(existing.occurred_at, occurred),
                "last_event_at": max(existing.last_event_at, occurred),
                "detection_score": max(existing.detection_score, event.detection_score),
                "evidence": refs,
                "updated_at": now,
            })

        record = {
            "event_id": str(event.event_id),
            "occurred_at": occurred,
            "detection_score": event.detection_score,
            "evidence_uri": evidence.uri if evidence else None,
            "received_at": now,
        }
        incident, outcome = self._repo.ingest(incident_id, str(event.event_id), record, apply)
        return IngestResult(incident_id=incident.id, outcome=outcome, received_at=now)

    def list(self, filters: IncidentFilters, limit: int, cursor: str | None) -> IncidentList:
        if filters.occurred_from and filters.occurred_to and filters.occurred_from > filters.occurred_to:
            raise ApiError(400, "invalid_range", "occurred_from must be earlier than occurred_to.")
        try:
            items, last_id = self._repo.list(filters, limit, decode_cursor(cursor))
        except InvalidCursor:
            raise ApiError(400, "invalid_cursor", "The pagination cursor is not valid.") from None
        return IncidentList(items=items, next_cursor=encode_cursor(last_id))

    def get(self, incident_id: str) -> Incident:
        incident = self._repo.get(incident_id) if INCIDENT_ID_RE.match(incident_id) else None
        if incident is None:
            raise ApiError(404, "incident_not_found", "Incident not found.")
        return incident

    def acknowledge(self, incident_id: str, user_id: str, note: str | None) -> Incident:
        if not INCIDENT_ID_RE.match(incident_id):
            raise ApiError(404, "incident_not_found", "Incident not found.")
        now = self._clock()

        def mutate(current: Incident) -> Incident:
            if current.status == "acknowledged":
                return current  # Repeating the request is harmless; the first acknowledgement is kept.
            return current.model_copy(update={
                "status": "acknowledged", "acknowledged_at": now, "acknowledged_by": user_id,
                "acknowledgement_note": (note or "").strip() or None, "updated_at": now,
            })

        updated = self._repo.update(incident_id, mutate)
        if updated is None:
            raise ApiError(404, "incident_not_found", "Incident not found.")
        return updated
