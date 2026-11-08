"""The published contract files and the API models must agree."""

import json

import jsonschema

from app.schemas.events import VisionEventV1
from app.schemas.incidents import Incident

from .conftest import CONTRACTS, load_example


def _schema() -> dict:
    return json.loads((CONTRACTS / "vision-event.v1.schema.json").read_text(encoding="utf-8"))


def test_example_event_matches_json_schema() -> None:
    jsonschema.Draft202012Validator(_schema(), format_checker=jsonschema.FormatChecker()).validate(load_example("vision-event.v1.restricted-zone-entry.json"))


def test_example_event_matches_api_model() -> None:
    VisionEventV1.model_validate(load_example("vision-event.v1.restricted-zone-entry.json"))


def test_required_fields_match_between_schema_and_model() -> None:
    model_required = {name for name, f in VisionEventV1.model_fields.items() if f.is_required()}
    assert set(_schema()["required"]) == model_required


def test_example_incident_matches_api_model() -> None:
    Incident.model_validate(load_example("incident.v1.json"))
