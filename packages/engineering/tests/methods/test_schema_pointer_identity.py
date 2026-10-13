"""Reference identity counterexamples found by independent review."""
from ordessa_engineering.methods.validation.references import validate_schema_refs


def errors(schema):
    return validate_schema_refs(schema, resource_id="schema", path="schema.json")


def test_urn_resource_keeps_local_pointer_and_anchor_identity():
    schema = {"$id": "urn:ordessa:method:test:schema:1", "$defs": {
        "name": {"type": "string", "$anchor": "name"}}, "$ref": "#/$defs/name"}
    assert errors(schema) == []
    schema["$ref"] = "#name"
    assert errors(schema) == []


def test_fragment_is_percent_decoded_once():
    schema = {"$defs": {"a": {"b": {"type": "string"}}}, "$ref": "#/$defs/a%252Fb"}
    assert len(errors(schema)) == 1
    schema["$defs"]["a%2Fb"] = {"type": "integer"}
    assert errors(schema) == []
    schema["$ref"] = "#/$defs/a%2Fb"
    assert errors(schema) == []


def test_pointer_escape_and_array_tokens_are_exact():
    schema = {"$defs": {"items": [{"type": "string"}], "a~2b": {"type": "integer"}},
              "$ref": "#/$defs/items/01"}
    assert len(errors(schema)) == 1
    schema["$ref"] = "#/$defs/items/0"
    assert errors(schema) == []
    schema["$ref"] = "#/$defs/a~2b"
    assert len(errors(schema)) == 1
    schema["$ref"] = "#/$defs/a~02b"
    assert errors(schema) == []
