"""API client and publisher: retries, permanent failures, outage handling, outbox replay."""

import json
import threading

import httpx
import pytest

from nigah_worker.publisher import EventApiClient, EventPublisher

EVENT = {"event_id": "0f4c2b7e-6a1d-4d3a-9a8e-3b2f1c9d7e55", "idempotency_key": "cam:zone:s1:1:restricted_zone_entry"}


class FakeApi:
    """Plays back a script of responses; each item is a status code or an exception."""

    def __init__(self, script):
        self.script = list(script)
        self.requests: list[httpx.Request] = []
        self.lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.requests.append(request)
            step = self.script.pop(0) if self.script else 201
        if isinstance(step, Exception):
            raise step
        body = {"outcome": "created" if step == 201 else "duplicate"} if step in (200, 201) else {"error": {"code": "x"}}
        return httpx.Response(step, json=body)

    def bodies(self):
        return [json.loads(r.content) for r in self.requests]


def make(api: FakeApi, tmp_path, **kw):
    client = EventApiClient("http://api.test", "secret-key", transport=httpx.MockTransport(api))
    results = []
    pub = EventPublisher(client, tmp_path / "outbox.jsonl", sleep=lambda _s: None, on_result=lambda e, r: results.append(r), **kw)
    return pub, results


def outbox(tmp_path):
    p = tmp_path / "outbox.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def test_client_sends_worker_key_and_json(tmp_path) -> None:
    api = FakeApi([201])
    pub, _ = make(api, tmp_path)
    pub.start(); pub.publish(EVENT); pub.close()
    req = api.requests[0]
    assert req.url.path == "/v1/events" and req.headers["X-Worker-Key"] == "secret-key"
    assert api.bodies() == [EVENT]


def test_empty_worker_key_is_refused() -> None:
    with pytest.raises(ValueError):
        EventApiClient("http://api.test", "")


def test_retries_connection_errors_and_5xx_with_the_same_event_id(tmp_path) -> None:
    api = FakeApi([httpx.ConnectError("refused"), 503, httpx.ReadTimeout("slow"), 429, 201])
    pub, results = make(api, tmp_path)
    pub.start(); pub.publish(EVENT); pub.close()
    assert len(api.requests) == 5
    assert {b["event_id"] for b in api.bodies()} == {EVENT["event_id"]}
    assert pub.sent == 1 and pub.failed == 0 and results[-1].status == 201
    assert outbox(tmp_path) == []


def test_duplicate_reply_counts_as_delivered(tmp_path) -> None:
    pub, results = make(FakeApi([200]), tmp_path)
    pub.start(); pub.publish(EVENT); pub.close()
    assert pub.sent == 1 and results[0].body == {"outcome": "duplicate"}


@pytest.mark.parametrize("status", [401, 409, 422])
def test_permanent_errors_are_not_retried_and_kept_for_inspection(tmp_path, status) -> None:
    api = FakeApi([status])
    pub, _ = make(api, tmp_path)
    pub.start(); pub.publish(EVENT); pub.close()
    assert len(api.requests) == 1 and pub.failed == 1
    [rec] = outbox(tmp_path)
    assert rec["event"] == EVENT and rec["retryable"] is False


def test_long_outage_saves_event_to_outbox_after_max_attempts(tmp_path) -> None:
    api = FakeApi([httpx.ConnectError("down")] * 10)
    pub, _ = make(api, tmp_path, max_attempts=3)
    pub.start(); pub.publish(EVENT); pub.close()
    assert len(api.requests) == 3 and pub.sent == 0
    [rec] = outbox(tmp_path)
    assert rec["event"] == EVENT and rec["retryable"] is True


def test_replay_resends_retryable_events_and_keeps_rejected_ones(tmp_path) -> None:
    rejected = {"event": {"event_id": "bad"}, "reason": "HTTP 422", "retryable": False}
    pending = {"event": EVENT, "reason": "down", "retryable": True}
    (tmp_path / "outbox.jsonl").write_text(json.dumps(rejected) + "\n" + json.dumps(pending) + "\n")
    api = FakeApi([200])
    pub, _ = make(api, tmp_path)
    pub.start()
    assert pub.replay_outbox() == 1
    pub.close()
    assert api.bodies() == [EVENT] and pub.sent == 1
    assert outbox(tmp_path) == [rejected]


def test_shutdown_during_outage_saves_unsent_events(tmp_path) -> None:
    gate = threading.Event()

    def blocked(_req):
        gate.wait(5)
        raise httpx.ConnectError("down")

    client = EventApiClient("http://api.test", "k", transport=httpx.MockTransport(blocked))
    pub = EventPublisher(client, tmp_path / "outbox.jsonl", max_attempts=50, base_delay=10)
    pub.start()
    for i in range(3):
        pub.publish({**EVENT, "event_id": f"e{i}"})
    gate.set()
    pub.close(timeout=0.5)  # gives up waiting quickly, as on Ctrl+C
    saved = sorted(r["event"]["event_id"] for r in outbox(tmp_path))
    assert saved == ["e0", "e1", "e2"]
