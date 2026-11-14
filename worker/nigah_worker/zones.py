"""Restricted-zone geometry. Pure functions; no OpenCV or model needed."""

from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    points: tuple[Point, ...]  # normalised (x, y), 0..1, origin top-left

    def to_pixels(self, width: int, height: int) -> list[tuple[int, int]]:
        return [(round(x * width), round(y * height)) for x, y in self.points]

    def contains(self, x: float, y: float) -> bool:
        """True if the normalised point is inside the polygon or on its edge."""
        return point_in_polygon((x, y), self.points)


def point_in_polygon(p: Point, polygon: Sequence[Point]) -> bool:
    """Ray casting. Points exactly on an edge or vertex count as inside."""
    x, y = p
    n = len(polygon)
    inside = False
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if _on_segment(x, y, x1, y1, x2, y2):
            return True
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def _on_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float, eps: float = 1e-9) -> bool:
    cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
    if abs(cross) > eps:
        return False
    return min(x1, x2) - eps <= px <= max(x1, x2) + eps and min(y1, y2) - eps <= py <= max(y1, y2) + eps


def anchor_point(box_xyxy: tuple[float, float, float, float], width: int, height: int, mode: str = "bottom_center") -> Point:
    """Normalised point that represents where a person is. Feet (bottom centre) suit floor zones."""
    x1, y1, x2, y2 = box_xyxy
    cx = (x1 + x2) / 2
    cy = y2 if mode == "bottom_center" else (y1 + y2) / 2
    return (min(max(cx / width, 0.0), 1.0), min(max(cy / height, 0.0), 1.0))
