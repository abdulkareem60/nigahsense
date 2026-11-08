"""Wiring: which repository and service the routes use. Tests override get_repository."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from .config import Settings, get_settings
from .repositories.base import IncidentRepository
from .repositories.memory import MemoryIncidentRepository
from .services.incidents import IncidentService


@lru_cache
def _repository_for(backend: str, project_id: str) -> IncidentRepository:
    if backend == "memory":
        return MemoryIncidentRepository()
    from .repositories.firestore import FirestoreIncidentRepository, make_client

    return FirestoreIncidentRepository(make_client(project_id))


def get_repository(settings: Annotated[Settings, Depends(get_settings)]) -> IncidentRepository:
    return _repository_for(settings.storage_backend, settings.firebase_project_id)


def get_incident_service(
    repo: Annotated[IncidentRepository, Depends(get_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IncidentService:
    return IncidentService(repo, max_future_skew_seconds=settings.max_future_skew_seconds)
