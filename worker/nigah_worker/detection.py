"""Detector/tracker boundary.

Everything model-specific lives behind `PersonTracker`. The rest of the worker (video source, zone
rule, API publisher) only sees `TrackedPerson` objects, so the model, thresholds and tracker can be
changed here without touching anything else.

Contract for any implementation:
  * `update(frame)` is called once per processed frame, in order, from a single thread.
  * It returns the people visible in that frame. Each has a `track_id` (int >= 0) that stays the
    same for the same person across frames as far as the tracker can manage.
  * `box` is in pixels of the given frame: (x1, y1, x2, y2), top-left origin.
  * `score` is the detector's confidence for that box, 0..1.
  * `reset()` forgets all tracks (called when a video restarts or a camera reconnects).
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class TrackedPerson:
    track_id: int
    box: tuple[float, float, float, float]
    score: float


class PersonTracker(Protocol):
    def update(self, frame: np.ndarray) -> list[TrackedPerson]: ...

    def reset(self) -> None: ...


PERSON_CLASS_ID = 0  # COCO "person" in Ultralytics YOLO models


class YoloPersonTracker:
    """Baseline: Ultralytics YOLO person detection + built-in ByteTrack/BoT-SORT tracking."""

    def __init__(self, model: str, device: str = "cpu", confidence: float = 0.35, iou: float = 0.5,
                 image_size: int = 640, tracker: str = "bytetrack.yaml") -> None:
        from ultralytics import YOLO  # imported here so tests and tools do not need PyTorch

        self._model_path = model
        self._model = YOLO(model)
        self._device = None if device == "auto" else device
        self._conf = confidence
        self._iou = iou
        self._imgsz = image_size
        self._tracker = tracker

    def update(self, frame: np.ndarray) -> list[TrackedPerson]:
        results = self._model.track(
            frame, persist=True, tracker=self._tracker, classes=[PERSON_CLASS_ID], conf=self._conf,
            iou=self._iou, imgsz=self._imgsz, device=self._device, verbose=False,
        )
        boxes = results[0].boxes
        if boxes is None or boxes.id is None:
            return []  # no detections, or the tracker has not confirmed any track yet
        ids = boxes.id.int().tolist()
        xyxy = boxes.xyxy.tolist()
        conf = boxes.conf.tolist()
        return [TrackedPerson(track_id=i, box=(b[0], b[1], b[2], b[3]), score=float(s)) for i, b, s in zip(ids, xyxy, conf, strict=True)]

    def reset(self) -> None:
        predictor = getattr(self._model, "predictor", None)
        for t in getattr(predictor, "trackers", None) or []:
            t.reset()

    def describe(self) -> str:
        return f"{self._model_path} on {self._device or 'auto'} (conf {self._conf}, tracker {self._tracker})"
