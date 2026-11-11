"""Worker configuration.

Two sources, kept apart on purpose:
  * a TOML file (camera, video source, detector, zones, rule) that is safe to commit as an example;
  * environment variables / worker/.env for secrets and deployment values (API URL, worker key, RTSP URL).
"""

import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Same identifier rule as contracts/vision-event.v1.schema.json (camera_id, zone_id).
IdStr = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CameraConfig(_Strict):
    id: IdStr
    name: str = ""


class SourceConfig(_Strict):
    type: Literal["file", "webcam", "rtsp"] = "file"
    # file
    path: str | None = None
    realtime: bool = True  # pace file playback to its frame rate, like a live camera
    loop: bool = False
    # webcam
    device_index: int = Field(default=0, ge=0)
    # rtsp: the URL (often containing a password) is read from this environment variable, never from the file
    url_env: str = "NIGAHSENSE_RTSP_URL"
    # webcam/rtsp reconnect policy
    reconnect_initial_seconds: float = Field(default=1.0, gt=0)
    reconnect_max_seconds: float = Field(default=30.0, gt=0)
    max_reconnect_attempts: int = Field(default=0, ge=0, description="0 = keep trying until stopped")
    max_consecutive_read_failures: int = Field(default=25, ge=1)

    @model_validator(mode="after")
    def _needs_path(self) -> "SourceConfig":
        if self.type == "file" and not self.path:
            raise ValueError("source.path is required when source.type = 'file'")
        return self


class DetectorConfig(_Strict):
    model: str = "models/yolo26n.pt"
    device: str = "cpu"  # "cpu", "0" for the first CUDA GPU, or "auto"
    confidence: Unit = 0.35
    iou: Unit = 0.5
    image_size: int = Field(default=640, ge=160, le=1920)
    tracker: str = "bytetrack.yaml"  # or "botsort.yaml"
    frame_stride: int = Field(default=1, ge=1, description="Process every Nth frame")


class ZoneConfig(_Strict):
    id: IdStr
    name: str = ""
    # Normalised [x, y] points: x = 0 left edge .. 1 right edge, y = 0 top edge .. 1 bottom edge.
    points: list[tuple[Unit, Unit]] = Field(min_length=3)


class RuleConfig(_Strict):
    min_score: Unit = 0.40
    confirm_frames: int = Field(default=3, ge=1)
    exit_frames: int = Field(default=5, ge=1)
    track_gap_seconds: float = Field(default=5.0, ge=0)
    reentry_cooldown_seconds: float = Field(default=30.0, ge=0)
    anchor: Literal["bottom_center", "center"] = "bottom_center"


class OutputConfig(_Strict):
    event_log: str | None = "runtime/events.jsonl"
    outbox: str = "runtime/outbox.jsonl"
    annotated_video: str | None = None
    show_window: bool = False


class WorkerConfig(_Strict):
    camera: CameraConfig
    source: SourceConfig
    detector: DetectorConfig = DetectorConfig()
    zones: list[ZoneConfig] = Field(min_length=1)
    rule: RuleConfig = RuleConfig()
    output: OutputConfig = OutputConfig()

    @field_validator("zones")
    @classmethod
    def _unique_zone_ids(cls, zones: list[ZoneConfig]) -> list[ZoneConfig]:
        ids = [z.id for z in zones]
        if len(ids) != len(set(ids)):
            raise ValueError("zone ids must be unique per camera")
        return zones


class WorkerEnv(BaseSettings):
    """Secrets and deployment values. Read from the environment or worker/.env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    nigahsense_api_url: str = "http://127.0.0.1:8000"
    nigahsense_worker_key: SecretStr = SecretStr("")
    nigahsense_request_timeout_seconds: float = 10.0
    nigahsense_max_send_attempts: int = 8


def load_config(path: str | Path) -> WorkerConfig:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Config file not found: {p}")
    with p.open("rb") as fh:
        data = tomllib.load(fh)
    # Relative paths in the file (video, model, outputs) are relative to the folder the worker is run from (worker/).
    return WorkerConfig.model_validate(data)
