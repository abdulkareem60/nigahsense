"""Video file handling and a full pipeline run with a scripted tracker (no model needed)."""

import threading
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from nigah_worker.config import SourceConfig, load_config
from nigah_worker.detection import TrackedPerson
from nigah_worker.pipeline import EventLog, run_pipeline
from nigah_worker.rules import RestrictedZoneRule
from nigah_worker.sources import FileSource, RtspSource, SourceError, _redact, open_source
from nigah_worker.zones import Zone

W, H = 160, 120


@pytest.fixture
def video(tmp_path) -> Path:
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (W, H))
    for i in range(20):
        writer.write(np.full((H, W, 3), i * 10, dtype=np.uint8))
    writer.release()
    return path


def test_missing_file_is_a_clear_error(tmp_path) -> None:
    with pytest.raises(SourceError, match="not found"):
        FileSource(str(tmp_path / "nope.mp4"))


def test_unreadable_file_is_a_clear_error(tmp_path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video")
    with pytest.raises(SourceError):
        list(FileSource(str(bad), realtime=False).frames())


def test_reads_to_end_with_increasing_utc_timestamps(video) -> None:
    frames = list(FileSource(str(video), realtime=False).frames())
    assert len(frames) == 20 and [f.index for f in frames] == list(range(20))
    times = [f.captured_at for f in frames]
    assert all(t.tzinfo is UTC for t in times) and times == sorted(times)
    assert times[-1] <= datetime.now(UTC)  # never in the future, even when read faster than real time


def test_loop_marks_restart_and_stops_on_request(video) -> None:
    stop = threading.Event()
    seen = []
    for f in FileSource(str(video), realtime=False, loop=True, stop=stop).frames():
        seen.append(f)
        if len(seen) == 45:
            stop.set()
    assert len(seen) == 45
    assert [f.index for f in seen if f.restarted] == [20, 40]


def test_rtsp_requires_url_env_and_redacts_credentials(monkeypatch) -> None:
    monkeypatch.delenv("NIGAHSENSE_RTSP_URL", raising=False)
    with pytest.raises(SourceError, match="NIGAHSENSE_RTSP_URL"):
        RtspSource(SourceConfig(type="rtsp"))
    assert _redact("rtsp://admin:hunter2@10.0.0.5:554/stream1") == "rtsp://***@10.0.0.5:554/stream1"


def test_example_config_is_valid() -> None:
    cfg = load_config(Path(__file__).resolve().parents[1] / "config" / "worker.example.toml")
    assert cfg.source.type == "file" and cfg.zones and cfg.camera.id


class ScriptedTracker:
    """Person walks from the left half into the right half and stays there."""

    def __init__(self) -> None:
        self.calls = 0
        self.resets = 0

    def update(self, frame: np.ndarray) -> list[TrackedPerson]:
        x = 30 if self.calls < 5 else 120
        self.calls += 1
        return [TrackedPerson(4, (x - 5, 40, x + 5, 100), 0.83)]

    def reset(self) -> None:
        self.resets += 1


def test_pipeline_sends_one_event_for_one_person_entering(video, tmp_path, api_event_model) -> None:
    zone = Zone("zone-right", "Right", ((0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)))
    sent = []
    stats = run_pipeline(
        FileSource(str(video), realtime=False).frames(), ScriptedTracker(), RestrictedZoneRule([zone]), sent.append,
        "cam-test", "s20261111000000abcd", threading.Event(), event_log=EventLog(str(tmp_path / "events.jsonl")),
        annotated_path=str(tmp_path / "out.mp4"),
    )
    assert stats.frames_processed == 20 and len(sent) == 1
    ev = api_event_model.model_validate(sent[0])
    assert (ev.camera_id, ev.zone_id, ev.track_id) == ("cam-test", "zone-right", 4)
    assert (tmp_path / "events.jsonl").read_text().count("event_emitted") == 1
    assert (tmp_path / "out.mp4").stat().st_size > 0


def test_open_source_dispatch(video) -> None:
    assert isinstance(open_source(SourceConfig(type="file", path=str(video))), FileSource)
