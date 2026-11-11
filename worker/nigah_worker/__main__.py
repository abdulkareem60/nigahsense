"""Run the vision worker.

    python -m nigah_worker --config config/worker.example.toml [--show] [--annotated runtime/annotated.mp4]
                           [--source file|webcam|rtsp] [--video PATH] [--no-realtime] [--max-frames N] [--dry-run]

Ctrl+C stops cleanly: the current frame finishes, queued events get up to 15 s to send, and anything
unsent is saved to the outbox and re-sent on the next start.
"""

import argparse
import json
import logging
import signal
import sys
import threading

from pydantic import ValidationError

from .config import WorkerEnv, load_config
from .events import new_session_id
from .pipeline import EventLog, run_pipeline
from .publisher import EventApiClient, EventPublisher, SendResult
from .rules import RestrictedZoneRule
from .sources import SourceError, open_source
from .zones import Zone

log = logging.getLogger("nigah_worker")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="nigah_worker", description="NigahSense restricted-zone vision worker")
    p.add_argument("--config", default="config/worker.example.toml")
    p.add_argument("--source", choices=["file", "webcam", "rtsp"], help="override source.type")
    p.add_argument("--video", help="override source.path (implies --source file)")
    p.add_argument("--webcam-index", type=int, help="override source.device_index (implies --source webcam)")
    p.add_argument("--no-realtime", action="store_true", help="process a file as fast as possible")
    p.add_argument("--show", action="store_true", help="show a live annotated window (press q to stop)")
    p.add_argument("--annotated", help="save an annotated review video to this .mp4 path")
    p.add_argument("--max-frames", type=int, help="stop after N frames (quick checks)")
    p.add_argument("--dry-run", action="store_true", help="detect and log events but do not send them to the API")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        log.error("%s", e)
        return 2
    except (ValidationError, ValueError) as e:
        log.error("Invalid config %s:\n%s", args.config, e)
        return 2

    src = cfg.source
    if args.video:
        src = src.model_copy(update={"type": "file", "path": args.video})
    elif args.webcam_index is not None:
        src = src.model_copy(update={"type": "webcam", "device_index": args.webcam_index})
    elif args.source:
        src = src.model_copy(update={"type": args.source})
    if args.no_realtime:
        src = src.model_copy(update={"realtime": False})
    if src.type == "file" and not src.path:
        log.error("source.path is required for a file source")
        return 2

    env = WorkerEnv()
    stop = threading.Event()

    def _on_signal(signum, _frame) -> None:
        if stop.is_set():
            log.warning("Second interrupt: exiting immediately")
            raise SystemExit(130)
        log.info("Stopping (signal %s)...", signum)
        stop.set()

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_signal)  # Ctrl+Break on Windows
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    try:
        source = open_source(src, stop)
    except SourceError as e:
        log.error("%s", e)
        return 2

    from .detection import YoloPersonTracker

    try:
        d = cfg.detector
        tracker = YoloPersonTracker(d.model, d.device, d.confidence, d.iou, d.image_size, d.tracker)
    except Exception as e:  # missing/corrupt weights, bad device string, no network for first download
        log.error("Could not load detector %s: %s", cfg.detector.model, e)
        return 2

    zones = [Zone(z.id, z.name, tuple(z.points)) for z in cfg.zones]
    r = cfg.rule
    rule = RestrictedZoneRule(zones, r.min_score, r.confirm_frames, r.exit_frames, r.track_gap_seconds, r.reentry_cooldown_seconds, r.anchor)
    session_id = new_session_id()
    event_log = EventLog(cfg.output.event_log)

    publisher: EventPublisher | None = None
    if args.dry_run:
        def publish(_event: dict) -> None:
            return None
    else:
        try:
            client = EventApiClient(env.nigahsense_api_url, env.nigahsense_worker_key.get_secret_value(), env.nigahsense_request_timeout_seconds)
        except ValueError as e:
            log.error("%s Set it in worker/.env (see worker/.env.example) or use --dry-run.", e)
            return 2

        def on_result(event: dict, res: SendResult) -> None:
            if res.ok:
                log.info("API %s: %s", res.status, json.dumps(res.body))
            event_log.write({"type": "api_result", "event_id": event["event_id"], "ok": res.ok, "status": res.status, "body": res.body, "error": res.error})

        publisher = EventPublisher(client, cfg.output.outbox, max_attempts=env.nigahsense_max_send_attempts, on_result=on_result)
        publisher.start()
        replayed = publisher.replay_outbox()
        if replayed:
            log.info("Re-sending %d event(s) saved by a previous run", replayed)
        publish = publisher.publish

    log.info("Camera %s | source %s | detector %s | zones %s | session %s%s",
             cfg.camera.id, source.describe, tracker.describe(), [z.id for z in zones], session_id, " | DRY RUN" if args.dry_run else "")

    code = 0
    try:
        stats = run_pipeline(
            source.frames(), tracker, rule, publish, cfg.camera.id, session_id, stop,
            frame_stride=cfg.detector.frame_stride, event_log=event_log,
            annotated_path=args.annotated or cfg.output.annotated_video, show_window=args.show or cfg.output.show_window,
            fps_hint=lambda: source.fps, max_frames=args.max_frames,
        )
        log.info("Done: %d frames read, %d processed in %.1fs, up to %d people at once, %d event(s) emitted",
                 stats.frames_read, stats.frames_processed, stats.seconds, stats.max_people, len(stats.events))
    except SourceError as e:
        log.error("%s", e)
        code = 2
    finally:
        if publisher:
            publisher.close()
            log.info("Publisher: %d sent, %d failed or saved to %s", publisher.sent, publisher.failed, cfg.output.outbox)
    return code


if __name__ == "__main__":
    sys.exit(main())
