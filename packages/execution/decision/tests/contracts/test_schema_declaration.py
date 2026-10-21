"""The packaged JSON schemas are produced by the single declaration generator.

`definitions.schemas.json_schema` is a **schema-declaration/build tool**: it turns
a DTO into a draft 2020-12 JSON schema. The packaged
`definitions/{request,result}.schema.json` are its build output, so a test
asserting equality keeps that output bound to the one owner and prevents schema
drift. This is not a runtime call path — the runtime never needs `json_schema` to
execute a decision.
"""
from __future__ import annotations

import json
from importlib.resources import files

from ordessa_decision import DecisionRequest, DecisionResult, json_schema

_SCHEMAS = {'request': DecisionRequest, 'result': DecisionResult}


def test_packaged_schema_bytes_match_declaration_generation():
    for name, cls in _SCHEMAS.items():
        raw = files('ordessa_decision').joinpath('definitions', f'{name}.schema.json').read_text(encoding='utf-8')
        assert json.loads(raw) == json_schema(cls), name


def test_declaration_is_closed_draft_2020_12_object():
    schema = json_schema(DecisionRequest)
    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['$ref'] == '#/$defs/DecisionRequest'
    definition = schema['$defs']['DecisionRequest']
    assert definition['type'] == 'object'
    assert definition['additionalProperties'] is False
