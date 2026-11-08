"""Vision event v1 — mirrors contracts/vision-event.v1.schema.json."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

IdStr = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
IdempotencyKey = Annotated[str, StringConstraints(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9:._-]+$")]
EvidenceUri = Annotated[str, StringConstraints(max_length=1024, pattern=r"^(gs://|s3://|https://|evidence/)[^\s]+$")]

EventType = Literal["restricted_zone_entry"]


class EvidenceRef(BaseModel):
    """A pointer to media already stored elsewhere. Never contains image or video bytes."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["snapshot", "clip"]
    uri: EvidenceUri
    captured_at: AwareDatetime | None = None

    @field_validator("uri")
    @classmethod
    def _no_parent_paths(cls, v: str) -> str:
        if ".." in v:
            raise ValueError("evidence uri must not contain '..'")
        return v


class VisionEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    event_id: UUID
    idempotency_key: IdempotencyKey
    event_type: EventType
    camera_id: IdStr
    zone_id: IdStr
    track_id: Annotated[int, Field(ge=0, strict=True)]
    occurred_at: AwareDatetime
    detection_score: Annotated[float, Field(ge=0, le=1)]
    evidence: EvidenceRef | None = None


class IngestResult(BaseModel):
    incident_id: str
    outcome: Literal["created", "merged", "duplicate"]
    received_at: datetime
