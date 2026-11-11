"""Restricted-zone entry rule: turns per-frame tracks into at most one entry event per visit.

For each (track, zone):
  * ENTRY is confirmed when the person's anchor point is inside the zone for `confirm_frames`
    consecutive processed frames, each with score >= `min_score`. One event is emitted then.
  * While the person stays inside, nothing more is emitted.
  * The person counts as LEFT after `exit_frames` consecutive frames outside (short jitter across
    the edge does not count).
  * A RE-ENTRY by the same track emits again only if `reentry_cooldown_seconds` have passed since
    that track's last event for this zone.
  * If a track is not seen for longer than `track_gap_seconds`, its state is dropped. A short
    occlusion (same track ID returns sooner) therefore does not create a new event.

Known limit: if the tracker gives the same person a NEW track ID (long occlusion, crowding), the
rule cannot tell, and a second event is possible. Improving tracker stability is the fix.
"""

from dataclasses import dataclass, field
from datetime import datetime

from .detection import TrackedPerson
from .zones import Zone, anchor_point


@dataclass(frozen=True)
class ZoneEntry:
    zone_id: str
    track_id: int
    occurred_at: datetime  # UTC time of the frame that confirmed entry
    score: float  # highest detector score during the confirmation frames
    visit: int  # 1 for the first entry of this track into this zone, 2 for a re-entry, ...


@dataclass
class _State:
    inside: bool = False
    in_streak: int = 0
    out_streak: int = 0
    streak_max_score: float = 0.0
    last_seen: datetime | None = None
    last_event_at: datetime | None = None
    visits: int = 0


@dataclass
class RestrictedZoneRule:
    zones: list[Zone]
    min_score: float = 0.40
    confirm_frames: int = 3
    exit_frames: int = 5
    track_gap_seconds: float = 5.0
    reentry_cooldown_seconds: float = 30.0
    anchor: str = "bottom_center"
    _states: dict[tuple[int, str], _State] = field(default_factory=dict, init=False, repr=False)

    def update(self, people: list[TrackedPerson], now: datetime, width: int, height: int) -> list[ZoneEntry]:
        events: list[ZoneEntry] = []
        for person in people:
            ax, ay = anchor_point(person.box, width, height, self.anchor)
            for zone in self.zones:
                st = self._states.setdefault((person.track_id, zone.id), _State())
                st.last_seen = now
                if zone.contains(ax, ay) and person.score >= self.min_score:
                    st.out_streak = 0
                    if st.inside:
                        continue
                    st.in_streak += 1
                    st.streak_max_score = max(st.streak_max_score, person.score)
                    if st.in_streak >= self.confirm_frames:
                        st.inside = True
                        cooled = st.last_event_at is None or (now - st.last_event_at).total_seconds() >= self.reentry_cooldown_seconds
                        if cooled:
                            st.visits += 1
                            st.last_event_at = now
                            events.append(ZoneEntry(zone.id, person.track_id, now, round(st.streak_max_score, 4), st.visits))
                else:
                    st.in_streak = 0
                    st.streak_max_score = 0.0
                    if st.inside:
                        st.out_streak += 1
                        if st.out_streak >= self.exit_frames:
                            st.inside = False
                            st.out_streak = 0
        self._forget_stale(now)
        return events

    def reset(self) -> None:
        self._states.clear()

    def is_inside(self, track_id: int, zone_id: str) -> bool:
        st = self._states.get((track_id, zone_id))
        return bool(st and st.inside)

    def _forget_stale(self, now: datetime) -> None:
        stale = [k for k, s in self._states.items() if s.last_seen and (now - s.last_seen).total_seconds() > self.track_gap_seconds]
        for k in stale:
            del self._states[k]
