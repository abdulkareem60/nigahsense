"""Scoring rules of the offline evaluation (no model needed)."""

from nigah_worker.detection import TrackedPerson
from nigah_worker.evaluation import score

TRUTH = {
    "frame_tolerance": 15, "match_distance_px": 60,
    "people": [
        {"id": "P", "zone_id": "z", "enters_zone": True, "enter_frame": 10, "keyframes": [[0, 100, 400], [40, 200, 400]]},
        {"id": "Q", "zone_id": "z", "enters_zone": True, "enter_frame": 10, "keyframes": [[0, 500, 400], [40, 500, 400]]},
        {"id": "E", "zone_id": "z", "enters_zone": "ambiguous", "enter_frame": 10, "keyframes": [[0, 700, 100], [40, 700, 100]]},
        {"id": "O", "zone_id": "z", "enters_zone": False, "keyframes": [[0, 300, 100], [40, 300, 100]]},
    ],
}


def alert(frame, x, y, track=1):
    return {"frame": frame, "zone_id": "z", "track_id": track, "feet": [x, y]}


def tracks_for(n=41, ids=None):
    ids = ids or {}
    out = []
    for f in range(n):
        x = 100 + 100 * f / 40
        tid = ids.get(f, 1)
        out.append([TrackedPerson(tid, (x - 10, 300, x + 10, 400), 0.9), TrackedPerson(2, (490, 300, 510, 400), 0.9)])
    return out


def test_one_alert_per_person_is_correct() -> None:
    s = score([alert(10, 125, 400), alert(12, 500, 400, 2)], tracks_for(), TRUTH, 768, 576, "bottom_center")
    assert (s["correct"], s["missed"], s["duplicates"], s["false_alerts"]) == (2, 0, 0, 0)


def test_second_alert_for_same_person_is_a_duplicate() -> None:
    s = score([alert(10, 125, 400), alert(30, 175, 400, 9), alert(12, 500, 400, 2)], tracks_for(), TRUTH, 768, 576, "bottom_center")
    assert (s["correct"], s["duplicates"], s["false_alerts"]) == (2, 1, 0)


def test_missed_person_and_false_alerts() -> None:
    s = score([alert(10, 125, 400), alert(10, 300, 100, 5), alert(10, 40, 40, 6)], tracks_for(), TRUTH, 768, 576, "bottom_center")
    assert s["missed_people"] == ["Q"] and s["false_alerts"] == 2  # one on a non-entering person, one near nobody


def test_ambiguous_person_is_ignored() -> None:
    s = score([alert(10, 125, 400), alert(12, 500, 400, 2), alert(20, 700, 100, 7)], tracks_for(), TRUTH, 768, 576, "bottom_center")
    assert (s["false_alerts"], s["ignored_ambiguous"]) == (0, 1)


def test_id_switch_is_counted_from_keyframes() -> None:
    s = score([], tracks_for(ids={f: 3 for f in range(25, 41)}), TRUTH, 768, 576, "bottom_center")
    assert s["id_chains"]["P"] == [1, 3] and s["id_switches"] == 1
