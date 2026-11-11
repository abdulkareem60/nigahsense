import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "contracts"


@pytest.fixture(scope="session")
def event_schema() -> dict:
    return json.loads((CONTRACTS / "vision-event.v1.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def api_event_model():
    """The API's own request model (backend/app/schemas/events.py), so worker payloads are checked
    against exactly what POST /v1/events accepts. Needs only pydantic, not FastAPI."""
    sys.path.insert(0, str(REPO / "backend"))
    try:
        from app.schemas.events import VisionEventV1
    finally:
        sys.path.remove(str(REPO / "backend"))
    return VisionEventV1
