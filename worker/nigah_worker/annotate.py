"""Draws zones, tracked people and events on frames, for a live window or a saved review video."""

from pathlib import Path

import cv2
import numpy as np

from .detection import TrackedPerson
from .rules import RestrictedZoneRule
from .zones import Zone, anchor_point

ZONE = (60, 60, 230)  # BGR red
OUTSIDE = (90, 200, 90)
INSIDE = (40, 40, 240)
TEXT_BG = (20, 20, 20)


def draw(frame: np.ndarray, zones: list[Zone], people: list[TrackedPerson], rule: RestrictedZoneRule,
         status: str, alerts: int) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    for z in zones:
        pts = np.array(z.to_pixels(w, h), dtype=np.int32)
        overlay = out.copy()
        cv2.fillPoly(overlay, [pts], ZONE)
        out = cv2.addWeighted(overlay, 0.18, out, 0.82, 0)
        cv2.polylines(out, [pts], True, ZONE, 2, cv2.LINE_AA)
        _label(out, z.name or z.id, tuple(pts[0]), ZONE)
    for p in people:
        inside = any(rule.is_inside(p.track_id, z.id) for z in zones)
        color = INSIDE if inside else OUTSIDE
        x1, y1, x2, y2 = (int(v) for v in p.box)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
        ax, ay = anchor_point(p.box, w, h, rule.anchor)
        cv2.circle(out, (int(ax * w), int(ay * h)), 4, color, -1, cv2.LINE_AA)
        _label(out, f"#{p.track_id} {p.score:.2f}", (x1, max(y1 - 4, 14)), color)
    _label(out, f"{status} | alerts sent: {alerts} | detections are possible, not confirmed", (8, h - 10), TEXT_BG)
    return out


def _label(img: np.ndarray, text: str, org: tuple[int, int], color: tuple[int, int, int]) -> None:
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    x, y = int(org[0]), int(org[1])
    cv2.rectangle(img, (x, y - th - base), (x + tw + 4, y + base - 2), color, -1)
    cv2.putText(img, text, (x + 2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)


class VideoSink:
    """Writes annotated frames to an .mp4 (review copy; stays on this machine, never in Git)."""

    def __init__(self, path: str, fps: float, size: tuple[int, int]) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps or 10.0, size)
        if not self._w.isOpened():
            raise RuntimeError(f"Could not open video writer for {path}")

    def write(self, frame: np.ndarray) -> None:
        self._w.write(frame)

    def close(self) -> None:
        self._w.release()
