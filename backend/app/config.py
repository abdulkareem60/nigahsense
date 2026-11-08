"""Application settings, read from environment variables (or backend/.env in development)."""

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    firebase_project_id: str = Field(default="demo-nigahsense", min_length=1)

    # "firestore" for real use (cloud or emulator); "memory" only for quick local experiments and tests.
    storage_backend: Literal["firestore", "memory"] = "firestore"

    # Shared secrets accepted in the X-Worker-Key header. Comma-separated so keys can be rotated.
    # Empty means event ingestion is disabled.
    worker_api_keys: SecretStr = SecretStr("")

    # Firebase custom-claim roles allowed to use operator endpoints.
    operator_roles: str = "operator,supervisor,admin"

    # Reject events whose occurred_at is further in the future than this (clock-skew allowance).
    max_future_skew_seconds: int = Field(default=300, ge=0)

    cors_origins: str = "http://localhost:3000"

    # Local development only. Google/Firebase SDKs read these from the process environment.
    firestore_emulator_host: str = ""
    firebase_auth_emulator_host: str = ""

    def export_emulator_env(self) -> None:
        if self.app_env == "production" and (self.firestore_emulator_host or self.firebase_auth_emulator_host):
            raise RuntimeError("Emulator hosts must not be set when APP_ENV=production.")
        if self.firestore_emulator_host:
            os.environ.setdefault("FIRESTORE_EMULATOR_HOST", self.firestore_emulator_host)
        if self.firebase_auth_emulator_host:
            os.environ.setdefault("FIREBASE_AUTH_EMULATOR_HOST", self.firebase_auth_emulator_host)

    def worker_keys(self) -> list[str]:
        return [k.strip() for k in self.worker_api_keys.get_secret_value().split(",") if k.strip()]

    def operator_role_set(self) -> frozenset[str]:
        return frozenset(r.strip() for r in self.operator_roles.split(",") if r.strip())

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.export_emulator_env()
    return settings
