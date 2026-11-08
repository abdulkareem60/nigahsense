"""Authentication.

Operators: Firebase ID token in `Authorization: Bearer <token>`, with a custom claim `role`
in OPERATOR_ROLES. Vision worker: a shared secret in `X-Worker-Key` (never a user token).
"""

import hmac
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Protocol

import firebase_admin
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as fb_auth

from .config import Settings, get_settings
from .errors import ApiError

_BEARER = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class Principal:
    uid: str
    role: str | None
    email: str | None = None


class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict[str, Any]: ...


class FirebaseTokenVerifier:
    """Verifies Firebase ID tokens. With FIREBASE_AUTH_EMULATOR_HOST set, accepts emulator tokens."""

    def __init__(self, project_id: str) -> None:
        name = "nigahsense-auth"
        try:
            self._app = firebase_admin.get_app(name)
        except ValueError:
            # Token verification needs only the project ID (public keys are fetched by the SDK).
            self._app = firebase_admin.initialize_app(credential=None, options={"projectId": project_id}, name=name)

    def verify(self, token: str) -> dict[str, Any]:
        return fb_auth.verify_id_token(token, app=self._app, check_revoked=False)


@lru_cache
def _verifier_for(project_id: str) -> FirebaseTokenVerifier:
    return FirebaseTokenVerifier(project_id)


def get_token_verifier(settings: Annotated[Settings, Depends(get_settings)]) -> TokenVerifier:
    return _verifier_for(settings.firebase_project_id)


_bearer = HTTPBearer(auto_error=False)


def require_operator(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise ApiError(401, "unauthenticated", "Sign in required.", headers=_BEARER)
    try:
        claims = verifier.verify(creds.credentials)
    except Exception:
        raise ApiError(401, "invalid_token", "The sign-in token is invalid or expired.", headers=_BEARER) from None
    role = claims.get("role")
    if role not in settings.operator_role_set():
        raise ApiError(403, "forbidden", "This account is not allowed to use operator features.")
    return Principal(uid=str(claims.get("uid") or claims.get("sub")), role=role, email=claims.get("email"))


def require_worker(
    settings: Annotated[Settings, Depends(get_settings)],
    x_worker_key: Annotated[str | None, Header()] = None,
) -> None:
    keys = settings.worker_keys()
    if not keys:
        raise ApiError(503, "ingestion_disabled", "Event ingestion is not configured on this server.")
    supplied = (x_worker_key or "").encode()
    # Compare against every key so timing does not reveal which key matched.
    ok = False
    for key in keys:
        ok |= hmac.compare_digest(supplied, key.encode())
    if not ok:
        raise ApiError(401, "invalid_worker_key", "A valid X-Worker-Key header is required.")
