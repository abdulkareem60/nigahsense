"""Incident records and incident-endpoint payloads."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .events import EventType, EvidenceRef

IncidentStatus = Literal["new", "acknowledged"]
ReviewOutcome = Literal["unreviewed", "confirmed", "false_alert", "uncertain"]


class Incident(BaseModel):
    id: str
    event_type: EventType
    camera_id: str
    zone_id: str
    track_id: int
    status: IncidentStatus = "new"
    review_outcome: ReviewOutcome = "unreviewed"
    detection_score: float
    occurred_at: datetime
    last_event_at: datetime
    event_count: int = 1
    first_event_id: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    acknowledgement_note: str | None = None


class IncidentList(BaseModel):
    items: list[Incident]
    next_cursor: str | None = None


class AcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[str, Field(max_length=500)] | None = None


class IncidentFilters(BaseModel):
    status: IncidentStatus | None = None
    camera_id: str | None = None
    event_type: EventType | None = None
    occurred_from: AwareDatetime | None = None
    occurred_to: AwareDatetime | None = None
