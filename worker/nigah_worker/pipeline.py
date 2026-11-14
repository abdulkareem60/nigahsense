"""Connects the parts: source -> tracker -> zone rule -> event publisher (+ optional annotation)."""

import json
import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .annotate import VideoSink, draw
from .detection import PersonTracker
from .events import build_event
from .rules import RestrictedZoneRule
from .sources import Frame

log = logging.getLogger("nigah_worker.pipeline")


@dataclass
class RunStats:
    frames_read: int = 0
    frames_processed: int = 0
    max_people: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0


class EventLog:
    """Local JSONL record of every event the worker produced (one line per event)."""

    def __init__(self, path: str | None) -> None:
        self._path = Path(path) if path else None
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        if not self._path:
            return
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def run_pipeline(
    frames: Iterable[Frame],
    tracker: PersonTracker,
    rule: RestrictedZoneRule,
    publish: Callable[[dict[str, Any]], None],
    camera_id: str,
    session_id: str,
    stop: threading.Event,
    frame_stride: int = 1,
    event_log: EventLog | None = None,
    annotated_path: str | None = None,
    show_window: bool = False,
    fps_hint: Callable[[], float] = lambda: 10.0,
    max_frames: int | None = None,
) -> RunStats:
    stats = RunStats()
    sink: VideoSink | None = None
    t0 = time.monotonic()
    last_log = t0
    try:
        for frame in frames:
            if stop.is_set():
                break
            stats.frames_read += 1
            if frame.restarted:
                tracker.reset()
                rule.reset()
            if frame.index % frame_stride:
                continue
            h, w = frame.image.shape[:2]
            people = tracker.update(frame.image)
            stats.frames_processed += 1
            stats.max_people = max(stats.max_people, len(people))
            for entry in rule.update(people, frame.captured_at, w, h):
                event = build_event(entry, camera_id, session_id)
                stats.events.append(event)
                log.info("ENTRY zone=%s track=%s score=%.2f frame=%d -> sending %s",
                         entry.zone_id, entry.track_id, entry.score, frame.index, event["event_id"])
                if event_log:
                    event_log.write({"type": "event_emitted", "frame": frame.index, "event": event})
                publish(event)

            if annotated_path or show_window:
                img = draw(frame.image, rule.zones, people, rule, f"frame {frame.index}", len(stats.events))
                if annotated_path:
                    if sink is None:
                        sink = VideoSink(annotated_path, fps_hint() / frame_stride, (w, h))
                    sink.write(img)
                if show_window:
                    import cv2

                    cv2.imshow("NigahSense worker (press q to stop)", img)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        stop.set()

            now = time.monotonic()
            if now - last_log >= 10:
                log.info("Processed %d frames (%.1f fps), %d people now, %d events so far",
                         stats.frames_processed, stats.frames_processed / (now - t0), len(people), len(stats.events))
                last_log = now
            if max_frames and stats.frames_read >= max_frames:
                break
    finally:
        stats.seconds = time.monotonic() - t0
        if sink:
            sink.close()
        if show_window:
            import cv2

            cv2.destroyAllWindows()
    return stats
