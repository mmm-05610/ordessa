"""Document-schema dialect and identity boundaries."""
from __future__ import annotations

import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from ordessa_engineering.methods.definitions.models import ResourceBytes, CapturedResource, SourceBundle, ParsedSourceBundle, ParsedContent, ParsedResource
from ordessa_engineering.methods.validation.schema import validate_document_schemas


def _diagnostics(schema: dict) -> set[str]:
    raw = json.dumps(schema, separators=(",", ":")).encode("utf-8")
    bundle = SourceBundle(ResourceBytes("method.yaml", "application/json", json.dumps({"resources": [
        {"id": "schema.test", "kind": "document_schema", "path": "schema.json", "media_type": "application/schema+json"}]}).encode()),
        (CapturedResource("schema.test", ResourceBytes("schema.json", "application/schema+json", raw)),))
    parsed = ParsedSourceBundle(bundle, ParsedContent(bundle.manifest_capture, json.loads(bundle.manifest_bytes)),
        (ParsedResource("schema.test", ParsedContent(bundle.resources[0].captured, schema)),))
    resource = parsed.resource_views["schema.test"]
    loaded = SimpleNamespace(resources={"schema.test": resource}, manifest={})

    return {item.code for item in validate_document_schemas(loaded)}


@pytest.mark.parametrize("identifier", [
    "https://ordessa.invalid/interfaces/example",
    "https://ordessa.invalid/design/interfaces/example",
    "urn:ordessa:schema:example",
])
def test_rejects_top_level_core_schema_ids(identifier: str) -> None:
    assert "SCHEMA_ID_RESERVED" in _diagnostics({"$id": identifier, "type": "object"})


@pytest.mark.parametrize("subschema", [
    {"$defs": {"owned": {"$id": "https://ordessa.invalid/interfaces/owned"}}},
    {"properties": {"owned": {"$id": "urn:ordessa:schema:owned"}}},
])
def test_rejects_core_ids_on_nested_schema_resources(subschema: dict) -> None:
    assert "SCHEMA_ID_RESERVED" in _diagnostics({"type": "object", **subschema})


def test_rejects_non_2020_12_dialect() -> None:
    codes = _diagnostics({
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
    })
    assert "SCHEMA_DRAFT_UNSUPPORTED" in codes


def test_accepts_default_2020_12_method_ids_and_literal_example_ids() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:ordessa:method:example-method",
        "type": "object",
        "default": {"$id": "urn:ordessa:schema:literal-data"},
        "examples": [{"$id": "https://ordessa.invalid/interfaces/literal-data"}],
        "$defs": {
            "local": {
                "$id": "urn:ordessa:method:example-method/local",
                "type": "string",
            },
        },
    }
    assert "SCHEMA_ID_RESERVED" not in _diagnostics(schema)
    assert "SCHEMA_DRAFT_UNSUPPORTED" not in _diagnostics(schema)


def test_missing_schema_dialect_uses_fixed_2020_12_default() -> None:
    codes = _diagnostics({"$id": "urn:ordessa:method:default-dialect", "type": "object"})
    assert "SCHEMA_DRAFT_UNSUPPORTED" not in codes
