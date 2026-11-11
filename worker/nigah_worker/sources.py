"""Video sources. Each yields `Frame`s with a UTC timestamp; detection code never opens video itself.

* FileSource   - recorded video (primary input for the first milestone). Optional real-time pacing
                 and looping. Timestamps = run start time + position in the video.
* WebcamSource - local camera by index. Timestamp = wall clock when the frame was read.
* RtspSource   - network camera. Reconnects with exponential backoff after open/read failures.
"""

import logging
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from .config import SourceConfig

log = logging.getLogger("nigah_worker.sources")


class SourceError(RuntimeError):
    """The source cannot be opened or has failed for good."""


@dataclass(frozen=True)
class Frame:
    image: np.ndarray
    index: int  # frame number since the source (re)started
    captured_at: datetime  # UTC
    restarted: bool = False  # True on the first frame after a loop or reconnect (trackers should reset)


class FileSource:
    def __init__(self, path: str, realtime: bool = True, loop: bool = False, stop: threading.Event | None = None) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise SourceError(f"Video file not found: {self.path}")
        self.realtime = realtime
        self.loop = loop
        self._stop = stop or threading.Event()
        self.fps = 0.0
        self.describe = f"file {self.path}"

    def frames(self) -> Iterator[Frame]:
        start = datetime.now(UTC)
        offset = timedelta(0)
        first = True
        index = 0
        while not self._stop.is_set():
            cap = cv2.VideoCapture(str(self.path))
            if not cap.isOpened():
                raise SourceError(f"OpenCV could not open video (unsupported codec or damaged file): {self.path}")
            self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frame_period = 1.0 / self.fps
            wall0 = time.monotonic()
            pass_frames = 0
            restarted = not first
            try:
                while not self._stop.is_set():
                    ok, img = cap.read()
                    if not ok:
                        break  # end of video
                    position = timedelta(seconds=pass_frames * frame_period)
                    if self.realtime:
                        lag = position.total_seconds() - (time.monotonic() - wall0)
                        if lag > 0:
                            self._stop.wait(lag)
                    captured = min(start + offset + position, datetime.now(UTC))  # never in the future
                    yield Frame(img, index, captured, restarted)
                    restarted = False
                    index += 1
                    pass_frames += 1
            finally:
                cap.release()
            if pass_frames == 0:
                raise SourceError(f"Video has no readable frames: {self.path}")
            first = False
            offset += timedelta(seconds=pass_frames * frame_period)
            if not self.loop:
                log.info("End of video after %d frames", index)
                return
            log.info("End of video; looping")


class _LiveSource:
    """Shared reconnect logic for webcam and RTSP."""

    def __init__(self, cfg: SourceConfig, stop: threading.Event | None = None) -> None:
        self.cfg = cfg
        self._stop = stop or threading.Event()
        self.fps = 0.0
        self.describe = "live"

    def _open(self) -> cv2.VideoCapture:
        raise NotImplementedError

    def frames(self) -> Iterator[Frame]:
        index = 0
        attempts = 0
        delay = self.cfg.reconnect_initial_seconds
        restarted = False
        while not self._stop.is_set():
            cap = self._open()
            if not cap.isOpened():
                cap.release()
                attempts += 1
                if self.cfg.max_reconnect_attempts and attempts >= self.cfg.max_reconnect_attempts:
                    raise SourceError(f"Could not open {self.describe} after {attempts} attempts")
                log.warning("Could not open %s; retrying in %.1fs (attempt %d)", self.describe, delay, attempts)
                self._stop.wait(delay)
                delay = min(delay * 2, self.cfg.reconnect_max_seconds)
                continue
            log.info("Opened %s", self.describe)
            self.fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            attempts = 0
            delay = self.cfg.reconnect_initial_seconds
            failures = 0
            try:
                while not self._stop.is_set():
                    ok, img = cap.read()
                    if not ok:
                        failures += 1
                        if failures >= self.cfg.max_consecutive_read_failures:
                            log.warning("%s stopped delivering frames; reconnecting", self.describe)
                            break
                        self._stop.wait(0.05)
                        continue
                    failures = 0
                    yield Frame(img, index, datetime.now(UTC), restarted)
                    restarted = False
                    index += 1
            finally:
                cap.release()
            restarted = True


class WebcamSource(_LiveSource):
    def __init__(self, cfg: SourceConfig, stop: threading.Event | None = None) -> None:
        super().__init__(cfg, stop)
        self.describe = f"webcam {cfg.device_index}"

    def _open(self) -> cv2.VideoCapture:
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY  # DirectShow opens faster on Windows
        return cv2.VideoCapture(self.cfg.device_index, backend)


class RtspSource(_LiveSource):
    def __init__(self, cfg: SourceConfig, stop: threading.Event | None = None) -> None:
        super().__init__(cfg, stop)
        url = os.environ.get(cfg.url_env, "")
        if not url:
            raise SourceError(f"RTSP source selected but environment variable {cfg.url_env} is empty")
        self._url = url
        self.describe = f"rtsp camera ({_redact(url)})"

    def _open(self) -> cv2.VideoCapture:
        # TCP transport and a 5 s open/read timeout avoid hanging forever on a dead camera.
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        return cv2.VideoCapture(self._url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])


def _redact(url: str) -> str:
    """rtsp://user:pass@host/x -> rtsp://***@host/x, so credentials never reach logs."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url


def open_source(cfg: SourceConfig, stop: threading.Event | None = None) -> FileSource | WebcamSource | RtspSource:
    if cfg.type == "file":
        return FileSource(cfg.path or "", realtime=cfg.realtime, loop=cfg.loop, stop=stop)
    if cfg.type == "webcam":
        return WebcamSource(cfg, stop)
    return RtspSource(cfg, stop)
