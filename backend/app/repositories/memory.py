"""In-process storage for tests and quick experiments. Data is lost when the process stops."""

import threading
from typing import Any

from ..schemas.incidents import Incident, IncidentFilters
from .base import ApplyEvent, IngestOutcome, InvalidCursor, Mutate


def _matches(i: Incident, f: IncidentFilters) -> bool:
    return (
        (f.status is None or i.status == f.status)
        and (f.camera_id is None or i.camera_id == f.camera_id)
        and (f.event_type is None or i.event_type == f.event_type)
        and (f.occurred_from is None or i.occurred_at >= f.occurred_from)
        and (f.occurred_to is None or i.occurred_at <= f.occurred_to)
    )


class MemoryIncidentRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._incidents: dict[str, Incident] = {}
        self._events: dict[str, dict[str, dict[str, Any]]] = {}

    def ingest(self, incident_id: str, event_id: str, event_record: dict[str, Any], apply: ApplyEvent) -> tuple[Incident, IngestOutcome]:
        with self._lock:
            existing = self._incidents.get(incident_id)
            seen = self._events.setdefault(incident_id, {})
            if existing is not None and event_id in seen:
                return existing, "duplicate"
            updated = apply(existing)
            self._incidents[incident_id] = updated
            seen[event_id] = dict(event_record)
            return updated, ("created" if existing is None else "merged")

    def get(self, incident_id: str) -> Incident | None:
        with self._lock:
            return self._incidents.get(incident_id)

    def list(self, filters: IncidentFilters, limit: int, cursor: str | None) -> tuple[list[Incident], str | None]:
        with self._lock:
            rows = sorted((i for i in self._incidents.values() if _matches(i, filters)), key=lambda i: (i.occurred_at, i.id), reverse=True)
        start = 0
        if cursor is not None:
            ids = [i.id for i in rows]
            if cursor not in ids:
                raise InvalidCursor(cursor)
            start = ids.index(cursor) + 1
        page = rows[start : start + limit]
        has_more = len(rows) > start + limit
        return page, (page[-1].id if has_more and page else None)

    def update(self, incident_id: str, mutate: Mutate) -> Incident | None:
        with self._lock:
            current = self._incidents.get(incident_id)
            if current is None:
                return None
            updated = mutate(current)
            self._incidents[incident_id] = updated
            return updated

    def ping(self) -> None:
        return None
