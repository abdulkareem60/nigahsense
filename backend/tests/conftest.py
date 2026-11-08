import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dependencies import get_repository
from app.main import create_app
from app.repositories.memory import MemoryIncidentRepository
from app.security import get_token_verifier

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
WORKER_KEY = "test-worker-key-1234567890"


class FakeVerifier:
    """Maps fixed test tokens to claims, standing in for Firebase token verification."""

    TOKENS = {
        "operator-token": {"uid": "op-1", "role": "operator", "email": "op@example.test"},
        "viewer-token": {"uid": "viewer-1", "role": "viewer"},
        "norole-token": {"uid": "nobody-1"},
    }

    def verify(self, token: str) -> dict[str, Any]:
        if token not in self.TOKENS:
            raise ValueError("bad token")
        return self.TOKENS[token]


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env="test", storage_backend="memory", worker_api_keys=WORKER_KEY, firebase_project_id="demo-nigahsense")


@pytest.fixture
def repo() -> MemoryIncidentRepository:
    return MemoryIncidentRepository()


@pytest.fixture
def client(settings: Settings, repo: MemoryIncidentRepository) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
    return TestClient(app)


WORKER = {"X-Worker-Key": WORKER_KEY}
OPERATOR = {"Authorization": "Bearer operator-token"}


def load_example(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS / "examples" / name).read_text(encoding="utf-8"))


def make_event(**overrides: Any) -> dict[str, Any]:
    event = load_example("vision-event.v1.restricted-zone-entry.json")
    event["event_id"] = str(uuid.uuid4())
    event.update(overrides)
    return event
