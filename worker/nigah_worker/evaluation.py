"""Offline evaluation of detection + tracking + the restricted-zone rule. No API or Firestore needed.

    # 1) Run the detector once and cache every person box (slow part, ~1-2 min on CPU per minute of video)
    python -m nigah_worker.evaluation detect --video samples/vtest.avi --model models/yolo26n.pt

    # 2) Replay the cache through a tracker config + the zone rule, and score against ground truth (seconds)
    python -m nigah_worker.evaluation run --video samples/vtest.avi --model models/yolo26n.pt \
        --tracker config/trackers/bytetrack-nigah.yaml --truth eval/ground_truth/vtest.json --det-conf 0.10

`run --live` instead runs the full model per frame (needed for trackers that use ReID features).
The zones and rule settings come from the worker config (--config), so results match the real worker.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .config import WorkerConfig, load_config
from .detection import PERSON_CLASS_ID, TrackedPerson
from .rules import RestrictedZoneRule
from .zones import Zone, anchor_point

CACHE_CONF = 0.05  # lowest score kept in the cache; later runs can filter higher


# ---------------------------------------------------------------- detection cache
def cache_path(video: str, model: str, imgsz: int) -> Path:
    return Path("runtime/eval") / f"{Path(video).stem}__{Path(model).stem}__{imgsz}.npz"


def detect(video: str, model: str, imgsz: int, device: str) -> Path:
    from ultralytics import YOLO

    yolo = YOLO(model)
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    frames: list[np.ndarray] = []
    t0 = time.monotonic()
    while True:
        ok, img = cap.read()
        if not ok:
            break
        r = yolo.predict(img, classes=[PERSON_CLASS_ID], conf=CACHE_CONF, imgsz=imgsz,
                         device=None if device == "auto" else device, verbose=False)[0]
        frames.append(r.boxes.data.cpu().numpy().astype(np.float32))  # x1 y1 x2 y2 conf cls
        h, w = img.shape[:2]
    cap.release()
    secs = time.monotonic() - t0
    out = cache_path(video, model, imgsz)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, fps=fps, width=w, height=h, detect_seconds=secs,
                        counts=np.array([len(f) for f in frames]), boxes=np.concatenate(frames) if frames else np.zeros((0, 6)))
    print(f"Cached {len(frames)} frames ({sum(len(f) for f in frames)} boxes >= {CACHE_CONF}) in {secs:.1f}s "
          f"({len(frames) / secs:.1f} fps) -> {out}")
    return out


@dataclass
class Cache:
    fps: float
    width: int
    height: int
    detect_seconds: float
    frames: list[np.ndarray]
    video: str | None = None  # needed only by trackers that use the image (GMC / ReID)


def load_cache(path: Path, video: str | None = None) -> Cache:
    d = np.load(path)
    splits = np.cumsum(d["counts"])[:-1]
    return Cache(float(d["fps"]), int(d["width"]), int(d["height"]), float(d["detect_seconds"]),
                 np.split(d["boxes"], splits), video)


# ---------------------------------------------------------------- tracking
def load_tracker_cfg(path: str, overrides: dict[str, Any]):
    from ultralytics.utils import YAML, IterableSimpleNamespace
    from ultralytics.utils.checks import check_yaml

    cfg = IterableSimpleNamespace(**(YAML.load(check_yaml(path)) | overrides))
    cfg.device = "cpu"
    return cfg


def replay(cache: Cache, tracker_yaml: str, overrides: dict[str, Any], det_conf: float, stride: int = 1) -> list[list[TrackedPerson] | None]:
    """Feed cached detections (score >= det_conf) to an Ultralytics tracker exactly as model.track() would."""
    from ultralytics.engine.results import Boxes
    from ultralytics.trackers.track import TRACKER_MAP

    cfg = load_tracker_cfg(tracker_yaml, overrides)
    if getattr(cfg, "with_reid", False):
        raise SystemExit(f"{tracker_yaml} uses ReID features; evaluate it with --live")
    tracker = TRACKER_MAP[cfg.tracker_type](args=cfg)
    tracker.reset()
    blank = np.zeros((cache.height, cache.width, 3), np.uint8)
    needs_img = getattr(cfg, "gmc_method", "none") not in (None, "none")
    if needs_img and not cache.video:
        raise SystemExit(f"{tracker_yaml} needs the video frames (gmc_method); pass the cache's video")
    cap = cv2.VideoCapture(cache.video) if needs_img else None
    out: list[list[TrackedPerson] | None] = []
    for i, dets in enumerate(cache.frames):
        img = blank
        if cap is not None:
            ok, frame = cap.read()
            img = frame if ok else blank
        if i % stride:
            out.append(None)  # skipped, as the worker does with detector.frame_stride
            continue
        keep = dets[dets[:, 4] >= det_conf]
        tracks = tracker.update(Boxes(keep, (cache.height, cache.width)), img)
        out.append([TrackedPerson(int(t[4]), (float(t[0]), float(t[1]), float(t[2]), float(t[3])), float(t[5])) for t in tracks])
    return out


def live(video: str, model: str, imgsz: int, tracker_yaml: str, det_conf: float, device: str, stride: int = 1) -> tuple[list[list[TrackedPerson] | None], float]:
    from .detection import YoloPersonTracker

    t = YoloPersonTracker(model, device, det_conf, 0.5, imgsz, tracker_yaml)
    cap = cv2.VideoCapture(video)
    out, t0 = [], time.monotonic()
    while True:
        ok, img = cap.read()
        if not ok:
            break
        out.append(None if len(out) % stride else t.update(img))
    cap.release()
    return out, time.monotonic() - t0


# ---------------------------------------------------------------- rule + scoring
def apply_rule(tracks: list[list[TrackedPerson]], cfg: WorkerConfig, fps: float, width: int, height: int):
    zones = [Zone(z.id, z.name, tuple(z.points)) for z in cfg.zones]
    r = cfg.rule
    rule = RestrictedZoneRule(zones, r.min_score, r.confirm_frames, r.exit_frames, r.track_gap_seconds, r.reentry_cooldown_seconds, r.anchor)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    entries, inside = [], []
    for i, people in enumerate(tracks):
        if people is None:
            inside.append(set())
            continue
        for e in rule.update(people, t0 + timedelta(seconds=i / fps), width, height):
            box = next(p.box for p in people if p.track_id == e.track_id)
            ax, ay = anchor_point(box, width, height, r.anchor)
            entries.append({"frame": i, "zone_id": e.zone_id, "track_id": e.track_id, "score": e.score, "visit": e.visit,
                            "feet": [round(ax * width), round(ay * height)]})
        inside.append({p.track_id for p in people for z in zones if rule.is_inside(p.track_id, z.id)})
    return entries, inside


def _interp(keyframes: list[list[float]], frame: int) -> tuple[float, float] | None:
    kf = sorted(keyframes)
    if not kf or frame < kf[0][0] or frame > kf[-1][0]:
        return None
    for (f1, x1, y1), (f2, x2, y2) in zip(kf, kf[1:]):
        if f1 <= frame <= f2:
            a = 0 if f2 == f1 else (frame - f1) / (f2 - f1)
            return x1 + a * (x2 - x1), y1 + a * (y2 - y1)
    return kf[-1][1], kf[-1][2]


def score(entries: list[dict], tracks: list[list[TrackedPerson]], truth: dict, width: int, height: int, anchor: str) -> dict:
    """Assign each alert to the annotated person whose feet are nearest at that frame (within match_distance_px).

    Per person: 0 alerts = missed (if they truly entered), 1 = correct, more = duplicate alerts.
    Alerts near nobody, or on a person who never entered, are false alerts. Ambiguous people are ignored.
    """
    tol = truth.get("frame_tolerance", 15)
    max_px = truth.get("match_distance_px", 60)
    people = truth["people"]
    per_person: dict[str, list[dict]] = {p["id"]: [] for p in people}
    unassigned = []
    for e in entries:
        best, best_d = None, None
        for p in people:
            if p["zone_id"] != e["zone_id"]:
                continue
            kf = sorted(p["keyframes"])
            f = min(max(e["frame"], kf[0][0]), kf[-1][0]) if abs(e["frame"] - min(max(e["frame"], kf[0][0]), kf[-1][0])) <= tol else None
            pos = None if f is None else _interp(kf, f)
            d = None if pos is None else float(np.hypot(pos[0] - e["feet"][0], pos[1] - e["feet"][1]))
            if d is not None and d <= max_px and (best_d is None or d < best_d):
                best, best_d = p, d
        (per_person[best["id"]].append(e) if best else unassigned.append(e))
    status = {p["id"]: p.get("enters_zone") for p in people}
    entered = [pid for pid, s in status.items() if s is True]
    missed = [pid for pid in entered if not per_person[pid]]
    duplicates = [e for pid in entered for e in per_person[pid][1:]]
    false_alerts = unassigned + [e for pid, s in status.items() if s is False for e in per_person[pid]]
    matched = [{**per_person[pid][0], "truth": pid} for pid in entered if per_person[pid]]
    extra = duplicates + false_alerts
    unmatched_truth = set(missed)

    switches, lost, id_chains = 0, 0, {}
    for p in people:
        chain = []
        for f, x, y in sorted(p["keyframes"]):
            f = int(f)
            if f >= len(tracks):
                continue
            while tracks[f] is None:  # with a frame stride, use the last processed frame
                f -= 1
            cands = [(np.hypot(*(np.array(_feet(t.box, width, height, anchor)) - (x, y))), t.track_id) for t in tracks[f]]
            cands = [c for c in cands if c[0] <= max_px]
            if not cands:
                lost += 1
                continue
            tid = min(cands)[1]
            if chain and chain[-1] != tid:
                switches += 1
            if not chain or chain[-1] != tid:
                chain.append(tid)
        id_chains[p["id"]] = chain
    return {"true_entries": len(entered), "alerts": len(entries), "correct": len(matched), "missed": len(unmatched_truth),
            "extra": len(extra), "duplicates": len(duplicates), "false_alerts": len(false_alerts),
            "ignored_ambiguous": sum(len(per_person[pid]) for pid, s in status.items() if s == "ambiguous"),
            "id_switches": switches, "keyframes_lost": lost, "missed_people": sorted(unmatched_truth),
            "extra_alerts": extra, "matched": matched, "id_chains": id_chains}


def _feet(box, width, height, anchor) -> tuple[float, float]:
    ax, ay = anchor_point(box, width, height, anchor)
    return ax * width, ay * height


# ---------------------------------------------------------------- CLI
def _overrides(items: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        k, v = item.split("=", 1)
        out[k] = json.loads(v) if v not in ("True", "False") else v == "True"
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nigah_worker.evaluation")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect", help="run the detector once and cache all person boxes")
    r = sub.add_parser("run", help="track + zone rule + score against ground truth")
    for s in (d, r):
        s.add_argument("--video", required=True)
        s.add_argument("--model", default="models/yolo26s.pt")
        s.add_argument("--imgsz", type=int, default=640)
        s.add_argument("--device", default="cpu")
    r.add_argument("--config", default="config/worker.example.toml", help="worker config with zones and rule")
    r.add_argument("--tracker", default="config/trackers/bytetrack-nigah.yaml")
    r.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a tracker setting")
    r.add_argument("--det-conf", type=float, default=None, help="detector score passed to the tracker (default: config detector.confidence)")
    r.add_argument("--truth", help="ground-truth JSON to score against")
    r.add_argument("--stride", type=int, default=1, help="process every Nth frame, like detector.frame_stride")
    r.add_argument("--live", action="store_true", help="run the model per frame instead of the cache (for ReID trackers)")
    r.add_argument("--dump", help="write per-frame tracks, zone decisions and alerts to this JSONL file")
    r.add_argument("--json", action="store_true", help="print the result as one JSON line")
    a = p.parse_args(argv)

    if a.cmd == "detect":
        detect(a.video, a.model, a.imgsz, a.device)
        return 0

    cfg = load_config(a.config)
    det_conf = a.det_conf if a.det_conf is not None else cfg.detector.confidence
    t0 = time.monotonic()
    if a.live:
        cap = cv2.VideoCapture(a.video)
        fps, width, height = cap.get(cv2.CAP_PROP_FPS) or 10.0, int(cap.get(3)), int(cap.get(4))
        cap.release()
        tracks, model_secs = live(a.video, a.model, a.imgsz, a.tracker, det_conf, a.device, a.stride)
        n = len(tracks)
        speed = n / model_secs
    else:
        path = cache_path(a.video, a.model, a.imgsz)
        if not path.is_file():
            print(f"No detection cache at {path}. Run the 'detect' command first.", file=sys.stderr)
            return 2
        cache = load_cache(path, a.video)
        fps, width, height = cache.fps, cache.width, cache.height
        tracks = replay(cache, a.tracker, _overrides(a.set), det_conf, a.stride)
        n = len(tracks)
        track_secs = time.monotonic() - t0
        speed = n / (cache.detect_seconds + track_secs)  # estimated end-to-end frames per second
    entries, inside = apply_rule(tracks, cfg, fps, width, height)

    if a.dump:
        Path(a.dump).parent.mkdir(parents=True, exist_ok=True)
        by_frame = {e["frame"]: [] for e in entries}
        for e in entries:
            by_frame[e["frame"]].append(e)
        with open(a.dump, "w", encoding="utf-8") as fh:
            for i, people in enumerate(tracks):
                if people is None:
                    continue
                rows = [{"id": t.track_id, "box": [round(v, 1) for v in t.box], "score": round(t.score, 3),
                         "feet": [round(v) for v in _feet(t.box, width, height, cfg.rule.anchor)], "inside": t.track_id in inside[i]}
                        for t in people]
                fh.write(json.dumps({"frame": i, "tracks": rows, "alerts": by_frame.get(i, [])}) + "\n")

    result: dict[str, Any] = {"tracker": a.tracker, "overrides": _overrides(a.set), "det_conf": det_conf, "stride": a.stride,
                              "model": Path(a.model).name, "imgsz": a.imgsz, "frames": n, "fps_est": round(speed, 1),
                              "alerts": [(e["frame"], e["track_id"]) for e in entries]}
    if a.truth:
        truth = json.loads(Path(a.truth).read_text(encoding="utf-8"))
        s = score(entries, tracks, truth, width, height, cfg.rule.anchor)
        result |= {k: s[k] for k in ("true_entries", "correct", "missed", "extra", "duplicates", "false_alerts",
                                     "ignored_ambiguous", "id_switches", "keyframes_lost", "missed_people", "id_chains")}
        result["extra_alerts"] = [(e["frame"], e["track_id"]) for e in s["extra_alerts"]]
    if a.json:
        print(json.dumps(result))
    else:
        for k, v in result.items():
            print(f"{k:>15}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
