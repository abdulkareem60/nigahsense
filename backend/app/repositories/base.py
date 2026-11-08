"""Storage interface for incidents. Services depend on this, not on Firestore directly."""

from collections.abc import Callable
from typing import Any, Literal, Protocol

from ..schemas.incidents import Incident, IncidentFilters

IngestOutcome = Literal["created", "merged", "duplicate"]

# Receives the stored incident (or None if new) and returns the incident to store.
ApplyEvent = Callable[[Incident | None], Incident]
# Receives the stored incident and returns the updated one.
Mutate = Callable[[Incident], Incident]


class InvalidCursor(Exception):
    pass


class IncidentRepository(Protocol):
    def ingest(self, incident_id: str, event_id: str, event_record: dict[str, Any], apply: ApplyEvent) -> tuple[Incident, IngestOutcome]:
        """Atomically record an event and create or update its incident.

        If event_id was already recorded for this incident, nothing is written and
        the outcome is "duplicate".
        """
        ...

    def get(self, incident_id: str) -> Incident | None: ...

    def list(self, filters: IncidentFilters, limit: int, cursor: str | None) -> tuple[list[Incident], str | None]:
        """Newest first (occurred_at, then id). cursor is the id of the last item of the previous page."""
        ...

    def update(self, incident_id: str, mutate: Mutate) -> Incident | None:
        """Atomically apply mutate to an incident. Returns None if it does not exist."""
        ...

    def ping(self) -> None:
        """Raise if storage is unreachable."""
        ...
