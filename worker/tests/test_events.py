"""Worker payloads must satisfy contracts/vision-event.v1.schema.json and the API model."""

import re
import uuid
from datetime import UTC, datetime, timedelta, timezone

import jsonschema
import pytest

from nigah_worker.events import build_event, idempotency_key, new_session_id, utc_rfc3339
from nigah_worker.rules import ZoneEntry

PKT = timezone(timedelta(hours=5))


def entry(**kw) -> ZoneEntry:
    base = dict(zone_id="zone-south-lawn", track_id=49, occurred_at=datetime(2026, 11, 11, 11, 18, 5, 123456, tzinfo=PKT), score=0.8612, visit=1)
    return ZoneEntry(**(base | kw))


def test_payload_matches_contract_schema_and_api_model(event_schema, api_event_model) -> None:
    ev = build_event(entry(), "cam-demo-plaza", "s20261111061700ab12")
    jsonschema.Draft202012Validator(event_schema, format_checker=jsonschema.FormatChecker()).validate(ev)
    parsed = api_event_model.model_validate(ev)
    assert parsed.camera_id == "cam-demo-plaza" and parsed.zone_id == "zone-south-lawn" and parsed.track_id == 49


def test_payload_fields() -> None:
    ev = build_event(entry(), "cam-demo-plaza", "s20261111061700ab12")
    assert ev["schema_version"] == "1.0" and ev["event_type"] == "restricted_zone_entry"
    assert uuid.UUID(ev["event_id"]).version == 4
    assert ev["occurred_at"] == "2026-11-11T06:18:05.123Z"  # converted from PKT to UTC
    assert ev["detection_score"] == 0.8612
    assert "evidence" not in ev  # media upload not implemented: no invented URLs


def test_each_event_gets_a_new_event_id() -> None:
    a, b = (build_event(entry(), "cam-demo-plaza", "s1aaaaaaaa") for _ in range(2))
    assert a["event_id"] != b["event_id"] and a["idempotency_key"] == b["idempotency_key"]


def test_idempotency_key_is_stable_and_follows_contract(event_schema) -> None:
    k1 = idempotency_key("cam-demo-plaza", "zone-south-lawn", "s20261111061700ab12", 49, 1)
    assert k1 == "cam-demo-plaza:zone-south-lawn:s20261111061700ab12:49:restricted_zone_entry"
    k2 = idempotency_key("cam-demo-plaza", "zone-south-lawn", "s20261111061700ab12", 49, 2)
    assert k2 == k1 + ".v2"
    pattern = re.compile(event_schema["properties"]["idempotency_key"]["pattern"])
    assert pattern.match(k1) and pattern.match(k2)


def test_session_ids_differ_between_runs_and_are_key_safe() -> None:
    now = datetime(2026, 11, 11, 6, 0, tzinfo=UTC)
    a, b = new_session_id(now), new_session_id(now)
    assert a != b and re.fullmatch(r"s\d{14}[0-9a-f]{4}", a)


def test_naive_timestamps_are_refused() -> None:
    with pytest.raises(ValueError):
        utc_rfc3339(datetime(2026, 11, 11, 6, 0))


@pytest.mark.parametrize("score", [-0.1, 1.7])
def test_score_is_clamped_to_contract_range(score, api_event_model) -> None:
    api_event_model.model_validate(build_event(entry(score=score), "cam-demo-plaza", "s1aaaaaaaa"))
