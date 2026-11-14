"""Regression test for the duplicate restricted-zone alert found on the sample video.

What happened (vtest.avi): person A walks beside person B and is hidden behind B at frames 559-566.
  1. YOLO26n only saw A's head and shoulders at low confidence (0.06-0.21), below the 0.35 detector
     threshold, so ByteTrack lost A for 5 frames and its motion prediction drifted away from A.
  2. When A reappeared half-hidden, the short box overlapped A's track too little, especially after
     ByteTrack's default fuse_score multiplied that overlap by the box's modest score.
  3. A new track ID was created and the zone rule (correctly, for a "new person") sent a second alert.
The fix is YOLO26s (keeps detecting the half-hidden person) plus config/trackers/bytetrack-nigah.yaml
(fuse_score off). Each alone was not robust in the evaluation.

The fixture holds real detector output for frames 500-719 (no video). These tests need Ultralytics
(and therefore PyTorch); they are skipped in the light test install.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ultralytics")

from nigah_worker.config import load_config  # noqa: E402
from nigah_worker.evaluation import Cache, replay  # noqa: E402
from nigah_worker.rules import RestrictedZoneRule  # noqa: E402
from nigah_worker.zones import Zone  # noqa: E402

WORKER = Path(__file__).resolve().parents[1]
NIGAH_TRACKER = str(WORKER / "config" / "trackers" / "bytetrack-nigah.yaml")
STOCK_TRACKER = "bytetrack.yaml"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "vtest_occlusion_detections.json").read_text(encoding="utf-8"))
FIRST = FIXTURE["first_frame"]
# Feet positions (frame, x, y) of person A, checked by eye: before the occlusion, after it, after A walks back.
A_BEFORE, A_AFTER, A_RETURN = (557, 188, 492), (575, 222, 477), (712, 346, 232)


def run(detections: str, tracker: str, det_conf: float = 0.35):
    frames = [np.array([r + [0.0] for r in f], dtype=np.float32).reshape(-1, 6) for f in FIXTURE["models"][detections]]
    cache = Cache(FIXTURE["fps"], FIXTURE["width"], FIXTURE["height"], 0.0, frames)
    tracks = replay(cache, tracker, {}, det_conf)
    cfg = load_config(WORKER / "config" / "worker.example.toml")
    r = cfg.rule
    rule = RestrictedZoneRule([Zone(z.id, z.name, tuple(z.points)) for z in cfg.zones], r.min_score, r.confirm_frames,
                              r.exit_frames, r.track_gap_seconds, r.reentry_cooldown_seconds, r.anchor)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    alerts = [e for i, people in enumerate(tracks)
              for e in rule.update(people, t0 + timedelta(seconds=i / FIXTURE["fps"]), FIXTURE["width"], FIXTURE["height"])]
    return tracks, alerts


def ids_of_a(tracks) -> set[int]:
    out = set()
    for frame, x, y in (A_BEFORE, A_AFTER, A_RETURN):
        people = tracks[frame - FIRST]
        best = min(people, key=lambda p: np.hypot((p.box[0] + p.box[2]) / 2 - x, p.box[3] - y))
        assert np.hypot((best.box[0] + best.box[2]) / 2 - x, best.box[3] - y) < 30, f"no track near person A at frame {frame}"
        out.add(best.track_id)
    return out


@pytest.mark.parametrize("detections", ["yolo26s_640", "yolo26s_512"])
def test_fixed_setup_sends_one_alert_per_person(detections) -> None:
    tracks, alerts = run(detections, NIGAH_TRACKER)
    assert len(alerts) == 2, [(a.track_id, a.occurred_at) for a in alerts]
    assert len({a.track_id for a in alerts}) == 2
    assert len(ids_of_a(tracks)) == 1, "person A changed track ID"


def test_original_failure_is_still_in_the_fixture() -> None:
    """Guards the fixture: yolo26n + stock ByteTrack must still give the duplicate, or the tests above prove nothing."""
    tracks, alerts = run("yolo26n_640", STOCK_TRACKER)
    assert len(alerts) == 3
    assert len(ids_of_a(tracks)) > 1


def test_detector_alone_is_not_enough_at_512px() -> None:
    """yolo26s @512 with stock fuse_score still duplicated: the tracker change is part of the fix."""
    _, alerts = run("yolo26s_512", STOCK_TRACKER)
    assert len(alerts) == 3


def test_tracker_change_alone_is_not_enough_with_yolo26n() -> None:
    """With yolo26n, A is lost for 5 frames; fuse_score off cannot bridge that, so the detector change is needed too."""
    _, alerts = run("yolo26n_640", NIGAH_TRACKER)
    assert len(alerts) == 3


def test_example_config_uses_the_fixed_setup() -> None:
    cfg = load_config(WORKER / "config" / "worker.example.toml")
    assert Path(cfg.detector.model).stem == "yolo26s"
    assert Path(cfg.detector.tracker).name == "bytetrack-nigah.yaml"
    assert cfg.detector.frame_stride == 1  # stride 2 brought duplicates back in the evaluation
