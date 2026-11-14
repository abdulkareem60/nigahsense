"""Builds vision event v1 payloads (contracts/vision-event.v1.schema.json). No network code here."""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from .rules import ZoneEntry

EVENT_TYPE = "restricted_zone_entry"
SCHEMA_VERSION = "1.0"


def new_session_id(now: datetime | None = None) -> str:
    """Identifies one worker run. Track IDs restart every run, so the session keeps idempotency keys unique."""
    now = now or datetime.now(UTC)
    return "s" + now.strftime("%Y%m%d%H%M%S") + secrets.token_hex(2)


def idempotency_key(camera_id: str, zone_id: str, session_id: str, track_id: int, visit: int) -> str:
    """Contract's recommended form for a first entry; later re-entries of the same track add '.v<visit>'."""
    key = f"{camera_id}:{zone_id}:{session_id}:{track_id}:{EVENT_TYPE}"
    return key if visit <= 1 else f"{key}.v{visit}"


def utc_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_event(entry: ZoneEntry, camera_id: str, session_id: str) -> dict[str, Any]:
    """One contract-valid event. `evidence` is omitted: media upload is not implemented yet."""
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key(camera_id, entry.zone_id, session_id, entry.track_id, entry.visit),
        "event_type": EVENT_TYPE,
        "camera_id": camera_id,
        "zone_id": entry.zone_id,
        "track_id": entry.track_id,
        "occurred_at": utc_rfc3339(entry.occurred_at),
        "detection_score": round(min(max(entry.score, 0.0), 1.0), 4),
    }
