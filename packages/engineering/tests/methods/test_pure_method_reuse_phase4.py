from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, SchemaError

from ordessa_engineering.methods.loading import parsing
from ordessa_engineering.methods.validation import schema as schema_validation
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.methods.definitions.models import (
    CapturedResource, ParsedContent, ParsedResource, ParsedSourceBundle,
    ResourceBytes, SourceBundle,
)


def test_small_parse_reuses_work_and_returns_mutation_isolated_values(monkeypatch):
    parsing._parse_small_document.cache_clear()
    calls = 0
    original = parsing.decode_json

    def counted(text):
        nonlocal calls
        calls += 1
        return original(text)

    monkeypatch.setattr(parsing, "decode_json", counted)
    first = parsing.parse_document(b'{"items": [1]}', "application/json", "one.json")
    first["items"].append(2)
    second = parsing.parse_document(b'{"items": [1]}', "application/json", "one.json")
    assert second == {"items": [1]}
    assert calls == 1


def test_parse_cache_reuses_sixty_resource_bundle_and_evicts_at_fixed_bound(monkeypatch):
    parsing._parse_small_document.cache_clear()
    calls = 0
    original = parsing.decode_json

    def counted(text):
        nonlocal calls
        calls += 1
        return original(text)

    monkeypatch.setattr(parsing, "decode_json", counted)
    resources = [(json.dumps({"resource": index}).encode(), f"resource-{index}.json")
                 for index in range(60)]
    for _ in range(2):
        for raw, path in resources:
            parsing.parse_document(raw, "application/json", path)
    assert calls == 60

    extra = [(json.dumps({"extra": index}).encode(), f"extra-{index}.json")
             for index in range(69)]
    for raw, path in extra:
        parsing.parse_document(raw, "application/json", path)
    assert parsing._parse_small_document.cache_info().currsize == 128
    raw, path = resources[0]
    parsing.parse_document(raw, "application/json", path)
    assert calls == 130


def test_parse_cache_separates_path_depth_media_and_large_input():
    parsing._parse_small_document.cache_clear()
    raw = b'{"nested": {"n": 1}}'
    assert parsing.parse_document(raw, "application/json", "one.json", depth_limit=4)
    assert parsing.parse_document(raw, "application/json", "two.json", depth_limit=4)
    with pytest.raises(MethodFailure) as too_shallow:
        parsing.parse_document(raw, "application/json", "one.json", depth_limit=1)
    assert too_shallow.value.error.code == "STRUCTURE_TOO_DEEP"
    assert too_shallow.value.error.path == "one.json"
    with pytest.raises(MethodFailure) as other_path:
        parsing.parse_document(raw, "application/json", "two.json", depth_limit=1)
    assert other_path.value.error.code == "STRUCTURE_TOO_DEEP"
    assert other_path.value.error.path == "two.json"
    yaml_raw = b"nested: {n: 1}\n"
    assert parsing.parse_document(yaml_raw, "application/yaml", "same.yaml") == {"nested": {"n": 1}}
    same_bytes = b'{"kind": "object"}'
    assert parsing.parse_document(same_bytes, "text/plain", "same.data") == same_bytes.decode()
    assert parsing.parse_document(same_bytes, "application/json", "same.data") == {"kind": "object"}
    assert parsing._parse_small_document.cache_info().currsize == 5
    large = b" " * (parsing._PARSE_CACHE_MAX_BYTES + 1)
    assert parsing.parse_document(large, "text/plain", "large.txt").isspace()
    assert parsing._parse_small_document.cache_info().currsize == 5


def test_cached_parse_preserves_original_duplicate_key_error_and_does_not_cache_it():
    parsing._parse_small_document.cache_clear()
    raw = b"x: 1\nx: 2\n"
    for path in ("first.yaml", "second.yaml"):
        with pytest.raises(MethodFailure) as uncached:
            parsing._parse_small_document.__wrapped__(raw, "application/yaml", path, 64)
        with pytest.raises(MethodFailure) as failure:
            parsing.parse_document(raw, "application/yaml", path)
        assert failure.value.error == uncached.value.error
        assert failure.value.error.code == "DUPLICATE_KEY"
        assert failure.value.error.path is None
    assert parsing._parse_small_document.cache_info().currsize == 0


def _loaded_schemas(schemas: dict[str, tuple[str, dict]]):
    declarations = []
    captures = []
    parsed_resources = []
    for resource_id, (path, schema) in schemas.items():
        raw = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
        declarations.append({"id": resource_id, "kind": "document_schema", "path": path,
                             "media_type": "application/schema+json"})
        capture = ResourceBytes(path, "application/schema+json", raw)
        captures.append(CapturedResource(resource_id, capture))
        parsed_resources.append(ParsedResource(resource_id, ParsedContent(capture, schema)))
    manifest = {"resources": declarations}
    manifest_capture = ResourceBytes("method.json", "application/json",
                                     json.dumps(manifest).encode())
    bundle = SourceBundle(manifest_capture, tuple(captures))
    parsed = ParsedSourceBundle(bundle, ParsedContent(manifest_capture, manifest), tuple(parsed_resources))
    return SimpleNamespace(resources=parsed.resource_views, manifest={})


def test_static_schema_cache_does_not_cache_reference_closure_or_reserved_id_context():
    schema_validation._check_schema_bytes.cache_clear()
    root_schema = {"$ref": "target.json#/properties/name", "type": "object"}
    without_target = _loaded_schemas({"main": ("main.json", root_schema)})
    first = schema_validation.validate_document_schemas(without_target)
    assert [item.code for item in first] == ["REMOTE_SCHEMA_REF"]

    with_target = _loaded_schemas({
        "main": ("main.json", root_schema),
        "target": ("target.json", {"type": "object", "properties": {"name": {"type": "string"}}}),
    })
    assert schema_validation.validate_document_schemas(with_target) == []

    reserved = _loaded_schemas({
        "reserved": ("reserved.json", {"$id": "urn:ordessa:schema:reserved", "type": "object"}),
    })
    for _ in range(2):
        diagnostics = schema_validation.validate_document_schemas(reserved)
        assert [item.code for item in diagnostics] == ["SCHEMA_ID_RESERVED"]


def test_schema_success_cache_is_bounded_by_exact_capture_and_schema_bytes(monkeypatch):
    schema_validation._check_schema_bytes.cache_clear()
    calls = 0
    original = Draft202012Validator.check_schema

    def counted(schema):
        nonlocal calls
        calls += 1
        return original(schema)

    monkeypatch.setattr(Draft202012Validator, "check_schema", counted)
    content = json.dumps({"type": "object"}, separators=(",", ":")).encode()
    schema_validation._check_schema_bytes(b"capture-a", content)
    schema_validation._check_schema_bytes(b"capture-a", content)
    schema_validation._check_schema_bytes(b"capture-b", content)
    schema_validation._check_schema_bytes(b"capture-a", b'{"type":"array"}')
    assert calls == 3


def test_schema_rejections_are_not_cached():
    schema_validation._check_schema_bytes.cache_clear()
    invalid = b'{"type":"not-a-json-schema-type"}'
    for _ in range(2):
        with pytest.raises(SchemaError):
            schema_validation._check_schema_bytes(b"captured-invalid", invalid)
    assert schema_validation._check_schema_bytes.cache_info().currsize == 0
