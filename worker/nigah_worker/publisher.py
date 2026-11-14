"""Sends events to POST /v1/events without blocking video processing.

* A background thread sends queued events in order.
* Retryable failures (connection errors, timeouts, HTTP 429 and 5xx) are retried with exponential
  backoff and jitter, reusing the SAME event_id, so the API treats a retry as a duplicate.
* Permanent failures (other 4xx, e.g. 401 bad key, 422 invalid event, 409 key conflict) are not
  retried; they are logged and written to the outbox with the error for a person to inspect.
* Events still unsent at shutdown, or after max attempts, are appended to an outbox JSONL file.
  On the next start, `replay_outbox()` re-queues them; event_id reuse keeps that safe.
"""

import json
import logging
import queue
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("nigah_worker.publisher")

SUCCESS = {200, 201}


@dataclass
class SendResult:
    ok: bool
    retryable: bool
    status: int | None
    body: Any = None
    error: str | None = None


class EventApiClient:
    """One HTTP attempt. Holds no retry logic so it is easy to test and replace."""

    def __init__(self, base_url: str, worker_key: str, timeout: float = 10.0, transport: httpx.BaseTransport | None = None) -> None:
        if not worker_key:
            raise ValueError("NIGAHSENSE_WORKER_KEY is empty; the API will refuse events without it.")
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
                                    headers={"X-Worker-Key": worker_key, "User-Agent": "nigahsense-worker/0.1"})

    def send(self, event: dict[str, Any]) -> SendResult:
        try:
            r = self._client.post("/v1/events", json=event)
        except httpx.TimeoutException as e:
            return SendResult(False, True, None, error=f"timeout: {e}")
        except httpx.TransportError as e:
            return SendResult(False, True, None, error=f"connection failed: {e}")
        try:
            body = r.json()
        except ValueError:
            body = r.text[:500]
        if r.status_code in SUCCESS:
            return SendResult(True, False, r.status_code, body)
        retryable = r.status_code == 429 or r.status_code >= 500
        return SendResult(False, retryable, r.status_code, body, error=f"HTTP {r.status_code}")

    def close(self) -> None:
        self._client.close()


class EventPublisher:
    def __init__(self, client: EventApiClient, outbox_path: str | Path, max_attempts: int = 8,
                 base_delay: float = 0.5, max_delay: float = 30.0, sleep: Callable[[float], None] | None = None,
                 on_result: Callable[[dict[str, Any], SendResult], None] | None = None) -> None:
        self._client = client
        self._outbox = Path(outbox_path)
        self._max_attempts = max_attempts
        self._base = base_delay
        self._max = max_delay
        self._stop = threading.Event()
        self._sleep = sleep or self._stop.wait  # waiting on the stop event makes shutdown immediate
        self._on_result = on_result
        self._q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="event-publisher", daemon=True)
        self.sent = 0
        self.failed = 0

    # -- public ---------------------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    def publish(self, event: dict[str, Any]) -> None:
        self._q.put(event)

    def replay_outbox(self) -> int:
        """Re-queue events left over from a previous run. Returns how many were queued."""
        if not self._outbox.is_file():
            return 0
        events, keep = [], []
        for line in self._outbox.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                (events.append(rec["event"]) if rec.get("retryable", True) else keep.append(line))
        # Rejected events stay in the file for a person to inspect; retryable ones are re-queued.
        if keep:
            self._outbox.write_text("\n".join(keep) + "\n", encoding="utf-8")
        else:
            self._outbox.unlink()
        for e in events:
            self.publish(e)
        return len(events)

    def close(self, timeout: float = 15.0) -> None:
        """Try to send what is queued for up to `timeout` seconds, then save the rest to the outbox."""
        self._q.put(None)
        self._thread.join(timeout)
        if self._thread.is_alive():
            self._stop.set()
            self._thread.join(5)
        while True:
            try:
                e = self._q.get_nowait()
            except queue.Empty:
                break
            if e is not None:
                self._save(e, "not sent before shutdown", retryable=True)
        self._client.close()

    # -- internals ------------------------------------------------------------
    def _run(self) -> None:
        while True:
            event = self._q.get()
            if event is None:
                return
            self._deliver(event)
            if self._stop.is_set():
                return

    def _deliver(self, event: dict[str, Any]) -> None:
        for attempt in range(1, self._max_attempts + 1):
            res = self._client.send(event)
            if res.ok:
                self.sent += 1
                self._report(event, res)
                return
            if not res.retryable:
                self.failed += 1
                log.error("Event %s rejected (%s): %s", event.get("event_id"), res.error, res.body)
                self._save(event, f"{res.error}: {res.body}", retryable=False)
                self._report(event, res)
                return
            if self._stop.is_set() or attempt == self._max_attempts:
                break
            delay = min(self._max, self._base * 2 ** (attempt - 1)) * (0.5 + random.random() / 2)
            log.warning("Send failed (%s), attempt %d/%d; retrying in %.1fs", res.error, attempt, self._max_attempts, delay)
            self._sleep(delay)
        self.failed += 1
        log.error("Giving up on event %s for now; saved to %s", event.get("event_id"), self._outbox)
        self._save(event, res.error or "unknown", retryable=True)
        self._report(event, res)

    def _report(self, event: dict[str, Any], res: SendResult) -> None:
        if self._on_result:
            self._on_result(event, res)

    def _save(self, event: dict[str, Any], reason: str, retryable: bool) -> None:
        self._outbox.parent.mkdir(parents=True, exist_ok=True)
        with self._outbox.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": event, "reason": reason, "retryable": retryable}) + "\n")
