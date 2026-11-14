import pytest

from nigah_worker.zones import Zone, anchor_point, point_in_polygon

SQUARE = ((0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6))
# Concave "L": a notch is cut out of the top-right corner.
L_SHAPE = ((0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (0.0, 1.0))


@pytest.mark.parametrize(("pt", "inside"), [
    ((0.4, 0.4), True), ((0.1, 0.4), False), ((0.7, 0.4), False), ((0.4, 0.1), False), ((0.4, 0.7), False),
    ((0.2, 0.4), True),  # on an edge
    ((0.6, 0.6), True),  # on a vertex
])
def test_square(pt, inside) -> None:
    assert point_in_polygon(pt, SQUARE) is inside


@pytest.mark.parametrize(("pt", "inside"), [((0.25, 0.25), True), ((0.75, 0.25), False), ((0.75, 0.75), True), ((0.25, 0.9), True)])
def test_concave_polygon(pt, inside) -> None:
    assert point_in_polygon(pt, L_SHAPE) is inside


def test_point_order_direction_does_not_matter() -> None:
    assert point_in_polygon((0.4, 0.4), tuple(reversed(SQUARE)))


def test_zone_pixels_and_contains() -> None:
    z = Zone("z", "Z", SQUARE)
    assert z.to_pixels(1000, 500) == [(200, 100), (600, 100), (600, 300), (200, 300)]
    assert z.contains(0.5, 0.5) and not z.contains(0.9, 0.9)


def test_anchor_uses_feet_by_default_and_clamps() -> None:
    assert anchor_point((100, 50, 200, 250), 1000, 500) == (0.15, 0.5)
    assert anchor_point((100, 50, 200, 250), 1000, 500, "center") == (0.15, 0.3)
    assert anchor_point((-10, 0, 10, 900), 1000, 500) == (0.0, 1.0)
