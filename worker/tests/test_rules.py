"""Entry confirmation, no repeat alerts while inside, exit hysteresis, tracking gaps, re-entry cooldown."""

from datetime import UTC, datetime, timedelta

from nigah_worker.detection import TrackedPerson
from nigah_worker.rules import RestrictedZoneRule
from nigah_worker.zones import Zone

W, H = 1000, 1000
ZONE = Zone("zone-a", "A", ((0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)))  # right half
T0 = datetime(2026, 11, 11, 6, 0, 0, tzinfo=UTC)


def person(track: int, inside: bool, score: float = 0.9) -> TrackedPerson:
    x = 750 if inside else 250
    return TrackedPerson(track, (x - 20, 400, x + 20, 600), score)  # feet at y=600


def rule(**kw) -> RestrictedZoneRule:
    defaults = dict(min_score=0.4, confirm_frames=3, exit_frames=3, track_gap_seconds=2.0, reentry_cooldown_seconds=10.0)
    return RestrictedZoneRule([ZONE], **(defaults | kw))


def play(r: RestrictedZoneRule, frames: list[list[TrackedPerson]], fps: float = 10.0, start: datetime = T0):
    out = []
    for i, people in enumerate(frames):
        out += r.update(people, start + timedelta(seconds=i / fps), W, H)
    return out


def test_entry_needs_confirm_frames_then_fires_once() -> None:
    r = rule()
    events = play(r, [[person(1, False)]] * 3 + [[person(1, True)]] * 2)
    assert events == []  # only 2 frames inside so far
    events = play(r, [[person(1, True)]], start=T0 + timedelta(seconds=1))
    assert len(events) == 1
    e = events[0]
    assert (e.zone_id, e.track_id, e.visit, e.score) == ("zone-a", 1, 1, 0.9)


def test_standing_inside_for_a_long_time_alerts_only_once() -> None:
    events = play(rule(), [[person(7, True)]] * 600)  # one minute at 10 fps
    assert len(events) == 1


def test_brief_flicker_outside_is_not_an_exit() -> None:
    frames = [[person(1, True)]] * 5 + [[person(1, False)]] * 2 + [[person(1, True)]] * 5
    assert len(play(rule(reentry_cooldown_seconds=0), frames)) == 1


def test_short_tracking_gap_does_not_create_a_new_alert() -> None:
    frames = [[person(1, True)]] * 5 + [[]] * 10 + [[person(1, True)]] * 5  # lost for 1 s < 2 s gap
    assert len(play(rule(reentry_cooldown_seconds=0), frames)) == 1


def test_long_gap_forgets_track_and_alerts_again_with_visit_1() -> None:
    frames = [[person(1, True)]] * 5 + [[]] * 40 + [[person(1, True)]] * 5  # lost for 4 s > 2 s gap
    events = play(rule(reentry_cooldown_seconds=0), frames)
    assert [e.visit for e in events] == [1, 1]  # same idempotency key -> the API merges it into the same incident


def test_reentry_within_cooldown_is_suppressed() -> None:
    frames = [[person(1, True)]] * 5 + [[person(1, False)]] * 5 + [[person(1, True)]] * 5  # back after 1 s
    assert len(play(rule(reentry_cooldown_seconds=10), frames)) == 1


def test_reentry_after_cooldown_alerts_with_next_visit_number() -> None:
    frames = [[person(1, True)]] * 5 + [[person(1, False)]] * 120 + [[person(1, True)]] * 5  # back after ~12 s
    events = play(rule(reentry_cooldown_seconds=10, track_gap_seconds=60), frames)
    assert [e.visit for e in events] == [1, 2]


def test_low_score_frames_do_not_count() -> None:
    assert play(rule(), [[person(1, True, score=0.3)]] * 20) == []


def test_two_people_each_alert_once() -> None:
    events = play(rule(), [[person(1, True), person(2, True), person(3, False)]] * 30)
    assert sorted(e.track_id for e in events) == [1, 2]


def test_score_is_highest_during_confirmation() -> None:
    frames = [[person(1, True, 0.5)], [person(1, True, 0.8)], [person(1, True, 0.6)]]
    assert play(rule(), frames)[0].score == 0.8


def test_reset_forgets_everything() -> None:
    r = rule()
    play(r, [[person(1, True)]] * 5)
    r.reset()
    assert len(play(r, [[person(1, True)]] * 5, start=T0 + timedelta(seconds=1))) == 1
